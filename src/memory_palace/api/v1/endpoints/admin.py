"""
v1/endpoints/admin.py - Admin endpoint

[升级] Phase 2 新增审批 API:
- GET /approvals - 列出待审批请求
- POST /approvals/{id}/approve - 批准
- POST /approvals/{id}/reject - 拒绝
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from ..schemas import HealthResponse
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel
import time

logger_model = __import__('logging').getLogger(__name__)
router = APIRouter()

_START_TIME = time.time()


# ---------------------------------------------------------------------------
# 审批相关模型
# ---------------------------------------------------------------------------

class ApprovalResponse(BaseModel):
    approval_id: str
    tool_name: str
    args: dict
    session_id: str
    user_id: str
    requested_at: float
    requested_by: str
    status: str


class ApproveRequest(BaseModel):
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    comment: Optional[str] = None


def get_admin_user():
    """Admin auth placeholder — implement with actual auth"""
    return {"user_id": "admin", "role": "admin"}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    from ....knowledge.db_client import check_connection

    components = {"db": "unknown", "llm": "unknown", "queue": "unknown"}

    try:
        ok = await check_connection()
        components["db"] = "healthy" if ok else "unhealthy"
    except Exception:
        components["db"] = "unhealthy"

    try:
        from ....tools.llm_wrapper import get_llm_client
        llm = get_llm_client()
        components["llm"] = "healthy"
    except Exception:
        components["llm"] = "unhealthy"

    try:
        from ....core.queue_worker import get_message_queue
        q = get_message_queue()
        components["queue"] = "healthy" if q else "unhealthy"
    except Exception:
        components["queue"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in components.values()) else "degraded"
    return HealthResponse(
        status=overall,
        timestamp=datetime.now(),
        version="1.0.0",
        uptime_seconds=time.time() - _START_TIME,
        components=components,
    )


@router.get("/metrics")
async def metrics():
    """Prometheus metrics 端点"""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/stats")
async def stats():
    """系统统计信息"""
    from ....knowledge.db_client import get_stats
    return await get_stats()


@router.get("/queue")
async def queue_status():
    """消息队列状态"""
    from ....core.queue_worker import get_message_queue
    q = get_message_queue()
    if q is None:
        return {"size": 0, "max_size": 1000, "full": False}
    size = q.qsize()
    return {
        "size": size,
        "max_size": q.maxsize,
        "full": q.full(),
    }


@router.post("/config/reload")
async def reload_config():
    """重新加载配置"""
    from ....config.app_settings import reload_settings
    try:
        reload_settings()
        return {"status": "ok", "message": "Configuration reloaded"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# [Phase 2] 审批 API
# ---------------------------------------------------------------------------

@router.get("/approvals", response_model=List[ApprovalResponse])
async def list_approvals(status: Optional[str] = "PENDING"):
    """
    列出审批请求

    Args:
        status: 筛选状态 (PENDING/APPROVED/REJECTED/ALL)

    Returns:
        审批请求列表
    """
    from ....core.permissions import get_permission_engine

    engine = get_permission_engine()
    approvals = await engine.get_pending_approvals()

    if status != "ALL":
        approvals = [a for a in approvals if a.status == status]

    return [
        ApprovalResponse(
            approval_id=a.approval_id,
            tool_name=a.tool_name,
            args=a.args,
            session_id=a.session_id,
            user_id=a.user_id,
            requested_at=a.requested_at,
            requested_by=a.requested_by,
            status=a.status
        )
        for a in approvals
    ]


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(approval_id: str):
    """获取审批请求详情"""
    from ....core.permissions import get_permission_engine

    engine = get_permission_engine()
    approval = await engine.get_approval(approval_id)

    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    return ApprovalResponse(
        approval_id=approval.approval_id,
        tool_name=approval.tool_name,
        args=approval.args,
        session_id=approval.session_id,
        user_id=approval.user_id,
        requested_at=approval.requested_at,
        requested_by=approval.requested_by,
        status=approval.status
    )


@router.post("/approvals/{approval_id}/approve")
async def approve_request(approval_id: str, body: ApproveRequest = None):
    """
    批准审批请求

    Args:
        approval_id: 审批单 ID
        body: 审批意见 (可选)

    Returns:
        {"approved": True} 或错误
    """
    from ....core.permissions import get_permission_engine

    engine = get_permission_engine()
    admin_user = get_admin_user()

    comment = body.comment if body else None
    result = await engine.approve(
        approval_id=approval_id,
        reviewer=admin_user["user_id"],
        comment=comment
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Approval not found or already processed"
        )

    return {"approved": True, "approval_id": approval_id}


@router.post("/approvals/{approval_id}/reject")
async def reject_request(approval_id: str, body: RejectRequest = None):
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
    admin_user = get_admin_user()

    comment = body.comment if body else None
    result = await engine.reject(
        approval_id=approval_id,
        reviewer=admin_user["user_id"],
        comment=comment
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Approval not found or already processed"
        )

    return {"rejected": True, "approval_id": approval_id}


@router.get("/permissions/tools")
async def list_tool_permissions():
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


class PersonaDeleteRequest(BaseModel):
    pass


# 仪表盘统计
@router.get("/dashboard")
async def admin_stats():
    """
    仪表盘统计数据：
    - 记忆库总量
    - 本周新增事件
    - 推送采纳率
    - 事件类型分布
    """
    from ....knowledge.db_client import db_client

    try:
        # 记忆库总量
        total_mem = await db_client.fetch_one(
            "SELECT COUNT(*) as cnt FROM confirmed_events"
        )
        total_count = total_mem["cnt"] if total_mem else 0

        # 本周新增事件
        week_ago = time.time() - 7 * 86400
        week_mem = await db_client.fetch_one(
            "SELECT COUNT(*) as cnt FROM confirmed_events WHERE confirmed_at > ?",
            (week_ago,)
        )
        week_count = week_mem["cnt"] if week_mem else 0

        # 推送采纳率
        total_push = await db_client.fetch_one(
            "SELECT COUNT(*) as cnt FROM push_logs"
        )
        adopted_push = await db_client.fetch_one(
            "SELECT COUNT(*) as cnt FROM push_logs WHERE adoption_status = 'adopted'"
        )
        total_push_cnt = total_push["cnt"] if total_push else 0
        adopted_cnt = adopted_push["cnt"] if adopted_push else 0
        adoption_rate = round(adopted_cnt / total_push_cnt * 100, 1) if total_push_cnt > 0 else 0

        # 事件类型分布
        type_dist = await db_client.fetch_all(
            "SELECT event_type, COUNT(*) as cnt FROM confirmed_events GROUP BY event_type ORDER BY cnt DESC"
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
):
    """
    获取事件记忆库列表
    支持筛选：event_type, from_user
    """
    from ....knowledge.db_client import db_client

    sql = "SELECT * FROM confirmed_events WHERE 1=1"
    params = []

    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    if from_user:
        sql += " AND from_user = ?"
        params.append(from_user)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = await db_client.fetch_all(sql, tuple(params))
    return {"events": rows, "limit": limit, "offset": offset}


# 事件详情
@router.get("/events/{event_id}")
async def get_event(event_id: str):
    """获取事件详情"""
    from ....knowledge.db_client import db_client

    row = await db_client.fetch_one(
        "SELECT * FROM confirmed_events WHERE event_id = ?", (event_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="事件不存在")
    return row


# 手动添加事件
@router.post("/events")
async def create_event(body: EventCreateRequest):
    """手动录入历史事件"""
    from ....knowledge.db_client import save_confirmed_event

    try:
        event_id = await save_confirmed_event(
            push_id="manual",
            from_user=body.from_user,
            raw_text=body.raw_text,
            event_type=body.event_type,
            severity=body.severity,
            context_trigger_data={"source": "manual_entry"},
            venue_id=body.venue_id or None,
        )
        return {"event_id": event_id, "status": "created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 推送日志
@router.get("/push_logs")
async def list_push_logs(
    limit: int = 50,
    offset: int = 0,
    adoption_status: Optional[str] = None,
    from_user: Optional[str] = None,
):
    """获取推送日志列表"""
    from ....knowledge.push_logger import get_recent_push_logs

    logs = await get_recent_push_logs(
        from_user=from_user,
        limit=limit,
        adoption_status=adoption_status,
    )
    return {"push_logs": logs, "limit": limit, "offset": offset}


# 数字分身列表
@router.get("/personas")
async def list_personas(
    job_title: Optional[str] = None,
    venue_id: Optional[str] = None,
):
    """获取数字分身列表"""
    from ....knowledge.db_client import db_client

    sql = "SELECT * FROM personas WHERE 1=1"
    params = []

    if job_title:
        sql += " AND job_title LIKE ?"
        params.append(f"%{job_title}%")
    if venue_id:
        sql += " AND venue_id = ?"
        params.append(venue_id)

    sql += " ORDER BY created_at DESC"
    rows = await db_client.fetch_all(sql, tuple(params))

    # 解析 JSON 字段
    import json as _json
    for row in rows:
        try:
            row["logic_entries"] = _json.loads(row.get("logic_entries", "[]"))
        except Exception:
            row["logic_entries"] = []

    return {"personas": rows}


class PersonaCreateRequest(BaseModel):
    job_title: str
    venue_id: Optional[str] = ""
    description: Optional[str] = ""
    logic_entries: list = []


@router.post("/personas")
async def create_persona(body: PersonaCreateRequest):
    """创建数字分身"""
    from ....knowledge.db_client import db_client
    import uuid, time as _time

    persona_id = str(uuid.uuid4())
    now = _time.time()

    import json as _json
    logic_json = _json.dumps(body.logic_entries or [])

    await db_client.execute(
        """INSERT INTO personas (id, job_title, venue_id, description, logic_entries, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (persona_id, body.job_title, body.venue_id or None, body.description or "", logic_json, now, now),
    )
    return {"persona_id": persona_id, "status": "created"}


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


@router.post("/personas/{persona_id}/interview/start")
async def start_interview(persona_id: str):
    """启动老员工访谈萃取"""
    from ....knowledge.db_client import db_client
    from ....skills.persona_extract import PersonaExtractSkill

    # 拿到 persona 的 job_title 和 venue_id
    row = await db_client.fetch_one(
        "SELECT job_title, venue_id FROM personas WHERE id = ?", (persona_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="分身不存在")

    skill = PersonaExtractSkill()
    result = await skill.run(
        context={
            "action": "start",
            "venue_id": row["venue_id"] or "",
            "job_title": row["job_title"],
            "source_persona_id": persona_id,
        },
        trace_id=f"interview_{persona_id}"
    )

    return {
        "interview_id": result.structured_data.get("interview_id"),
        "current_question": result.structured_data.get("current_question"),
        "total_questions": result.structured_data.get("total_questions"),
        "reply_text": result.reply_text,
        "stage": result.structured_data.get("stage"),
    }


@router.post("/personas/{persona_id}/interview/continue")
async def continue_interview(persona_id: str, body: InterviewContinueRequest):
    """继续访谈，回答当前问题"""
    from ....skills.persona_extract import PersonaExtractSkill

    skill = PersonaExtractSkill()
    result = await skill.run(
        context={
            "action": "continue",
            "interview_id": body.interview_id,
            "answer": body.answer,
        },
        trace_id=f"interview_{persona_id}"
    )

    return {
        "current_question": result.structured_data.get("current_question"),
        "total_questions": result.structured_data.get("total_questions"),
        "reply_text": result.reply_text,
        "stage": result.structured_data.get("stage"),
        "prompt_finalize": result.structured_data.get("prompt_finalize", False),
    }


@router.post("/personas/{persona_id}/interview/finalize")
async def finalize_interview(persona_id: str, body: InterviewFinalizeRequest):
    """结束访谈，保存逻辑条目到分身"""
    from ....skills.persona_extract import PersonaExtractSkill

    skill = PersonaExtractSkill()
    result = await skill.run(
        context={
            "action": "finalize",
            "interview_id": body.interview_id,
        },
        trace_id=f"interview_{persona_id}"
    )

    persona_data = result.structured_data

    return {
        "persona_id": persona_data.get("persona_id", persona_id),
        "total_entries": persona_data.get("total_entries", 0),
        "reply_text": result.reply_text,
    }


@router.post("/personas/{persona_id}/chat")
async def persona_chat(persona_id: str, body: PersonaChatRequest):
    """向数字分身提问（第一人称回答）"""
    from ....knowledge.db_client import db_client
    from ....skills.persona_extract.invoke import ask_persona

    # 拿到 persona 的 job_title 和 venue_id
    row = await db_client.fetch_one(
        "SELECT job_title, venue_id FROM personas WHERE id = ?", (persona_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="分身不存在")

    result = await ask_persona(
        venue_id=row["venue_id"] or "",
        job_title=row["job_title"],
        question=body.question,
        trace_id=f"chat_{persona_id}"
    )

    return result


# 删除分身
@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str):
    """删除分身档案"""
    from ....knowledge.db_client import db_client

    rowcount = await db_client.execute(
        "DELETE FROM personas WHERE id = ?", (persona_id,)
    )
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="分身不存在")
    return {"deleted": True, "persona_id": persona_id}

