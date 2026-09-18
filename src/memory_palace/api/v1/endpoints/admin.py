"""
v1/endpoints/admin.py - Admin endpoint

[升级] Phase 2 新增审批 API:
- GET /approvals - 列出待审批请求
- POST /approvals/{id}/approve - 批准
- POST /approvals/{id}/reject - 拒绝
"""
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse
from ..schemas import HealthResponse
from datetime import datetime
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field
import os
import re
import time
import json

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error
from ....config.secrets import read_secret
from ....core.event_dossier import build_event_dossier
from ....core.runtime_recovery import list_recent_global_recovery_runs
from ....core.sensitive_output import public_error_message, public_record
from ....core.simulator_outbox import (
    SimulatorRecipientsNotReady,
    build_event_participant_delivery,
)
from ....tools.sms_client import notification_action_readiness

logger_model = __import__('logging').getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_auth)])

_START_TIME = time.time()


# ---------------------------------------------------------------------------
# 审批相关模型
# ---------------------------------------------------------------------------

class ApprovalResponse(BaseModel):
    approval_id: str
    business_id: Optional[str] = None
    tool_name: str
    args: dict
    session_id: str
    event_id: Optional[str] = None
    task_id: Optional[str] = None
    user_id: str
    requested_at: float
    requested_by: str
    status: str
    venue_id: str
    reviewed_at: Optional[float] = None
    reviewed_by: Optional[str] = None
    comment: Optional[str] = None
    execution_result: Optional[dict] = None
    execution_error: Optional[str] = None
    correlation_trace_id: Optional[str] = None
    execution_trace_id: Optional[str] = None
    execution_status: Optional[str] = None
    supersedes_approval_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    evidence_snapshot: dict = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    comment: Optional[str] = None


class ControlledActionRequest(BaseModel):
    action_code: Optional[str] = None
    tool_name: Optional[str] = None
    recipient_scope: Literal["SESSION", "EVENT_PARTICIPANTS"] = "SESSION"
    session_id: str
    event_id: str
    task_id: str
    supersedes_approval_id: Optional[str] = None
    message: str
    recipient: Optional[str] = None
    priority: str = "normal"


def get_admin_user(user: dict = Depends(require_roles("admin", "manager"))):
    return user


def _decode_json_value(value: Any, default: Any):
    if value in (None, ""):
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _public_dead_letter(entry: dict[str, Any]) -> dict[str, Any]:
    message = entry.get("message")
    if not isinstance(message, dict):
        message = {}
    public_entry = public_record(entry, ("id", "created_at_ms", "retries"))
    public_entry["message"] = public_record(
        message,
        (
            "msg_id",
            "message_id",
            "trace_id",
            "session_id",
            "user_id",
            "venue_id",
            "channel",
            "external_message_id",
            "external_conversation_id",
        ),
    )
    public_entry["error"] = public_error_message(
        entry.get("error"),
        context="queue",
    )
    return public_entry


@router.get("/health", response_model=HealthResponse)
async def health_check(
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    """返回基于真实依赖和最近模型证据的健康状态。"""
    components = {"db": "unknown", "llm": "unknown", "queue": "unknown", "pgvector": "unknown"}

    try:
        ok = await db.fetch_one("SELECT 1 AS ok")
        components["db"] = "healthy" if ok else "unhealthy"
    except Exception:
        components["db"] = "unhealthy"

    from ....tools.llm_wrapper import REQUIRED_GENERATIVE_MODEL

    configured_model = os.environ.get("LLM_DEFAULT_MODEL", REQUIRED_GENERATIVE_MODEL)
    if configured_model != REQUIRED_GENERATIVE_MODEL:
        components["llm"] = "misconfigured_model"
    elif os.environ.get("MOCK_LLM", "").lower() == "true":
        components["llm"] = "mocked_not_ready"
    elif not read_secret("DEEPSEEK_API_KEY"):
        components["llm"] = "disabled_requires_config"
    else:
        try:
            latest_call = await db.fetch_one(
                """
                SELECT status, is_mock FROM llm_call_logs
                WHERE venue_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (principal["venue_id"],),
            )
            if latest_call is None:
                components["llm"] = "configured_unverified"
            elif latest_call.get("status") == "SUCCEEDED" and not bool(latest_call.get("is_mock")):
                components["llm"] = "healthy"
            else:
                components["llm"] = "degraded"
        except Exception:
            components["llm"] = "unhealthy"

    queue = _runtime_queue(request)
    if queue is not None and hasattr(queue, "diagnostics"):
        try:
            queue_diagnostics = await queue.diagnostics()
            components["queue"] = "healthy" if queue_diagnostics.get("connected") else "unhealthy"
        except Exception:
            components["queue"] = "unhealthy"
    else:
        components["queue"] = "unhealthy"

    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is not None and hasattr(vector_store, "health"):
        try:
            components["pgvector"] = vector_store.health().get("status", "unhealthy")
        except Exception:
            components["pgvector"] = "unhealthy"
    else:
        components["pgvector"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in components.values()) else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(),
        version="1.0.0",
        uptime_seconds=time.time() - _START_TIME,
        components=components,
    )


@router.get("/metrics")
async def metrics(_principal: dict = Depends(require_auth)):
    """Prometheus metrics 端点"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/stats")
async def stats(
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    """系统统计信息"""
    messages = await db.fetch_one(
        "SELECT COUNT(*) AS count FROM message_runs WHERE venue_id = ?",
        (principal["venue_id"],),
    )
    sessions = await db.fetch_one(
        "SELECT COUNT(*) AS count FROM sessions WHERE venue_id = ?",
        (principal["venue_id"],),
    )
    return {
        "total_messages": messages["count"] if messages else 0,
        "total_sessions": sessions["count"] if sessions else 0,
    }


def _runtime_queue(request: Request):
    return getattr(request.app.state, "message_queue", None)


@router.get("/queue")
async def queue_status(
    request: Request,
    _principal: dict = Depends(require_roles("admin")),
):
    """返回正式 Redis Streams 的积压、消费组与死信诊断。"""
    queue = _runtime_queue(request)
    if queue is None or not hasattr(queue, "diagnostics"):
        raise api_error(request, 503, "QUEUE_UNAVAILABLE", "消息队列尚未就绪。", "检查 Redis 和 App 启动日志。", retryable=True)
    try:
        return await queue.diagnostics()
    except Exception:
        logger_model.exception("读取消息队列诊断失败")
        raise api_error(request, 503, "QUEUE_DIAGNOSTICS_FAILED", "无法读取消息队列状态。", "检查 Redis 连接后重试。", retryable=True)


@router.get("/recovery-runs")
async def list_runtime_recovery_runs(
    limit: int = Query(20, ge=1, le=100),
    _principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    """Return recent global App recovery evidence without tenant payloads."""
    return {
        "recovery_runs": await list_recent_global_recovery_runs(db, limit=limit),
    }


@router.get("/dead-letters")
async def list_dead_letters(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    principal: dict = Depends(require_roles("admin")),
):
    """列出当前场地可见的死信，不暴露其他场地载荷。"""
    queue = _runtime_queue(request)
    if queue is None or not hasattr(queue, "list_dead_letters"):
        raise api_error(request, 503, "QUEUE_UNAVAILABLE", "消息队列尚未就绪。", "检查 Redis 和 App 启动日志。", retryable=True)
    try:
        entries = await queue.list_dead_letters(limit=200)
    except Exception:
        logger_model.exception("读取死信队列失败")
        raise api_error(request, 503, "DEAD_LETTER_READ_FAILED", "无法读取死信队列。", "检查 Redis 连接后重试。", retryable=True)
    visible = [
        entry
        for entry in entries
        if entry.get("message", {}).get("venue_id") == principal["venue_id"]
    ][:limit]
    return {
        "dead_letters": [_public_dead_letter(entry) for entry in visible],
        "limit": limit,
    }


@router.post("/dead-letters/{dead_letter_id}/retry")
async def retry_dead_letter(
    dead_letter_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    """安全重试当前场地的一条死信，并写入审计。"""
    queue = _runtime_queue(request)
    if queue is None or not hasattr(queue, "retry_dead_letter"):
        raise api_error(request, 503, "QUEUE_UNAVAILABLE", "消息队列尚未就绪。", "检查 Redis 和 App 启动日志。", retryable=True)

    try:
        entries = await queue.list_dead_letters(limit=200)
    except Exception:
        logger_model.exception("重试前读取死信失败")
        raise api_error(request, 503, "DEAD_LETTER_READ_FAILED", "无法读取死信队列。", "检查 Redis 连接后重试。", retryable=True)
    entry = next(
        (
            candidate
            for candidate in entries
            if candidate.get("id") == dead_letter_id
            and candidate.get("message", {}).get("venue_id") == principal["venue_id"]
        ),
        None,
    )
    if entry is None:
        raise api_error(request, 404, "DEAD_LETTER_NOT_FOUND", "死信不存在。", "刷新死信列表后重试。")

    try:
        result = await queue.retry_dead_letter(dead_letter_id)
    except ValueError:
        raise api_error(request, 409, "DEAD_LETTER_INVALID", "死信载荷已损坏，无法重试。", "保留记录并联系系统管理员。")
    except Exception as exc:
        if "ALREADY_RETRIED" in str(exc):
            raise api_error(request, 409, "DEAD_LETTER_ALREADY_RETRIED", "该死信已经重试。", "刷新死信列表查看最新状态。")
        logger_model.exception("死信重试失败")
        raise api_error(request, 503, "DEAD_LETTER_RETRY_FAILED", "死信重新入队失败。", "检查 Redis 状态后重试。", retryable=True)
    if result is None:
        raise api_error(request, 404, "DEAD_LETTER_NOT_FOUND", "死信不存在。", "刷新死信列表后重试。")

    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="DEAD_LETTER_RETRIED",
        resource_type="dead_letter",
        resource_id=dead_letter_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "message_id": result.get("message_id"),
            "stream_message_id": result.get("stream_message_id"),
        },
    )
    public_result = public_record(
        result,
        ("dead_letter_id", "stream_message_id", "message_id"),
    )
    return {**public_result, "trace_id": trace_id}


@router.post("/config/reload")
async def reload_config(
    request: Request,
    principal: dict = Depends(require_roles("admin")),
    db=Depends(get_request_db),
):
    """重新加载配置"""
    from ....config import config
    from ....config.app_settings import reload_settings
    trace_id = request_trace_id(request)
    try:
        config.reload()
        reload_settings()
        await write_audit(
            db,
            principal=principal,
            action="CONFIG_RELOADED",
            resource_type="configuration",
            resource_id="runtime",
            outcome="SUCCEEDED",
            trace_id=trace_id,
        )
        return {"status": "ok", "message": "Configuration reloaded", "trace_id": trace_id}
    except Exception as exc:
        await write_audit(
            db,
            principal=principal,
            action="CONFIG_RELOAD_FAILED",
            resource_type="configuration",
            resource_id="runtime",
            outcome="FAILED",
            trace_id=trace_id,
            metadata={"error_type": type(exc).__name__},
        )
        raise api_error(
            request,
            400,
            "CONFIG_RELOAD_FAILED",
            "运行配置重载失败。",
            "检查配置文件和环境变量后重试。",
        ) from exc


# ---------------------------------------------------------------------------
# [Phase 2] 审批 API
# ---------------------------------------------------------------------------


@router.post("/action-requests", status_code=202)
async def request_controlled_action(
    body: ControlledActionRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
    idempotency_key: Optional[str] = Header(
        None,
        alias="Idempotency-Key",
        max_length=128,
    ),
):
    """Submit a registered high-risk communication action for approval."""
    from ....core.controlled_action_policy import get_controlled_action_policy
    from ....core.permissions import SensitivityLevel, get_permission_engine
    from ....tools.tool_executor import get_tool

    action_code = str(body.action_code or "").strip().upper()
    requested_tool_name = str(body.tool_name or "").strip()
    action_policy = get_controlled_action_policy(action_code) if action_code else None
    if action_code and action_policy is None:
        raise api_error(
            request,
            422,
            "ACTION_CODE_NOT_SUPPORTED",
            "该高风险业务动作未注册。",
            "刷新动作列表后重新选择。",
        )
    tool_name = action_policy.tool_name if action_policy else requested_tool_name
    if action_policy and requested_tool_name and requested_tool_name != tool_name:
        raise api_error(
            request,
            409,
            "ACTION_POLICY_MISMATCH",
            "业务动作与执行工具不匹配。",
            "移除客户端工具覆盖并重试。",
        )
    if tool_name == "record_manager_decision" and action_policy is None:
        raise api_error(
            request,
            422,
            "ACTION_CODE_REQUIRED",
            "管理决策必须使用已注册的高风险业务动作。",
            "提交动作列表中的 action_code，不要直接指定执行工具。",
        )
    session_id = body.session_id.strip()
    event_id = body.event_id.strip()
    task_id = body.task_id.strip()
    supersedes_approval_id = (
        body.supersedes_approval_id.strip()
        if body.supersedes_approval_id
        else None
    )
    message = body.message.strip()
    priority = body.priority.strip().lower()
    recipient_scope = (
        "EVENT_PARTICIPANTS"
        if action_policy and action_policy.delivery_channel == "WECOM_SIMULATOR_OUTBOX"
        else body.recipient_scope
    )
    normalized_idempotency_key = (
        idempotency_key.strip() if idempotency_key is not None else None
    )
    if tool_name not in {"send_sms", "send_alert", "send_in_app_alert", "record_manager_decision"}:
        raise api_error(
            request,
            422,
            "ACTION_NOT_SUPPORTED",
            "该受控动作未开放给正式客户端。",
            "请选择站内告警、短信通知或告警广播。",
        )
    if not session_id or len(session_id) > 64:
        raise api_error(request, 422, "SESSION_ID_INVALID", "必须关联一个有效会话。", "从会话列表中重新选择。")
    if not event_id or len(event_id) > 64:
        raise api_error(request, 422, "EVENT_ID_INVALID", "必须关联一个有效事件。", "从事件详情重新发起动作。")
    if not task_id or len(task_id) > 64:
        raise api_error(request, 422, "TASK_ID_INVALID", "必须关联一个有效任务。", "从事件任务图重新发起动作。")
    if idempotency_key is not None and not normalized_idempotency_key:
        raise api_error(
            request,
            422,
            "APPROVAL_IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key 不能为空。",
            "使用稳定 UUID 作为本次申请的幂等键。",
        )
    if not message or len(message) > 1000:
        raise api_error(request, 422, "ACTION_MESSAGE_INVALID", "动作内容长度必须为 1 到 1000 个字符。", "修改内容后重试。")

    session = await db.fetch_one(
        "SELECT session_id FROM sessions WHERE session_id = ? AND venue_id = ?",
        (session_id, principal["venue_id"]),
    )
    if session is None:
        raise api_error(request, 404, "SESSION_NOT_FOUND", "关联会话不存在。", "刷新会话列表后重试。")

    event = await db.fetch_one(
        """
        SELECT event_id, business_id, status, severity
        FROM confirmed_events
        WHERE event_id = ? AND venue_id = ?
        """,
        (event_id, principal["venue_id"]),
    )
    if event is None:
        raise api_error(request, 404, "EVENT_NOT_FOUND", "关联事件不存在。", "从事件详情重新发起动作。")

    task = await db.fetch_one(
        """
        SELECT id, business_id, event_id, session_id, description, status,
               result, result_schema_json, evidence_refs_json, error,
               assigned_user_id, completed_at, updated_at
        FROM tasks
        WHERE id = ? AND venue_id = ?
        """,
        (task_id, principal["venue_id"]),
    )
    if task is None:
        raise api_error(request, 404, "TASK_NOT_FOUND", "关联任务不存在。", "刷新事件任务图后重试。")
    if task.get("event_id") != event_id or task.get("session_id") != session_id:
        raise api_error(
            request,
            409,
            "ACTION_CONTEXT_MISMATCH",
            "事件、任务和会话不属于同一处置链。",
            "从目标事件的任务详情重新发起动作。",
        )

    if tool_name == "record_manager_decision":
        args = {"decision": action_code, "message": message}
    elif tool_name == "send_sms":
        recipient = (body.recipient or "").strip()
        if not re.fullmatch(r"\+?[0-9]{6,20}", recipient):
            raise api_error(request, 422, "RECIPIENT_INVALID", "短信收件号码格式无效。", "请输入 6 到 20 位数字，可带国家区号 +。")
        if priority not in {"normal", "high"}:
            raise api_error(request, 422, "ACTION_PRIORITY_INVALID", "短信优先级无效。", "请选择普通或高优先级。")
        args = {"phone": recipient, "message": message, "priority": priority}
    else:
        if action_policy and action_policy.delivery_channel == "WECOM_SIMULATOR_OUTBOX":
            priority = "critical"
        if priority not in {"info", "warning", "critical"}:
            raise api_error(request, 422, "ACTION_PRIORITY_INVALID", "告警级别无效。", "请选择提示、警告或严重。")
        args = {"message": message, "level": priority}
        if tool_name == "send_in_app_alert":
            args["recipient_scope"] = recipient_scope

    if supersedes_approval_id:
        previous = await db.fetch_one(
            """
            SELECT approval_id, status, event_id, task_id, tool_name, args
            FROM approval_requests
            WHERE approval_id = ? AND venue_id = ?
            """,
            (supersedes_approval_id, principal["venue_id"]),
        )
        if previous is None:
            raise api_error(
                request,
                404,
                "SUPERSEDED_APPROVAL_NOT_FOUND",
                "被替代的审批不存在。",
                "刷新审批历史后重新提交。",
            )
        if str(previous.get("status") or "").upper() != "REJECTED":
            raise api_error(
                request,
                409,
                "SUPERSEDED_APPROVAL_NOT_REJECTED",
                "只能重新提交已拒绝的审批。",
                "确认原审批状态后再试。",
            )
        if (
            previous.get("event_id") != event_id
            or previous.get("task_id") != task_id
            or previous.get("tool_name") != tool_name
        ):
            raise api_error(
                request,
                409,
                "SUPERSEDED_APPROVAL_MISMATCH",
                "重新提交的事件、任务或动作与原审批不一致。",
                "从原审批详情执行重新提交。",
            )
        previous_args = _decode_json_value(previous.get("args"), {})
        if action_code and previous_args.get("decision") != action_code:
            raise api_error(
                request,
                409,
                "SUPERSEDED_APPROVAL_MISMATCH",
                "重新提交的业务动作与原审批不一致。",
                "从原审批详情执行重新提交。",
            )

    if tool_name not in {"send_in_app_alert", "record_manager_decision"}:
        readiness = notification_action_readiness(tool_name, priority)
        if not readiness["available"]:
            missing = ", ".join(readiness["missing"])
            raise api_error(
                request,
                409,
                "INTEGRATION_DISABLED",
                "外部通知渠道未配置，当前动作已安全禁用。",
                f"请先配置并验收以下依赖：{missing}。",
            )

    engine = get_permission_engine()
    engine.set_database(db)
    permission = engine.get_tool_permission(tool_name)
    if get_tool(tool_name) is None or permission is None or permission.level != SensitivityLevel.APPROVAL:
        raise api_error(request, 409, "ACTION_NOT_APPROVABLE", "动作执行链尚未就绪。", "联系管理员检查工具注册与权限配置。")

    trace_id = request_trace_id(request)
    action_context = {
        "session_id": session_id,
        "event_id": event_id,
        "task_id": task_id,
        "supersedes_approval_id": supersedes_approval_id,
        "idempotency_key": normalized_idempotency_key,
        "user_id": principal["user_id"],
        "venue_id": principal["venue_id"],
        "agent_name": f"formal-client:{principal.get('username') or principal['user_id']}",
        "correlation_trace_id": trace_id,
        "action_code": action_code or None,
    }
    result = None
    if normalized_idempotency_key:
        existing_approval = await db.fetch_one(
            """
            SELECT approval_id FROM approval_requests
            WHERE venue_id = ? AND idempotency_key = ?
            """,
            (principal["venue_id"], normalized_idempotency_key),
        )
        if existing_approval is not None:
            result = await engine.check_and_execute(
                tool_name,
                args,
                action_context,
            )

    if result is None:
        delivery_snapshot = None
        if tool_name == "send_in_app_alert" and recipient_scope == "EVENT_PARTICIPANTS":
            try:
                delivery_snapshot = await build_event_participant_delivery(
                    db,
                    venue_id=principal["venue_id"],
                    event_id=event_id,
                )
            except SimulatorRecipientsNotReady as exc:
                raise api_error(
                    request,
                    409,
                    exc.code,
                    "内部系统接入收件人尚未全部就绪，未创建审批。",
                    "请让缺失人员先进入企业内部系统接入环境建立会话，或恢复其账号与接入身份后重试。",
                    details={"missing_recipients": exc.missing},
                ) from exc
        evidence_snapshot = {
            "captured_at": time.time(),
            "action_code": action_code or None,
            "event_business_id": event.get("business_id"),
            "task": {
                "id": task["id"],
                "business_id": task.get("business_id"),
                "event_id": task.get("event_id"),
                "session_id": task.get("session_id"),
                "description": task.get("description"),
                "status": task.get("status"),
                "result": _decode_json_value(task.get("result"), None),
                "result_schema": _decode_json_value(task.get("result_schema_json"), {}),
                "evidence_refs": _decode_json_value(task.get("evidence_refs_json"), []),
                "error": task.get("error"),
                "assigned_user_id": task.get("assigned_user_id"),
                "completed_at": task.get("completed_at"),
                "updated_at": task.get("updated_at"),
            },
        }
        if delivery_snapshot is not None:
            evidence_snapshot["delivery"] = delivery_snapshot
        result = await engine.check_and_execute(
            tool_name,
            args,
            {**action_context, "evidence_snapshot": evidence_snapshot},
        )
    if result.get("status") == "cooldown":
        raise api_error(request, 409, "ACTION_COOLDOWN", "同类动作仍在冷却期。", "稍后重试。")
    if result.get("status") == "idempotency_conflict":
        raise api_error(
            request,
            409,
            "APPROVAL_IDEMPOTENCY_CONFLICT",
            "该 Idempotency-Key 已用于不同的审批请求。",
            "复用原请求内容，或为新请求生成新的幂等键。",
        )
    if result.get("status") != "pending_approval":
        raise api_error(request, 409, "APPROVAL_NOT_CREATED", "未能创建审批请求。", "检查权限引擎状态后重试。")

    await write_audit(
        db,
        principal=principal,
        action="CONTROLLED_ACTION_REQUESTED",
        resource_type="approval",
        resource_id=result["approval_id"],
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "tool_name": tool_name,
            "session_id": session_id,
            "event_id": event_id,
            "task_id": task_id,
            "approval_business_id": result.get("business_id"),
            "idempotent_replay": bool(result.get("idempotent_replay")),
            "approval_status": "PENDING",
        },
    )
    return {**result, "trace_id": trace_id}


@router.get("/approvals", response_model=List[ApprovalResponse])
async def list_approvals(
    status: Optional[str] = "PENDING",
    admin_user: dict = Depends(get_admin_user),
    db=Depends(get_request_db),
):
    """
    列出审批请求

    Args:
        status: 筛选状态 (PENDING/APPROVED/REJECTED/ALL)

    Returns:
        审批请求列表
    """
    sql = "SELECT * FROM approval_requests WHERE venue_id = ?"
    params = [admin_user["venue_id"]]
    if status and status != "ALL":
        sql += " AND status = ?"
        params.append(status.upper())
    sql += " ORDER BY requested_at DESC"
    rows = await db.fetch_all(sql, tuple(params))
    responses = []
    for row in rows:
        args = json.loads(row["args"]) if isinstance(row.get("args"), str) else row.get("args") or {}
        execution_result = row.get("execution_result")
        if isinstance(execution_result, str):
            try:
                execution_result = json.loads(execution_result)
            except json.JSONDecodeError:
                execution_result = {"raw": execution_result}
        responses.append(
            ApprovalResponse(
                approval_id=row["approval_id"],
                business_id=row.get("business_id"),
                tool_name=row["tool_name"],
                args=args,
                session_id=row.get("session_id") or "",
                event_id=row.get("event_id"),
                task_id=row.get("task_id"),
                user_id=row.get("user_id") or "",
                requested_at=row["requested_at"],
                requested_by=row.get("requested_by") or "",
                status=row.get("status") or "PENDING",
                venue_id=row.get("venue_id") or "",
                reviewed_at=row.get("reviewed_at"),
                reviewed_by=row.get("reviewed_by"),
                comment=row.get("comment"),
                execution_result=execution_result,
                execution_error=row.get("execution_error"),
                correlation_trace_id=row.get("correlation_trace_id"),
                execution_trace_id=row.get("execution_trace_id"),
                execution_status=row.get("execution_status"),
                supersedes_approval_id=row.get("supersedes_approval_id"),
                idempotency_key=row.get("idempotency_key"),
                evidence_snapshot=_decode_json_value(
                    row.get("evidence_snapshot_json"),
                    {},
                ),
            )
        )
    return responses


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    request: Request,
    admin_user: dict = Depends(get_admin_user),
    db=Depends(get_request_db),
):
    """获取审批请求详情"""
    approval = await db.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ? AND venue_id = ?",
        (approval_id, admin_user["venue_id"]),
    )
    if not approval:
        raise api_error(request, 404, "APPROVAL_NOT_FOUND", "审批请求不存在。", "刷新审批列表后重试。")

    args = json.loads(approval["args"]) if isinstance(approval.get("args"), str) else approval.get("args") or {}
    execution_result = approval.get("execution_result")
    if isinstance(execution_result, str):
        try:
            execution_result = json.loads(execution_result)
        except json.JSONDecodeError:
            execution_result = {"raw": execution_result}

    return ApprovalResponse(
        approval_id=approval["approval_id"],
        business_id=approval.get("business_id"),
        tool_name=approval["tool_name"],
        args=args,
        session_id=approval.get("session_id") or "",
        event_id=approval.get("event_id"),
        task_id=approval.get("task_id"),
        user_id=approval.get("user_id") or "",
        requested_at=approval["requested_at"],
        requested_by=approval.get("requested_by") or "",
        status=approval.get("status") or "PENDING",
        venue_id=approval.get("venue_id") or "",
        reviewed_at=approval.get("reviewed_at"),
        reviewed_by=approval.get("reviewed_by"),
        comment=approval.get("comment"),
        execution_result=execution_result,
        execution_error=approval.get("execution_error"),
        correlation_trace_id=approval.get("correlation_trace_id"),
        execution_trace_id=approval.get("execution_trace_id"),
        execution_status=approval.get("execution_status"),
        supersedes_approval_id=approval.get("supersedes_approval_id"),
        idempotency_key=approval.get("idempotency_key"),
        evidence_snapshot=_decode_json_value(
            approval.get("evidence_snapshot_json"),
            {},
        ),
    )


@router.post("/approvals/{approval_id}/approve")
async def approve_request(
    approval_id: str,
    request: Request,
    body: ApproveRequest = None,
    admin_user: dict = Depends(get_admin_user),
    db=Depends(get_request_db),
):
    """
    批准审批请求

    Args:
        approval_id: 审批单 ID
        body: 审批意见 (可选)

    Returns:
        {"approved": True} 或错误
    """
    from ....core.permissions import get_permission_engine

    scenic_operations = getattr(request.app.state, "scenic_operations", None)
    engine = (
        scenic_operations.permission_engine
        if scenic_operations is not None
        else get_permission_engine()
    )
    engine.set_database(db)
    comment = body.comment if body else None
    approval = await db.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ? AND venue_id = ?",
        (approval_id, admin_user["venue_id"]),
    )
    request_level_trace_id = request_trace_id(request)
    trace_id = approval.get("correlation_trace_id") if approval else None
    trace_id = trace_id or request_level_trace_id
    request.state.trace_id = trace_id
    result = await engine.approve(
        approval_id=approval_id,
        reviewer=admin_user["user_id"],
        comment=comment,
        venue_id=admin_user["venue_id"],
        trace_id=trace_id,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Approval not found or already processed"
        )

    await write_audit(
        db,
        principal=admin_user,
        action="APPROVAL_APPROVED",
        resource_type="approval",
        resource_id=approval_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"comment": comment},
    )
    row = await db.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ? AND venue_id = ?",
        (approval_id, admin_user["venue_id"]),
    )
    execution_result = row.get("execution_result") if row else None
    if isinstance(execution_result, str):
        try:
            execution_result = json.loads(execution_result)
        except json.JSONDecodeError:
            execution_result = {"raw": execution_result}
    execution_status = execution_result.get("status") if isinstance(execution_result, dict) else None
    await write_audit(
        db,
        principal=admin_user,
        action="CONTROLLED_ACTION_EXECUTED",
        resource_type="approval",
        resource_id=approval_id,
        outcome="SUCCEEDED" if execution_status == "executed" else "FAILED",
        trace_id=trace_id,
        metadata={
            "tool_name": row.get("tool_name") if row else None,
            "execution_status": execution_status,
            "execution_error": row.get("execution_error") if row else None,
        },
    )
    if scenic_operations is not None and row and row.get("event_id"):
        await scenic_operations.reconcile_event(admin_user["venue_id"], row["event_id"])
    return {
        "approved": True,
        "approval_id": approval_id,
        "execution_result": execution_result,
        "execution_error": row.get("execution_error") if row else None,
        "trace_id": trace_id,
    }


@router.post("/approvals/{approval_id}/reject")
async def reject_request(
    approval_id: str,
    request: Request,
    body: RejectRequest = None,
    admin_user: dict = Depends(get_admin_user),
    db=Depends(get_request_db),
):
    """
    拒绝审批请求

    Args:
        approval_id: 审批单 ID
        body: 拒绝原因 (可选)

    Returns:
        {"rejected": True} 或错误
    """
    from ....core.permissions import get_permission_engine

    engine = get_permission_engine()
    engine.set_database(db)
    comment = body.comment if body else None
    approval = await db.fetch_one(
        "SELECT * FROM approval_requests WHERE approval_id = ? AND venue_id = ?",
        (approval_id, admin_user["venue_id"]),
    )
    request_level_trace_id = request_trace_id(request)
    trace_id = approval.get("correlation_trace_id") if approval else None
    trace_id = trace_id or request_level_trace_id
    request.state.trace_id = trace_id
    result = await engine.reject(
        approval_id=approval_id,
        reviewer=admin_user["user_id"],
        comment=comment,
        venue_id=admin_user["venue_id"],
        trace_id=trace_id,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Approval not found or already processed"
        )

    await write_audit(
        db,
        principal=admin_user,
        action="APPROVAL_REJECTED",
        resource_type="approval",
        resource_id=approval_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"comment": comment},
    )
    return {"rejected": True, "approval_id": approval_id, "trace_id": trace_id}


@router.get("/permissions/tools")
async def list_tool_permissions(
    _principal: dict = Depends(require_roles("admin", "manager")),
):
    """列出所有工具的权限配置"""
    from ....core.permissions import get_permission_engine

    engine = get_permission_engine()
    tools = []

    for tool_name, perm in engine._tool_permissions.items():
        tools.append({
            "tool_name": tool_name,
            "level": perm.level.value,
            "level_name": perm.level.name,
            "description": perm.description,
            "cooldown_seconds": perm.cooldown_seconds
        })

    return {"tools": tools}


# =============================================================================
# Sprint 4 新增: 管理后台 5 页面 API
# =============================================================================

class EventCreateRequest(BaseModel):
    raw_text: str
    event_type: str
    severity: str
    from_user: str
    venue_id: Optional[str] = ""
    source_id: Optional[str] = Field(None, max_length=128)


class PersonaDeleteRequest(BaseModel):
    pass


# 仪表盘统计
@router.get("/dashboard")
async def admin_stats(
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    """
    仪表盘统计数据：
    - 记忆库总量
    - 本周新增事件
    - 推送采纳率
    - 事件类型分布
    """
    try:
        # 记忆库总量
        total_mem = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM confirmed_events WHERE venue_id = ?",
            (principal["venue_id"],),
        )
        total_count = total_mem["cnt"] if total_mem else 0

        # 本周新增事件
        week_ago = time.time() - 7 * 86400
        week_mem = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM confirmed_events WHERE venue_id = ? AND confirmed_at > ?",
            (principal["venue_id"], week_ago)
        )
        week_count = week_mem["cnt"] if week_mem else 0

        # 推送采纳率
        total_push = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM push_logs WHERE venue_id = ?",
            (principal["venue_id"],),
        )
        adopted_push = await db.fetch_one(
            "SELECT COUNT(*) as cnt FROM push_logs WHERE venue_id = ? AND adoption_status = 'adopted'",
            (principal["venue_id"],),
        )
        total_push_cnt = total_push["cnt"] if total_push else 0
        adopted_cnt = adopted_push["cnt"] if adopted_push else 0
        adoption_rate = round(adopted_cnt / total_push_cnt * 100, 1) if total_push_cnt > 0 else 0

        # 事件类型分布
        type_dist = await db.fetch_all(
            """
            SELECT event_type, COUNT(*) as cnt FROM confirmed_events
            WHERE venue_id = ? GROUP BY event_type ORDER BY cnt DESC
            """,
            (principal["venue_id"],),
        )

        return {
            "total_memory_count": total_count,
            "week_new_events": week_count,
            "push_adoption_rate": adoption_rate,
            "total_pushes": total_push_cnt,
            "adopted_pushes": adopted_cnt,
            "event_type_distribution": [
                {"type": row["event_type"], "count": row["cnt"]}
                for row in type_dist
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 事件记忆库列表
@router.get("/events")
async def list_events(
    limit: int = 50,
    offset: int = 0,
    event_type: Optional[str] = None,
    from_user: Optional[str] = None,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """
    获取事件记忆库列表
    支持筛选：event_type, from_user
    """
    sql = """
        SELECT event.*,
               assignee.display_name AS assigned_to_name,
               reporter.display_name AS reporter_name,
               source_message.session_id AS source_session_id,
               source_message.channel AS source_channel
        FROM confirmed_events AS event
        LEFT JOIN users AS assignee
          ON assignee.id = event.assigned_to
         AND assignee.venue_id = event.venue_id
        LEFT JOIN users AS reporter
          ON reporter.id = event.from_user
         AND reporter.venue_id = event.venue_id
        LEFT JOIN message_runs AS source_message
          ON source_message.message_id = event.push_id
         AND source_message.venue_id = event.venue_id
        WHERE event.venue_id = ?
    """
    params = [principal["venue_id"]]

    if event_type:
        sql += " AND event.event_type = ?"
        params.append(event_type)
    if from_user:
        sql += " AND event.from_user = ?"
        params.append(from_user)

    sql += " ORDER BY event.created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = await db.fetch_all(sql, tuple(params))
    return {"events": rows, "limit": limit, "offset": offset}


# 事件详情
@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """获取事件详情"""
    row = await db.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (event_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(
            request,
            404,
            "EVENT_NOT_FOUND",
            "事件不存在。",
            "刷新事件列表后重试。",
        )
    dossier = await build_event_dossier(
        db,
        event=row,
        venue_id=principal["venue_id"],
    )
    return {**row, "dossier": dossier}


# 手动添加事件
@router.post("/events")
async def create_event(
    body: EventCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """手动录入历史事件"""
    from ....knowledge.db_client import save_confirmed_event

    trace_id = request_trace_id(request)
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise api_error(
            request,
            503,
            "VECTOR_STORE_UNAVAILABLE",
            "向量知识库尚未就绪。",
            "检查 PostgreSQL pgvector 与本地 bge-m3 状态后重试。",
            retryable=True,
        )

    event_id = None
    try:
        event_id = await save_confirmed_event(
            push_id=body.source_id or "manual",
            from_user=body.from_user,
            raw_text=body.raw_text,
            event_type=body.event_type,
            severity=body.severity,
            context_trigger_data={"source": "manual_entry"},
            source_type="HISTORY",
            venue_id=principal["venue_id"],
            trace_id=trace_id,
            database=db,
            vector_client=vector_store,
        )
        await write_audit(
            db,
            principal=principal,
            action="EVENT_CREATED",
            resource_type="event",
            resource_id=event_id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={"event_type": body.event_type, "severity": body.severity},
        )
        return {"event_id": event_id, "status": "created", "trace_id": trace_id}
    except Exception as exc:
        compensation_errors = []
        if event_id:
            try:
                vector_store.delete_experience(f"evt_{event_id}", strict=True)
            except Exception as compensation_exc:
                compensation_errors.append(type(compensation_exc).__name__)
            try:
                await db.execute(
                    "DELETE FROM event_activities WHERE event_id = ? AND venue_id = ?",
                    (event_id, principal["venue_id"]),
                )
                await db.execute(
                    "DELETE FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
                    (event_id, principal["venue_id"]),
                )
            except Exception as compensation_exc:
                compensation_errors.append(type(compensation_exc).__name__)
        await write_audit(
            db,
            principal=principal,
            action="EVENT_CREATE_FAILED",
            resource_type="event",
            resource_id=event_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={
                "error_type": type(exc).__name__,
                "compensation_errors": compensation_errors,
            },
        )
        raise api_error(
            request,
            503,
            "EVENT_CREATE_FAILED",
            "事件创建未完成。",
            "检查 PostgreSQL、pgvector 与本地 bge-m3 状态后重试。",
            retryable=True,
        ) from exc


# 推送日志
@router.get("/push_logs")
async def list_push_logs(
    limit: int = 50,
    offset: int = 0,
    adoption_status: Optional[str] = None,
    from_user: Optional[str] = None,
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    """获取推送日志列表"""
    sql = "SELECT * FROM push_logs WHERE venue_id = ?"
    params = [principal["venue_id"]]
    if from_user:
        sql += " AND from_user = ?"
        params.append(from_user)
    if adoption_status:
        sql += " AND adoption_status = ?"
        params.append(adoption_status)
    sql += " ORDER BY pushed_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    logs = await db.fetch_all(sql, tuple(params))
    import json as _json
    for row in logs:
        try:
            row["hit_keywords"] = _json.loads(row.get("hit_keywords") or "[]")
        except (TypeError, _json.JSONDecodeError):
            row["hit_keywords"] = []
    return {"push_logs": logs, "limit": limit, "offset": offset}


# 数字分身列表
@router.get("/personas")
async def list_personas(
    job_title: Optional[str] = None,
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    """获取数字分身列表"""
    from ....skills.persona_extract import PersonaExtractSkill

    sql = "SELECT * FROM personas WHERE venue_id = ?"
    params = [principal["venue_id"]]

    if job_title:
        sql += " AND job_title LIKE ?"
        params.append(f"%{job_title}%")
    sql += " ORDER BY created_at DESC"
    rows = await db.fetch_all(sql, tuple(params))

    # 解析 JSON 字段
    import json as _json
    for row in rows:
        try:
            row["logic_entries"] = _json.loads(row.get("logic_entries", "[]"))
        except Exception:
            row["logic_entries"] = []
    active_rows = await db.fetch_all(
        """
        SELECT id, source_persona_id, current_question
        FROM persona_interviews
        WHERE venue_id = ? AND status = 'ACTIVE' AND source_persona_id IS NOT NULL
        ORDER BY updated_at DESC
        """,
        (principal["venue_id"],),
    )
    active_by_persona = {}
    for interview in active_rows:
        active_by_persona.setdefault(interview["source_persona_id"], interview)
    for row in rows:
        active = active_by_persona.get(row["id"])
        row["active_interview_id"] = active.get("id") if active else None
        row["active_interview_question"] = (
            min(int(active["current_question"]), PersonaExtractSkill.TOTAL_QUESTIONS)
            if active
            else None
        )

    return {"personas": rows}


class PersonaCreateRequest(BaseModel):
    job_title: str
    venue_id: Optional[str] = ""
    description: Optional[str] = ""
    logic_entries: list = []


@router.post("/personas")
async def create_persona(
    body: PersonaCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """创建数字分身"""
    import uuid, time as _time

    persona_id = str(uuid.uuid4())
    now = _time.time()

    import json as _json
    logic_json = _json.dumps(body.logic_entries or [])

    await db.execute(
        """INSERT INTO personas (id, job_title, venue_id, description, logic_entries, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (persona_id, body.job_title, principal["venue_id"], body.description or "", logic_json, now, now),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="PERSONA_CREATED",
        resource_type="persona",
        resource_id=persona_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"job_title": body.job_title},
    )
    return {"persona_id": persona_id, "status": "created", "trace_id": trace_id}


# ============================================================================
# 访谈萃取 + 分身调用 API
# ============================================================================

class InterviewStartRequest(BaseModel):
    pass


class InterviewContinueRequest(BaseModel):
    interview_id: str
    answer: str


class InterviewFinalizeRequest(BaseModel):
    interview_id: str


class PersonaChatRequest(BaseModel):
    question: str


@router.get("/personas/{persona_id}/interview/active")
async def get_active_interview(
    persona_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """恢复当前场地中尚未完成的 Persona 访谈。"""
    from ....skills.persona_extract import PersonaExtractSkill

    persona = await db.fetch_one(
        "SELECT id FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not persona:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")
    row = await db.fetch_one(
        """
        SELECT id, current_question, raw_answers_json, trace_id, created_at, updated_at
        FROM persona_interviews
        WHERE source_persona_id = ? AND venue_id = ? AND status = 'ACTIVE'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (persona_id, principal["venue_id"]),
    )
    trace_id = request_trace_id(request)
    if not row:
        return {"interview": None, "trace_id": trace_id}

    skill = PersonaExtractSkill(db_client=db)
    current_question = int(row["current_question"])
    prompt = skill.interview_prompt(current_question)
    try:
        raw_answers = json.loads(row.get("raw_answers_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        raw_answers = {}
    return {
        "interview": {
            "interview_id": row["id"],
            "current_question": prompt["current_question"],
            "total_questions": prompt["total_questions"],
            "reply_text": prompt["reply_text"],
            "stage": prompt["stage"],
            "prompt_finalize": prompt["prompt_finalize"],
            "answered_questions": len(raw_answers),
            "origin_trace_id": row.get("trace_id"),
            "updated_at": row.get("updated_at"),
        },
        "trace_id": trace_id,
    }


@router.post("/personas/{persona_id}/interview/start")
async def start_interview(
    persona_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """启动老员工访谈萃取"""
    from ....skills.persona_extract import PersonaExtractSkill

    # 拿到 persona 的 job_title 和 venue_id
    row = await db.fetch_one(
        "SELECT job_title, venue_id FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")
    active = await db.fetch_one(
        """
        SELECT id FROM persona_interviews
        WHERE source_persona_id = ? AND venue_id = ? AND status = 'ACTIVE'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (persona_id, principal["venue_id"]),
    )
    if active:
        raise api_error(
            request,
            409,
            "INTERVIEW_ALREADY_ACTIVE",
            "该分身已有进行中的访谈。",
            "使用继续访谈入口恢复现有进度。",
        )

    skill = PersonaExtractSkill(db_client=db)
    trace_id = request_trace_id(request)
    result = await skill.run(
        context={
            "action": "start",
            "venue_id": row["venue_id"] or "",
            "job_title": row["job_title"],
            "source_persona_id": persona_id,
            "created_by": principal["user_id"],
        },
        trace_id=trace_id,
    )
    if not result.success:
        raise api_error(request, 409, "INTERVIEW_START_FAILED", result.reply_text, "检查 Persona 状态后重试。")
    interview_id = result.structured_data.get("interview_id")
    await write_audit(
        db,
        principal=principal,
        action="PERSONA_INTERVIEW_STARTED",
        resource_type="persona_interview",
        resource_id=interview_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"persona_id": persona_id},
    )

    return {
        "interview_id": interview_id,
        "current_question": result.structured_data.get("current_question"),
        "total_questions": result.structured_data.get("total_questions"),
        "reply_text": result.reply_text,
        "stage": result.structured_data.get("stage"),
        "trace_id": trace_id,
    }


@router.post("/personas/{persona_id}/interview/continue")
async def continue_interview(
    persona_id: str,
    body: InterviewContinueRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """继续访谈，回答当前问题"""
    from ....skills.persona_extract import PersonaExtractSkill

    row = await db.fetch_one(
        "SELECT id FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")
    skill = PersonaExtractSkill(db_client=db)
    trace_id = request_trace_id(request)
    result = await skill.run(
        context={
            "action": "continue",
            "interview_id": body.interview_id,
            "answer": body.answer,
            "venue_id": principal["venue_id"],
        },
        trace_id=trace_id,
    )
    if not result.success:
        error = result.structured_data.get("error")
        if error == "interview_not_found":
            raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在或不属于当前场地。", "返回分身页面重新开始访谈。")
        raise api_error(request, 409, "INTERVIEW_CONTINUE_FAILED", result.reply_text, "检查访谈状态后重试。")
    await write_audit(
        db,
        principal=principal,
        action="PERSONA_INTERVIEW_CONTINUED",
        resource_type="persona_interview",
        resource_id=body.interview_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "persona_id": persona_id,
            "current_question": result.structured_data.get("current_question"),
        },
    )

    return {
        "current_question": result.structured_data.get("current_question"),
        "total_questions": result.structured_data.get("total_questions"),
        "reply_text": result.reply_text,
        "stage": result.structured_data.get("stage"),
        "prompt_finalize": result.structured_data.get("prompt_finalize", False),
        "trace_id": trace_id,
    }


@router.post("/personas/{persona_id}/interview/finalize")
async def finalize_interview(
    persona_id: str,
    body: InterviewFinalizeRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """结束访谈，保存逻辑条目到分身"""
    from ....skills.persona_extract import PersonaExtractSkill

    row = await db.fetch_one(
        "SELECT id FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")
    skill = PersonaExtractSkill(db_client=db)
    trace_id = request_trace_id(request)
    result = await skill.run(
        context={
            "action": "finalize",
            "interview_id": body.interview_id,
            "venue_id": principal["venue_id"],
        },
        trace_id=trace_id,
    )
    if not result.success:
        error = result.structured_data.get("error")
        if error == "interview_not_found":
            raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在或不属于当前场地。", "返回分身页面重新开始访谈。")
        raise api_error(request, 409, "INTERVIEW_NOT_READY", result.reply_text, "完成剩余问题后再结束访谈。")

    persona_data = result.structured_data
    await write_audit(
        db,
        principal=principal,
        action="PERSONA_INTERVIEW_FINALIZED",
        resource_type="persona_interview",
        resource_id=body.interview_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "persona_id": persona_data.get("persona_id", persona_id),
            "total_entries": persona_data.get("total_entries", 0),
        },
    )

    return {
        "persona_id": persona_data.get("persona_id", persona_id),
        "total_entries": persona_data.get("total_entries", 0),
        "reply_text": result.reply_text,
        "trace_id": trace_id,
    }


@router.post("/personas/{persona_id}/chat")
async def persona_chat(
    persona_id: str,
    body: PersonaChatRequest,
    request: Request,
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    """向数字分身提问（第一人称回答）"""
    from ....skills.persona_extract.invoke import ask_persona

    # 拿到 persona 的 job_title 和 venue_id
    row = await db.fetch_one(
        "SELECT job_title, venue_id FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not row:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")

    trace_id = request_trace_id(request)
    try:
        result = await ask_persona(
            venue_id=row["venue_id"] or "",
            job_title=row["job_title"],
            question=body.question,
            trace_id=trace_id,
            database=db,
            persona_id=persona_id,
        )
    except Exception as exc:
        await write_audit(
            db,
            principal=principal,
            action="PERSONA_QUERY_FAILED",
            resource_type="persona",
            resource_id=persona_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={"error_type": type(exc).__name__},
        )
        raise api_error(
            request,
            503,
            "LLM_UNAVAILABLE",
            "数字分身暂时无法生成回答。",
            "稍后重试；如持续失败，请使用 Trace ID 联系管理员。",
            retryable=True,
        ) from exc

    await write_audit(
        db,
        principal=principal,
        action="PERSONA_QUERIED",
        resource_type="persona",
        resource_id=persona_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"entries_used": result.get("entries_used", 0)},
    )

    return {**result, "trace_id": trace_id}


# 删除分身
@router.delete("/personas/{persona_id}")
async def delete_persona(
    persona_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    """删除分身档案"""
    persona = await db.fetch_one(
        "SELECT id, job_title FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if not persona:
        raise api_error(request, 404, "PERSONA_NOT_FOUND", "分身不存在。", "刷新分身列表后重试。")
    rowcount = await db.execute(
        "DELETE FROM personas WHERE id = ? AND venue_id = ?",
        (persona_id, principal["venue_id"]),
    )
    if rowcount == 0:
        raise api_error(request, 409, "PERSONA_DELETE_CONFLICT", "分身状态已变化，删除未完成。", "刷新后重试。")
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="PERSONA_DELETED",
        resource_type="persona",
        resource_id=persona_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"job_title": persona["job_title"]},
    )
    return {"deleted": True, "persona_id": persona_id, "trace_id": trace_id}

