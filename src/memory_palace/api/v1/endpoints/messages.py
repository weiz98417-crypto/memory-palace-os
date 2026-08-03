"""API v1 message intake and status endpoints."""

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...audit import write_audit
from ...auth import require_auth
from ....core.message_runs import MessageRunRepository
from ....core.queue_worker import get_message_queue
from ..schemas import MessageAcceptedResponse, MessageCreateRequest, MessageStatusResponse

router = APIRouter()


@router.post("/", response_model=MessageAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_message(
    req: MessageCreateRequest,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    """接受自由文本消息并交给异步 Agent 处理链路。"""
    message_id = str(uuid.uuid4())
    trace_id = uuid.uuid4().hex
    session_id = req.session_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    metadata = {**(req.metadata or {}), "venue_id": principal["venue_id"]}

    queue = get_message_queue()
    if queue is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="消息队列尚未就绪")

    db_client = getattr(request.app.state, "db_client", None)
    if db_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="运行状态存储尚未就绪")
    if req.session_id:
        existing_session = await db_client.fetch_one(
            "SELECT venue_id, user_id FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if existing_session and (
            existing_session.get("venue_id") != principal["venue_id"]
            or existing_session.get("user_id") != principal["user_id"]
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    repository = MessageRunRepository(db_client)
    await repository.create(
        message_id=message_id,
        trace_id=trace_id,
        session_id=session_id,
        user_id=principal["user_id"],
        venue_id=principal["venue_id"],
        content=req.content,
    )

    try:
        await write_audit(
            db_client,
            principal=principal,
            action="MESSAGE_RUN_CREATED",
            resource_type="message_run",
            resource_id=message_id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={"session_id": session_id, "status": "QUEUED"},
        )
    except Exception as exc:
        try:
            await repository.mark_failed(message_id, "消息审计记录失败")
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="消息审计记录失败",
        ) from exc

    try:
        await queue.put(
            {
                "msg_id": message_id,
                "trace_id": trace_id,
                "session_id": session_id,
                "from_user": principal["user_id"],
                "venue_id": principal["venue_id"],
                "msg_type": "text",
                "content": req.content,
                "timestamp": time.time(),
                "metadata": metadata,
            }
        )
    except Exception as exc:
        await repository.mark_failed(message_id, "消息入队失败")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="消息入队失败",
        ) from exc

    return MessageAcceptedResponse(
        message_id=message_id,
        trace_id=trace_id,
        session_id=session_id,
        status="QUEUED",
        created_at=created_at,
    )


@router.get(
    "/{message_id}",
    response_model=MessageStatusResponse,
    response_model_exclude_none=True,
)
async def get_message(
    message_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
):
    """获取消息详情"""
    db_client = getattr(request.app.state, "db_client", None)
    if db_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="运行状态存储尚未就绪")

    msg = await MessageRunRepository(db_client).get(
        message_id,
        principal["venue_id"],
        user_id=principal["user_id"],
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if principal.get("role") != "admin":
        msg["target_agent"] = None
        msg["result"] = None
        msg["dead_letter_id"] = None
    return MessageStatusResponse(**msg)
