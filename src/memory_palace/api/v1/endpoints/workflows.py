"""Formal event, task, and action-log workflow endpoints."""

from __future__ import annotations

import json
import hashlib
import time
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel, Field

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth, require_roles
from ...errors import api_error
from ....core.event_closure import calculate_event_closure_conditions
from ....core.event_activities import append_event_activity
from ....core.event_experience_candidates import (
    EventExperienceCandidateError,
    ensure_event_experience_candidate,
)
from ....core.task_activities import append_task_activity
from ....core.task_graph import TaskGraph, TaskStatus
from ....skills.todo.skill import TodoWriteSkill
from ....tools.llm_wrapper import llm_client as default_llm_client


router = APIRouter(dependencies=[Depends(require_auth)])
TASK_DECOMPOSITION_LEASE_SECONDS = 300


class EventUpdateRequest(BaseModel):
    assigned_to: Optional[str] = Field(None, max_length=64)
    event_type: Optional[str] = Field(None, min_length=1, max_length=80)
    severity: Optional[Literal["P0", "P1", "P2", "P3", "P4", "P3/P4"]] = None


class EventCloseRequest(BaseModel):
    resolution: str = Field(..., min_length=3, max_length=4000)


class TaskCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    event_id: Optional[str] = Field(None, max_length=80)
    description: str = Field(..., min_length=2, max_length=2000)
    dependencies: list[str] = Field(default_factory=list, max_length=50)
    assigned_user_id: Optional[str] = Field(None, max_length=64)
    assigned_agent: Optional[str] = Field(None, max_length=80)
    max_attempts: int = Field(3, ge=1, le=10)


class TaskDecomposeRequest(BaseModel):
    goal: str = Field(..., min_length=3, max_length=4000)
    session_id: str = Field(..., min_length=1, max_length=64)
    event_id: Optional[str] = Field(None, max_length=80)
    assigned_user_id: Optional[str] = Field(None, max_length=64)
    max_attempts: int = Field(3, ge=1, le=10)


class TaskAssignRequest(BaseModel):
    assigned_user_id: Optional[str] = Field(None, max_length=64)
    assigned_agent: Optional[str] = Field(None, max_length=80)


class TaskCompleteRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class TaskFailRequest(BaseModel):
    error: str = Field(..., min_length=2, max_length=2000)


class PushAdoptionRequest(BaseModel):
    status: Literal["pending", "adopted", "rejected"]
    notes: Optional[str] = Field(None, max_length=2000)


def _decode_task(row: dict[str, Any]) -> dict[str, Any]:
    for key, default in (("dependencies", []), ("result", None)):
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value) if value else default
            except json.JSONDecodeError:
                row[key] = default
    return row


async def _get_task_graph(request: Request, db) -> TaskGraph:
    container = getattr(request.app.state, "container", None)
    graph = getattr(container, "task_graph", None)
    if graph is None:
        graph = getattr(request.app.state, "task_graph", None)
    if graph is None:
        raise api_error(
            request,
            503,
            "TASK_GRAPH_NOT_READY",
            "任务服务尚未就绪。",
            "稍后重试或联系管理员检查系统健康状态。",
            retryable=True,
        )
    graph.set_database(db)
    return graph


async def _task_row(
    db,
    task_id: str,
    venue_id: str,
    *,
    include_staged: bool = False,
) -> Optional[dict[str, Any]]:
    sql = "SELECT * FROM tasks WHERE id = ? AND venue_id = ?"
    if not include_staged:
        sql += " AND status != 'STAGED'"
    row = await db.fetch_one(
        sql,
        (task_id, venue_id),
    )
    return _decode_task(row) if row else None


async def _require_visible_event(
    request: Request,
    db,
    *,
    event_id: str,
    venue_id: str,
) -> dict[str, Any]:
    event = await db.fetch_one(
        "SELECT event_id, business_id FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (event_id, venue_id),
    )
    if event is None:
        raise api_error(
            request,
            404,
            "EVENT_NOT_FOUND",
            "关联事件不存在。",
            "刷新事件列表后重新选择。",
        )
    return event


async def _delete_task_creation_activities(
    db,
    *,
    venue_id: str,
    decomposition_id: str,
    task_ids: list[str],
) -> None:
    idempotency_keys = [
        *(f"task-created:{task_id}" for task_id in task_ids),
        f"task-decomposed:{decomposition_id}",
    ]
    placeholders = ",".join("?" for _ in idempotency_keys)
    await db.execute(
        f"""
        DELETE FROM event_activities
        WHERE venue_id = ? AND idempotency_key IN ({placeholders})
        """,
        (venue_id, *idempotency_keys),
    )


async def _rollback_manual_task_creation(
    graph: TaskGraph,
    db,
    *,
    venue_id: str,
    event_id: Optional[str],
    task_id: str,
) -> list[str]:
    rollback_errors = []
    try:
        await graph.delete_tasks([task_id], venue_id=venue_id)
    except Exception as rollback_error:
        rollback_errors.append(str(rollback_error))
    try:
        await db.execute(
            """
            DELETE FROM audit_logs
            WHERE venue_id = ? AND action = 'TASK_CREATED'
              AND resource_type = 'task' AND resource_id = ?
            """,
            (venue_id, task_id),
        )
    except Exception as rollback_error:
        rollback_errors.append(str(rollback_error))
    if event_id:
        try:
            await db.execute(
                """
                DELETE FROM event_activities
                WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
                """,
                (venue_id, event_id, f"task-created:{task_id}"),
            )
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
    return rollback_errors


async def _audit_decomposition_failure(
    db,
    *,
    principal: dict,
    trace_id: str,
    session_id: str,
    reason: str,
    error: Optional[str] = None,
    event_id: Optional[str] = None,
) -> None:
    metadata = {"reason": reason}
    if error:
        metadata["error"] = error[:1000]
    if event_id:
        metadata["event_id"] = event_id
    await write_audit(
        db,
        principal=principal,
        action="TASK_DECOMPOSITION_FAILED",
        resource_type="session",
        resource_id=session_id,
        outcome="FAILED",
        trace_id=trace_id,
        metadata=metadata,
    )


def _decomposition_fingerprint(
    *,
    goal: str,
    session_id: str,
    event_id: Optional[str],
    assigned_user_id: Optional[str],
    max_attempts: int,
) -> str:
    fingerprint_payload = {
        "assigned_user_id": assigned_user_id,
        "goal": goal,
        "max_attempts": max_attempts,
        "session_id": session_id,
    }
    if event_id:
        fingerprint_payload["event_id"] = event_id
    canonical_request = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def _decode_json_field(value: Any, default: Any) -> Any:
    if not value:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


async def _decomposition_by_key(db, principal: dict, idempotency_key: str):
    return await db.fetch_one(
        """
        SELECT * FROM task_decompositions
        WHERE venue_id = ? AND requested_by = ? AND idempotency_key = ?
        """,
        (principal["venue_id"], principal["user_id"], idempotency_key),
    )


def _decomposition_status_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "status": row["status"],
        "decomposition_id": row["decomposition_id"],
        "idempotency_key": row["idempotency_key"],
        "trace_id": row["trace_id"],
        "retryable": row["status"] in ("PROCESSING", "STAGED", "FAILED"),
        "result": _decode_json_field(row.get("response_json"), None),
        "error": row.get("error"),
    }
    if row.get("event_id"):
        payload["event_id"] = row["event_id"]
    return payload


def _processing_lease_expired(row: dict[str, Any]) -> bool:
    return time.time() - float(row.get("updated_at") or 0) >= TASK_DECOMPOSITION_LEASE_SECONDS


async def _cleanup_decomposition_attempt(
    graph: TaskGraph,
    db,
    row: dict[str, Any],
) -> None:
    orphan_rows = await db.fetch_all(
        """
        SELECT id FROM tasks
        WHERE venue_id = ? AND decomposition_id = ? AND status = 'STAGED'
        """,
        (row["venue_id"], row["decomposition_id"]),
    )
    persisted_task_ids = _decode_json_field(row.get("task_ids"), [])
    if not isinstance(persisted_task_ids, list):
        persisted_task_ids = []
    cleanup_task_ids = list(
        dict.fromkeys(
            [
                task_id
                for task_id in [
                    *persisted_task_ids,
                    *(task["id"] for task in orphan_rows),
                ]
                if isinstance(task_id, str) and task_id
            ]
        )
    )
    await graph.delete_tasks(
        cleanup_task_ids,
        venue_id=row["venue_id"],
    )
    audit_conditions = [
        "(action = 'TASK_DECOMPOSED' AND resource_type = 'task_decomposition' AND resource_id = ?)"
    ]
    audit_parameters = [row["venue_id"], row["decomposition_id"]]
    if cleanup_task_ids:
        task_placeholders = ",".join("?" for _ in cleanup_task_ids)
        audit_conditions.append(
            "(action = 'TASK_CREATED' AND resource_type = 'task' "
            f"AND resource_id IN ({task_placeholders}))"
        )
        audit_parameters.extend(cleanup_task_ids)
    await db.execute(
        f"""
        DELETE FROM audit_logs
        WHERE venue_id = ? AND ({' OR '.join(audit_conditions)})
        """,
        tuple(audit_parameters),
    )
    await _delete_task_creation_activities(
        db,
        venue_id=row["venue_id"],
        decomposition_id=row["decomposition_id"],
        task_ids=cleanup_task_ids,
    )


async def _expire_processing_decomposition(
    graph: TaskGraph,
    db,
    row: dict[str, Any],
) -> dict[str, Any]:
    cleanup_started_at = time.time()
    claimed = await db.execute(
        """
        UPDATE task_decompositions
        SET error = 'processing_cleanup_pending', updated_at = ?
        WHERE decomposition_id = ? AND venue_id = ? AND status = 'PROCESSING'
          AND trace_id = ? AND updated_at = ?
        """,
        (
            cleanup_started_at,
            row["decomposition_id"],
            row["venue_id"],
            row["trace_id"],
            row["updated_at"],
        ),
    )
    if claimed == 1:
        await _cleanup_decomposition_attempt(graph, db, row)
        await db.execute(
            """
            UPDATE task_decompositions
            SET status = 'FAILED', error = 'processing_lease_expired', updated_at = ?
            WHERE decomposition_id = ? AND venue_id = ? AND status = 'PROCESSING'
              AND trace_id = ? AND error = 'processing_cleanup_pending'
              AND updated_at = ?
            """,
            (
                time.time(),
                row["decomposition_id"],
                row["venue_id"],
                row["trace_id"],
                cleanup_started_at,
            ),
        )
    refreshed = await db.fetch_one(
        "SELECT * FROM task_decompositions WHERE decomposition_id = ?",
        (row["decomposition_id"],),
    )
    return refreshed or row


async def _finish_prepared_decomposition(graph: TaskGraph, db, row: dict[str, Any]):
    task_ids = _decode_json_field(row.get("task_ids"), [])
    if not task_ids or not row.get("response_json"):
        raise RuntimeError("暂存任务分解记录不完整")
    tasks = await graph.activate_tasks(task_ids)
    if len(tasks) != len(task_ids) or any(task.status == TaskStatus.STAGED for task in tasks):
        raise RuntimeError("暂存任务尚未完整发布")
    if row["status"] != "COMPLETED":
        updated = await db.execute(
            """
            UPDATE task_decompositions
            SET status = 'COMPLETED', error = NULL, updated_at = ?
            WHERE decomposition_id = ? AND status = 'STAGED'
            """,
            (time.time(), row["decomposition_id"]),
        )
        if updated != 1:
            refreshed = await db.fetch_one(
                "SELECT status FROM task_decompositions WHERE decomposition_id = ?",
                (row["decomposition_id"],),
            )
            if not refreshed or refreshed["status"] != "COMPLETED":
                raise RuntimeError("任务分解完成状态未能持久化")
    return _decode_json_field(row["response_json"], None)


async def _mark_decomposition_failed(
    db,
    decomposition_id: str,
    error: str,
    *,
    trace_id: Optional[str] = None,
) -> int:
    sql = """
        UPDATE task_decompositions
        SET status = 'FAILED', error = ?, updated_at = ?
        WHERE decomposition_id = ? AND status != 'COMPLETED'
    """
    parameters: tuple[Any, ...] = (error[:2000], time.time(), decomposition_id)
    if trace_id:
        sql += " AND trace_id = ?"
        parameters = (*parameters, trace_id)
    return await db.execute(
        sql,
        parameters,
    )


async def _record_event_close_denied(
    db,
    *,
    principal: dict,
    event_id: str,
    trace_id: str,
    message: str,
    closure_conditions: dict[str, Any],
) -> None:
    await write_audit(
        db,
        principal=principal,
        action="EVENT_CLOSE_DENIED",
        resource_type="event",
        resource_id=event_id,
        outcome="DENIED",
        trace_id=trace_id,
        metadata={"closure_conditions": closure_conditions},
    )
    await append_event_activity(
        db,
        venue_id=principal["venue_id"],
        event_id=event_id,
        activity_type="EVENT_CLOSE_DENIED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        payload={
            "summary": message,
            "blocker_count": closure_conditions.get("blocker_count", 0),
            "blocker_counts": closure_conditions.get("blocker_counts", {}),
        },
        idempotency_key=f"event-close-denied:{trace_id}",
    )


async def _rollback_event_close(
    db,
    *,
    principal: dict,
    event_id: str,
    trace_id: str,
    closed_at: float,
    previous: dict[str, Any],
) -> list[str]:
    rollback_errors = []
    try:
        await db.execute(
            """
            DELETE FROM event_activities
            WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
            """,
            (principal["venue_id"], event_id, f"event-closed:{event_id}"),
        )
    except Exception as rollback_error:
        rollback_errors.append(str(rollback_error))
    try:
        await db.execute(
            """
            DELETE FROM audit_logs
            WHERE venue_id = ? AND action = 'EVENT_CLOSED'
              AND resource_type = 'event' AND resource_id = ? AND trace_id = ?
            """,
            (principal["venue_id"], event_id, trace_id),
        )
    except Exception as rollback_error:
        rollback_errors.append(str(rollback_error))
    try:
        restored = await db.execute(
            """
            UPDATE confirmed_events
            SET status = ?, resolution = ?, closed_at = ?, updated_at = ?, trace_id = ?
            WHERE event_id = ? AND venue_id = ? AND status = 'CLOSED' AND closed_at = ?
            """,
            (
                previous.get("status") or "OPEN",
                previous.get("resolution"),
                previous.get("closed_at"),
                previous.get("updated_at"),
                previous.get("trace_id"),
                event_id,
                principal["venue_id"],
                closed_at,
            ),
        )
        if restored != 1:
            rollback_errors.append("event close state changed before rollback")
    except Exception as rollback_error:
        rollback_errors.append(str(rollback_error))
    return rollback_errors


def _event_candidate_llm_client(request: Request):
    container = getattr(request.app.state, "container", None)
    if container is not None:
        configured = getattr(container, "llm_client", None)
        if configured is not None:
            return configured
    return getattr(request.app.state, "llm_client", None) or default_llm_client


def _retryable_candidate_failure(trace_id: str) -> dict[str, Any]:
    return {
        "outcome": "FAILED",
        "candidate": None,
        "idempotent_replay": False,
        "retryable": True,
        "extraction": {
            "status": "FAILED",
            "model": "deepseek-v4-flash",
            "trace_id": trace_id,
            "attempt_count": 0,
            "error": "经验候选生成失败，可从事件卷宗重试。",
        },
        "activity": None,
    }


async def _record_candidate_generation_failure(
    db,
    *,
    principal: dict[str, Any],
    event_id: str,
    trace_id: str,
    error: Exception,
) -> None:
    try:
        await write_audit(
            db,
            principal=principal,
            action="EXPERIENCE_CANDIDATE_GENERATION",
            resource_type="event",
            resource_id=event_id,
            outcome="FAILED",
            trace_id=trace_id,
            metadata={
                "retryable": True,
                "model": "deepseek-v4-flash",
                "error_type": type(error).__name__,
            },
        )
    except Exception:
        return


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str,
    body: EventUpdateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (event_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "EVENT_NOT_FOUND", "事件不存在。", "刷新事件列表后重试。")
    if current.get("status") == "CLOSED":
        raise api_error(request, 409, "EVENT_ALREADY_CLOSED", "已闭环事件不能继续修改。", "查看事件详情和审计记录。")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"event": current, "trace_id": request_trace_id(request)}
    set_sql = ", ".join(f"{column} = ?" for column in updates)
    await db.execute(
        f"UPDATE confirmed_events SET {set_sql}, updated_at = ? WHERE event_id = ? AND venue_id = ?",
        (*updates.values(), time.time(), event_id, principal["venue_id"]),
    )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="EVENT_UPDATED",
        resource_type="event",
        resource_id=event_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"changed_fields": sorted(updates)},
    )
    await append_event_activity(
        db,
        venue_id=principal["venue_id"],
        event_id=event_id,
        activity_type="EVENT_UPDATED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        payload={
            "summary": "事件分类、等级或负责人信息已更新。",
            "changed_fields": sorted(updates),
            "changes": updates,
        },
        idempotency_key=f"event-updated:{event_id}:{trace_id}",
    )
    return {
        "event": await db.fetch_one(
            "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
            (event_id, principal["venue_id"]),
        ),
        "trace_id": trace_id,
    }


@router.post("/events/{event_id}/close")
async def close_event(
    event_id: str,
    body: EventCloseRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await db.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (event_id, principal["venue_id"]),
    )
    if not current:
        raise api_error(request, 404, "EVENT_NOT_FOUND", "事件不存在。", "刷新事件列表后重试。")
    if current.get("status") == "CLOSED":
        raise api_error(request, 409, "EVENT_ALREADY_CLOSED", "事件已经闭环。", "查看闭环结果。")
    if principal["role"] == "operator" and current.get("assigned_to") not in (None, "", principal["user_id"]):
        raise api_error(request, 403, "EVENT_NOT_ASSIGNED", "只能关闭分配给自己的事件。", "请联系值班经理调整负责人。")
    trace_id = request_trace_id(request)
    closure_conditions = await calculate_event_closure_conditions(
        db,
        venue_id=principal["venue_id"],
        event_id=event_id,
    )
    if not closure_conditions["ready"]:
        message = closure_conditions["blockers"][0]["message"]
        await _record_event_close_denied(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            message=message,
            closure_conditions=closure_conditions,
        )
        raise api_error(
            request,
            409,
            "EVENT_CLOSE_BLOCKED",
            message,
            "完成提示中的任务、审批或动作执行后，再次提交闭环。",
            details={"closure_conditions": closure_conditions},
        )

    resolution = body.resolution.strip()
    meaningful_length = len("".join(resolution.split()))
    if meaningful_length < 12:
        insufficient_conditions = {
            **closure_conditions,
            "ready": False,
            "blocker_count": 1,
            "blocker_counts": {"RESOLUTION_INSUFFICIENT": 1},
            "blockers": [
                {
                    "code": "RESOLUTION_INSUFFICIENT",
                    "message": "闭环结果过短，无法说明实际结果、有效动作和失败动作。",
                    "resource_type": "event",
                    "resource_id": event_id,
                }
            ],
        }
        message = insufficient_conditions["blockers"][0]["message"]
        await _record_event_close_denied(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            message=message,
            closure_conditions=insufficient_conditions,
        )
        raise api_error(
            request,
            422,
            "EVENT_RESOLUTION_INSUFFICIENT",
            message,
            "补充现场结果、已执行动作和需要继续观察的事项后重试。",
            details={"closure_conditions": insufficient_conditions},
        )

    now = time.time()
    closed = await db.execute(
        """
        UPDATE confirmed_events
        SET status = 'CLOSED', resolution = ?, closed_at = ?, updated_at = ?,
            trace_id = COALESCE(NULLIF(trace_id, ''), ?)
        WHERE event_id = ? AND venue_id = ? AND COALESCE(status, 'OPEN') != 'CLOSED'
        """,
        (resolution, now, now, trace_id, event_id, principal["venue_id"]),
    )
    if closed != 1:
        raise api_error(
            request,
            409,
            "EVENT_STATE_CHANGED",
            "事件状态已被其他操作更新。",
            "刷新事件卷宗后确认当前状态。",
        )

    try:
        await write_audit(
            db,
            principal=principal,
            action="EVENT_CLOSED",
            resource_type="event",
            resource_id=event_id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={
                "resolution_length": len(resolution),
                "closure_conditions": closure_conditions,
            },
        )
        await append_event_activity(
            db,
            venue_id=principal["venue_id"],
            event_id=event_id,
            activity_type="EVENT_CLOSED",
            created_by=principal["user_id"],
            trace_id=trace_id,
            payload={
                "resolution": resolution,
                "closure_conditions": closure_conditions,
            },
            idempotency_key=f"event-closed:{event_id}",
            created_at=now,
        )
    except Exception as persistence_error:
        rollback_errors = await _rollback_event_close(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            closed_at=now,
            previous=current,
        )
        if rollback_errors:
            raise api_error(
                request,
                500,
                "EVENT_CLOSE_ROLLBACK_FAILED",
                "闭环证据写入失败，且事件状态未能完整恢复。",
                "停止重复操作并使用 Trace ID 联系管理员核对事件状态。",
            ) from persistence_error
        raise api_error(
            request,
            503,
            "EVENT_CLOSE_PERSISTENCE_FAILED",
            "闭环证据写入失败，事件已保持为处理中。",
            "稍后使用原事件重新提交闭环。",
            retryable=True,
        ) from persistence_error

    try:
        experience_candidate = await ensure_event_experience_candidate(
            db,
            venue_id=principal["venue_id"],
            event_id=event_id,
            trace_id=trace_id,
            principal={
                "venue_id": principal["venue_id"],
                "user_id": principal["user_id"],
            },
            llm_client=_event_candidate_llm_client(request),
        )
    except Exception as candidate_error:
        await _record_candidate_generation_failure(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            error=candidate_error,
        )
        experience_candidate = _retryable_candidate_failure(trace_id)

    return {
        "closed": True,
        "event_id": event_id,
        "trace_id": trace_id,
        "closure_conditions": closure_conditions,
        "experience_candidate": experience_candidate,
    }


@router.post("/events/{event_id}/experience-candidate/retry")
async def retry_event_experience_candidate(
    event_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    event = await db.fetch_one(
        "SELECT event_id, status FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
        (event_id, principal["venue_id"]),
    )
    if event is None:
        raise api_error(
            request,
            404,
            "EVENT_NOT_FOUND",
            "事件不存在。",
            "刷新事件列表后重试。",
        )
    if str(event.get("status") or "OPEN").upper() != "CLOSED":
        raise api_error(
            request,
            409,
            "EXPERIENCE_CANDIDATE_NOT_ELIGIBLE",
            "只有已闭环事件可以生成经验候选。",
            "先完成事件闭环条件和闭环结果，再生成候选。",
        )

    trace_id = request_trace_id(request)
    try:
        result = await ensure_event_experience_candidate(
            db,
            venue_id=principal["venue_id"],
            event_id=event_id,
            trace_id=trace_id,
            principal={
                "venue_id": principal["venue_id"],
                "user_id": principal["user_id"],
            },
            llm_client=_event_candidate_llm_client(request),
        )
    except EventExperienceCandidateError as candidate_error:
        await _record_candidate_generation_failure(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            error=candidate_error,
        )
        raise api_error(
            request,
            409,
            "EXPERIENCE_CANDIDATE_NOT_ELIGIBLE",
            "当前事件暂不能生成经验候选。",
            "确认事件已闭环且模型服务已初始化后重试。",
            retryable=True,
        ) from candidate_error
    except Exception as candidate_error:
        await _record_candidate_generation_failure(
            db,
            principal=principal,
            event_id=event_id,
            trace_id=trace_id,
            error=candidate_error,
        )
        raise api_error(
            request,
            503,
            "EXPERIENCE_CANDIDATE_RETRY_FAILED",
            "经验候选重试未能完成。",
            "检查模型和数据库健康状态后再次重试。",
            retryable=True,
        ) from candidate_error

    await write_audit(
        db,
        principal=principal,
        action="EXPERIENCE_CANDIDATE_RETRY",
        resource_type="event",
        resource_id=event_id,
        outcome=(
            "FAILED"
            if result["outcome"] == "FAILED"
            else "PENDING"
            if result["outcome"] == "IN_PROGRESS"
            else "SUCCEEDED"
        ),
        trace_id=trace_id,
        metadata={
            "candidate_id": (result.get("candidate") or {}).get("id"),
            "outcome": result["outcome"],
            "retryable": result["retryable"],
            "model": "deepseek-v4-flash",
        },
    )
    return {**result, "trace_id": trace_id}


@router.get("/tasks")
async def list_tasks(
    task_status: Optional[str] = Query(None, alias="status"),
    session_id: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    sql = "SELECT * FROM tasks WHERE venue_id = ? AND status != 'STAGED'"
    params: list[Any] = [principal["venue_id"]]
    if task_status:
        sql += " AND status = ?"
        params.append(task_status.upper())
    if session_id:
        sql += " AND session_id = ?"
        params.append(session_id)
    if principal["role"] == "operator":
        sql += " AND assigned_user_id = ?"
        params.append(principal["user_id"])
    elif assigned_user_id:
        sql += " AND assigned_user_id = ?"
        params.append(assigned_user_id)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = [_decode_task(row) for row in await db.fetch_all(sql, tuple(params))]
    return {"tasks": rows, "limit": limit, "offset": offset}


@router.post("/tasks/decompose", status_code=status.HTTP_201_CREATED)
async def decompose_tasks(
    body: TaskDecomposeRequest,
    request: Request,
    response: Response,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=128),
):
    trace_id = request_trace_id(request)
    decomposition_id = uuid.uuid4().hex
    goal = body.goal.strip()
    session_id = body.session_id.strip()
    event_id = body.event_id.strip() if body.event_id else None
    assigned_user_id = body.assigned_user_id.strip() if body.assigned_user_id else None
    idempotency_key = (idempotency_key or "").strip()
    if not idempotency_key:
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="invalid_idempotency_key",
        )
        raise api_error(
            request,
            422,
            "TASK_IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key 不能为空。",
            "为本次任务分解生成一个稳定的 UUID 后重试。",
        )
    if len(goal) < 3:
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="invalid_goal",
        )
        raise api_error(
            request,
            422,
            "TASK_GOAL_INVALID",
            "任务目标至少需要 3 个有效字符。",
            "补充清晰、可执行的任务目标后重试。",
        )
    if not session_id:
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="invalid_session_id",
        )
        raise api_error(request, 422, "SESSION_ID_INVALID", "必须关联一个有效会话。", "从会话列表中重新选择。")

    session = await db.fetch_one(
        "SELECT session_id, stage FROM sessions WHERE session_id = ? AND venue_id = ?",
        (session_id, principal["venue_id"]),
    )
    if session is None:
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="session_not_found_or_not_visible",
        )
        raise api_error(request, 404, "SESSION_NOT_FOUND", "关联会话不存在。", "刷新会话列表后重试。")
    if session.get("stage") == "CLOSED":
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="session_closed",
        )
        raise api_error(request, 409, "SESSION_CLOSED", "已关闭会话不能继续分解任务。", "选择活动会话后重试。")

    if event_id:
        try:
            await _require_visible_event(
                request,
                db,
                event_id=event_id,
                venue_id=principal["venue_id"],
            )
        except Exception:
            await _audit_decomposition_failure(
                db,
                principal=principal,
                trace_id=trace_id,
                session_id=session_id,
                reason="event_not_found_or_not_visible",
            )
            raise

    if assigned_user_id:
        assignee = await db.fetch_one(
            "SELECT id FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
            (assigned_user_id, principal["venue_id"]),
        )
        if assignee is None:
            await _audit_decomposition_failure(
                db,
                principal=principal,
                trace_id=trace_id,
                session_id=session_id,
                reason="assignee_not_found_or_not_visible",
                event_id=event_id,
            )
            raise api_error(
                request,
                400,
                "TASK_ASSIGNEE_INVALID",
                "负责人不存在、跨场地或已停用。",
                "请选择当前场地的有效用户。",
            )

    try:
        graph = await _get_task_graph(request, db)
    except Exception:
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="task_graph_not_ready",
            event_id=event_id,
        )
        raise
    fingerprint = _decomposition_fingerprint(
        goal=goal,
        session_id=session_id,
        event_id=event_id,
        assigned_user_id=assigned_user_id,
        max_attempts=body.max_attempts,
    )
    now = time.time()
    inserted = await db.execute(
        """
        INSERT INTO task_decompositions (
            decomposition_id, venue_id, requested_by, idempotency_key,
            request_fingerprint, session_id, event_id, trace_id, status, task_ids,
            response_json, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSING', '[]', NULL, NULL, ?, ?)
        ON CONFLICT(venue_id, requested_by, idempotency_key) DO NOTHING
        """,
        (
            decomposition_id,
            principal["venue_id"],
            principal["user_id"],
            idempotency_key,
            fingerprint,
            session_id,
            event_id,
            trace_id,
            now,
            now,
        ),
    )
    if inserted == 0:
        existing = await _decomposition_by_key(db, principal, idempotency_key)
        if existing is None:
            raise api_error(
                request,
                503,
                "TASK_IDEMPOTENCY_STATE_UNAVAILABLE",
                "任务分解幂等状态暂时不可用。",
                "稍后使用同一 Idempotency-Key 重试。",
                retryable=True,
            )
        if existing["request_fingerprint"] != fingerprint:
            raise api_error(
                request,
                409,
                "TASK_IDEMPOTENCY_KEY_REUSED",
                "该 Idempotency-Key 已用于不同的任务分解请求。",
                "为新请求生成新的 Idempotency-Key。",
            )
        decomposition_id = existing["decomposition_id"]
        if existing["status"] == "COMPLETED":
            return _decode_json_field(existing.get("response_json"), None)
        if existing["status"] == "STAGED":
            try:
                original_result = await _finish_prepared_decomposition(graph, db, existing)
            except Exception as recovery_error:
                response.status_code = status.HTTP_202_ACCEPTED
                payload = _decomposition_status_payload(existing)
                payload["error"] = str(recovery_error)
                return payload
            return original_result
        if existing["status"] == "PROCESSING":
            if not _processing_lease_expired(existing):
                response.status_code = status.HTTP_202_ACCEPTED
                return _decomposition_status_payload(existing)
            existing = await _expire_processing_decomposition(graph, db, existing)
            if existing["status"] != "FAILED":
                response.status_code = status.HTTP_202_ACCEPTED
                return _decomposition_status_payload(existing)
        if existing and existing["status"] == "FAILED":
            await _cleanup_decomposition_attempt(graph, db, existing)
            claimed = await db.execute(
                """
                UPDATE task_decompositions
                SET status = 'PROCESSING', trace_id = ?, task_ids = '[]',
                    response_json = NULL, error = NULL, updated_at = ?
                WHERE decomposition_id = ? AND venue_id = ? AND status = 'FAILED'
                  AND trace_id = ? AND updated_at = ?
                """,
                (
                    trace_id,
                    time.time(),
                    decomposition_id,
                    principal["venue_id"],
                    existing["trace_id"],
                    existing["updated_at"],
                ),
            )
            if claimed != 1:
                refreshed = await _decomposition_by_key(db, principal, idempotency_key)
                response.status_code = status.HTTP_202_ACCEPTED
                return _decomposition_status_payload(refreshed)
    output = await TodoWriteSkill(task_graph=graph).run(
        {
            "goal": goal,
            "session_id": session_id,
            "event_id": event_id,
            "venue_id": principal["venue_id"],
            "assigned_user_id": assigned_user_id,
            "max_attempts": body.max_attempts,
            "defer_activation": True,
            "decomposition_id": decomposition_id,
        },
        trace_id=trace_id,
    )
    if not output.success:
        marked = await _mark_decomposition_failed(
            db,
            decomposition_id,
            output.error_msg or output.action_taken or "agent_failed",
            trace_id=trace_id,
        )
        if marked != 1:
            refreshed = await _decomposition_by_key(db, principal, idempotency_key)
            response.status_code = status.HTTP_202_ACCEPTED
            return _decomposition_status_payload(refreshed)
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason=output.action_taken or "agent_failed",
            error=output.error_msg,
            event_id=event_id,
        )
        raise api_error(
            request,
            502,
            "TASK_DECOMPOSITION_FAILED",
            "模型未能生成合法的任务结构。",
            "稍后重试；如持续失败，请使用 Trace ID 联系管理员。",
            retryable=True,
        )

    structured_data = output.structured_data or {}
    task_ids = structured_data.get("task_ids")
    if not isinstance(task_ids, list) or not task_ids:
        marked = await _mark_decomposition_failed(
            db,
            decomposition_id,
            "agent_result_missing_tasks",
            trace_id=trace_id,
        )
        if marked != 1:
            refreshed = await _decomposition_by_key(db, principal, idempotency_key)
            response.status_code = status.HTTP_202_ACCEPTED
            return _decomposition_status_payload(refreshed)
        await _audit_decomposition_failure(
            db,
            principal=principal,
            trace_id=trace_id,
            session_id=session_id,
            reason="agent_result_missing_tasks",
            event_id=event_id,
        )
        raise api_error(
            request,
            502,
            "TASK_DECOMPOSITION_FAILED",
            "任务分解结果不完整。",
            "使用 Trace ID 联系管理员检查 Agent 输出。",
            retryable=True,
        )

    linked = await db.execute(
        """
        UPDATE task_decompositions
        SET task_ids = ?, updated_at = ?
        WHERE decomposition_id = ? AND status = 'PROCESSING' AND trace_id = ?
        """,
        (json.dumps(task_ids), time.time(), decomposition_id, trace_id),
    )
    if linked != 1:
        await graph.delete_tasks(task_ids, venue_id=principal["venue_id"])
        refreshed = await _decomposition_by_key(db, principal, idempotency_key)
        response.status_code = status.HTTP_202_ACCEPTED
        return _decomposition_status_payload(refreshed)

    tasks = []
    for task_id in task_ids:
        task = await _task_row(db, task_id, principal["venue_id"], include_staged=True)
        if task is None:
            await graph.delete_tasks(task_ids, venue_id=principal["venue_id"])
            await _mark_decomposition_failed(
                db,
                decomposition_id,
                "task_persistence_mismatch",
                trace_id=trace_id,
            )
            await _audit_decomposition_failure(
                db,
                principal=principal,
                trace_id=trace_id,
                session_id=session_id,
                reason="task_persistence_mismatch",
                event_id=event_id,
            )
            raise api_error(
                request,
                500,
                "TASK_PERSISTENCE_FAILED",
                "任务已生成但持久化校验失败。",
                "使用 Trace ID 联系管理员检查任务存储。",
                retryable=True,
            )
        tasks.append(task)

    try:
        for task in tasks:
            await write_audit(
                db,
                principal=principal,
                action="TASK_CREATED",
                resource_type="task",
                resource_id=task["id"],
                outcome="SUCCEEDED",
                trace_id=trace_id,
                metadata={
                    "business_id": task.get("business_id"),
                    "event_id": event_id,
                    "session_id": session_id,
                    "dependencies": task["dependencies"],
                    "assigned_user_id": task.get("assigned_user_id"),
                    "max_attempts": task["max_attempts"],
                    "generated_by": "TodoWrite",
                },
            )
            if event_id:
                await append_event_activity(
                    db,
                    venue_id=principal["venue_id"],
                    event_id=event_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    activity_type="TASK_CREATED",
                    created_by=principal["user_id"],
                    idempotency_key=f"task-created:{task['id']}",
                    payload={
                        "task_id": task["id"],
                        "business_id": task.get("business_id"),
                        "title": task["description"],
                        "status": (
                            TaskStatus.BLOCKED.value
                            if task["dependencies"]
                            else TaskStatus.PENDING.value
                        ),
                        "status_label": (
                            "等待前置任务"
                            if task["dependencies"]
                            else "待开始"
                        ),
                        "assigned_user_id": task.get("assigned_user_id"),
                        "dependencies": task["dependencies"],
                    },
                )
        await write_audit(
            db,
            principal=principal,
            action="TASK_DECOMPOSED",
            resource_type="task_decomposition",
            resource_id=decomposition_id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={
                "event_id": event_id,
                "tasks_created": len(tasks),
                "goal_length": len(goal),
                "assigned_user_id": assigned_user_id,
                "max_attempts": body.max_attempts,
                "agent_id": "TodoWrite",
            },
        )
        if event_id:
            await append_event_activity(
                db,
                venue_id=principal["venue_id"],
                event_id=event_id,
                session_id=session_id,
                trace_id=trace_id,
                activity_type="TASK_DECOMPOSED",
                created_by=principal["user_id"],
                idempotency_key=f"task-decomposed:{decomposition_id}",
                payload={
                    "decomposition_id": decomposition_id,
                    "goal": goal,
                    "tasks_created": len(tasks),
                    "task_business_ids": [task.get("business_id") for task in tasks],
                },
            )
    except Exception as audit_error:
        rollback_errors = []
        try:
            await graph.delete_tasks(task_ids, venue_id=principal["venue_id"])
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        try:
            await _delete_task_creation_activities(
                db,
                venue_id=principal["venue_id"],
                decomposition_id=decomposition_id,
                task_ids=task_ids,
            )
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        try:
            task_placeholders = ",".join("?" for _ in task_ids)
            await db.execute(
                f"""
                DELETE FROM audit_logs
                WHERE venue_id = ? AND trace_id = ? AND (
                    (action = 'TASK_CREATED' AND resource_type = 'task'
                     AND resource_id IN ({task_placeholders}))
                    OR (action = 'TASK_DECOMPOSED' AND resource_type = 'task_decomposition'
                        AND resource_id = ?)
                )
                """,
                (principal["venue_id"], trace_id, *task_ids, decomposition_id),
            )
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        try:
            await _mark_decomposition_failed(
                db,
                decomposition_id,
                str(audit_error),
                trace_id=trace_id,
            )
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        try:
            await _audit_decomposition_failure(
                db,
                principal=principal,
                trace_id=trace_id,
                session_id=session_id,
                reason="success_persistence_failed",
                error=str(audit_error),
                event_id=event_id,
            )
        except Exception as rollback_error:
            rollback_errors.append(str(rollback_error))
        if rollback_errors:
            raise api_error(
                request,
                500,
                "TASK_DECOMPOSITION_ROLLBACK_FAILED",
                "任务分解失败且自动回滚未完整完成。",
                "请停止重试并使用 Trace ID 联系管理员人工核查。",
                retryable=False,
            )
        raise api_error(
            request,
            500,
            "TASK_DECOMPOSITION_PERSISTENCE_FAILED",
            "任务分解结果未能完整持久化，已安全回滚。",
            "稍后重试；如持续失败，请使用 Trace ID 联系管理员。",
            retryable=True,
        )

    visible_tasks = []
    for task in tasks:
        visible_task = dict(task)
        visible_task["status"] = (
            TaskStatus.BLOCKED.value
            if visible_task.get("dependencies")
            else TaskStatus.PENDING.value
        )
        visible_tasks.append(visible_task)
    original_result = {
        "status": "created",
        "trace_id": trace_id,
        "decomposition_id": decomposition_id,
        "idempotency_key": idempotency_key,
        "agent_id": "TodoWrite",
        "session_id": session_id,
        "event_id": event_id,
        "tasks_created": len(visible_tasks),
        "tasks": visible_tasks,
    }
    prepared_at = time.time()
    prepared = await db.execute(
        """
        UPDATE task_decompositions
        SET status = 'STAGED', task_ids = ?, response_json = ?,
            error = NULL, updated_at = ?
        WHERE decomposition_id = ? AND status = 'PROCESSING' AND trace_id = ?
        """,
        (
            json.dumps(task_ids),
            json.dumps(original_result, ensure_ascii=False),
            prepared_at,
            decomposition_id,
            trace_id,
        ),
    )
    if prepared != 1:
        await _cleanup_decomposition_attempt(
            graph,
            db,
            {
                "venue_id": principal["venue_id"],
                "decomposition_id": decomposition_id,
                "task_ids": task_ids,
            },
        )
        refreshed = await _decomposition_by_key(db, principal, idempotency_key)
        response.status_code = status.HTTP_202_ACCEPTED
        return _decomposition_status_payload(refreshed)
    prepared_row = {
        "decomposition_id": decomposition_id,
        "venue_id": principal["venue_id"],
        "requested_by": principal["user_id"],
        "idempotency_key": idempotency_key,
        "request_fingerprint": fingerprint,
        "session_id": session_id,
        "event_id": event_id,
        "trace_id": trace_id,
        "status": "STAGED",
        "task_ids": json.dumps(task_ids),
        "response_json": json.dumps(original_result, ensure_ascii=False),
        "error": None,
        "created_at": now,
        "updated_at": prepared_at,
    }
    try:
        return await _finish_prepared_decomposition(graph, db, prepared_row)
    except Exception as activation_error:
        response.status_code = status.HTTP_202_ACCEPTED
        payload = _decomposition_status_payload(prepared_row)
        payload["error"] = str(activation_error)
        return payload


@router.get("/tasks/decompositions/status")
async def get_task_decomposition_status(
    request: Request,
    idempotency_key: str = Query(..., min_length=1, max_length=128),
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise api_error(
            request,
            422,
            "TASK_IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key 不能为空。",
            "使用原任务分解请求的稳定 UUID 后重试。",
        )
    row = await _decomposition_by_key(db, principal, idempotency_key)
    if row is None:
        raise api_error(
            request,
            404,
            "TASK_DECOMPOSITION_NOT_FOUND",
            "未找到当前用户的任务分解请求。",
            "确认使用原 Idempotency-Key 和原账号后重试。",
        )
    if row["status"] == "COMPLETED" or row["status"] == "FAILED":
        return _decomposition_status_payload(row)

    graph = await _get_task_graph(request, db)
    if row["status"] == "STAGED":
        try:
            await _finish_prepared_decomposition(graph, db, row)
            row = await _decomposition_by_key(db, principal, idempotency_key)
        except Exception as recovery_error:
            payload = _decomposition_status_payload(row)
            payload["error"] = str(recovery_error)
            return payload
    elif row["status"] == "PROCESSING" and _processing_lease_expired(row):
        row = await _expire_processing_decomposition(graph, db, row)
    return _decomposition_status_payload(row)


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    principal: dict = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row or (
        principal["role"] == "operator"
        and row.get("assigned_user_id") != principal["user_id"]
    ):
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    return {"task": row}


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreateRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    event_id = body.event_id.strip() if body.event_id else None
    if event_id:
        await _require_visible_event(
            request,
            db,
            event_id=event_id,
            venue_id=principal["venue_id"],
        )
    if body.assigned_user_id:
        user = await db.fetch_one(
            "SELECT id FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
            (body.assigned_user_id, principal["venue_id"]),
        )
        if not user:
            raise api_error(request, 400, "TASK_ASSIGNEE_INVALID", "负责人不存在、跨场地或已停用。", "请选择当前场地的有效用户。")
    if body.dependencies:
        placeholders = ",".join("?" for _ in body.dependencies)
        rows = await db.fetch_all(
            f"SELECT id FROM tasks WHERE venue_id = ? AND id IN ({placeholders})",
            (principal["venue_id"], *body.dependencies),
        )
        if {row["id"] for row in rows} != set(body.dependencies):
            raise api_error(request, 400, "TASK_DEPENDENCY_INVALID", "依赖任务不存在或不属于当前场地。", "重新选择依赖任务。")
    graph = await _get_task_graph(request, db)
    task = await graph.create_task(
        session_id=body.session_id,
        description=body.description.strip(),
        dependencies=body.dependencies,
        assigned_agent=body.assigned_agent,
        assigned_user_id=body.assigned_user_id,
        max_attempts=body.max_attempts,
        venue_id=principal["venue_id"],
        event_id=event_id,
    )
    trace_id = request_trace_id(request)
    try:
        await write_audit(
            db,
            principal=principal,
            action="TASK_CREATED",
            resource_type="task",
            resource_id=task.id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={
                "business_id": task.business_id,
                "event_id": event_id,
                "session_id": body.session_id,
                "dependencies": body.dependencies,
            },
        )
        if event_id:
            await append_event_activity(
                db,
                venue_id=principal["venue_id"],
                event_id=event_id,
                session_id=body.session_id,
                trace_id=trace_id,
                activity_type="TASK_CREATED",
                created_by=principal["user_id"],
                idempotency_key=f"task-created:{task.id}",
                payload={
                    "task_id": task.id,
                    "business_id": task.business_id,
                    "title": task.description,
                    "status": task.status.value,
                    "status_label": (
                        "等待前置任务"
                        if task.status == TaskStatus.BLOCKED
                        else "待开始"
                    ),
                    "assigned_user_id": task.assigned_user_id,
                    "dependencies": task.dependencies,
                },
            )
    except Exception:
        rollback_errors = await _rollback_manual_task_creation(
            graph,
            db,
            venue_id=principal["venue_id"],
            event_id=event_id,
            task_id=task.id,
        )
        if rollback_errors:
            raise api_error(
                request,
                500,
                "TASK_CREATION_ROLLBACK_FAILED",
                "任务创建失败且自动回滚未完整完成。",
                "请停止重试并使用 Trace ID 联系管理员人工核查。",
                retryable=False,
            )
        raise api_error(
            request,
            500,
            "TASK_CREATION_PERSISTENCE_FAILED",
            "任务创建结果未能完整持久化，已安全回滚。",
            "稍后重试；如持续失败，请使用 Trace ID 联系管理员。",
            retryable=True,
        )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.patch("/tasks/{task_id}/assignment")
async def assign_task(
    task_id: str,
    body: TaskAssignRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    current = await _task_row(db, task_id, principal["venue_id"])
    if not current:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if body.assigned_user_id:
        user = await db.fetch_one(
            "SELECT id FROM users WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'",
            (body.assigned_user_id, principal["venue_id"]),
        )
        if not user:
            raise api_error(request, 400, "TASK_ASSIGNEE_INVALID", "负责人不存在、跨场地或已停用。", "请选择当前场地的有效用户。")
    graph = await _get_task_graph(request, db)
    task = await graph.assign_task(
        task_id,
        assigned_user_id=body.assigned_user_id,
        assigned_agent=body.assigned_agent,
    )
    if not task:
        raise api_error(request, 404, "TASK_NOT_LOADED", "任务尚未载入任务图。", "重启应用恢复任务图后重试。", retryable=True)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_ASSIGNED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"assigned_user_id": body.assigned_user_id, "assigned_agent": body.assigned_agent},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_ASSIGNED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary="任务负责人已更新。",
        extra_payload={
            "previous_assigned_user_id": current.get("assigned_user_id"),
            "previous_assigned_agent": current.get("assigned_agent"),
        },
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/tasks/{task_id}/start")
async def start_task(
    task_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager", "operator")),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if principal["role"] == "operator" and row.get("assigned_user_id") not in (None, "", principal["user_id"]):
        raise api_error(request, 403, "TASK_NOT_ASSIGNED", "只能执行分配给自己的任务。", "请联系值班经理调整负责人。")
    graph = await _get_task_graph(request, db)
    if principal["role"] == "operator" and not row.get("assigned_user_id"):
        await graph.assign_task(task_id, assigned_user_id=principal["user_id"])
    task = await graph.start_task(task_id, agent_name=row.get("assigned_agent"))
    if not task or task.status != TaskStatus.RUNNING:
        raise api_error(request, 409, "TASK_NOT_RUNNABLE", "任务当前不可执行，可能仍在等待依赖。", "先完成依赖任务或恢复失败任务。")
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_STARTED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_STARTED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary="任务已开始执行。",
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    body: TaskCompleteRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager", "operator")),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if principal["role"] == "operator" and row.get("assigned_user_id") != principal["user_id"]:
        raise api_error(request, 403, "TASK_NOT_ASSIGNED", "只能完成分配给自己的任务。", "请联系值班经理调整负责人。")
    if row["status"] != TaskStatus.RUNNING.value:
        raise api_error(request, 409, "TASK_NOT_RUNNING", "只有执行中的任务可以完成。", "先开始任务。")
    graph = await _get_task_graph(request, db)
    task = await graph.complete_task(task_id, result=body.result)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_COMPLETED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
    )
    result_summary = body.result.get("summary")
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_COMPLETED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary=str(result_summary or "任务已完成并提交现场结果。"),
        extra_payload={"result": body.result},
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/tasks/{task_id}/fail")
async def fail_task(
    task_id: str,
    body: TaskFailRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager", "operator")),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if principal["role"] == "operator" and row.get("assigned_user_id") != principal["user_id"]:
        raise api_error(request, 403, "TASK_NOT_ASSIGNED", "只能更新分配给自己的任务。", "请联系值班经理调整负责人。")
    if row["status"] != TaskStatus.RUNNING.value:
        raise api_error(
            request,
            409,
            "TASK_NOT_RUNNING",
            "只有执行中的任务可以上报执行失败。",
            "人工阻塞任务请由值班经理解除阻塞；其他状态请刷新任务详情。",
        )
    graph = await _get_task_graph(request, db)
    task = await graph.fail_task(task_id, body.error.strip())
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_FAILED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={
            "error": body.error.strip(),
            "attempts": task.attempts if task else row.get("attempts", 0),
            "max_attempts": task.max_attempts if task else row.get("max_attempts", 0),
            "will_retry": task.status == TaskStatus.PENDING if task else False,
        },
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_FAILED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary=body.error.strip(),
        extra_payload={
            "error": body.error.strip(),
            "will_retry": task.status == TaskStatus.PENDING if task else False,
        },
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if row["status"] != TaskStatus.FAILED.value:
        raise api_error(request, 409, "TASK_NOT_FAILED", "只有失败且重试耗尽的任务可以恢复。", "查看任务当前状态。")
    graph = await _get_task_graph(request, db)
    task = await graph.retry_task(task_id)
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_RETRIED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"attempts": task.attempts, "max_attempts": task.max_attempts},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_RETRIED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary="任务已由值班经理恢复为待执行。",
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/tasks/{task_id}/unblock")
async def unblock_task(
    task_id: str,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    row = await _task_row(db, task_id, principal["venue_id"])
    if not row:
        raise api_error(request, 404, "TASK_NOT_FOUND", "任务不存在。", "刷新任务列表后重试。")
    if row["status"] != TaskStatus.BLOCKED.value or not row.get("block_reason"):
        raise api_error(
            request,
            409,
            "TASK_NOT_MANUALLY_BLOCKED",
            "任务当前没有待处理的人工阻塞。",
            "查看任务当前状态和依赖关系。",
        )
    graph = await _get_task_graph(request, db)
    task = await graph.unblock_task(task_id)
    if not task or task.block_reason:
        raise api_error(
            request,
            503,
            "TASK_UNBLOCK_NOT_PERSISTED",
            "任务恢复状态未能保存。",
            "稍后重试或联系系统管理员。",
            retryable=True,
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_UNBLOCKED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"block_reason": row["block_reason"]},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_UNBLOCKED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary="现场障碍已确认解决，任务已恢复推进。",
        extra_payload={"previous_block_reason": row["block_reason"]},
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.patch("/push_logs/{push_id}/adoption")
async def update_push_adoption(
    push_id: str,
    body: PushAdoptionRequest,
    request: Request,
    principal: dict = Depends(require_roles("admin", "manager")),
    db=Depends(get_request_db),
):
    if body.status == "pending":
        row = await db.fetch_one(
            "SELECT adoption_status FROM push_logs WHERE push_id = ? AND venue_id = ?",
            (push_id, principal["venue_id"]),
        )
        if not row:
            raise api_error(request, 404, "PUSH_LOG_NOT_FOUND", "动作日志不存在。", "刷新日志列表后重试。")
        if row.get("adoption_status") != "pending":
            raise api_error(
                request,
                409,
                "PUSH_LOG_STATE_CHANGED",
                "动作日志已完成采纳确认，不能重新打开。",
                "刷新动作日志后查看当前采纳状态。",
            )
        return {
            "updated": False,
            "push_id": push_id,
            "status": "pending",
            "trace_id": request_trace_id(request),
        }
    confirmed_at = time.time() if body.status in {"adopted", "rejected"} else None
    updated = await db.execute(
        """
        UPDATE push_logs SET adoption_status = ?, confirmed_notes = ?, confirmed_by = ?, confirmed_at = ?
        WHERE push_id = ? AND venue_id = ? AND adoption_status = 'pending'
        """,
        (body.status, body.notes, principal["user_id"], confirmed_at, push_id, principal["venue_id"]),
    )
    if updated != 1:
        row = await db.fetch_one(
            "SELECT adoption_status FROM push_logs WHERE push_id = ? AND venue_id = ?",
            (push_id, principal["venue_id"]),
        )
        if not row:
            raise api_error(request, 404, "PUSH_LOG_NOT_FOUND", "动作日志不存在。", "刷新日志列表后重试。")
        raise api_error(
            request,
            409,
            "PUSH_LOG_STATE_CHANGED",
            "动作日志已被其他操作完成采纳确认。",
            "刷新动作日志后查看当前采纳状态。",
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="PUSH_ADOPTION_UPDATED",
        resource_type="push_log",
        resource_id=push_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"status": body.status},
    )
    return {"updated": True, "push_id": push_id, "status": body.status, "trace_id": trace_id}
