"""
v1/endpoints/messages.py - Message endpoint
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from ..schemas import MessageCreateRequest, MessageResponse
from datetime import datetime
import uuid

router = APIRouter()


@router.post("/", response_model=MessageResponse, status_code=202)
async def create_message(req: MessageCreateRequest, background_tasks: BackgroundTasks):
    """
    提交用户消息（异步处理，返回 message_id）
    """
    message_id = str(uuid.uuid4())
    session_id = req.session_id or str(uuid.uuid4())

    # Enqueue to message queue for async processing
    from ...queue_worker import get_message_queue
    queue = get_message_queue()
    await queue.put({
        "message_id": message_id,
        "session_id": session_id,
        "user_id": req.user_id,
        "content": req.content,
        "metadata": req.metadata or {},
    })

    return MessageResponse(
        message_id=message_id,
        session_id=session_id,
        content=req.content,
        agent_name="router",
        created_at=datetime.now(),
        metadata=req.metadata,
    )


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(message_id: str):
    """获取消息详情"""
    from ...knowledge.db_client import get_message
    msg = await get_message(message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessageResponse(**msg)
