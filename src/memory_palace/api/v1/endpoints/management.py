"""Formal user, venue, settings, and audit management endpoints."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import BaseModel, Field

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, hash_password, require_auth, require_roles
from ...errors import api_error
from ....config.feature_registry import registry_snapshot
from ....config.integration_readiness import (
    external_integration_readiness,
    wechat_integration_readiness,
)
from ....config.secrets import read_secret
from ....core.sensitive_output import (
    public_error_message,
    public_record,
    sanitize_public_value,
)
from ....core.trace_timeline import build_trace_timeline
from ....tools.sms_client import notification_channel_readiness


router = APIRouter(dependencies=[Depends(require_auth)])

RoleName = Literal["admin", "manager", "operator"]
AccountStatus = Literal["ACTIVE", "DISABLED"]

SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    "organization_name": {"type": "string", "default": "示范景区运营中心"},
    "timezone": {"type": "string", "default": "Asia/Shanghai"},
    "sla_p0_minutes": {"type": "integer", "default": 5, "minimum": 1, "maximum": 120},
    "sla_p1_minutes": {"type": "integer", "default": 15, "minimum": 1, "maximum": 240},
    "sla_p2_minutes": {"type": "integer", "default": 60, "minimum": 5, "maximum": 1440},
    "knowledge_review_required": {"type": "boolean", "default": True},
    "sop_review_required": {"type": "boolean", "default": True},
}


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=80)
    role: RoleName
    venue_id: str = Field(..., min_length=1, max_length=64)
    department: Optional[str] = Field(None, min_length=1, max_length=120)
    job_title: Optional[str] = Field(None, min_length=1, max_length=120)


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    role: Optional[RoleName] = None
    venue_id: Optional[str] = Field(None, min_length=1, max_length=64)
    department: Optional[str] = Field(None, min_length=1, max_length=120)
    job_title: Optional[str] = Field(None, min_length=1, max_length=120)
    status: Optional[AccountStatus] = None


class PasswordResetRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class VenueCreateRequest(BaseModel):
    id: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(..., min_length=2, max_length=120)


class VenueUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    status: Optional[AccountStatus] = None


class SettingUpdateRequest(BaseModel):
    value: Any


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "venue_id": row["venue_id"],
        "department": row.get("department"),
        "job_title": row.get("job_title"),
        "status": row["status"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_login_at": row.get("last_login_at"),
    }


def _coerce_setting(key: str, value: Any) -> tuple[str, str, Any]:
    definition = SETTING_DEFINITIONS[key]
    value_type = definition["type"]
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("必须为布尔值")
        return json.dumps(value), value_type, value
    if value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("必须为整数")
        if value < definition["minimum"] or value > definition["maximum"]:
            raise ValueError(f"必须在 {definition['minimum']}-{definition['maximum']} 之间")
        return str(value), value_type, value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("必须为非空字符串")
    cleaned = value.strip()[:200]
    return cleaned, value_type, cleaned


def _decode_setting(value: str, value_type: str) -> Any:
    if value_type == "boolean":
        return json.loads(value)
    if value_type == "integer":
        return int(value)
    return value


@router.get("/assignees")
async def list_assignees(
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    rows = await db.fetch_all(
        """
        SELECT id, username, display_name, role, venue_id
        FROM users
        WHERE venue_id = ? AND status = 'ACTIVE' AND role IN ('manager', 'operator')
        ORDER BY role, display_name, username
        """,
        (principal["venue_id"],),
    )
    return {"assignees": rows}


@router.get("/users")
async def list_users(
    venue_id: Optional[str] = None,
    account_status: Optional[AccountStatus] = Query(None, alias="status"),
    _principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM users WHERE 1 = 1"
    params: list[Any] = []
    if venue_id:
        sql += " AND venue_id = ?"
        params.append(venue_id)
    if account_status:
        sql += " AND status = ?"
        params.append(account_status)
    sql += " ORDER BY venue_id, role, username"
    return {"users": [_public_user(row) for row in await db.fetch_all(sql, tuple(params))]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    trace_id = request_trace_id(request)
    venue = await db.fetch_one("SELECT id FROM venues WHERE id = ? AND status = 'ACTIVE'", (body.venue_id,))
    if not venue:
        raise api_error(request, 400, "VENUE_NOT_ACTIVE", "目标场地不存在或已停用。", "请选择有效场地。")
    existing = await db.fetch_one("SELECT id FROM users WHERE lower(username) = lower(?)", (body.username,))
    if existing:
        raise api_error(request, 409, "USERNAME_EXISTS", "用户名已存在。", "请更换用户名。")

    now = time.time()
    user_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO users (
            id, username, password_hash, display_name, role, venue_id,
            department, job_title, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """,
        (
            user_id,
            body.username.lower(),
            hash_password(body.password),
            body.display_name.strip(),
            body.role,
            body.venue_id,
            body.department.strip() if body.department else None,
            body.job_title.strip() if body.job_title else None,
            now,
            now,
        ),
    )
    await write_audit(
        db,
        principal=principal,
        action="USER_CREATED",
        resource_type="user",
        resource_id=user_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "username": body.username.lower(),
            "role": body.role,
            "venue_id": body.venue_id,
            "department": body.department.strip() if body.department else None,
            "job_title": body.job_title.strip() if body.job_title else None,
        },
    )
    row = await db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return {"user": _public_user(row), "trace_id": trace_id}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not current:
        raise api_error(request, 404, "USER_NOT_FOUND", "用户不存在。", "刷新列表后重试。")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"user": _public_user(current), "trace_id": request_trace_id(request)}
    if user_id == principal["user_id"] and updates.get("status") == "DISABLED":
        raise api_error(request, 409, "CANNOT_DISABLE_SELF", "不能停用当前登录账号。", "请使用其他管理员账号操作。")
    if "venue_id" in updates:
        venue = await db.fetch_one("SELECT id FROM venues WHERE id = ? AND status = 'ACTIVE'", (updates["venue_id"],))
        if not venue:
            raise api_error(request, 400, "VENUE_NOT_ACTIVE", "目标场地不存在或已停用。", "请选择有效场地。")

    set_sql = ", ".join(f"{column} = ?" for column in updates)
    await db.execute(
        f"UPDATE users SET {set_sql}, updated_at = ? WHERE id = ?",
        (*updates.values(), time.time(), user_id),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="USER_UPDATED",
        resource_type="user",
        resource_id=user_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    row = await db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    return {"user": _public_user(row), "trace_id": trace_id}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    body: PasswordResetRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    if not await db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)):
        raise api_error(request, 404, "USER_NOT_FOUND", "用户不存在。", "刷新列表后重试。")
    await db.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (hash_password(body.password), time.time(), user_id),
    )
    await db.execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (time.time(), user_id),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="USER_PASSWORD_RESET",
        resource_type="user",
        resource_id=user_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    return {"reset": True, "trace_id": trace_id}


@router.get("/venues")
async def list_venues(
    _principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    return {"venues": await db.fetch_all("SELECT * FROM venues ORDER BY name")}


@router.post("/venues", status_code=status.HTTP_201_CREATED)
async def create_venue(
    body: VenueCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    if await db.fetch_one("SELECT id FROM venues WHERE id = ?", (body.id,)):
        raise api_error(request, 409, "VENUE_EXISTS", "场地标识已存在。", "请更换场地标识。")
    now = time.time()
    await db.execute(
        "INSERT INTO venues (id, name, status, created_at, updated_at) VALUES (?, ?, 'ACTIVE', ?, ?)",
        (body.id, body.name.strip(), now, now),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="VENUE_CREATED",
        resource_type="venue",
        resource_id=body.id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"name": body.name.strip()},
    )
    return {"venue": await db.fetch_one("SELECT * FROM venues WHERE id = ?", (body.id,)), "trace_id": trace_id}


@router.patch("/venues/{venue_id}")
async def update_venue(
    venue_id: str,
    body: VenueUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one("SELECT * FROM venues WHERE id = ?", (venue_id,))
    if not current:
        raise api_error(request, 404, "VENUE_NOT_FOUND", "场地不存在。", "刷新列表后重试。")
    updates = body.model_dump(exclude_none=True)
    if venue_id == principal["venue_id"] and updates.get("status") == "DISABLED":
        raise api_error(request, 409, "CANNOT_DISABLE_CURRENT_VENUE", "不能停用当前登录场地。", "切换管理场地后再操作。")
    if updates:
        set_sql = ", ".join(f"{column} = ?" for column in updates)
        await db.execute(
            f"UPDATE venues SET {set_sql}, updated_at = ? WHERE id = ?",
            (*updates.values(), time.time(), venue_id),
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="VENUE_UPDATED",
        resource_type="venue",
        resource_id=venue_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    return {"venue": await db.fetch_one("SELECT * FROM venues WHERE id = ?", (venue_id,)), "trace_id": trace_id}


@router.get("/settings")
async def list_settings(
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    rows = await db.fetch_all(
        "SELECT setting_key, setting_value, value_type, updated_by, updated_at FROM system_settings WHERE venue_id = ?",
        (principal["venue_id"],),
    )
    stored = {row["setting_key"]: row for row in rows}
    settings = []
    for key, definition in SETTING_DEFINITIONS.items():
        row = stored.get(key)
        value = definition["default"] if row is None else _decode_setting(row["setting_value"], row["value_type"])
        settings.append(
            {
                "key": key,
                "value": value,
                "type": definition["type"],
                "updated_by": row.get("updated_by") if row else None,
                "updated_at": row.get("updated_at") if row else None,
            }
        )
    return {"settings": settings}


@router.put("/settings/{setting_key}")
async def update_setting(
    setting_key: str,
    body: SettingUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    if setting_key not in SETTING_DEFINITIONS:
        raise api_error(request, 404, "SETTING_NOT_SUPPORTED", "该配置项不允许通过客户端修改。", "请查看支持的非敏感配置。")
    try:
        stored_value, value_type, public_value = _coerce_setting(setting_key, body.value)
    except ValueError as exc:
        raise api_error(request, 422, "SETTING_VALUE_INVALID", f"配置值无效：{exc}", "修正配置值后重试。") from exc
    now = time.time()
    await db.execute(
        """
        INSERT INTO system_settings (venue_id, setting_key, setting_value, value_type, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(venue_id, setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            value_type = excluded.value_type,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (principal["venue_id"], setting_key, stored_value, value_type, principal["user_id"], now),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="SETTING_UPDATED",
        resource_type="system_setting",
        resource_id=setting_key,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"value_type": value_type},
    )
    return {"key": setting_key, "value": public_value, "type": value_type, "trace_id": trace_id}


async def _integration_status_rows(venue_id: str, db) -> list[dict[str, Any]]:
    model_name = os.environ.get("LLM_DEFAULT_MODEL", "deepseek-v4-flash")
    deepseek_missing = []
    if not read_secret("DEEPSEEK_API_KEY"):
        deepseek_missing.append("DEEPSEEK_API_KEY")
    if model_name != "deepseek-v4-flash":
        deepseek_missing.append("LLM_DEFAULT_MODEL=deepseek-v4-flash")
    deepseek_configured = not deepseek_missing
    deepseek_evidence = None
    if deepseek_configured and db is not None:
        deepseek_evidence = await db.fetch_one(
            """
            SELECT provider, model_name, status, is_mock, request_id, trace_id, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
              AND provider = 'deepseek'
              AND model_name = 'deepseek-v4-flash'
              AND status = 'SUCCEEDED'
              AND NOT COALESCE(is_mock, FALSE)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (venue_id,),
        )
    deepseek_verified = deepseek_evidence is not None
    in_app_evidence = None
    wechat_evidence = None
    if db is not None:
        in_app_evidence = await db.fetch_one(
            """
            SELECT push_id, recipient, delivery_status, trace_id, pushed_at
            FROM push_logs
            WHERE venue_id = ? AND channel = 'in_app' AND delivery_status = 'DELIVERED'
            ORDER BY pushed_at DESC
            LIMIT 1
            """,
            (venue_id,),
        )
        wechat_evidence = await db.fetch_one(
            """
            SELECT run.message_id, run.external_message_id, run.trace_id,
                   run.delivery_status, run.delivered_at,
                   ledger.push_id AS reply_push_id, ledger.recipient
            FROM message_runs AS run
            JOIN push_logs AS ledger
              ON ledger.venue_id = run.venue_id
             AND ledger.msg_id = run.message_id
             AND ledger.channel = 'WECOM_REPLY'
             AND ledger.delivery_status = 'DELIVERED'
            WHERE run.venue_id = ? AND run.channel = 'WECOM'
              AND run.status = 'COMPLETED'
              AND run.delivery_status = 'DELIVERED'
            ORDER BY run.delivered_at DESC, run.updated_at DESC
            LIMIT 1
            """,
            (venue_id,),
        )

    wechat_readiness = wechat_integration_readiness()
    sms_external = external_integration_readiness(("SMS_PROVIDER", "SMS_API_KEY"))
    voice_external = external_integration_readiness(("VOICE_PROVIDER", "VOICE_API_KEY"))
    wechat_configured = bool(wechat_readiness["configured"])
    wechat_verified = wechat_configured and wechat_evidence is not None
    sms_configured = bool(sms_external["configured"])
    voice_configured = bool(voice_external["configured"])
    sms_readiness = notification_channel_readiness("sms")
    voice_readiness = notification_channel_readiness("voice")
    integrations = [
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "status": (
                "READY"
                if deepseek_verified
                else "BLOCKED"
                if deepseek_configured
                else "DISABLED_REQUIRES_CONFIG"
            ),
            "model": model_name,
            "configured": deepseek_configured,
            "live_verified": deepseek_verified,
            "missing": deepseek_missing,
            "evidence": deepseek_evidence,
            "blocked_reason": None if deepseek_verified else "需要一次真实且非 Mock 的 DeepSeek 成功调用证据。",
        },
        {
            "id": "in_app",
            "name": "站内告警",
            "status": "READY" if in_app_evidence else "BLOCKED",
            "configured": True,
            "live_verified": in_app_evidence is not None,
            "missing": [],
            "evidence": in_app_evidence,
            "blocked_reason": None if in_app_evidence else "需要完成一次审批后的站内告警投递。",
        },
        {
            "id": "wechat",
            "name": "企业微信",
            "status": (
                "READY" if wechat_verified else str(wechat_readiness["status"])
            ),
            "configured": wechat_configured,
            "safe_disabled_verified": not wechat_configured,
            "live_verified": wechat_verified,
            "missing": wechat_readiness["missing"],
            "evidence": wechat_evidence if wechat_verified else None,
            "blocked_reason": None if wechat_verified or not wechat_configured else "需要客户沙箱回调与回复成功证据。",
        },
        {
            "id": "sms",
            "name": "短信",
            "status": str(sms_external["status"]),
            "configured": sms_configured,
            "safe_disabled_verified": not sms_configured and not sms_readiness["available"],
            "live_verified": False,
            "missing": sms_external["missing"],
            "evidence": None,
            "blocked_reason": "需要真实供应商适配器和沙箱发送成功证据。" if sms_configured else None,
        },
        {
            "id": "voice",
            "name": "语音电话",
            "status": str(voice_external["status"]),
            "configured": voice_configured,
            "safe_disabled_verified": not voice_configured and not voice_readiness["available"],
            "live_verified": False,
            "missing": voice_external["missing"],
            "evidence": None,
            "blocked_reason": "需要真实供应商适配器和沙箱呼叫成功证据。" if voice_configured else None,
        },
    ]
    return integrations


@router.get("/integrations")
async def integration_statuses(
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    return {"integrations": await _integration_status_rows(principal["venue_id"], db)}


async def _collect_registry_evidence(request: Request, db, venue_id: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "audits": {},
        "facts": {},
        "runtime": {
            "database": "unhealthy",
            "queue": "unhealthy",
            "chromadb": "unhealthy",
            "scheduler": "unhealthy",
        },
        "integrations": {},
        "collection_errors": [],
        "collected_at": time.time(),
    }
    facts_sql = """
        SELECT
            (SELECT COUNT(*) FROM confirmed_events WHERE venue_id = ?) AS events_total,
            (SELECT COUNT(*) FROM confirmed_events WHERE venue_id = ? AND status = 'CLOSED') AS events_closed,
            (SELECT COUNT(*) FROM message_runs WHERE venue_id = ?) AS message_runs_total,
            (SELECT COUNT(*) FROM message_runs WHERE venue_id = ? AND status = 'COMPLETED') AS message_runs_completed,
            (SELECT COUNT(*) FROM sessions WHERE venue_id = ?) AS sessions_total,
            (SELECT COUNT(*) FROM sessions WHERE venue_id = ? AND stage = 'CLOSED') AS sessions_closed,
            (SELECT COUNT(*) FROM tasks WHERE venue_id = ?) AS tasks_total,
            (SELECT COUNT(*) FROM tasks WHERE venue_id = ? AND status = 'DONE') AS tasks_done,
            (SELECT COUNT(*) FROM approval_requests WHERE venue_id = ? AND status = 'APPROVED') AS approvals_approved,
            (SELECT COUNT(*) FROM approval_requests WHERE venue_id = ? AND status = 'REJECTED') AS approvals_rejected,
            (SELECT COUNT(*) FROM approval_requests WHERE venue_id = ? AND (execution_result IS NOT NULL OR execution_error IS NOT NULL)) AS approvals_executed,
            (SELECT COUNT(*) FROM push_logs WHERE venue_id = ? AND channel NOT LIKE '%_REPLY') AS push_logs_total,
            (SELECT COUNT(*) FROM push_logs WHERE venue_id = ? AND channel NOT LIKE '%_REPLY' AND adoption_status IN ('adopted', 'rejected')) AS push_logs_reviewed,
            (SELECT COUNT(*) FROM tool_invocation_logs WHERE venue_id = ?) AS tool_invocations_total,
            (SELECT COUNT(*) FROM knowledge_documents WHERE venue_id = ?) AS knowledge_total,
            (SELECT COUNT(*) FROM sop_documents WHERE venue_id = ? AND status = 'PUBLISHED') AS sops_published,
            (SELECT COUNT(*) FROM personas WHERE venue_id = ?) AS personas_total,
            (SELECT COUNT(*) FROM persona_interviews WHERE venue_id = ? AND status = 'COMPLETED') AS interviews_completed,
            (SELECT COUNT(*) FROM watcher_policies WHERE venue_id = ?) AS watcher_policies_total,
            (SELECT COUNT(*) FROM watcher_runs WHERE venue_id = ? AND status = 'SUCCEEDED') AS watcher_runs_succeeded,
            (SELECT COUNT(*) FROM watcher_findings WHERE venue_id = ? AND assigned_to IS NOT NULL AND assigned_to <> '') AS watcher_findings_assigned,
            (SELECT COUNT(*) FROM watcher_findings WHERE venue_id = ? AND status = 'CLOSED') AS watcher_findings_closed,
            (SELECT COUNT(*) FROM users WHERE venue_id = ?) AS users_total,
            (SELECT COUNT(*) FROM venues) AS venues_total,
            (SELECT COUNT(*) FROM system_settings WHERE venue_id = ?) AS settings_total,
            (SELECT COUNT(*) FROM backup_records WHERE venue_id = ? AND status = 'COMPLETED') AS backups_completed
    """
    try:
        row = await db.fetch_one(facts_sql, tuple(venue_id for _ in range(facts_sql.count("?")))) or {}
        evidence["facts"] = {
            "events.total": row.get("events_total", 0),
            "events.closed": row.get("events_closed", 0),
            "message_runs.total": row.get("message_runs_total", 0),
            "message_runs.completed_count": row.get("message_runs_completed", 0),
            "sessions.total": row.get("sessions_total", 0),
            "sessions.closed": row.get("sessions_closed", 0),
            "tasks.total": row.get("tasks_total", 0),
            "tasks.done": row.get("tasks_done", 0),
            "approvals.approved": row.get("approvals_approved", 0),
            "approvals.rejected": row.get("approvals_rejected", 0),
            "approvals.executed": row.get("approvals_executed", 0),
            "push_logs.total": row.get("push_logs_total", 0),
            "push_logs.reviewed": row.get("push_logs_reviewed", 0),
            "tool_invocations.total": row.get("tool_invocations_total", 0),
            "knowledge.total": row.get("knowledge_total", 0),
            "sops.published": row.get("sops_published", 0),
            "personas.total": row.get("personas_total", 0),
            "interviews.completed": row.get("interviews_completed", 0),
            "watcher_policies.total": row.get("watcher_policies_total", 0),
            "watcher_runs.succeeded": row.get("watcher_runs_succeeded", 0),
            "watcher_findings.assigned": row.get("watcher_findings_assigned", 0),
            "watcher_findings.closed": row.get("watcher_findings_closed", 0),
            "users.total": row.get("users_total", 0),
            "venues.total": row.get("venues_total", 0),
            "settings.total": row.get("settings_total", 0),
            "backups.completed": row.get("backups_completed", 0),
        }
        evidence["runtime"]["database"] = "healthy"
    except Exception as exc:
        evidence["collection_errors"].append({"source": "database_facts", "error_type": type(exc).__name__})

    try:
        rows = await db.fetch_all(
            """
            SELECT action, outcome, trace_id, resource_type, resource_id, created_at
            FROM audit_logs
            WHERE venue_id = ? AND outcome IN ('SUCCEEDED', 'DENIED', 'PENDING')
            ORDER BY created_at DESC
            LIMIT 1000
            """,
            (venue_id,),
        )
        outcome_contract = {
            "SESSION_CLOSE_DENIED": {"DENIED"},
            "CONTROLLED_ACTION_REQUESTED": {"SUCCEEDED", "PENDING"},
        }
        for row in rows:
            accepted_outcomes = outcome_contract.get(row["action"], {"SUCCEEDED"})
            if row.get("outcome") in accepted_outcomes:
                evidence["audits"].setdefault(row["action"], []).append(row)
    except Exception as exc:
        evidence["collection_errors"].append({"source": "audit_logs", "error_type": type(exc).__name__})

    queue = getattr(request.app.state, "message_queue", None)
    if queue is not None and hasattr(queue, "diagnostics"):
        try:
            diagnostics = await queue.diagnostics()
            evidence["runtime"]["queue"] = "healthy" if diagnostics.get("connected") else "unhealthy"
        except Exception as exc:
            evidence["collection_errors"].append({"source": "queue", "error_type": type(exc).__name__})

    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is not None and hasattr(vector_store, "health"):
        try:
            evidence["runtime"]["chromadb"] = vector_store.health().get("status", "unhealthy")
        except Exception as exc:
            evidence["collection_errors"].append({"source": "chromadb", "error_type": type(exc).__name__})

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        scheduler_backend = getattr(scheduler, "scheduler", scheduler)
        running = getattr(scheduler_backend, "running", None)
        evidence["runtime"]["scheduler"] = "healthy" if running is not False else "unhealthy"

    try:
        integrations = await _integration_status_rows(venue_id, db)
        evidence["integrations"] = {item["id"]: item for item in integrations}
    except Exception as exc:
        evidence["collection_errors"].append({"source": "integrations", "error_type": type(exc).__name__})

    try:
        live_calls = await db.fetch_all(
            """
            SELECT trace_id, request_id, agent_id, agent_name, provider, model_name, status, is_mock, created_at
            FROM llm_call_logs
            WHERE venue_id = ?
              AND provider = 'deepseek'
              AND model_name = 'deepseek-v4-flash'
              AND status = 'SUCCEEDED'
              AND NOT COALESCE(is_mock, FALSE)
            ORDER BY created_at DESC
            LIMIT 500
            """,
            (venue_id,),
        )
        live_by_trace_agent: dict[tuple[str, str], dict[str, Any]] = {}
        for row in live_calls:
            trace_id = row.get("trace_id")
            agent_id = row.get("agent_id") or row.get("agent_name")
            if trace_id and agent_id:
                live_by_trace_agent.setdefault((trace_id, agent_id), row)
        live_trace_ids = {trace_id for trace_id, _agent_id in live_by_trace_agent}
        agent_evidence: dict[str, list[dict[str, Any]]] = {}

        def record_agent(
            agent_id: str,
            trace_id: str,
            source: str,
            live_call: Optional[dict[str, Any]] = None,
        ) -> None:
            live_call = live_call or live_by_trace_agent.get((trace_id, agent_id))
            if not live_call:
                return
            attributed_agent = live_call.get("agent_id") or live_call.get("agent_name")
            if attributed_agent != agent_id:
                return
            records = agent_evidence.setdefault(agent_id, [])
            evidence_key = (trace_id, live_call.get("request_id"))
            if any((row["trace_id"], row.get("request_id")) == evidence_key for row in records):
                return
            records.append(
                {
                    "kind": "agent_trace",
                    "agent_id": agent_id,
                    "agent_name": live_call.get("agent_name") or agent_id,
                    "provider": live_call.get("provider"),
                    "model_name": live_call.get("model_name"),
                    "status": live_call.get("status"),
                    "is_mock": bool(live_call.get("is_mock")),
                    "success": live_call.get("status") == "SUCCEEDED",
                    "source": source,
                    "trace_id": trace_id,
                    "request_id": live_call.get("request_id"),
                    "created_at": live_call.get("created_at"),
                }
            )

        for live_call in live_calls:
            agent_id = live_call.get("agent_id")
            if agent_id:
                record_agent(agent_id, live_call.get("trace_id", ""), "llm_call_log", live_call)

        message_runs = await db.fetch_all(
            """
            SELECT trace_id, target_agent, result_json
            FROM message_runs
            WHERE venue_id = ? AND status = 'COMPLETED'
            ORDER BY created_at DESC
            LIMIT 500
            """,
            (venue_id,),
        )
        evidence["facts"]["message_runs.completed"] = [
            {"trace_id": row["trace_id"], "status": "COMPLETED"}
            for row in message_runs
            if row.get("trace_id")
        ]
        message_agents = {
            "commander": "Commander",
            "memory_ops": "MemoryOps",
            "persona": "Persona",
            "persona_extract": "PersonaExtract",
            "todo_write": "TodoWrite",
        }
        for row in message_runs:
            trace_id = row.get("trace_id")
            if trace_id not in live_trace_ids:
                continue
            try:
                result = json.loads(row.get("result_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                result = {}
            route = result.get("route") if isinstance(result, dict) else {}
            route = route if isinstance(route, dict) else {}
            if route.get("context_trigger_data"):
                record_agent("ContextTrigger", trace_id, "message_run")
            if route.get("router_confidence") is not None:
                record_agent("Router", trace_id, "message_run")
            target_agent = row.get("target_agent") or route.get("target_agent")
            if target_agent in message_agents:
                record_agent(message_agents[target_agent], trace_id, "message_run")

        audit_agent_actions = {
            "PERSONA_QUERIED": "Persona",
            "PERSONA_INTERVIEW_FINALIZED": "PersonaExtract",
            "TASK_CREATED": "TodoWrite",
            "WATCHER_RUN": "Watcher",
        }
        for action, agent_id in audit_agent_actions.items():
            for row in evidence["audits"].get(action, []):
                record_agent(agent_id, row.get("trace_id", ""), "audit_log")

        for agent_id in (
            "ContextTrigger",
            "Router",
            "Commander",
            "MemoryOps",
            "Persona",
            "PersonaExtract",
            "TodoWrite",
            "Watcher",
        ):
            evidence["facts"][f"agents.{agent_id}.live_succeeded"] = agent_evidence.get(agent_id, [])
    except Exception as exc:
        evidence["collection_errors"].append({"source": "agent_traces", "error_type": type(exc).__name__})
    return evidence


@router.get("/feature-registry")
async def feature_registry(
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    evidence = await _collect_registry_evidence(request, db, principal["venue_id"])
    snapshot = registry_snapshot(evidence=evidence)
    snapshot["evidence_collected_at"] = evidence["collected_at"]
    snapshot["collection_errors"] = evidence["collection_errors"]
    return snapshot


@router.get("/llm-calls")
async def list_llm_calls(
    trace_id: Optional[str] = None,
    call_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM llm_call_logs WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if trace_id:
        sql += " AND trace_id = ?"
        params.append(trace_id)
    if call_status:
        sql += " AND status = ?"
        params.append(call_status.upper())
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.fetch_all(sql, tuple(params))
    llm_calls = []
    for row in rows:
        public_call = public_record(
            row,
            (
                "id",
                "venue_id",
                "trace_id",
                "agent_id",
                "agent_name",
                "provider",
                "model_name",
                "status",
                "attempt_count",
                "latency_seconds",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "request_id",
                "error_type",
                "is_mock",
                "created_at",
            ),
        )
        public_call["error_summary"] = public_error_message(
            row.get("error_message"),
            context="model",
        )
        public_call["is_mock"] = bool(row.get("is_mock"))
        llm_calls.append(public_call)
    return {"llm_calls": llm_calls, "limit": limit, "offset": offset}


@router.get("/audit-logs")
async def list_audit_logs(
    trace_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM audit_logs WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if trace_id:
        sql += " AND trace_id = ?"
        params.append(trace_id)
    if action:
        sql += " AND action = ?"
        params.append(action)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = await db.fetch_all(sql, tuple(params))
    audit_logs = []
    for row in rows:
        try:
            metadata = json.loads(row.get("metadata_json", "{}") or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        public_log = public_record(
            row,
            (
                "id",
                "venue_id",
                "user_id",
                "action",
                "resource_type",
                "resource_id",
                "outcome",
                "trace_id",
                "created_at",
            ),
        )
        public_log["metadata"] = sanitize_public_value(metadata)
        audit_logs.append(public_log)
    return {"audit_logs": audit_logs, "limit": limit, "offset": offset}


@router.get("/traces/{trace_id}")
async def get_trace_timeline(
    request: Request,
    trace_id: str = Path(..., min_length=6, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    timeline = await build_trace_timeline(
        db,
        venue_id=principal["venue_id"],
        trace_id=trace_id,
        technical=principal.get("role") == "admin",
    )
    if timeline is None:
        raise api_error(
            request,
            404,
            "TRACE_NOT_FOUND",
            "当前场地不存在该 Trace。",
            "检查 Trace ID，或切换到有权访问的场地。",
        )
    return timeline
