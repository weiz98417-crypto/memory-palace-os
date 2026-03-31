"""
v1/endpoints/sessions.py - Sessions endpoint
"""
from fastapi import APIRouter, HTTPException, Query
from ..schemas import SessionInfo
from typing import Optional
from datetime import datetime

router = APIRouter()


@router.get("/", response_model=list[SessionInfo])
async def list_sessions(
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """列出会话"""
    from ...knowledge.db_client import get_sessions
    sessions = await get_sessions(user_id=user_id, limit=limit)
    return [SessionInfo(**s) for s in sessions]


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    """获取会话详情"""
    from ...knowledge.db_client import get_session_by_id
    session = await get_session_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfo(**session)


@router.delete("/{session_id}")
async def close_session(session_id: str):
    """关闭会话"""
    from ...session_state import SessionStateManager
    try:
        manager = SessionStateManager()
        await manager.close_session(session_id)
        return {"status": "ok", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
