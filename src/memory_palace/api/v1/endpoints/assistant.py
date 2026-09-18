"""Employee-facing assistant endpoints."""

import json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel, Field, StringConstraints

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth
from ...errors import api_error
from ....core.attachments import message_attachments as load_message_attachments
from ....core.canonical_ingress import (
    CanonicalIngressError,
    CanonicalMessageIngress,
    IngressMessage,
)
from ....core.message_runs import MessageRunRepository
from ....core.queue_worker import get_message_queue
from ....core.task_activities import append_task_activity
from ....core.task_graph import Task, TaskStatus
from .workflows import _get_task_graph
from ..schemas import (
    AssistantConversationMessage,
    AssistantIdentityResponse,
    AssistantMessageCreateRequest,
    AssistantMessageRetryResponse,
    AssistantSessionMessagesResponse,
    AssistantSessionSummary,
    AssistantSessionsResponse,
    CanonicalMessageAcceptedResponse,
)


router = APIRouter()


class AssistantTaskCompleteRequest(BaseModel):
    summary: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=2, max_length=4000),
    ]
    result: dict[str, Any] = Field(default_factory=dict)


class AssistantTaskBlockRequest(BaseModel):
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=2, max_length=2000),
    ]


async def _employee_task_row(db, principal: dict[str, str], task_id: str):
    return await db.fetch_one(
        """
        SELECT * FROM tasks
        WHERE id = ? AND venue_id = ? AND assigned_user_id = ?
          AND status != 'STAGED'
        """,
        (task_id, principal["venue_id"], principal["user_id"]),
    )


async def _require_employee_task(
    db,
    principal: dict[str, str],
    task_id: str,
    request: Request,
):
    row = await _employee_task_row(db, principal, task_id)
    if not row:
        raise api_error(
            request,
            404,
            "TASK_NOT_FOUND",
            "任务不存在或未分配给当前员工。",
            "刷新工作列表后重试。",
        )
    return row


async def _employee_event_row(db, principal: dict[str, str], event_id: str):
    return await db.fetch_one(
        """
        SELECT * FROM confirmed_events AS event
        WHERE event.event_id = ? AND event.venue_id = ?
          AND (
            event.assigned_to = ?
            OR event.from_user = ?
            OR event.from_user = ?
            OR EXISTS (
                SELECT 1 FROM channel_identities AS identity
                WHERE identity.venue_id = event.venue_id
                  AND identity.user_id = ?
                  AND identity.external_user_id = event.from_user
                  AND identity.status = 'ACTIVE'
            )
          )
        """,
        (
            event_id,
            principal["venue_id"],
            principal["user_id"],
            principal["user_id"],
            principal.get("username", ""),
            principal["user_id"],
        ),
    )


async def _require_employee_event(
    db,
    principal: dict[str, str],
    event_id: str,
    request: Request,
):
    row = await _employee_event_row(db, principal, event_id)
    if not row:
        raise api_error(
            request,
            404,
            "EVENT_NOT_FOUND",
            "事件不存在或当前员工无权查看。",
            "返回我的工作列表后刷新事件状态。",
        )
    return row


@router.get("/work")
async def get_assistant_work(
    task_status: Optional[str] = Query(default=None),
    event_status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    task_sql = """
        SELECT * FROM tasks
        WHERE venue_id = ? AND assigned_user_id = ? AND status != 'STAGED'
    """
    task_params: list[object] = [principal["venue_id"], principal["user_id"]]
    if task_status:
        task_sql += " AND status = ?"
        task_params.append(task_status.upper())
    task_sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    task_params.extend((limit, offset))
    task_rows = await db.fetch_all(task_sql, tuple(task_params))

    event_sql = """
        SELECT * FROM confirmed_events AS event
        WHERE event.venue_id = ?
          AND (
            event.assigned_to = ?
            OR event.from_user = ?
            OR event.from_user = ?
            OR EXISTS (
                SELECT 1 FROM channel_identities AS identity
                WHERE identity.venue_id = event.venue_id
                  AND identity.user_id = ?
                  AND identity.external_user_id = event.from_user
                  AND identity.status = 'ACTIVE'
            )
          )
    """
    event_params: list[object] = [
        principal["venue_id"],
        principal["user_id"],
        principal["user_id"],
        principal.get("username", ""),
        principal["user_id"],
    ]
    if event_status:
        event_sql += " AND event.status = ?"
        event_params.append(event_status.upper())
    event_sql += " ORDER BY event.created_at DESC LIMIT ? OFFSET ?"
    event_params.extend((limit, offset))
    event_rows = await db.fetch_all(event_sql, tuple(event_params))

    return {
        "tasks": [Task.from_dict(row).to_dict() for row in task_rows],
        "events": event_rows,
        "limit": limit,
        "offset": offset,
    }


@router.get("/work/tasks/{task_id}")
async def get_assistant_task(
    task_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _require_employee_task(db, principal, task_id, request)
    return {"task": Task.from_dict(row).to_dict()}


@router.get("/work/events/{event_id}")
async def get_assistant_event(
    event_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _require_employee_event(db, principal, event_id, request)
    return {"event": row}


@router.get("/knowledge/sops/{sop_id}")
async def get_assistant_sop_reference(
    sop_id: int,
    request: Request,
    version: Optional[str] = Query(default=None, min_length=1, max_length=20),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await db.fetch_one(
        """
        SELECT
            sop.id,
            sop.title,
            sop.content,
            sop.category,
            sop.version,
            sop.status,
            sop.published_at,
            COALESCE(publisher.display_name, publisher.username, '知识负责人') AS publisher_name
        FROM sop_documents AS sop
        LEFT JOIN users AS publisher ON publisher.id = sop.reviewed_by
        WHERE sop.id = ? AND sop.venue_id = ? AND sop.status = 'PUBLISHED'
        """,
        (sop_id, principal["venue_id"]),
    )
    if not row or (version is not None and str(row["version"]) != version):
        raise api_error(
            request,
            404,
            "SOP_REFERENCE_NOT_FOUND",
            "已发布 SOP 不存在或当前员工无权查看。",
            "返回助手会话后刷新引用卡片。",
        )
    return {
        "sop": {
            "id": str(row["id"]),
            "source_type": "SOP",
            "source_label": "已发布 SOP",
            "title": row["title"],
            "content": row["content"],
            "category": row["category"],
            "version": str(row["version"]),
            "status": row["status"],
            "status_label": "已发布",
            "publisher_name": row["publisher_name"],
            "published_at": row["published_at"],
        }
    }


@router.post("/work/tasks/{task_id}/start")
async def start_assistant_task(
    task_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _require_employee_task(db, principal, task_id, request)
    if row["status"] != TaskStatus.PENDING.value:
        raise api_error(
            request,
            409,
            "TASK_NOT_RUNNABLE",
            "任务当前不可开始。",
            "刷新任务详情，确认任务处于待执行状态。",
        )
    if row.get("event_id"):
        approval_gate = await db.fetch_one(
            """
            SELECT approval.status, approval.execution_status
            FROM scenic_incidents AS incident
            JOIN approval_requests AS approval
              ON approval.approval_id = incident.decision_approval_id
             AND approval.venue_id = incident.venue_id
            WHERE incident.venue_id = ?
              AND incident.event_id = ?
              AND incident.repair_task_id = ?
            """,
            (principal["venue_id"], row["event_id"], task_id),
        )
        if approval_gate and (
            approval_gate["status"] != "APPROVED"
            or approval_gate["execution_status"] != "SUCCEEDED"
        ):
            raise api_error(
                request,
                409,
                "TASK_APPROVAL_REQUIRED",
                "该检修任务必须等待车辆处置审批完成。",
                "请由值班经理批准并执行审批后再开始任务。",
            )
    graph = await _get_task_graph(request, db)
    task = await graph.start_task(task_id, agent_name=row.get("assigned_agent"))
    if not task or task.status != TaskStatus.RUNNING:
        raise api_error(
            request,
            409,
            "TASK_NOT_RUNNABLE",
            "任务当前不可开始。",
            "刷新任务详情，确认前置任务已完成。",
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_STARTED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"entry": "assistant_work"},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_STARTED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary="任务已开始执行。",
        extra_payload={"entry": "assistant_work"},
    )
    scenic_operations = getattr(request.app.state, "scenic_operations", None)
    if scenic_operations is not None and task.event_id:
        await scenic_operations.reconcile_event(principal["venue_id"], task.event_id)
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/work/tasks/{task_id}/complete")
async def complete_assistant_task(
    task_id: str,
    body: AssistantTaskCompleteRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _require_employee_task(db, principal, task_id, request)
    if row["status"] != TaskStatus.RUNNING.value:
        raise api_error(
            request,
            409,
            "TASK_NOT_RUNNING",
            "只有执行中的任务可以完成。",
            "先开始任务。",
        )
    summary = body.summary.strip()
    graph = await _get_task_graph(request, db)
    structured_result = dict(body.result)
    structured_result["summary"] = summary
    if len(json.dumps(structured_result, ensure_ascii=False)) > 8000:
        raise api_error(
            request,
            422,
            "TASK_RESULT_TOO_LARGE",
            "结构化现场结果过长。",
            "精简检查项后重新提交。",
        )
    task = await graph.complete_task(task_id, result=structured_result)
    if not task:
        raise api_error(
            request,
            503,
            "TASK_NOT_LOADED",
            "任务状态暂时无法更新。",
            "稍后重试或联系管理员恢复任务服务。",
            retryable=True,
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_COMPLETED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"entry": "assistant_work", "summary_length": len(summary)},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_COMPLETED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary=summary,
        extra_payload={
            "entry": "assistant_work",
            "result": structured_result,
        },
    )
    scenic_operations = getattr(request.app.state, "scenic_operations", None)
    if scenic_operations is not None and task.event_id:
        await scenic_operations.reconcile_event(principal["venue_id"], task.event_id)
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post("/work/tasks/{task_id}/block")
async def block_assistant_task(
    task_id: str,
    body: AssistantTaskBlockRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    row = await _require_employee_task(db, principal, task_id, request)
    if row["status"] != TaskStatus.RUNNING.value:
        raise api_error(
            request,
            409,
            "TASK_NOT_RUNNING",
            "只有执行中的任务可以上报阻塞。",
            "先开始任务，或刷新任务详情。",
        )
    reason = body.reason.strip()
    graph = await _get_task_graph(request, db)
    task = await graph.block_task(task_id, reason)
    if not task or task.status != TaskStatus.BLOCKED or task.block_reason != reason:
        raise api_error(
            request,
            503,
            "TASK_BLOCK_NOT_PERSISTED",
            "任务阻塞状态未能保存。",
            "稍后重试或联系管理员查看任务服务。",
            retryable=True,
        )
    trace_id = request_trace_id(request)
    await write_audit(
        db,
        principal=principal,
        action="TASK_BLOCKED",
        resource_type="task",
        resource_id=task_id,
        outcome="SUCCEEDED",
        trace_id=trace_id,
        metadata={"entry": "assistant_work", "reason": reason},
    )
    await append_task_activity(
        db,
        venue_id=principal["venue_id"],
        task=task,
        activity_type="TASK_BLOCKED",
        created_by=principal["user_id"],
        trace_id=trace_id,
        summary=reason,
        extra_payload={"entry": "assistant_work", "reason": reason},
    )
    return {"task": task.to_dict(), "trace_id": trace_id}


@router.post(
    "/messages",
    response_model=CanonicalMessageAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_assistant_message(
    body: AssistantMessageCreateRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    queue = get_message_queue()
    if queue is None:
        raise HTTPException(status_code=503, detail="Message queue is not ready")

    try:
        accepted = await CanonicalMessageIngress(db, queue).accept(
            IngressMessage(
                channel="WEB",
                content=body.content,
                external_message_id=body.external_message_id,
                external_conversation_id=body.external_conversation_id,
                metadata=body.metadata or {},
                attachments=body.attachments,
            ),
            actor=principal,
        )
    except CanonicalIngressError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return CanonicalMessageAcceptedResponse(**accepted.__dict__)


async def _visible_identity(db, principal: dict[str, str], acting_user_id: Optional[str]):
    user_id = acting_user_id or principal["user_id"]
    if user_id != principal["user_id"] and principal.get("role") not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="Acting identity is not allowed")
    row = await db.fetch_one(
        """
        SELECT id AS user_id, display_name, role, venue_id, status
        FROM users WHERE id = ?
        """,
        (user_id,),
    )
    if not row or row["venue_id"] != principal["venue_id"]:
        raise HTTPException(status_code=404, detail="Employee identity not found")
    if row["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="Employee identity is inactive")
    return row


@router.post(
    "/messages/{message_id}/retry",
    response_model=AssistantMessageRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_assistant_message(
    message_id: str,
    request: Request,
    acting_user_id: Optional[str] = Query(default=None),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    identity = await _visible_identity(db, principal, acting_user_id)
    run = await db.fetch_one(
        """
        SELECT * FROM message_runs
        WHERE message_id = ? AND venue_id = ? AND user_id = ?
        """,
        (message_id, principal["venue_id"], identity["user_id"]),
    )
    if run is None:
        raise api_error(
            request,
            404,
            "MESSAGE_NOT_FOUND",
            "没有找到可重试的原消息。",
            "刷新会话后从本人失败消息重试。",
        )
    if run["status"] not in {"RETRY_REQUIRED", "DEAD_LETTERED"}:
        raise api_error(
            request,
            409,
            "MESSAGE_RETRY_NOT_ALLOWED",
            "该消息当前不需要人工重试。",
            "等待当前处理结束；仅在消息显示需要人工重试时操作。",
        )
    dead_letter_id = str(run.get("dead_letter_id") or "").strip()
    queue = get_message_queue()
    if not dead_letter_id or queue is None or not hasattr(queue, "retry_dead_letter"):
        raise api_error(
            request,
            503,
            "MESSAGE_RETRY_UNAVAILABLE",
            "原消息的重试记录暂时不可用。",
            "稍后重试或联系管理员检查死信队列。",
            retryable=True,
        )
    try:
        retried = await queue.retry_dead_letter(dead_letter_id)
    except Exception as exc:
        if "ALREADY_RETRIED" in str(exc).upper():
            raise api_error(
                request,
                409,
                "MESSAGE_ALREADY_RETRIED",
                "该消息已经重新提交，请勿重复操作。",
                "返回原会话查看处理进度。",
            ) from exc
        raise api_error(
            request,
            503,
            "MESSAGE_RETRY_UNAVAILABLE",
            "原消息暂时无法重新提交。",
            "稍后从同一消息再次重试。",
            retryable=True,
        ) from exc
    if not retried:
        raise api_error(
            request,
            409,
            "MESSAGE_ALREADY_RETRIED",
            "该消息已经重新提交或死信记录已处理。",
            "返回原会话查看处理进度。",
        )

    repository = MessageRunRepository(db)
    await repository.mark_manual_retry(message_id)
    updated = await repository.get(message_id, principal["venue_id"])
    try:
        await write_audit(
            db,
            principal=principal,
            action="MESSAGE_MANUAL_RETRY_REQUESTED",
            resource_type="message_run",
            resource_id=message_id,
            outcome="SUCCEEDED",
            trace_id=request_trace_id(request),
            metadata={
                "acting_user_id": identity["user_id"],
                "attempt_count": updated["attempt_count"],
                "manual_retry_count": updated["manual_retry_count"],
            },
        )
    except Exception as exc:
        logger.error(
            "人工重试审计写入失败 [message_id={}]: {}",
            message_id,
            type(exc).__name__,
        )
    return AssistantMessageRetryResponse(
        message_id=message_id,
        trace_id=updated["trace_id"],
        session_id=updated["session_id"],
        attempt_count=updated["attempt_count"],
        manual_retry_count=updated["manual_retry_count"],
        stream_message_id=str(retried.get("stream_message_id") or ""),
    )


async def _session_summary(db, *, session_id: str, venue_id: str, user_id: str):
    row = await db.fetch_one(
        """
        SELECT s.session_id, s.user_id, s.venue_id, s.stage,
               s.message_count, s.created_at, s.updated_at,
               c.channel, c.external_conversation_id,
               u.display_name, u.role
        FROM sessions s
        JOIN channel_conversations c ON c.session_id = s.session_id
        JOIN users u ON u.id = s.user_id AND u.venue_id = s.venue_id
        WHERE s.session_id = ? AND s.venue_id = ? AND s.user_id = ?
          AND c.status = 'ACTIVE' AND u.status = 'ACTIVE'
        """,
        (session_id, venue_id, user_id),
    )
    if not row:
        return None
    latest = await db.fetch_one(
        """
        SELECT content, reply_text, status FROM message_runs
        WHERE session_id = ? AND venue_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, venue_id),
    )
    count = await db.fetch_one(
        "SELECT COUNT(*) AS count FROM message_runs WHERE session_id = ? AND venue_id = ?",
        (session_id, venue_id),
    )
    row["message_count"] = int(count["count"]) if count else 0
    row["last_message"] = (
        (latest.get("reply_text") or latest.get("content")) if latest else None
    )
    row["last_status"] = latest.get("status") if latest else None
    return row


@router.get("/sessions", response_model=AssistantSessionsResponse)
async def list_assistant_sessions(
    acting_user_id: Optional[str] = Query(default=None),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    identity = await _visible_identity(db, principal, acting_user_id)
    rows = await db.fetch_all(
        """
        SELECT session_id FROM channel_conversations
        WHERE venue_id = ? AND user_id = ? AND status = 'ACTIVE'
        ORDER BY updated_at DESC
        """,
        (principal["venue_id"], identity["user_id"]),
    )
    sessions = []
    for item in rows:
        summary = await _session_summary(
            db,
            session_id=item["session_id"],
            venue_id=principal["venue_id"],
            user_id=identity["user_id"],
        )
        if summary:
            sessions.append(AssistantSessionSummary(**summary))
    return AssistantSessionsResponse(sessions=sessions)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=AssistantSessionMessagesResponse,
)
async def get_assistant_session_messages(
    session_id: str,
    acting_user_id: Optional[str] = Query(default=None),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    identity = await _visible_identity(db, principal, acting_user_id)
    summary = await _session_summary(
        db,
        session_id=session_id,
        venue_id=principal["venue_id"],
        user_id=identity["user_id"],
    )
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")

    runs = await db.fetch_all(
        """
        SELECT * FROM message_runs
        WHERE session_id = ? AND venue_id = ?
        ORDER BY created_at, message_id
        """,
        (session_id, principal["venue_id"]),
    )
    attachments_by_message = await load_message_attachments(
        db,
        venue_id=principal["venue_id"],
        message_ids=(run["message_id"] for run in runs),
    )
    messages = []
    for run in runs:
        try:
            result = json.loads(run.get("result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        cards = result.get("business_cards")
        if not isinstance(cards, list):
            cards = []
        common = {
            "message_id": run["message_id"],
            "session_id": session_id,
            "trace_id": run["trace_id"],
            "channel": run.get("channel") or summary["channel"],
            "error": run.get("error"),
        }
        messages.append(
            AssistantConversationMessage(
                id=f"{run['message_id']}:user",
                role="user",
                content=run["content"],
                status="SENT",
                created_at=float(run["created_at"]),
                business_cards=[],
                attachments=attachments_by_message.get(run["message_id"], []),
                **common,
            )
        )
        messages.append(
            AssistantConversationMessage(
                id=f"{run['message_id']}:assistant",
                role="assistant",
                content=run.get("reply_text"),
                status=run["status"],
                created_at=float(run.get("processed_at") or run["updated_at"]),
                business_cards=cards,
                attachments=[],
                attempt_count=int(run.get("attempt_count") or 0),
                max_attempts=int(run.get("max_attempts") or 4),
                manual_retry_count=int(run.get("manual_retry_count") or 0),
                retryable=run["status"] in {"RETRY_REQUIRED", "DEAD_LETTERED"},
                delivery_status=run.get("delivery_status"),
                delivery_error=run.get("delivery_error"),
                delivered_at=run.get("delivered_at"),
                **common,
            )
        )
    return AssistantSessionMessagesResponse(
        session=AssistantSessionSummary(**summary),
        identity=AssistantIdentityResponse(**identity),
        messages=messages,
    )
