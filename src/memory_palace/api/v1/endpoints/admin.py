"""
v1/endpoints/admin.py - Admin endpoint
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from ..schemas import HealthResponse
from datetime import datetime
from typing import Optional
import time

logger_model = __import__('logging').getLogger(__name__)
router = APIRouter()

_START_TIME = time.time()


def get_admin_user():
    """Admin auth placeholder — implement with actual auth"""
    return {"user_id": "admin", "role": "admin"}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    from ...knowledge.db_client import check_connection

    components = {"db": "unknown", "llm": "unknown", "queue": "unknown"}

    try:
        ok = await check_connection()
        components["db"] = "healthy" if ok else "unhealthy"
    except Exception:
        components["db"] = "unhealthy"

    try:
        from ...tools.llm_wrapper import get_llm_client
        llm = get_llm_client()
        components["llm"] = "healthy"
    except Exception:
        components["llm"] = "unhealthy"

    try:
        from ...core.queue_worker import get_message_queue
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
    from ...knowledge.db_client import get_stats
    return await get_stats()


@router.get("/queue")
async def queue_status():
    """消息队列状态"""
    from ...core.queue_worker import get_message_queue
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
    from ...config.app_settings import reload_settings
    try:
        reload_settings()
        return {"status": "ok", "message": "Configuration reloaded"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
