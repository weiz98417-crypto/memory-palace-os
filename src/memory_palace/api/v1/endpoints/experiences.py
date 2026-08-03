"""Governed expert-experience lifecycle for admin and employee clients."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error
from ....core.experience_assets import (
    DeepSeekExperienceDraftExtractor,
    EXPERIENCE_DRAFT_FIELDS,
    ExperienceDraftExtractionError,
    ExperienceStateError,
    authorization_allows,
    next_experience_status,
    validate_extracted_experience_draft,
)
from ....tools.llm_wrapper import llm_client


admin_router = APIRouter(dependencies=[Depends(require_auth)])
assistant_router = APIRouter(dependencies=[Depends(require_auth)])

INTERVIEW_QUESTIONS = (
    "哪些现场信号可以区分不同故障原因？",
    "正确的检查和处置顺序是什么，为什么？",
    "出现哪些红线时必须停止操作并升级处理？",
    "这条经验适用于哪些场地、岗位和情形，又有哪些例外？",
)
EDITABLE_CARD_FIELDS = {
    "title",
    "applicable_context",
    "signals",
    "decision_rule",
    "recommended_actions",
    "rationale",
    "prohibitions",
    "exceptions",
    "source_excerpts",
}
JSON_CARD_FIELDS = {
    "signals_json": "signals",
    "recommended_actions_json": "recommended_actions",
    "prohibitions_json": "prohibitions",
    "exceptions_json": "exceptions",
    "source_excerpts_json": "source_excerpts",
}


class AuthorizationScope(BaseModel):
    scope_type: Literal["VENUE", "DEPARTMENT", "ROLE", "JOB_TITLE", "USER"]
    scope_value: str = Field(..., min_length=1, max_length=160)

    @field_validator("scope_value")
    @classmethod
    def normalize_scope_value(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("授权值不能为空")
        return value


class ExpertCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=80)
    job_title: str = Field(..., min_length=1, max_length=120)
    department: str = Field(..., min_length=1, max_length=120)
    years_experience: int = Field(0, ge=0, le=80)
    expertise: list[str] = Field(default_factory=list, max_length=30)
    authorization_status: Literal["PENDING", "SIGNED"] = "PENDING"
    authorization_statement: Optional[str] = Field(None, min_length=10, max_length=2000)


class ExpertUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    job_title: Optional[str] = Field(None, min_length=1, max_length=120)
    department: Optional[str] = Field(None, min_length=1, max_length=120)
    years_experience: Optional[int] = Field(None, ge=0, le=80)
    expertise: Optional[list[str]] = Field(None, max_length=30)
    authorization_status: Optional[Literal["PENDING", "SIGNED"]] = None
    authorization_statement: Optional[str] = Field(None, min_length=10, max_length=2000)
    status: Optional[Literal["ACTIVE", "INACTIVE"]] = None


class InterviewCreateRequest(BaseModel):
    expert_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=2, max_length=200)
    source_event_id: Optional[str] = Field(None, max_length=80)
    authorization_scopes: list[AuthorizationScope] = Field(..., min_length=1, max_length=30)


class InterviewAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=8000)
    source_excerpt: Optional[str] = Field(None, max_length=2000)


class ExperienceCardUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    applicable_context: Optional[str] = Field(None, min_length=2, max_length=4000)
    signals: Optional[list[str]] = Field(None, min_length=1, max_length=50)
    decision_rule: Optional[str] = Field(None, min_length=2, max_length=4000)
    recommended_actions: Optional[list[str]] = Field(None, min_length=1, max_length=50)
    rationale: Optional[str] = Field(None, min_length=2, max_length=4000)
    prohibitions: Optional[list[str]] = Field(None, min_length=1, max_length=50)
    exceptions: Optional[list[str]] = Field(None, min_length=1, max_length=50)
    source_excerpts: Optional[list[str]] = Field(None, min_length=1, max_length=100)
    change_note: str = Field(..., min_length=2, max_length=1000)


class ReviewRequest(BaseModel):
    comment: str = Field(..., min_length=2, max_length=2000)


class OptionalReviewRequest(BaseModel):
    comment: str = Field("", max_length=2000)


class ExperienceSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(5, ge=1, le=20)
    threshold: float = Field(0.0, ge=0.0, le=1.0)
    session_id: Optional[str] = Field(None, max_length=64)


class ExperienceFeedbackRequest(BaseModel):
    feedback: Literal["HELPFUL", "NOT_APPLICABLE", "NEEDS_EXPERT"]
    session_id: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=2000)


def _now() -> float:
    return time.time()


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_expert(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["expertise"] = _json(result.pop("expertise_json", "[]"), [])
    return result


def _decode_interview(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    index = int(result.get("current_question_index") or 0)
    result["progress"] = {
        "answered": index,
        "total": len(INTERVIEW_QUESTIONS),
        "percent": min(100, round(index / len(INTERVIEW_QUESTIONS) * 100)),
    }
    result["next_question"] = INTERVIEW_QUESTIONS[index] if index < len(INTERVIEW_QUESTIONS) else None
    return result


def _decode_card(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for stored_name, public_name in JSON_CARD_FIELDS.items():
        result[public_name] = _json(result.pop(stored_name, "[]"), [])
    result["source"] = {
        "expert_id": result.get("expert_id"),
        "expert_name": result.get("expert_name"),
        "interview_id": result.get("source_interview_id"),
        "interview_business_id": result.get("interview_business_id"),
        "event_id": result.get("source_event_id"),
    }
    return result


async def _business_id(db, prefix: str, table: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(20):
        candidate = f"{prefix}-{day}-{uuid.uuid4().hex[:4].upper()}"
        exists = await db.fetch_one(f"SELECT 1 AS found FROM {table} WHERE business_id = ?", (candidate,))
        if exists is None:
            return candidate
    raise RuntimeError(f"cannot allocate {prefix} business id")


async def _expert_row(db, expert_id: str, venue_id: str) -> Optional[dict[str, Any]]:
    return await db.fetch_one(
        "SELECT * FROM expert_profiles WHERE id = ? AND venue_id = ?",
        (expert_id, venue_id),
    )


async def _interview_row(db, interview_id: str, venue_id: str) -> Optional[dict[str, Any]]:
    return await db.fetch_one(
        """
        SELECT i.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department
        FROM experience_interviews i
        JOIN expert_profiles e ON e.id = i.expert_id AND e.venue_id = i.venue_id
        WHERE i.id = ? AND i.venue_id = ?
        """,
        (interview_id, venue_id),
    )


async def _card_row(db, card_id: str, venue_id: str) -> Optional[dict[str, Any]]:
    return await db.fetch_one(
        """
        SELECT c.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department,
               i.business_id AS interview_business_id
        FROM experience_cards c
        JOIN expert_profiles e ON e.id = c.expert_id AND e.venue_id = c.venue_id
        LEFT JOIN experience_interviews i
          ON i.id = c.source_interview_id AND i.venue_id = c.venue_id
        WHERE c.id = ? AND c.venue_id = ?
        """,
        (card_id, venue_id),
    )


async def _card_scopes(db, card_id: str, venue_id: str) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT scope_type, scope_value
        FROM experience_authorizations
        WHERE card_id = ? AND venue_id = ?
        ORDER BY scope_type, scope_value
        """,
        (card_id, venue_id),
    )


async def _interview_scopes(db, interview_id: str, venue_id: str) -> list[dict[str, Any]]:
    return await db.fetch_all(
        """
        SELECT scope_type, scope_value
        FROM experience_interview_authorizations
        WHERE interview_id = ? AND venue_id = ?
        ORDER BY scope_type, scope_value
        """,
        (interview_id, venue_id),
    )


async def _card_payload(db, row: dict[str, Any]) -> dict[str, Any]:
    card = _decode_card(row)
    card["authorization_scopes"] = await _card_scopes(db, row["id"], row["venue_id"])
    return card


def _card_snapshot(row: dict[str, Any], scopes: list[dict[str, Any]]) -> dict[str, Any]:
    card = _decode_card(row)
    keep = {
        "business_id",
        "title",
        "applicable_context",
        "signals",
        "decision_rule",
        "recommended_actions",
        "rationale",
        "prohibitions",
        "exceptions",
        "source_excerpts",
        "source",
        "current_version",
    }
    snapshot = {key: card.get(key) for key in keep}
    snapshot["authorization_scopes"] = scopes
    return snapshot


def _card_draft(row: dict[str, Any]) -> dict[str, Any]:
    decoded = _decode_card(row)
    return {field: decoded.get(field) for field in EXPERIENCE_DRAFT_FIELDS}


async def _validate_card_source_excerpts(
    db,
    request: Request,
    row: dict[str, Any],
    draft: dict[str, Any],
) -> dict[str, Any]:
    interview_id = row.get("source_interview_id")
    if not interview_id:
        raise api_error(
            request,
            422,
            "EXPERIENCE_SOURCE_EXCERPTS_INVALID",
            "经验来源无法回溯到访谈原文。",
            "使用带有完整访谈来源的经验卡后重试。",
        )
    turns = await db.fetch_all(
        "SELECT * FROM experience_interview_turns WHERE interview_id = ? AND venue_id = ? ORDER BY turn_number",
        (interview_id, row["venue_id"]),
    )
    try:
        return validate_extracted_experience_draft(draft, {"turns": turns})
    except ExperienceDraftExtractionError as exc:
        raise api_error(
            request,
            422,
            "EXPERIENCE_SOURCE_EXCERPTS_INVALID",
            "经验来源原话无法回溯到访谈记录。",
            "仅保留访谈回答中逐字出现的来源片段。",
        ) from exc


async def _write_review(
    db,
    *,
    card: dict[str, Any],
    action: str,
    from_status: str,
    to_status: str,
    comment: str,
    actor_id: str,
) -> None:
    await db.execute(
        """
        INSERT INTO experience_reviews (
            id, venue_id, card_id, action, from_status, to_status,
            comment, actor_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            card["venue_id"],
            card["id"],
            action,
            from_status,
            to_status,
            comment.strip(),
            actor_id,
            _now(),
        ),
    )


async def _write_card_version(
    db,
    *,
    row: dict[str, Any],
    version: int,
    change_note: str,
    actor_id: str,
) -> None:
    scopes = await _card_scopes(db, row["id"], row["venue_id"])
    await db.execute(
        """
        INSERT INTO experience_card_versions (
            id, venue_id, card_id, version_number, snapshot_json,
            change_note, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            row["venue_id"],
            row["id"],
            version,
            _json_text(_card_snapshot(row, scopes)),
            change_note.strip(),
            actor_id,
            _now(),
        ),
    )


async def _principal_with_profile(db, principal: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(principal)
    user = await db.fetch_one(
        "SELECT * FROM users WHERE id = ? AND venue_id = ?",
        (principal["user_id"], principal["venue_id"]),
    )
    if user:
        enriched["department"] = user.get("department") or ""
        enriched["job_title"] = user.get("job_title") or ""
    expert = await db.fetch_one(
        """
        SELECT department, job_title FROM expert_profiles
        WHERE user_id = ? AND venue_id = ? AND status = 'ACTIVE'
        """,
        (principal["user_id"], principal["venue_id"]),
    )
    if expert:
        enriched["department"] = expert.get("department") or enriched.get("department", "")
        enriched["job_title"] = expert.get("job_title") or enriched.get("job_title", "")
    return enriched


async def _resolve_employee_principal(
    db,
    request: Request,
    principal: dict[str, Any],
    acting_user_id: Optional[str],
) -> dict[str, Any]:
    """Resolve a controlled employee identity without changing the audit actor."""
    if acting_user_id is None:
        return principal

    target_id = acting_user_id.strip()
    if target_id != principal["user_id"] and principal.get("role") not in {"admin", "manager"}:
        raise api_error(
            request,
            403,
            "EXPERIENCE_ACTING_IDENTITY_FORBIDDEN",
            "普通员工不能代办其他员工的经验工作。",
            "使用本人身份继续，或请管理员、经理代办。",
        )

    target = await db.fetch_one(
        """
        SELECT u.id AS user_id, u.username, u.display_name, u.role, u.venue_id, u.status
        FROM users u
        WHERE u.id = ?
          AND u.venue_id = ?
          AND u.status = 'ACTIVE'
          AND u.role IN ('operator', 'manager')
          AND EXISTS (
              SELECT 1
              FROM channel_identities ci
              WHERE ci.venue_id = u.venue_id
                AND ci.user_id = u.id
                AND ci.channel = 'WECOM_SIMULATOR'
                AND ci.status = 'ACTIVE'
          )
        """,
        (target_id, principal["venue_id"]),
    )
    if target is None:
        raise api_error(
            request,
            404,
            "EXPERIENCE_ACTING_IDENTITY_NOT_FOUND",
            "目标员工不存在、未绑定企微或已停用。",
            "从当前场地的已绑定员工列表中重新选择。",
        )

    effective = dict(principal)
    effective.update(
        {
            "user_id": target["user_id"],
            "username": target.get("username") or target["user_id"],
            "display_name": target.get("display_name") or "",
            "role": target.get("role") or principal.get("role"),
            "venue_id": target["venue_id"],
        }
    )
    if target_id != principal["user_id"]:
        await write_audit(
            db,
            principal=principal,
            action="EXPERIENCE_ACTING_IDENTITY_USED",
            resource_type="user",
            resource_id=target_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata={
                "acting_user_id": target_id,
                "actor_user_id": principal["user_id"],
                "actor_role": principal.get("role"),
                "entry": "assistant_experience",
            },
        )
    return effective


def _acting_audit_metadata(
    principal: dict[str, Any],
    employee: dict[str, Any],
    **metadata: Any,
) -> dict[str, Any]:
    if employee["user_id"] == principal["user_id"]:
        return metadata
    return {
        **metadata,
        "acting_user_id": employee["user_id"],
        "actor_user_id": principal["user_id"],
        "actor_role": principal.get("role"),
    }


def _vector_store(request: Request):
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is None:
        raise api_error(
            request,
            503,
            "EXPERIENCE_INDEX_NOT_READY",
            "经验检索服务尚未就绪。",
            "稍后重试或联系管理员检查向量服务。",
            retryable=True,
        )
    return vector_store


def _require_expert_owner(request: Request, row: dict[str, Any], principal: dict[str, Any]) -> None:
    if row.get("expert_user_id") != principal["user_id"]:
        raise api_error(
            request,
            403,
            "EXPERIENCE_EXPERT_REQUIRED",
            "只有受邀专家本人可以执行此操作。",
            "切换到访谈邀请对应的专家账号。",
        )


def _require_transition(request: Request, current: str, action: str) -> str:
    try:
        return next_experience_status(current, action)
    except ExperienceStateError as exc:
        raise api_error(
            request,
            409,
            "EXPERIENCE_STATE_CONFLICT",
            "当前经验状态不允许执行该操作。",
            "刷新经验详情并按状态提示继续。",
        ) from exc


@admin_router.get("/experts")
async def list_experts(
    query: Optional[str] = Query(None, max_length=120),
    expert_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM expert_profiles WHERE venue_id = ?"
    params: list[Any] = [principal["venue_id"]]
    if expert_status:
        sql += " AND status = ?"
        params.append(expert_status.upper())
    if query:
        sql += " AND (display_name LIKE ? OR job_title LIKE ? OR department LIKE ?)"
        keyword = f"%{query.strip()}%"
        params.extend((keyword, keyword, keyword))
    sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    rows = await db.fetch_all(sql, tuple(params))
    return {"experts": [_decode_expert(row) for row in rows], "limit": limit, "offset": offset}


@admin_router.post("/experts", status_code=status.HTTP_201_CREATED)
async def create_expert(
    body: ExpertCreateRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    user = await db.fetch_one(
        "SELECT id FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
        (body.user_id, principal["venue_id"]),
    )
    if user is None:
        raise api_error(
            request,
            400,
            "EXPERT_USER_INVALID",
            "专家必须关联当前场地的有效员工。",
            "从当前场地员工列表中重新选择。",
        )
    duplicate = await db.fetch_one(
        "SELECT id FROM expert_profiles WHERE user_id = ? AND venue_id = ?",
        (body.user_id, principal["venue_id"]),
    )
    if duplicate:
        raise api_error(request, 409, "EXPERT_EXISTS", "该员工已经有专家档案。", "打开现有档案进行更新。")
    if body.authorization_status == "SIGNED" and not body.authorization_statement:
        raise api_error(
            request,
            422,
            "EXPERT_AUTHORIZATION_STATEMENT_REQUIRED",
            "签署经验使用授权时必须保存专家确认的授权声明。",
            "填写授权声明后重新保存专家档案。",
        )

    expert_id = uuid.uuid4().hex
    business_id = await _business_id(db, "ZJ", "expert_profiles")
    now = _now()
    await db.execute(
        """
        INSERT INTO expert_profiles (
            id, business_id, venue_id, user_id, display_name, job_title,
            department, years_experience, expertise_json, authorization_status,
            authorization_statement, authorization_signed_at, status,
            created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
        """,
        (
            expert_id,
            business_id,
            principal["venue_id"],
            body.user_id,
            body.display_name.strip(),
            body.job_title.strip(),
            body.department.strip(),
            body.years_experience,
            _json_text([item.strip() for item in body.expertise if item.strip()]),
            body.authorization_status,
            body.authorization_statement.strip() if body.authorization_statement else None,
            now if body.authorization_status == "SIGNED" else None,
            principal["user_id"],
            now,
            now,
        ),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="EXPERT_CREATED",
        resource_type="expert",
        resource_id=expert_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "business_id": business_id,
            "display_name": body.display_name.strip(),
            "authorization_status": body.authorization_status,
        },
    )
    row = await _expert_row(db, expert_id, principal["venue_id"])
    return {"expert": _decode_expert(row), "trace_id": trace_id}


@admin_router.get("/experts/{expert_id}")
async def get_expert(
    expert_id: str,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _expert_row(db, expert_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERT_NOT_FOUND", "当前场地不存在该专家。", "刷新专家列表后重试。")
    return {"expert": _decode_expert(row)}


@admin_router.patch("/experts/{expert_id}")
async def update_expert(
    expert_id: str,
    body: ExpertUpdateRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _expert_row(db, expert_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERT_NOT_FOUND", "当前场地不存在该专家。", "刷新专家列表后重试。")
    updates = body.model_dump(exclude_none=True)
    if "expertise" in updates:
        updates["expertise_json"] = _json_text([item.strip() for item in updates.pop("expertise") if item.strip()])
    if updates.get("authorization_status") == "SIGNED":
        statement = updates.get("authorization_statement") or row.get("authorization_statement")
        if not statement:
            raise api_error(
                request,
                422,
                "EXPERT_AUTHORIZATION_STATEMENT_REQUIRED",
                "签署经验使用授权时必须保存专家确认的授权声明。",
                "填写授权声明后重新保存。",
            )
        updates["authorization_statement"] = statement.strip()
        updates["authorization_signed_at"] = row.get("authorization_signed_at") or _now()
    elif updates.get("authorization_status") == "PENDING":
        updates["authorization_signed_at"] = None
    if not updates:
        return {"expert": _decode_expert(row)}
    updates["updated_at"] = _now()
    await db.execute(
        f"UPDATE expert_profiles SET {', '.join(f'{key} = ?' for key in updates)} WHERE id = ? AND venue_id = ?",
        (*updates.values(), expert_id, principal["venue_id"]),
    )
    updated = await _expert_row(db, expert_id, principal["venue_id"])
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action=(
            "EXPERT_AUTHORIZATION_SIGNED"
            if updates.get("authorization_status") == "SIGNED"
            else "EXPERT_UPDATED"
        ),
        resource_type="expert",
        resource_id=expert_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    return {"expert": _decode_expert(updated), "trace_id": trace_id}


@admin_router.get("/experience-interviews")
async def list_interviews(
    interview_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = """
        SELECT i.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department
        FROM experience_interviews i
        JOIN expert_profiles e ON e.id = i.expert_id AND e.venue_id = i.venue_id
        WHERE i.venue_id = ?
    """
    params: list[Any] = [principal["venue_id"]]
    if interview_status:
        sql += " AND i.status = ?"
        params.append(interview_status.upper())
    sql += " ORDER BY i.updated_at DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    rows = await db.fetch_all(sql, tuple(params))
    return {"interviews": [_decode_interview(row) for row in rows], "limit": limit, "offset": offset}


@admin_router.post("/experience-interviews", status_code=status.HTTP_201_CREATED)
async def create_interview(
    body: InterviewCreateRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    expert = await _expert_row(db, body.expert_id, principal["venue_id"])
    if expert is None or expert.get("status") != "ACTIVE":
        raise api_error(request, 404, "EXPERT_NOT_FOUND", "当前场地不存在可用专家。", "选择有效专家后重试。")
    if expert.get("authorization_status") != "SIGNED":
        raise api_error(
            request,
            409,
            "EXPERT_AUTHORIZATION_REQUIRED",
            "该专家尚未签署经验使用授权，不能发起访谈。",
            "先在专家档案中保存授权声明和签署状态。",
        )
    interview_id = uuid.uuid4().hex
    business_id = await _business_id(db, "FT", "experience_interviews")
    now = _now()
    await db.execute(
        """
        INSERT INTO experience_interviews (
            id, business_id, venue_id, expert_id, title, source_event_id,
            status, current_question_index, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'INVITED', 0, ?, ?, ?)
        """,
        (
            interview_id,
            business_id,
            principal["venue_id"],
            body.expert_id,
            body.title.strip(),
            body.source_event_id.strip() if body.source_event_id else None,
            principal["user_id"],
            now,
            now,
        ),
    )
    for scope in body.authorization_scopes:
        await db.execute(
            """
            INSERT INTO experience_interview_authorizations (
                id, venue_id, interview_id, scope_type, scope_value, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                principal["venue_id"],
                interview_id,
                scope.scope_type,
                scope.scope_value,
                principal["user_id"],
                now,
            ),
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="EXPERIENCE_INTERVIEW_INVITED",
        resource_type="experience_interview",
        resource_id=interview_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"business_id": business_id, "expert_id": body.expert_id},
    )
    row = await _interview_row(db, interview_id, principal["venue_id"])
    result = _decode_interview(row)
    result["authorization_scopes"] = await _interview_scopes(db, interview_id, principal["venue_id"])
    return {"interview": result, "trace_id": trace_id}


@admin_router.get("/experience-interviews/{interview_id}")
async def get_admin_interview(
    interview_id: str,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _interview_row(db, interview_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "当前场地不存在该访谈。", "刷新访谈列表后重试。")
    turns = await db.fetch_all(
        "SELECT * FROM experience_interview_turns WHERE interview_id = ? AND venue_id = ? ORDER BY turn_number",
        (interview_id, principal["venue_id"]),
    )
    result = _decode_interview(row)
    result["turns"] = turns
    result["authorization_scopes"] = await _interview_scopes(db, interview_id, principal["venue_id"])
    return {"interview": result}


@assistant_router.get("/experience")
async def employee_experience_home(
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    expert = await db.fetch_one(
        "SELECT * FROM expert_profiles WHERE user_id = ? AND venue_id = ?",
        (employee["user_id"], employee["venue_id"]),
    )
    if expert is None:
        return {"expert": None, "interviews": [], "cards": []}
    interviews = await db.fetch_all(
        """
        SELECT i.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department
        FROM experience_interviews i
        JOIN expert_profiles e ON e.id = i.expert_id AND e.venue_id = i.venue_id
        WHERE i.expert_id = ? AND i.venue_id = ?
        ORDER BY i.updated_at DESC
        """,
        (expert["id"], employee["venue_id"]),
    )
    cards = await db.fetch_all(
        """
        SELECT c.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department,
               i.business_id AS interview_business_id
        FROM experience_cards c
        JOIN expert_profiles e ON e.id = c.expert_id AND e.venue_id = c.venue_id
        LEFT JOIN experience_interviews i ON i.id = c.source_interview_id AND i.venue_id = c.venue_id
        WHERE c.expert_id = ? AND c.venue_id = ?
        ORDER BY c.updated_at DESC
        """,
        (expert["id"], employee["venue_id"]),
    )
    return {
        "expert": _decode_expert(expert),
        "interviews": [_decode_interview(row) for row in interviews],
        "cards": [await _card_payload(db, row) for row in cards],
    }


@assistant_router.get("/experience/interviews/{interview_id}")
async def get_employee_interview(
    interview_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _interview_row(db, interview_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在。", "返回经验共创列表后重试。")
    _require_expert_owner(request, row, employee)
    turns = await db.fetch_all(
        "SELECT * FROM experience_interview_turns WHERE interview_id = ? AND venue_id = ? ORDER BY turn_number",
        (interview_id, employee["venue_id"]),
    )
    result = _decode_interview(row)
    result["turns"] = turns
    result["authorization_scopes"] = await _interview_scopes(db, interview_id, employee["venue_id"])
    return {"interview": result}


@assistant_router.post("/experience/interviews/{interview_id}/accept")
async def accept_interview(
    interview_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _interview_row(db, interview_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈邀请不存在。", "刷新经验共创列表后重试。")
    _require_expert_owner(request, row, employee)
    if row["status"] == "INVITED":
        now = _now()
        trace_id = request_trace_id(request)
        async with db.transaction() as transaction:
            await transaction.execute(
                "UPDATE experience_interviews SET status = 'ACCEPTED', accepted_at = ?, updated_at = ? WHERE id = ? AND venue_id = ? AND status = 'INVITED'",
                (now, now, interview_id, employee["venue_id"]),
            )
            await write_audit(
                transaction,
                principal=principal,
                action="EXPERIENCE_INTERVIEW_ACCEPTED",
                resource_type="experience_interview",
                resource_id=interview_id,
                outcome="SUCCEEDED",
                trace_id=trace_id,
                metadata=_acting_audit_metadata(
                    principal,
                    employee,
                    business_id=row["business_id"],
                ),
            )
            updated = await _interview_row(transaction, interview_id, employee["venue_id"])
    elif row["status"] not in {"ACCEPTED", "IN_PROGRESS", "PAUSED"}:
        raise api_error(request, 409, "INTERVIEW_STATE_CONFLICT", "当前访谈不能接受。", "刷新访谈状态后继续。")
    else:
        updated = row
    return {"interview": _decode_interview(updated)}


@assistant_router.post("/experience/interviews/{interview_id}/answers")
async def answer_interview_question(
    interview_id: str,
    body: InterviewAnswerRequest,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
):
    answer = body.answer.strip()
    if not answer:
        raise api_error(
            request,
            422,
            "INTERVIEW_ANSWER_REQUIRED",
            "回答不能为空。",
            "填写本题回答后再提交。",
        )
    source_excerpt = (body.source_excerpt or "").strip() or answer
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    now = _now()
    turn_id = uuid.uuid4().hex
    idempotent_replay = False
    async with db.transaction() as transaction:
        row = await _interview_row(transaction, interview_id, employee["venue_id"])
        if row is None:
            raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在。", "刷新访谈后重试。")
        _require_expert_owner(request, row, employee)
        if row["status"] not in {"ACCEPTED", "IN_PROGRESS"}:
            raise api_error(request, 409, "INTERVIEW_NOT_ACTIVE", "访谈当前未处于回答状态。", "接受或恢复访谈后再回答。")
        turn_number = int(row.get("current_question_index") or 0) + 1
        stable_key = (idempotency_key or f"{interview_id}:{turn_number}").strip()
        existing = await transaction.fetch_one(
            "SELECT * FROM experience_interview_turns WHERE venue_id = ? AND interview_id = ? AND idempotency_key = ?",
            (employee["venue_id"], interview_id, stable_key),
        )
        if existing:
            turn = existing
            updated = row
            idempotent_replay = True
        else:
            if turn_number > len(INTERVIEW_QUESTIONS):
                raise api_error(request, 409, "INTERVIEW_ANSWERS_COMPLETE", "访谈问题已经回答完毕。", "检查提取预览并完成访谈。")
            inserted = await transaction.execute(
                """
                INSERT INTO experience_interview_turns (
                    id, venue_id, interview_id, turn_number, question_text,
                    answer_text, source_excerpt, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    turn_id,
                    employee["venue_id"],
                    interview_id,
                    turn_number,
                    INTERVIEW_QUESTIONS[turn_number - 1],
                    answer,
                    source_excerpt[:2000],
                    stable_key,
                    now,
                    now,
                ),
            )
            if inserted == 0:
                existing = await transaction.fetch_one(
                    "SELECT * FROM experience_interview_turns WHERE venue_id = ? AND interview_id = ? AND idempotency_key = ?",
                    (employee["venue_id"], interview_id, stable_key),
                )
                if existing is None:
                    raise api_error(
                        request,
                        409,
                        "INTERVIEW_ANSWER_CONFLICT",
                        "本题已由另一个请求回答。",
                        "刷新访谈进度后继续。",
                    )
                turn = existing
                updated = await _interview_row(transaction, interview_id, employee["venue_id"])
                idempotent_replay = True
            else:
                await transaction.execute(
                    """
                    UPDATE experience_interviews
                    SET status = 'IN_PROGRESS', current_question_index = ?, updated_at = ?
                    WHERE id = ? AND venue_id = ?
                    """,
                    (turn_number, now, interview_id, employee["venue_id"]),
                )
                await write_audit(
                    transaction,
                    principal=principal,
                    action="EXPERIENCE_INTERVIEW_ANSWERED",
                    resource_type="experience_interview",
                    resource_id=interview_id,
                    outcome="SUCCEEDED",
                    trace_id=request_trace_id(request),
                    metadata=_acting_audit_metadata(
                        principal,
                        employee,
                        business_id=row["business_id"],
                        turn_number=turn_number,
                        idempotency_key=stable_key,
                    ),
                )
                updated = await _interview_row(transaction, interview_id, employee["venue_id"])
                turn = await transaction.fetch_one(
                    "SELECT * FROM experience_interview_turns WHERE id = ?",
                    (turn_id,),
                )
    return {"turn": turn, "interview": _decode_interview(updated), "idempotent_replay": idempotent_replay}


@assistant_router.post("/experience/interviews/{interview_id}/pause")
async def pause_interview(
    interview_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _interview_row(db, interview_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在。", "刷新访谈后重试。")
    _require_expert_owner(request, row, employee)
    if row["status"] not in {"ACCEPTED", "IN_PROGRESS"}:
        raise api_error(request, 409, "INTERVIEW_NOT_ACTIVE", "当前访谈不能暂停。", "刷新访谈状态后重试。")
    now = _now()
    async with db.transaction() as transaction:
        await transaction.execute(
            "UPDATE experience_interviews SET status = 'PAUSED', paused_at = ?, updated_at = ? WHERE id = ? AND venue_id = ?",
            (now, now, interview_id, employee["venue_id"]),
        )
        await write_audit(
            transaction,
            principal=principal,
            action="EXPERIENCE_INTERVIEW_PAUSED",
            resource_type="experience_interview",
            resource_id=interview_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata=_acting_audit_metadata(
                principal,
                employee,
                business_id=row["business_id"],
            ),
        )
        updated = await _interview_row(transaction, interview_id, employee["venue_id"])
    return {"interview": _decode_interview(updated)}


@assistant_router.post("/experience/interviews/{interview_id}/resume")
async def resume_interview(
    interview_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _interview_row(db, interview_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在。", "刷新访谈后重试。")
    _require_expert_owner(request, row, employee)
    if row["status"] != "PAUSED":
        raise api_error(request, 409, "INTERVIEW_NOT_PAUSED", "访谈当前不需要恢复。", "继续当前访谈即可。")
    now = _now()
    async with db.transaction() as transaction:
        await transaction.execute(
            "UPDATE experience_interviews SET status = 'IN_PROGRESS', paused_at = NULL, updated_at = ? WHERE id = ? AND venue_id = ?",
            (now, interview_id, employee["venue_id"]),
        )
        await write_audit(
            transaction,
            principal=principal,
            action="EXPERIENCE_INTERVIEW_RESUMED",
            resource_type="experience_interview",
            resource_id=interview_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata=_acting_audit_metadata(
                principal,
                employee,
                business_id=row["business_id"],
            ),
        )
        updated = await _interview_row(transaction, interview_id, employee["venue_id"])
    return {"interview": _decode_interview(updated)}


@assistant_router.post(
    "/experience/interviews/{interview_id}/complete",
    status_code=status.HTTP_201_CREATED,
)
async def complete_interview(
    interview_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _interview_row(db, interview_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "INTERVIEW_NOT_FOUND", "访谈不存在。", "刷新访谈后重试。")
    _require_expert_owner(request, row, employee)
    existing = await db.fetch_one(
        "SELECT id FROM experience_cards WHERE source_interview_id = ? AND venue_id = ?",
        (interview_id, employee["venue_id"]),
    )
    if existing:
        existing_row = await _card_row(db, existing["id"], employee["venue_id"])
        return {"card": await _card_payload(db, existing_row), "idempotent_replay": True}
    if row["status"] not in {"ACCEPTED", "IN_PROGRESS", "PAUSED"}:
        raise api_error(request, 409, "INTERVIEW_STATE_CONFLICT", "当前访谈不能完成。", "接受或恢复访谈后重试。")

    turns = await db.fetch_all(
        "SELECT * FROM experience_interview_turns WHERE interview_id = ? AND venue_id = ? ORDER BY turn_number",
        (interview_id, employee["venue_id"]),
    )
    if len(turns) != len(INTERVIEW_QUESTIONS) or any(not str(turn.get("answer_text") or "").strip() for turn in turns):
        raise api_error(
            request,
            409,
            "INTERVIEW_ANSWERS_INCOMPLETE",
            "访谈问题尚未全部回答，暂不能生成经验草稿。",
            "完成剩余问题后再开始萃取。",
        )

    trace_id = request_trace_id(request)
    acting_metadata = _acting_audit_metadata(principal, employee)
    evidence = {
        "interview_id": interview_id,
        "business_id": row["business_id"],
        "title": row["title"],
        "source_event_id": row.get("source_event_id"),
        "expert_id": row["expert_id"],
        "expert_name": row.get("expert_name") or "",
        "expert_job_title": row.get("expert_job_title") or "",
        "turns": [dict(turn) for turn in turns],
    }
    try:
        extractor = getattr(request.app.state, "experience_draft_extractor", None)
        if extractor is None:
            extractor = DeepSeekExperienceDraftExtractor(llm_client)
        draft = await extractor.extract(
            evidence,
            trace_id=trace_id,
            venue_id=employee["venue_id"],
        )
        draft = validate_extracted_experience_draft(draft, evidence)
    except ExperienceDraftExtractionError as exc:
        await write_audit(
            db,
            principal=principal,
            action="EXPERIENCE_EXTRACTION_FAILED",
            resource_type="experience_interview",
            resource_id=interview_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={
                "agent": "PersonaExtract",
                "model": "deepseek-v4-flash",
                "error": str(exc)[:500],
                **acting_metadata,
            },
        )
        raise api_error(
            request,
            503,
            "EXPERIENCE_EXTRACTION_FAILED",
            "经验萃取暂时失败，访谈回答已经安全保存。",
            "稍后从当前访谈重新生成草稿，或联系管理员查看模型诊断。",
            retryable=True,
        ) from exc
    except Exception as exc:
        await write_audit(
            db,
            principal=principal,
            action="EXPERIENCE_EXTRACTION_FAILED",
            resource_type="experience_interview",
            resource_id=interview_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={
                "agent": "PersonaExtract",
                "model": "deepseek-v4-flash",
                "error_type": type(exc).__name__,
                **acting_metadata,
            },
        )
        raise api_error(
            request,
            503,
            "EXPERIENCE_EXTRACTION_FAILED",
            "经验萃取暂时失败，访谈回答已经安全保存。",
            "稍后从当前访谈重新生成草稿，或联系管理员查看模型诊断。",
            retryable=True,
        ) from exc

    card_id = uuid.uuid4().hex
    business_id = await _business_id(db, "JY", "experience_cards")
    now = _now()
    replayed_card_payload = None
    async with db.transaction() as transaction:
        existing = await transaction.fetch_one(
            "SELECT id FROM experience_cards WHERE source_interview_id = ? AND venue_id = ?",
            (interview_id, employee["venue_id"]),
        )
        if existing:
            existing_row = await _card_row(transaction, existing["id"], employee["venue_id"])
            replayed_card_payload = await _card_payload(transaction, existing_row)
        else:
            inserted = await transaction.execute(
                """
                INSERT INTO experience_cards (
                    id, business_id, venue_id, expert_id, source_interview_id,
                    source_event_id, title, applicable_context, signals_json,
                    decision_rule, recommended_actions_json, rationale,
                    prohibitions_json, exceptions_json, source_excerpts_json,
                    extraction_trace_id, status, current_version, index_status, created_by, updated_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'DRAFT', 1, 'NOT_INDEXED', ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    card_id,
                    business_id,
                    employee["venue_id"],
                    row["expert_id"],
                    interview_id,
                    row.get("source_event_id"),
                    draft["title"],
                    draft["applicable_context"],
                    _json_text(draft["signals"]),
                    draft["decision_rule"],
                    _json_text(draft["recommended_actions"]),
                    draft["rationale"],
                    _json_text(draft["prohibitions"]),
                    _json_text(draft["exceptions"]),
                    _json_text(draft["source_excerpts"]),
                    trace_id,
                    employee["user_id"],
                    employee["user_id"],
                    now,
                    now,
                ),
            )
            if inserted == 0:
                existing = await transaction.fetch_one(
                    "SELECT id FROM experience_cards WHERE source_interview_id = ? AND venue_id = ?",
                    (interview_id, employee["venue_id"]),
                )
                if existing is None:
                    raise RuntimeError("experience card insert conflicted without a replayable source interview")
                existing_row = await _card_row(transaction, existing["id"], employee["venue_id"])
                replayed_card_payload = await _card_payload(transaction, existing_row)
            else:
                scopes = await _interview_scopes(transaction, interview_id, employee["venue_id"])
                for scope in scopes:
                    await transaction.execute(
                        """
                        INSERT INTO experience_authorizations (
                            id, venue_id, card_id, scope_type, scope_value, created_by, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uuid.uuid4().hex,
                            employee["venue_id"],
                            card_id,
                            scope["scope_type"],
                            scope["scope_value"],
                            employee["user_id"],
                            now,
                        ),
                    )
                await transaction.execute(
                    "UPDATE experience_interviews SET status = 'COMPLETED', completed_at = ?, updated_at = ? WHERE id = ? AND venue_id = ?",
                    (now, now, interview_id, employee["venue_id"]),
                )
                created = await _card_row(transaction, card_id, employee["venue_id"])
                await _write_card_version(
                    transaction,
                    row=created,
                    version=1,
                    change_note="访谈完成后生成经验草稿",
                    actor_id=employee["user_id"],
                )
                await write_audit(
                    transaction,
                    principal=principal,
                    action="EXPERIENCE_DRAFT_CREATED",
                    resource_type="experience_card",
                    resource_id=card_id,
                    outcome="SUCCEEDED",
                    trace_id=trace_id,
                    metadata={
                        "business_id": business_id,
                        "interview_id": interview_id,
                        "version": 1,
                        "agent": "PersonaExtract",
                        "model": "deepseek-v4-flash",
                        **acting_metadata,
                    },
                )
                card_payload = await _card_payload(transaction, created)
    if replayed_card_payload is not None:
        return {"card": replayed_card_payload, "idempotent_replay": True}
    return {
        "card": card_payload,
        "trace_id": trace_id,
        "idempotent_replay": False,
        "extraction": {"agent": "PersonaExtract", "model": "deepseek-v4-flash"},
    }


@assistant_router.put("/experience/cards/{card_id}")
async def revise_experience_card(
    card_id: str,
    body: ExperienceCardUpdateRequest,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _card_row(db, card_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验共创列表后重试。")
    _require_expert_owner(request, row, employee)
    if row["status"] != "DRAFT":
        raise api_error(request, 409, "EXPERIENCE_NOT_EDITABLE", "只有草稿可以修订。", "等待审核结果或创建新版本。")
    values = body.model_dump(exclude_none=True)
    change_note = values.pop("change_note")
    values = {key: value for key, value in values.items() if key in EDITABLE_CARD_FIELDS}
    if not values:
        raise api_error(request, 422, "EXPERIENCE_NO_CHANGES", "没有需要保存的经验字段。", "修改至少一个字段后重试。")
    candidate = _card_draft(row)
    candidate.update(values)
    validated = await _validate_card_source_excerpts(db, request, row, candidate)
    values = {key: validated[key] for key in values}
    stored_values: dict[str, Any] = {}
    reverse_json = {public: stored for stored, public in JSON_CARD_FIELDS.items()}
    for key, value in values.items():
        stored_values[reverse_json.get(key, key)] = _json_text(value) if key in reverse_json else value.strip()
    new_version = int(row["current_version"]) + 1
    stored_values.update(
        {
            "current_version": new_version,
            "updated_by": employee["user_id"],
            "updated_at": _now(),
        }
    )
    async with db.transaction() as transaction:
        await transaction.execute(
            f"UPDATE experience_cards SET {', '.join(f'{key} = ?' for key in stored_values)} WHERE id = ? AND venue_id = ? AND status = 'DRAFT'",
            (*stored_values.values(), card_id, employee["venue_id"]),
        )
        updated = await _card_row(transaction, card_id, employee["venue_id"])
        await _write_card_version(
            transaction,
            row=updated,
            version=new_version,
            change_note=change_note,
            actor_id=employee["user_id"],
        )
        await _write_review(
            transaction,
            card=updated,
            action="REVISE",
            from_status="DRAFT",
            to_status="DRAFT",
            comment=change_note,
            actor_id=employee["user_id"],
        )
        await write_audit(
            transaction,
            principal=principal,
            action="EXPERIENCE_CARD_REVISED",
            resource_type="experience_card",
            resource_id=card_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata=_acting_audit_metadata(
                principal,
                employee,
                business_id=row["business_id"],
                version=new_version,
                changed_fields=sorted(values),
            ),
        )
        card_payload = await _card_payload(transaction, updated)
    return {"card": card_payload}


@assistant_router.post("/experience/cards/{card_id}/confirm")
async def confirm_experience_card(
    card_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _card_row(db, card_id, employee["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验共创列表后重试。")
    _require_expert_owner(request, row, employee)
    next_status = _require_transition(request, row["status"], "confirm")
    scopes = await _card_scopes(db, card_id, employee["venue_id"])
    card = _decode_card(row)
    missing = [
        name
        for name in ("applicable_context", "signals", "decision_rule", "recommended_actions", "prohibitions", "exceptions", "source_excerpts")
        if not card.get(name)
    ]
    if not scopes:
        missing.append("authorization_scopes")
    if missing:
        raise api_error(
            request,
            422,
            "EXPERIENCE_INCOMPLETE",
            "经验卡缺少确认所需信息。",
            f"补充字段：{', '.join(missing)}。",
        )
    await _validate_card_source_excerpts(db, request, row, _card_draft(row))
    now = _now()
    async with db.transaction() as transaction:
        affected = await transaction.execute(
            """
            UPDATE experience_cards
            SET status = ?, confirmed_by = ?, confirmed_at = ?, updated_by = ?, updated_at = ?
            WHERE id = ? AND venue_id = ? AND status = 'DRAFT'
            """,
            (next_status, employee["user_id"], now, employee["user_id"], now, card_id, employee["venue_id"]),
        )
        if affected != 1:
            raise api_error(
                request,
                409,
                "EXPERIENCE_STATE_CONFLICT",
                "经验卡状态已由另一个请求更新。",
                "刷新经验详情后重试。",
            )
        updated = await _card_row(transaction, card_id, employee["venue_id"])
        await _write_review(
            transaction,
            card=updated,
            action="CONFIRM",
            from_status="DRAFT",
            to_status=next_status,
            comment="专家确认经验内容和授权范围",
            actor_id=employee["user_id"],
        )
        await write_audit(
            transaction,
            principal=principal,
            action="EXPERIENCE_CARD_CONFIRMED",
            resource_type="experience_card",
            resource_id=card_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata=_acting_audit_metadata(
                principal,
                employee,
                business_id=row["business_id"],
                version=row["current_version"],
            ),
        )
        card_payload = await _card_payload(transaction, updated)
    return {"card": card_payload}


@admin_router.get("/experience-cards")
async def list_experience_cards(
    card_status: Optional[str] = Query(None, alias="status"),
    query: Optional[str] = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    sql = """
        SELECT c.*, e.display_name AS expert_name, e.user_id AS expert_user_id,
               e.job_title AS expert_job_title, e.department AS expert_department,
               i.business_id AS interview_business_id
        FROM experience_cards c
        JOIN expert_profiles e ON e.id = c.expert_id AND e.venue_id = c.venue_id
        LEFT JOIN experience_interviews i ON i.id = c.source_interview_id AND i.venue_id = c.venue_id
        WHERE c.venue_id = ?
    """
    params: list[Any] = [principal["venue_id"]]
    if card_status:
        sql += " AND c.status = ?"
        params.append(card_status.upper())
    if query:
        sql += " AND (c.title LIKE ? OR c.business_id LIKE ? OR e.display_name LIKE ?)"
        keyword = f"%{query.strip()}%"
        params.extend((keyword, keyword, keyword))
    sql += " ORDER BY c.updated_at DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    rows = await db.fetch_all(sql, tuple(params))
    return {"experience_cards": [await _card_payload(db, row) for row in rows], "limit": limit, "offset": offset}


@admin_router.get("/experience-cards/{card_id}")
async def get_experience_card(
    card_id: str,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _card_row(db, card_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "当前场地不存在该经验卡。", "刷新经验列表后重试。")
    versions = await db.fetch_all(
        "SELECT * FROM experience_card_versions WHERE card_id = ? AND venue_id = ? ORDER BY version_number DESC",
        (card_id, principal["venue_id"]),
    )
    for version in versions:
        version["snapshot"] = _json(version.pop("snapshot_json", "{}"), {})
    reviews = await db.fetch_all(
        "SELECT * FROM experience_reviews WHERE card_id = ? AND venue_id = ? ORDER BY created_at",
        (card_id, principal["venue_id"]),
    )
    usage_records = await db.fetch_all(
        """
        SELECT
            usage.usage_type,
            user_account.display_name AS user_display_name,
            usage.query_text,
            usage.score,
            usage.note,
            usage.experience_version,
            usage.created_at
        FROM experience_usage_logs usage
        LEFT JOIN users user_account
          ON user_account.id = usage.user_id
         AND user_account.venue_id = usage.venue_id
        WHERE usage.card_id = ? AND usage.venue_id = ?
        ORDER BY usage.created_at DESC
        """,
        (card_id, principal["venue_id"]),
    )
    for usage_record in usage_records:
        usage_record["user_display_name"] = (
            usage_record.get("user_display_name") or "已停用员工"
        )
    usage_types = [str(record.get("usage_type") or "").upper() for record in usage_records]
    card = await _card_payload(db, row)
    card["versions"] = versions
    card["review_timeline"] = reviews
    card["usage_records"] = usage_records
    card["usage_summary"] = {
        "total": len(usage_records),
        "retrieved": usage_types.count("RETRIEVED"),
        "viewed": usage_types.count("VIEWED"),
        "referenced": usage_types.count("REFERENCED"),
        "feedback": sum(
            usage_type in {"HELPFUL", "NOT_APPLICABLE", "NEEDS_EXPERT"}
            for usage_type in usage_types
        ),
    }
    if row.get("source_interview_id"):
        card["source_turns"] = await db.fetch_all(
            "SELECT turn_number, question_text, answer_text, source_excerpt, created_at FROM experience_interview_turns WHERE interview_id = ? AND venue_id = ? ORDER BY turn_number",
            (row["source_interview_id"], principal["venue_id"]),
        )
    else:
        card["source_turns"] = []
    return {"experience_card": card}


@admin_router.post("/experience-cards/{card_id}/submit")
async def submit_experience_card(
    card_id: str,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _card_row(db, card_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验列表后重试。")
    if row.get("expert_user_id") == principal["user_id"]:
        raise api_error(request, 403, "EXPERIENCE_SELF_REVIEW", "专家不能审核自己提交的经验。", "交由另一位知识负责人审核。")
    next_status = _require_transition(request, row["status"], "submit")
    now = _now()
    await db.execute(
        "UPDATE experience_cards SET status = ?, reviewed_by = ?, updated_by = ?, updated_at = ? WHERE id = ? AND venue_id = ? AND status = 'EXPERT_CONFIRMED'",
        (next_status, principal["user_id"], principal["user_id"], now, card_id, principal["venue_id"]),
    )
    updated = await _card_row(db, card_id, principal["venue_id"])
    await _write_review(
        db,
        card=updated,
        action="SUBMIT",
        from_status="EXPERT_CONFIRMED",
        to_status=next_status,
        comment="提交知识负责人审核",
        actor_id=principal["user_id"],
    )
    return {"card": await _card_payload(db, updated)}


@admin_router.post("/experience-cards/{card_id}/reject")
async def reject_experience_card(
    card_id: str,
    body: ReviewRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _card_row(db, card_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验列表后重试。")
    if row.get("expert_user_id") == principal["user_id"]:
        raise api_error(request, 403, "EXPERIENCE_SELF_REVIEW", "专家不能审核自己提交的经验。", "交由另一位知识负责人审核。")
    next_status = _require_transition(request, row["status"], "reject")
    now = _now()
    await db.execute(
        """
        UPDATE experience_cards
        SET status = ?, reviewed_by = ?, confirmed_by = NULL, confirmed_at = NULL,
            updated_by = ?, updated_at = ?
        WHERE id = ? AND venue_id = ? AND status = 'IN_REVIEW'
        """,
        (next_status, principal["user_id"], principal["user_id"], now, card_id, principal["venue_id"]),
    )
    updated = await _card_row(db, card_id, principal["venue_id"])
    await _write_review(
        db,
        card=updated,
        action="REJECT",
        from_status="IN_REVIEW",
        to_status=next_status,
        comment=body.comment,
        actor_id=principal["user_id"],
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="EXPERIENCE_REJECTED",
        resource_type="experience_card",
        resource_id=card_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"business_id": row["business_id"], "comment": body.comment.strip()},
    )
    return {"card": await _card_payload(db, updated), "trace_id": trace_id}


def _publish_validation(card: dict[str, Any], scopes: list[dict[str, Any]]) -> list[str]:
    decoded = _decode_card(card)
    missing = [
        key
        for key in (
            "title",
            "applicable_context",
            "signals",
            "decision_rule",
            "recommended_actions",
            "rationale",
            "prohibitions",
            "exceptions",
            "source_excerpts",
        )
        if not decoded.get(key)
    ]
    if not card.get("expert_id") and not card.get("source_event_id"):
        missing.append("source")
    if not scopes:
        missing.append("authorization_scopes")
    return missing


def _vector_content(card: dict[str, Any]) -> str:
    decoded = _decode_card(card)
    sections = (
        ("标题", decoded.get("title")),
        ("适用情境", decoded.get("applicable_context")),
        ("观察信号", "；".join(decoded.get("signals") or [])),
        ("判断规则", decoded.get("decision_rule")),
        ("建议动作", "；".join(decoded.get("recommended_actions") or [])),
        ("原因", decoded.get("rationale")),
        ("禁忌", "；".join(decoded.get("prohibitions") or [])),
        ("例外", "；".join(decoded.get("exceptions") or [])),
    )
    return "\n".join(f"{label}：{value}" for label, value in sections if value)


@admin_router.post("/experience-cards/{card_id}/publish")
async def publish_experience_card(
    card_id: str,
    body: OptionalReviewRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _card_row(db, card_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验列表后重试。")
    if row.get("expert_user_id") == principal["user_id"]:
        raise api_error(request, 403, "EXPERIENCE_SELF_REVIEW", "专家不能发布自己提交的经验。", "交由另一位知识负责人发布。")
    next_status = _require_transition(request, row["status"], "publish")
    scopes = await _card_scopes(db, card_id, principal["venue_id"])
    missing = _publish_validation(row, scopes)
    if missing:
        raise api_error(
            request,
            422,
            "EXPERIENCE_NOT_PUBLISHABLE",
            "经验卡缺少发布所需内容或授权。",
            f"补充字段：{', '.join(missing)}。",
        )
    vector_store = _vector_store(request)
    version = int(row["current_version"])
    vector_doc_id = f"experience:{row['venue_id']}:{card_id}:v{version}"
    metadata = {
        "venue_id": row["venue_id"],
        "card_id": card_id,
        "business_id": row["business_id"],
        "expert_id": row["expert_id"],
        "expert_name": row.get("expert_name") or "",
        "source_event_id": row.get("source_event_id") or "",
        "version": version,
        "asset_type": "EXPERIENCE_CARD",
        "status": next_status,
    }
    try:
        stored = vector_store.upsert_experience(
            _vector_content(row),
            metadata,
            vector_doc_id,
            strict=True,
        )
        if stored is False:
            raise RuntimeError("vector store rejected experience")
    except Exception as exc:
        raise api_error(
            request,
            503,
            "EXPERIENCE_INDEX_WRITE_FAILED",
            "经验索引写入失败，尚未发布。",
            "保持当前审核状态，稍后重试发布。",
            retryable=True,
        ) from exc

    now = _now()
    try:
        updated_count = await db.execute(
            """
            UPDATE experience_cards
            SET status = ?, published_version = ?, vector_doc_id = ?,
                index_status = 'INDEXED', published_by = ?, published_at = ?,
                reviewed_by = ?, updated_by = ?, updated_at = ?
            WHERE id = ? AND venue_id = ? AND status = 'IN_REVIEW'
            """,
            (
                next_status,
                version,
                vector_doc_id,
                principal["user_id"],
                now,
                principal["user_id"],
                principal["user_id"],
                now,
                card_id,
                principal["venue_id"],
            ),
        )
        if updated_count != 1:
            raise RuntimeError("experience status changed during publish")
    except Exception as exc:
        try:
            vector_store.delete_experience(vector_doc_id, strict=True)
        except Exception:
            pass
        raise api_error(
            request,
            409,
            "EXPERIENCE_PUBLISH_CONFLICT",
            "经验状态已变化，本次发布没有生效。",
            "刷新经验详情后重试。",
        ) from exc

    updated = await _card_row(db, card_id, principal["venue_id"])
    await _write_review(
        db,
        card=updated,
        action="PUBLISH",
        from_status="IN_REVIEW",
        to_status=next_status,
        comment=body.comment,
        actor_id=principal["user_id"],
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="EXPERIENCE_PUBLISHED",
        resource_type="experience_card",
        resource_id=card_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"business_id": row["business_id"], "version": version, "vector_doc_id": vector_doc_id},
    )
    return {"card": await _card_payload(db, updated), "trace_id": trace_id}


@admin_router.post("/experience-cards/{card_id}/deprecate")
async def deprecate_experience_card(
    card_id: str,
    body: ReviewRequest,
    request: Request,
    principal: dict[str, Any] = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _card_row(db, card_id, principal["venue_id"])
    if row is None:
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "经验卡不存在。", "刷新经验列表后重试。")
    next_status = _require_transition(request, row["status"], "deprecate")
    vector_store = _vector_store(request)
    vector_doc_id = row.get("vector_doc_id")
    if vector_doc_id:
        try:
            deleted = vector_store.delete_experience(vector_doc_id, strict=True)
            if deleted is False:
                raise RuntimeError("vector delete rejected")
        except Exception as exc:
            raise api_error(
                request,
                503,
                "EXPERIENCE_INDEX_DELETE_FAILED",
                "经验索引移除失败，尚未停用。",
                "稍后重试停用，避免旧经验继续被检索。",
                retryable=True,
            ) from exc
    now = _now()
    await db.execute(
        """
        UPDATE experience_cards
        SET status = ?, index_status = 'REMOVED', deprecated_at = ?,
            updated_by = ?, updated_at = ?
        WHERE id = ? AND venue_id = ? AND status = 'PUBLISHED'
        """,
        (next_status, now, principal["user_id"], now, card_id, principal["venue_id"]),
    )
    updated = await _card_row(db, card_id, principal["venue_id"])
    await _write_review(
        db,
        card=updated,
        action="DEPRECATE",
        from_status="PUBLISHED",
        to_status=next_status,
        comment=body.comment,
        actor_id=principal["user_id"],
    )
    return {"card": await _card_payload(db, updated)}


@assistant_router.post("/experience/search")
async def search_experiences(
    body: ExperienceSearchRequest,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    vector_store = _vector_store(request)
    try:
        hits = vector_store.query_experience(
            body.query.strip(),
            top_k=body.top_k,
            threshold=body.threshold,
            venue_id=employee["venue_id"],
            strict=True,
        )
    except Exception as exc:
        raise api_error(
            request,
            503,
            "EXPERIENCE_SEARCH_FAILED",
            "经验检索暂时失败。",
            "稍后重试；紧急问题请升级人工负责人。",
            retryable=True,
        ) from exc

    effective_principal = await _principal_with_profile(db, employee)
    experiences: list[dict[str, Any]] = []
    for hit in hits:
        metadata = hit.get("metadata") or {}
        card_id = metadata.get("card_id")
        if card_id:
            row = await _card_row(db, str(card_id), employee["venue_id"])
        else:
            row = await db.fetch_one(
                "SELECT id FROM experience_cards WHERE vector_doc_id = ? AND venue_id = ?",
                (str(hit.get("id") or ""), employee["venue_id"]),
            )
            row = await _card_row(db, row["id"], employee["venue_id"]) if row else None
        if row is None or row.get("status") != "PUBLISHED":
            continue
        if row.get("vector_doc_id") != hit.get("id"):
            continue
        scopes = await _card_scopes(db, row["id"], employee["venue_id"])
        if not authorization_allows(row["venue_id"], scopes, effective_principal):
            continue
        decoded = _decode_card(row)
        result = {
            "id": row["id"],
            "business_id": row["business_id"],
            "title": row["title"],
            "applicable_context": row["applicable_context"],
            "signals": decoded["signals"],
            "decision_rule": row["decision_rule"],
            "recommended_actions": decoded["recommended_actions"],
            "rationale": row["rationale"],
            "prohibitions": decoded["prohibitions"],
            "exceptions": decoded["exceptions"],
            "version": row["published_version"],
            "score": hit.get("score"),
            "authorization_scopes": scopes,
            "source": decoded["source"],
            "ai_generated": True,
            "expert_confirmed": True,
            "published": True,
        }
        experiences.append(result)
        await db.execute(
            """
            INSERT INTO experience_usage_logs (
                id, venue_id, card_id, user_id, session_id, usage_type,
                query_text, score, experience_version, created_at
            ) VALUES (?, ?, ?, ?, ?, 'RETRIEVED', ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                employee["venue_id"],
                row["id"],
                employee["user_id"],
                body.session_id,
                body.query.strip(),
                hit.get("score"),
                row.get("published_version"),
                _now(),
            ),
        )
    return {"experiences": experiences, "query": body.query.strip()}


@assistant_router.post("/experience/cards/{card_id}/feedback")
async def record_experience_feedback(
    card_id: str,
    body: ExperienceFeedbackRequest,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None, min_length=1, max_length=64),
    principal: dict[str, Any] = Depends(require_auth),
    db=Depends(get_request_db),
):
    employee = await _resolve_employee_principal(db, request, principal, acting_user_id)
    row = await _card_row(db, card_id, employee["venue_id"])
    if row is None or row.get("status") != "PUBLISHED":
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "找不到可反馈的已发布经验。", "刷新引用来源后重试。")
    effective_principal = await _principal_with_profile(db, employee)
    scopes = await _card_scopes(db, card_id, employee["venue_id"])
    if not authorization_allows(row["venue_id"], scopes, effective_principal):
        raise api_error(request, 404, "EXPERIENCE_NOT_FOUND", "找不到可反馈的已发布经验。", "确认当前账号的经验授权范围。")
    usage_id = uuid.uuid4().hex
    await db.execute(
        """
        INSERT INTO experience_usage_logs (
            id, venue_id, card_id, user_id, session_id, usage_type,
            query_text, score, note, experience_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, '', NULL, ?, ?, ?)
        """,
        (
            usage_id,
            employee["venue_id"],
            card_id,
            employee["user_id"],
            body.session_id,
            body.feedback,
            body.note,
            row.get("published_version"),
            _now(),
        ),
    )
    return {"recorded": True, "feedback_id": usage_id, "business_id": row["business_id"]}
