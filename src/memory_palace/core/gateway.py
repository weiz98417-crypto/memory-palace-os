"""
gateway.py · 企微 Webhook 接入网关 + API 版本路由
================================================================
职责：
  1. 承接企业微信高频 Webhook，执行严格的 AES-256-CBC 验签与解密。
  2. 极速响应：提取 MsgId 后通过统一消息队列协议入队，绝不等待大模型。
  3. 全局防御：解密失败或队列溢出时，永远返回 200 "success"，防止黑客探测。
  4. API 版本路由：支持 /v1/ /v2/ 版本共存，便于平滑升级。
  5. 健康检查：/health, /ready, /metrics 端点。
  6. 流量打点：为每个请求注入 TraceID，便于全链路追踪。
"""

import os
import time
import uuid
import traceback
import asyncio
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

from fastapi import APIRouter, Request, FastAPI, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from loguru import logger

from src.memory_palace.config.integration_readiness import wechat_integration_readiness

# ── 指标计数器 ────────────────────────────────────────────────────────────
_queue_full_count: int = 0

async def _check_auth(request: Request) -> None:
    """Verify admin authentication. Skips in DEMO_MODE."""
    import os
    if os.environ.get("DEMO_MODE", "").lower() == "true":
        return
    from src.memory_palace.api.auth import require_auth
    await require_auth(request)


# ==============================================================================
# 配置模型
# ==============================================================================

class APIVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


@dataclass
class GatewayConfig:
    """网关配置"""
    app_name: str = "Memory Palace OS"
    version: str = "1.0.0"
    api_versions: List[str] = field(default_factory=lambda: ["/v1", "/v2 (coming soon)"])
    max_queue_size: int = 10000
    enable_cors: bool = True
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


# ==============================================================================
# 请求/响应模型
# ==============================================================================

class WeChatMessage(BaseModel):
    """企微消息模型"""
    msg_id: str
    from_user: str
    msg_type: str
    content: str = ""
    timestamp: float
    raw_xml: str = ""
    trace_id: str = ""
    api_version: str = "v1"


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    timestamp: float
    version: str
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    """就绪检查响应"""
    status: str
    timestamp: float
    dependencies: Dict[str, Any]


class APIInfoResponse(BaseModel):
    """API 信息响应"""
    name: str
    version: str
    api_versions: List[str]
    endpoints: Dict[str, str]


# ==============================================================================
# 全局变量
# ==============================================================================

# 企微加解密实例
wx_crypto: Optional[object] = None

# 应用启动时间
APP_START_TIME = time.time()

# 网关配置
config = GatewayConfig()


# ==============================================================================
# 企微加解密初始化
# ==============================================================================

def get_wx_crypto():
    """Return no real crypto adapter while the project is simulator-only."""
    global wx_crypto
    if wx_crypto is not None:
        wx_crypto = None
    return wx_crypto


def create_mock_wx_crypto():
    """创建 Mock 加解密实例 (仅用于开发测试)"""
    class MockCrypto:
        def VerifyURL(self, msg_signature: str, timestamp: str, nonce: str, echostr: str):
            logger.info(f"[Mock] 验签请求: sig={msg_signature[:10]}...")
            return (0, echostr)  # 始终验签成功

        def DecryptMsg(self, raw_xml: bytes, msg_signature: str, timestamp: str, nonce: str):
            logger.debug(f"[Mock] 解密请求")
            return (0, raw_xml.decode("utf-8"))  # 始终解密成功

    return MockCrypto()


# ==============================================================================
# ==============================================================================
# 路由定义
# ==============================================================================

# 根路由
root_router = APIRouter(tags=["Root"])


@root_router.get("/", response_model=APIInfoResponse)
async def root():
    """API 根路径 - 返回版本信息"""
    return APIInfoResponse(
        name=config.app_name,
        version=config.version,
        api_versions=config.api_versions,
        endpoints={
            "health": "/health",
            "ready": "/ready",
            "metrics": "/metrics",
            "wechat": "/v1/wechat",
            "api": "/v1",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    )


# ==============================================================================
# 健康检查路由
# ==============================================================================

health_router = APIRouter(tags=["Health"])


@health_router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    存活检查 (Liveness Probe)
    - 用于 K8s livenessProbe
    - 返回 200 即表示进程存活
    """
    return HealthResponse(
        status="alive",
        timestamp=time.time(),
        version=config.version,
        uptime_seconds=time.time() - APP_START_TIME
    )


@health_router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(request: Request):
    """
    就绪检查 (Readiness Probe)
    - 用于 K8s readinessProbe
    - 检查依赖服务是否就绪 (队列、数据库等)
    """
    checks = {
        "status": "ready",
        "timestamp": time.time(),
        "dependencies": {}
    }

    # 检查消息队列
    try:
        queue: asyncio.Queue = request.app.state.message_queue
        queue_size = queue.qsize()
        max_size = getattr(queue, 'maxsize', 0)
        checks["dependencies"]["message_queue"] = {
            "available": True,
            "current_size": queue_size,
            "max_size": max_size if max_size > 0 else "unlimited",
            "utilization": f"{(queue_size / max_size * 100):.1f}%" if max_size > 0 else "N/A"
        }
    except Exception as e:
        checks["dependencies"]["message_queue"] = {
            "available": False,
            "error": str(e)
        }
        checks["status"] = "degraded"

    # 检查企微加解密
    checks["dependencies"]["wechat_crypto"] = {
        "available": False,
        "mode": "disabled_by_policy",
        "simulator_entrypoint": "/simulator/wecom/",
    }

    # 检查数据库 (可选)
    try:
        from src.memory_palace.knowledge.db_client import check_connection
        db_available = await check_connection()
        checks["dependencies"]["database"] = {
            "available": db_available
        }
        if not db_available:
            checks["status"] = "degraded"
    except Exception as e:
        checks["dependencies"]["database"] = {
            "available": False,
            "error": str(e)
        }
        checks["status"] = "degraded"

    status_code = 200 if checks["status"] == "ready" else 503
    return JSONResponse(checks, status_code=status_code)


@health_router.get("/metrics")
async def metrics_endpoint():
    """
    Prometheus 指标端点
    - /metrics 由 Prometheus 主动抓取
    """
    try:
        from src.memory_palace.core.metrics import get_metrics_registry
        registry = get_metrics_registry()
        if registry:
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
            return PlainTextResponse(
                generate_latest(registry),
                media_type=CONTENT_TYPE_LATEST
            )
    except Exception as e:
        logger.warning(f"指标收集失败: {e}")

    return PlainTextResponse("# No metrics available", media_type="text/plain")


# ==============================================================================
# 企微 Webhook 路由
# ==============================================================================

wechat_router = APIRouter(prefix="/v1/wechat", tags=["WeChat Webhook"])
router = wechat_router  # 别名，兼容 main.py 的导入方式


@wechat_router.get("")
async def verify_wechat_url(
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = ""
):
    """
    企微管理后台配置 Webhook 时，触发的首次 GET 验签
    """
    readiness = wechat_integration_readiness()
    logger.warning("真实企微 Webhook 验签已按项目策略禁用")
    return PlainTextResponse(str(readiness["blocked_reason"]), status_code=503)


@wechat_router.post("")
async def receive_wechat_message(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = ""
):
    """Reject real WeCom callbacks before reading or processing request data."""
    trace_id = uuid.uuid4().hex[:8]
    from src.memory_palace.tools.trace_context import set_trace_id
    set_trace_id(trace_id)
    readiness = wechat_integration_readiness()
    logger.warning(f"[Trace-{trace_id}] 真实企微回调已按项目策略禁用")
    return PlainTextResponse("integration disabled", status_code=503)


# ==============================================================================
# V1 API 路由
# ==============================================================================

v1_router = APIRouter(prefix="/v1", tags=["V1 API"])


# --------------------------------------------------------------------------
# V1 - 消息接口
# --------------------------------------------------------------------------

@v1_router.get("/messages")
async def list_messages(
    request: Request,
    from_user: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """获取消息列表"""
    try:
        from src.memory_palace.knowledge.db_client import get_messages
        messages = await get_messages(
            from_user=from_user,
            limit=limit,
            offset=offset
        )
        return {"code": 0, "data": messages, "total": len(messages)}
    except Exception as e:
        logger.error(f"获取消息列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.get("/messages/{msg_id}")
async def get_message(msg_id: str):
    """获取单条消息详情"""
    try:
        from src.memory_palace.knowledge.db_client import get_message_by_id
        message = await get_message_by_id(msg_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return {"code": 0, "data": message}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------
# V1 - 技能接口
# --------------------------------------------------------------------------

@v1_router.get("/skills")
async def list_skills():
    """获取所有已注册的技能列表"""
    try:
        from src.memory_palace.skills import get_registered_skills
        skills = get_registered_skills()
        return {
            "code": 0,
            "data": [
                {
                    "name": s.name,
                    "description": s.description,
                    "version": s.version,
                    "enabled": s.enabled
                }
                for s in skills
            ],
            "total": len(skills)
        }
    except Exception as e:
        logger.error(f"获取技能列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    """获取指定技能详情"""
    try:
        from src.memory_palace.skills import get_skill_by_name
        skill = get_skill_by_name(skill_name)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"code": 0, "data": skill}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取技能失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.post("/skills/{skill_name}/reload")
async def reload_skill(skill_name: str):
    """热更新指定技能"""
    try:
        from src.memory_palace.core.hot_reload import reload_skill as do_reload
        result = await do_reload(skill_name)
        return {"code": 0, "message": f"Skill {skill_name} reloaded", "data": result}
    except Exception as e:
        logger.error(f"热更新技能失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------
# V1 - 会话接口
# --------------------------------------------------------------------------

@v1_router.get("/sessions")
async def list_sessions(
    from_user: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """获取会话列表"""
    try:
        from src.memory_palace.knowledge.db_client import get_sessions
        sessions = await get_sessions(
            user_id=from_user,
            limit=limit
        )
        return {"code": 0, "data": sessions, "total": len(sessions)}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情及历史消息"""
    try:
        from src.memory_palace.knowledge.db_client import get_session_by_id, get_messages_by_session
        session = await get_session_by_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = await get_messages_by_session(session_id)
        return {"code": 0, "data": {**session, "messages": messages}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    try:
        from src.memory_palace.knowledge.db_client import delete_session
        await delete_session(session_id)
        return {"code": 0, "message": "Session deleted"}
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------
# V1 - 管理后台接口
# --------------------------------------------------------------------------

@v1_router.get("/admin/stats")
async def get_stats(request: Request):
    """获取系统统计信息。生产环境需 X-API-Key 或 JWT，DEMO_MODE 免认证。"""
    await _check_auth(request)
    try:
        from src.memory_palace.knowledge.db_client import get_stats
        stats = await get_stats()
        return {"code": 0, "data": stats}
    except Exception as e:
        logger.error(f"获取统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.get("/admin/queue")
async def get_queue_status(request: Request):
    """获取队列状态"""
    try:
        queue: asyncio.Queue = request.app.state.message_queue
        return {
            "code": 0,
            "data": {
                "size": queue.qsize(),
                "max_size": getattr(queue, 'maxsize', 0),
                "empty": queue.empty(),
                "full": queue.full()
            }
        }
    except Exception as e:
        logger.error(f"获取队列状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------
# V1 - 知识库接口
# --------------------------------------------------------------------------

@v1_router.post("/knowledge/query")
async def query_knowledge(
    question: str,
    top_k: int = 5,
    threshold: float = 0.7
):
    """查询知识库"""
    try:
        from src.memory_palace.knowledge import vector_store
        results = vector_store.query(question, top_k=top_k, threshold=threshold)
        return {"code": 0, "data": results}
    except Exception as e:
        logger.error(f"查询知识库失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@v1_router.post("/knowledge/add")
async def add_knowledge(
    content: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """添加知识条目"""
    try:
        from src.memory_palace.knowledge import vector_store
        result = vector_store.add(content, metadata or {})
        return {"code": 0, "message": "Knowledge added", "id": result}
    except Exception as e:
        logger.error(f"添加知识失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Demo 路由 (仅在 DEMO_MODE=true 时挂载)
# ==============================================================================

demo_router = APIRouter(prefix="/demo", tags=["Demo"])

# In-memory result cache: trace_id → {reply_text, route, ...}
_demo_results: dict = {}

class DemoMessage(BaseModel):
    content: str = ""
    from_user: str = "demo_user"


class DemoInterviewStart(BaseModel):
    job_title: str
    venue_id: str = ""


class DemoInterviewContinue(BaseModel):
    interview_id: str
    answer: str


class DemoInterviewFinalize(BaseModel):
    interview_id: str


class DemoTodoDecompose(BaseModel):
    goal: str
    from_user: str = "demo"


@demo_router.post("/send")
async def demo_send_message(payload: DemoMessage, request: Request):
    """
    Demo 消息入口：直接构造 payload 推入队列，跳过企微加密。
    仅在 DEMO_MODE=true 时可用。
    """
    trace_id = uuid.uuid4().hex[:8]
    from src.memory_palace.tools.trace_context import set_trace_id
    set_trace_id(trace_id)
    msg_id = f"demo_{uuid.uuid4().hex[:12]}"

    # Tenant context: set venue_id for multi-tenant isolation
    try:
        from src.memory_palace.core.tenant import set_venue_id
        set_venue_id(f"demo_{payload.from_user}")
    except Exception:
        pass

    message = {
        "msg_id": msg_id,
        "from_user": payload.from_user,
        "msg_type": "text",
        "content": payload.content,
        "event": "",
        "timestamp": time.time(),
        "raw_xml": "",
        "trace_id": trace_id,
        "api_version": "v1",
    }

    try:
        queue = request.app.state.message_queue
        accepted = await asyncio.wait_for(queue.put(message), timeout=1.0)
        if not accepted:
            raise HTTPException(status_code=409, detail="Duplicate message")
        logger.info(
            f"[Trace-{trace_id}] 📥 [Demo] 消息已入队 "
            f"[MsgId={msg_id}] content={payload.content[:50]}"
        )
        return {
            "code": 0,
            "trace_id": trace_id,
            "msg_id": msg_id,
            "message": "Message enqueued. GET /demo/result/{trace_id} to get the reply.",
        }
    except asyncio.TimeoutError:
        global _queue_full_count
        _queue_full_count += 1
        logger.error(f"[Trace-{trace_id}] 🚨 Demo 消息入队失败：队列已满")
        raise HTTPException(status_code=503, detail="Queue full")
    except AttributeError:
        logger.error(f"[Trace-{trace_id}] Demo 消息入队失败：队列未初始化")
        raise HTTPException(status_code=500, detail="Queue not initialized")


@demo_router.get("/result/{trace_id}")
async def demo_get_result(trace_id: str):
    """轮询获取指定 trace_id 的处理结果"""
    result = _demo_results.pop(trace_id, None)
    if result is None:
        return {"code": 1, "trace_id": trace_id, "message": "Not ready yet. Pipeline may still be processing."}
    return {"code": 0, "trace_id": trace_id, **result}


# ── PersonaExtract 访谈 ──────────────────────────────────────────────────

@demo_router.post("/persona/interview/start")
async def demo_persona_start(payload: DemoInterviewStart):
    """开始 PersonaExtract 访谈，返回第一个问题"""
    try:
        from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill
        skill = PersonaExtractSkill()
        result = await skill.start_interview(
            job_title=payload.job_title,
            venue_id=payload.venue_id,
            trace_id="demo_persona",
        )
        sd = result.structured_data or {}
        return {
            "code": 0,
            "data": {
                "interview_id": sd.get("interview_id", ""),
                "question": result.reply_text,
                "question_number": sd.get("current_question", 1),
            },
        }
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.post("/persona/interview/continue")
async def demo_persona_continue(payload: DemoInterviewContinue):
    """继续访谈，返回下一个问题或标记完成"""
    try:
        from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill
        skill = PersonaExtractSkill()
        result = await skill.continue_interview(
            interview_id=payload.interview_id,
            answer=payload.answer,
            trace_id="demo_persona",
        )
        sd = result.structured_data or {}
        return {
            "code": 0,
            "data": {
                "interview_id": sd.get("interview_id", payload.interview_id),
                "question": result.reply_text,
                "question_number": sd.get("current_question", 0),
                "is_complete": sd.get("stage") in ("summary", "summary_shown") or sd.get("prompt_finalize") == True,
                "extracted_entries_count": sd.get("extracted_entries_count"),
            },
        }
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.post("/persona/interview/finalize")
async def demo_persona_finalize(payload: DemoInterviewFinalize):
    """完成访谈，保存 persona 并返回提取的逻辑条目"""
    try:
        from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill
        skill = PersonaExtractSkill()
        result = await skill.finalize_interview(
            interview_id=payload.interview_id,
            trace_id="demo_persona",
        )
        sd = result.structured_data or {}
        return {
            "code": 0,
            "data": {
                "interview_id": payload.interview_id,
                "logic_entries": sd.get("entries", []),
                "persona_id": sd.get("persona_id"),
            },
        }
    except Exception as e:
        return {"code": 1, "error": str(e)}


# ── Todo 分解 ──────────────────────────────────────────────────────────────

@demo_router.post("/todo/decompose")
async def demo_todo_decompose(payload: DemoTodoDecompose, request: Request):
    """触发 Todo skill 任务分解，通过消息队列派发"""
    import uuid as _uuid
    trace_id = _uuid.uuid4().hex[:8]
    msg_id = f"demo_todo_{_uuid.uuid4().hex[:12]}"
    message = {
        "msg_id": msg_id,
        "from_user": payload.from_user,
        "msg_type": "demo_todo_decompose",
        "content": payload.goal,
        "event": "",
        "timestamp": time.time(),
        "raw_xml": "",
        "trace_id": trace_id,
        "api_version": "v1",
    }
    try:
        queue = request.app.state.message_queue
        accepted = await asyncio.wait_for(queue.put(message), timeout=1.0)
        if not accepted:
            raise HTTPException(status_code=409, detail="Duplicate message")
        logger.info(f"[Trace-{trace_id}] Todo 分解已入队: {payload.goal[:50]}")
        return {
            "code": 0,
            "trace_id": trace_id,
            "message": f"Decomposition queued. Poll GET /demo/result/{trace_id}, then GET /demo/tasks.",
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Queue full")
    except AttributeError:
        raise HTTPException(status_code=500, detail="Queue not initialized")


# ── 知识库搜索 ──────────────────────────────────────────────────────────────

# In-memory demo knowledge cache (loaded by /demo/scenario/switch)
_demo_knowledge_cache: list = []

@demo_router.get("/knowledge/search")
async def demo_knowledge_search(q: str = "", top_k: int = 5):
    """搜索 demo 知识库（基于子串匹配，因 DeepSeek 无 embedding API）"""
    if not q or not _demo_knowledge_cache:
        return {"code": 0, "data": [], "message": "No query or no knowledge loaded. Switch scenario first."}
    results = []
    ql = q.lower()
    for item in _demo_knowledge_cache:
        content = item.get("content", "")
        score = content.lower().count(ql) * 10
        if ql in content.lower():
            score += 50
        if score > 0:
            results.append({"content": content, "score": score, "metadata": item.get("metadata", {})})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"code": 0, "data": results[:top_k]}


# ── Watcher 日志 ────────────────────────────────────────────────────────────

@demo_router.get("/watcher-log")
async def demo_watcher_log():
    """返回最近的 incident_logs + push_logs"""
    try:
        from src.memory_palace.knowledge.db_client import db_client as _db
        incidents = await _db.fetch_all(
            "SELECT case_id as id, severity, dispatched_instruction as summary, created_at FROM incident_logs ORDER BY created_at DESC LIMIT 20"
        )
        pushes = await _db.fetch_all(
            "SELECT push_id as id, severity, event_type, raw_text, pushed_at FROM push_logs ORDER BY pushed_at DESC LIMIT 20"
        )
        items = []
        for row in (incidents or []):
            items.append({"id": row["id"], "type": "incident", "summary": row.get("summary") or "", "severity": row["severity"] or "P3", "created_at": row["created_at"]})
        for row in (pushes or []):
            ts = row["pushed_at"]
            if isinstance(ts, (int, float)):
                from datetime import datetime
                ts = datetime.fromtimestamp(ts).isoformat()
            items.append({"id": row["id"], "type": "push", "summary": row.get("raw_text") or row.get("event_type") or "", "severity": row["severity"] or "P3", "created_at": ts})
        items.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return {"code": 0, "data": items[:30]}
    except Exception as e:
        return {"code": 1, "error": str(e), "data": []}


# ── 场景切换 ────────────────────────────────────────────────────────────────

@demo_router.get("/scenario/switch")
async def demo_scenario_switch(name: str = ""):
    """切换种子数据场景"""
    if name not in ("daily", "emergency"):
        return {"code": 1, "error": f"Unknown scenario: {name}. Valid: daily, emergency"}
    try:
        from scripts.seed_data import load_scenario
        result = await load_scenario(name)
        return {"code": 0, "data": result}
    except ImportError:
        return {"code": 1, "error": "seed_data module not found. Ensure scripts/ is in PYTHONPATH."}
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.get("/stats")
async def demo_get_stats(request: Request):
    """返回系统运行统计，供演示控制台仪表盘使用"""
    stats = {
        "queue_depth": 0,
        "queue_capacity": 0,
        "message_count": 0,
        "task_count": 0,
        "skills_registered": 0,
        "last_watcher_run": None,
    }
    try:
        queue: asyncio.Queue = request.app.state.message_queue
        stats["queue_depth"] = queue.qsize()
        stats["queue_capacity"] = getattr(queue, "maxsize", 10000)
    except Exception as e:
        logger.debug(f"demo/stats: queue read failed: {e}")

    try:
        from src.memory_palace.knowledge.db_client import db_client as _db
        row = await _db.fetch_one("SELECT COUNT(*) as cnt FROM messages")
        stats["message_count"] = row["cnt"] if row else 0
    except Exception as e:
        logger.debug(f"demo/stats: message_count read failed: {e}")

    try:
        from src.memory_palace.core.task_graph import task_graph as _tg
        stats["task_count"] = len(_tg._tasks)
    except Exception as e:
        logger.debug(f"demo/stats: task_count read failed: {e}")

    try:
        from src.memory_palace.skills import list_skill_names
        stats["skills_registered"] = len(list_skill_names())
    except Exception as e:
        logger.debug(f"demo/stats: skills_registered read failed: {e}")

    try:
        from src.memory_palace.core.scheduler import get_last_watcher_run
        stats["last_watcher_run"] = get_last_watcher_run()
    except Exception as e:
        logger.debug(f"demo/stats: last_watcher_run read failed: {e}")

    return {"code": 0, "data": stats}


@demo_router.get("/tasks")
async def demo_get_tasks():
    """返回 TaskGraph 中的任务列表"""
    try:
        from src.memory_palace.core.task_graph import task_graph as _tg
        tasks = []
        for tid, t in _tg._tasks.items():
            tasks.append({
                "id": tid,
                "description": t.description,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "dependencies": t.dependencies,
                "assigned_agent": t.assigned_agent,
                "session_id": t.session_id,
            })
        return {"code": 0, "data": tasks}
    except Exception as e:
        return {"code": 0, "data": [], "error": str(e)}


# ── Knowledge Base Admin ───────────────────────────────────────────────────

@demo_router.get("/kb/entries")
async def demo_kb_entries(limit: int = 50, offset: int = 0):
    """列出知识库条目"""
    try:
        items = [{"content": item["content"], "metadata": item.get("metadata", {})}
                 for item in _demo_knowledge_cache]
        return {"code": 0, "data": items[offset:offset + limit], "total": len(items)}
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.post("/kb/entries")
async def demo_kb_add(request: Request):
    """手动添加知识库条目"""
    try:
        body = await request.json()
        content = body.get("content", "")
        metadata = body.get("metadata", {})
        if not content:
            return {"code": 1, "error": "content is required"}
        _demo_knowledge_cache.append({"content": content, "metadata": metadata})
        return {"code": 0, "message": "Entry added", "total": len(_demo_knowledge_cache)}
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.delete("/kb/entries/{index}")
async def demo_kb_delete(index: int):
    """删除知识库条目"""
    try:
        if 0 <= index < len(_demo_knowledge_cache):
            _demo_knowledge_cache.pop(index)
            return {"code": 0, "message": "Deleted"}
        return {"code": 1, "error": "Index out of range"}
    except Exception as e:
        return {"code": 1, "error": str(e)}


@demo_router.post("/kb/reindex")
async def demo_kb_reindex():
    """重建知识库索引（重新加载当前场景）"""
    try:
        from scripts.seed_data import load_scenario
        # Re-load whatever scenario was last used
        result = await load_scenario("daily")
        return {"code": 0, "data": result}
    except Exception as e:
        return {"code": 1, "error": str(e)}


def demo_store_result(trace_id: str, result: dict) -> None:
    """存储处理结果供轮询（由 queue_worker 调用）"""
    _demo_results[trace_id] = result
    if len(_demo_results) > 100:
        oldest = next(iter(_demo_results))
        del _demo_results[oldest]


# ==============================================================================
# V2 路由 (预留)
# ==============================================================================

# v2_router = APIRouter(prefix="/v2", tags=["V2 API"])
#
# @v2_router.get("/messages")
# async def v2_list_messages():
#     """V2 消息列表 (扩展接口)"""
#     pass


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "GatewayConfig",
    "WeChatMessage",
    "HealthResponse",
    "ReadinessResponse",
    "APIInfoResponse",
    "APIVersion"
]

    
