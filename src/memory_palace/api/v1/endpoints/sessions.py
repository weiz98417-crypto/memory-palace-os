"""
v1/endpoints/sessions.py - Sessions endpoint
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ..schemas import SessionInfo
from typing import Optional

from ...audit import request_trace_id, write_audit
from ...auth import get_request_db, require_auth
from ...errors import api_error

router = APIRouter()


@router.get("/", response_model=list[SessionInfo])
async def list_sessions(
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    """列出会话"""
    effective_user = user_id
    if principal["role"] == "operator":
        effective_user = principal["user_id"]
    if effective_user:
        sessions = await db.fetch_all(
            """
            SELECT * FROM sessions
            WHERE venue_id = ? AND user_id = ?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (principal["venue_id"], effective_user, limit),
        )
    else:
        sessions = await db.fetch_all(
            "SELECT * FROM sessions WHERE venue_id = ? ORDER BY updated_at DESC LIMIT ?",
            (principal["venue_id"], limit),
        )
    return [SessionInfo(**s) for s in sessions]


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    """获取会话详情"""
    sql = "SELECT * FROM sessions WHERE session_id = ? AND venue_id = ?"
    params = [session_id, principal["venue_id"]]
    if principal["role"] == "operator":
        sql += " AND user_id = ?"
        params.append(principal["user_id"])
    session = await db.fetch_one(sql, tuple(params))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfo(**session)


@router.delete("/{session_id}")
async def close_session(
    session_id: str,
    request: Request,
    principal: dict[str, str] = Depends(require_auth),
    db=Depends(get_request_db),
):
    """关闭会话"""
    lookup_sql = "SELECT stage FROM sessions WHERE session_id = ? AND venue_id = ?"
    params = [session_id, principal["venue_id"]]
    if principal["role"] == "operator":
        lookup_sql += " AND user_id = ?"
        params.append(principal["user_id"])
    trace_id = request_trace_id(request)
    current = await db.fetch_one(lookup_sql, tuple(params))
    if current is None:
        await write_audit(
            db,
            principal=principal,
            action="SESSION_CLOSE_DENIED",
            resource_type="session",
            resource_id=session_id,
            outcome="DENIED",
            trace_id=trace_id,
            metadata={"reason": "not_found_or_not_visible"},
        )
        raise api_error(request, 404, "SESSION_NOT_FOUND", "会话不存在。", "刷新会话列表后重试。")

    changed = await db.execute(
        "UPDATE sessions SET stage = 'CLOSED', updated_at = ? WHERE session_id = ? AND venue_id = ? AND stage = ?",
        (time.time(), session_id, principal["venue_id"], current["stage"]),
    )
    if changed == 0:
        raise api_error(request, 409, "SESSION_STATE_CHANGED", "会话状态已变化。", "刷新会话后重试。")
    try:
        await write_audit(
            db,
            principal=principal,
            action="SESSION_CLOSED",
            resource_type="session",
            resource_id=session_id,
            outcome="SUCCEEDED",
            trace_id=trace_id,
            metadata={"previous_stage": current["stage"]},
        )
    except Exception:
        await db.execute(
            "UPDATE sessions SET stage = ?, updated_at = ? WHERE session_id = ? AND venue_id = ? AND stage = 'CLOSED'",
            (current["stage"], time.time(), session_id, principal["venue_id"]),
        )
        raise
    return {"status": "ok", "session_id": session_id, "trace_id": trace_id}
