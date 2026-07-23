"""
gateway.py · 企微 Webhook 接入网关 + API 版本路由
================================================================
职责：
  1. 承接企业微信高频 Webhook，执行严格的 AES-256-CBC 验签与解密。
  2. 极速响应：提取 MsgId 后立刻推入 asyncio.Queue，绝不阻塞等待大模型。
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
import xml.etree.ElementTree as ET
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

from fastapi import APIRouter, Request, FastAPI, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from loguru import logger

# ── 指标计数器 ────────────────────────────────────────────────────────────
_queue_full_count: int = 0

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
    """懒加载获取企微加解密实例"""
    global wx_crypto
    if wx_crypto is None:
        try:
            from src.memory_palace.tools.wechat_crypto import WXBizMsgCrypt
            wx_crypto = WXBizMsgCrypt(
                token=os.environ.get("WECHAT_TOKEN", ""),
                encoding_aes_key=os.environ.get("WECHAT_ENCODING_AES_KEY", ""),
                corp_id=os.environ.get("WECHAT_CORP_ID", "")
            )
            logger.info("✅ 企微加解密套件初始化成功")
        except Exception as e:
            logger.warning(f"⚠️ 企微加解密套件初始化失败: {e}，将以 Mock 模式运行")
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
    crypto = get_wx_crypto()
    is_mock = isinstance(crypto, type(create_mock_wx_crypto())) if crypto else True
    checks["dependencies"]["wechat_crypto"] = {
        "available": crypto is not None,
        "mode": "mock" if is_mock else "enabled"
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
    crypto = get_wx_crypto()
    if not crypto:
        logger.error("企微加解密套件未初始化")
        return PlainTextResponse("Crypto Not Initialized", status_code=500)

    try:
        ret, decrypted_echostr = crypto.VerifyURL(msg_signature, timestamp, nonce, echostr)
        if ret == 0:
            logger.success("✅ 企微 Webhook URL 验签成功！")
            return PlainTextResponse(decrypted_echostr)
        else:
            logger.error(f"❌ 企微 Webhook 验签失败，错误码: {ret}")
            return PlainTextResponse("Verification Failed", status_code=403)
    except Exception as e:
        logger.error(f"验签异常: {e}")
        return PlainTextResponse("Verification Error", status_code=500)


@wechat_router.post("")
async def receive_wechat_message(
    request: Request,
    msg_signature: str = "",
    timestamp: str = "",
    nonce: str = ""
):
    """
    接收企微真实业务消息。
    设计原则：全程耗时必须 < 50ms。解密 -> 组装 -> 入队 -> return success。
    """
    start_time = time.time()
    trace_id = uuid.uuid4().hex[:8]

    try:
        # 1. 获取原始加密 XML
        raw_xml = await request.body()
        logger.debug(f"[Trace-{trace_id}] 收到企微推送消息，大小: {len(raw_xml)} bytes")

        # 2. 解密消息
        crypto = get_wx_crypto()
        if crypto:
            try:
                ret, decrypted_xml = crypto.DecryptMsg(raw_xml, msg_signature, timestamp, nonce)
                if ret != 0:
                    logger.error(f"[Trace-{trace_id}] 消息解密失败，错误码: {ret}")
                    return PlainTextResponse("success")  # 防探测
            except Exception as e:
                logger.error(f"[Trace-{trace_id}] 解密异常: {e}")
                return PlainTextResponse("success")  # 防探测
        else:
            # Mock 模式：尝试 UTF-8 解码，失败则尝试系统默认编码
            try:
                decrypted_xml = raw_xml.decode("utf-8")
            except UnicodeDecodeError:
                decrypted_xml = raw_xml.decode("utf-8", errors="replace")

        # 3. 解析 XML 提取关键字段
        try:
            xml_tree = ET.fromstring(decrypted_xml)
        except ET.ParseError as e:
            logger.error(f"[Trace-{trace_id}] XML 解析失败: {e}")
            return PlainTextResponse("success")

        msg_type = xml_tree.findtext("MsgType", default="unknown")
        from_user = xml_tree.findtext("FromUserName", default="unknown")

        msg_id = xml_tree.findtext("MsgId")
        if not msg_id:
            create_time = xml_tree.findtext("CreateTime", default=str(int(time.time())))
            msg_id = f"EVENT_{from_user}_{create_time}"

        # 4. 消息过滤 - 拦截无效事件
        if msg_type == "event":
            event = xml_tree.findtext("Event", default="")
            # 过滤掉进入会话等无用事件
            if event in ("enter_agent", "unsubscribe"):
                logger.debug(f"[Trace-{trace_id}] 拦截无效事件: {event}")
                return PlainTextResponse("success")

        # 5. 组装 Payload
        payload = {
            "msg_id": msg_id,
            "from_user": from_user,
            "msg_type": msg_type,
            "content": xml_tree.findtext("Content", default=""),
            "event": xml_tree.findtext("Event", default=""),
            "timestamp": time.time(),
            "raw_xml": decrypted_xml,
            "trace_id": trace_id,
            "api_version": "v1"
        }

        # 6. 安全推入队列
        try:
            queue: asyncio.Queue = request.app.state.message_queue
            try:
                queue.put_nowait(payload)
                latency_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[Trace-{trace_id}] 📥 消息已成功入队 "
                    f"[MsgId={msg_id}, Type={msg_type}] | "
                    f"网关耗时: {latency_ms:.1f}ms"
                )
            except asyncio.QueueFull:
                global _queue_full_count
                _queue_full_count += 1
                logger.error(
                    f"[Trace-{trace_id}] 🚨 严重告警：系统消息队列已满！(累计 {_queue_full_count} 次)"
                )
                # 发送告警通知 (可选)
                try:
                    from src.memory_palace.tools.sms_client import send_alert
                    send_alert(f"[Memory Palace] 队列已满，消息丢失: {msg_id}", level="P0")
                except:
                    pass
                return PlainTextResponse("success")
        except AttributeError:
            logger.error(f"[Trace-{trace_id}] 消息队列未初始化")
            return PlainTextResponse("success", status_code=500)

    except Exception as e:
        logger.error(
            f"[Trace-{trace_id}] 网关发生未捕获异常: {e}\n"
            f"{traceback.format_exc()}"
        )
        # 全局防御兜底
        return PlainTextResponse("success")

    return PlainTextResponse("success")


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
async def get_stats():
    """获取系统统计信息"""
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


@demo_router.post("/send")
async def demo_send_message(payload: DemoMessage, request: Request):
    """
    Demo 消息入口：直接构造 payload 推入队列，跳过企微加密。
    仅在 DEMO_MODE=true 时可用。
    """
    trace_id = uuid.uuid4().hex[:8]
    msg_id = f"demo_{uuid.uuid4().hex[:12]}"

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
        queue: asyncio.Queue = request.app.state.message_queue
        queue.put_nowait(message)
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
    except asyncio.QueueFull:
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

    