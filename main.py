"""
memory-palace-os · 主入口
========================
职责：
  1. 启动 FastAPI 应用，挂载企微 Webhook 路由
  2. 启动异步消息消费队列（asyncio.Queue），解耦接收与处理
  3. 启动 APScheduler 定时任务（Watcher 鹰眼巡检）
  4. 环境变量 Fail-Fast 校验（缺 Key 启动即报错，不等运行时）
  5. 优雅关机：排空队列后再退出

运行方式：
  开发：uvicorn main:app --reload --port 8000
  生产：gunicorn main:app -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
"""

import asyncio
import os
import signal
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

load_dotenv()

# ── 内部模块 ──────────────────────────────────────────────────────────────────
from src.memory_palace.config.env_validator import validate_env  # P0: 启动校验
from src.memory_palace.tools.logger_config import setup_logger  # 日志初始化


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 0. 启动前：加载 .env + Fail-Fast 环境变量校验
#    所有必需 Key 缺失时直接 sys.exit(1)，不让残缺配置的服务跑起来
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() == "true"
# DEMO_MODE: 跳过环境变量严格校验，允许缺失 Key 运行时降级
if not _DEMO_MODE:
    validate_env()  # 内部会 sys.exit(1) + 打印缺失项
    # Secrets validation (fail-fast on missing required secrets)
    try:
        from src.memory_palace.config.secrets import secrets as _secrets

        missing = _secrets.validate(demo_mode=False)
        if missing:
            logger.error(f"缺少必需的密钥: {missing}")
            sys.exit(1)
    except Exception as e:
        logger.warning(f"密钥校验跳过: {e}")
else:
    logger.info("🎮 DEMO_MODE 已启用 — 跳过环境变量严格校验")
setup_logger()  # 初始化 loguru（多文件归档、自动旋转）


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Demo 专用内存队列
#    正式模式在 lifespan 中创建并验证 Redis Streams 队列。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_QUEUE_MAXSIZE = int(os.environ.get("MEMORY_PALACE_QUEUE_MAXSIZE", 10000))
IN_MEMORY_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 生命周期管理（lifespan 替代已废弃的 on_event）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    启动阶段：拉起队列消费者 + 定时任务调度器
    关机阶段：等待队列排空（最多 30 秒）后优雅退出

    [Phase 3] 新增:
    - Task Graph 持久化恢复
    - Permission Engine 恢复待审批请求
    """
    if _DEMO_MODE:
        logger.info("🎮 企业演示隔离模式已启动")
        yield
        logger.info("👋 企业演示隔离模式已退出")
        return

    from src.memory_palace.core.queue_worker import MessageQueueWorker, set_message_queue
    from src.memory_palace.core.scheduler import TaskScheduler
    from src.memory_palace.skills import _auto_register_skills

    logger.info("🚀 Memory Palace OS 正在启动...")

    # —— 注册所有 Agent（触发 @register_skill 装饰器）——
    _auto_register_skills()
    logger.info("✅ Agent 技能注册完成")

    # —— 初始化正式依赖注入容器与 PostgreSQL（失败即阻止启动）——
    from src.memory_palace.core.container import AppContainer

    app_container = AppContainer()

    # —— 确保数据库表存在（幂等，先于 Phase 恢复）——
    from src.memory_palace.knowledge.db_init import init_database

    await init_database(app_container.db_client)
    from src.memory_palace.api.v1.endpoints.auth import bootstrap_identity_store

    await bootstrap_identity_store(app_container.db_client)
    app_container.llm_client.set_database(app_container.db_client)
    logger.info("✅ 数据库表初始化完成")

    # —— 正式模式只使用 Redis Streams，不允许静默降级 ——
    from src.memory_palace.core.redis_queue import RedisStreamsQueue
    from src.memory_palace.core.runtime_recovery import recover_application_runtime

    runtime_queue = RedisStreamsQueue()
    recovery_run = await recover_application_runtime(
        app_container.db_client,
        task_graph=app_container.task_graph,
        permission_engine=app_container.permission_engine,
        runtime_queue=runtime_queue,
        app_version=app.version,
    )
    logger.info(
        "✅ 持久化启动恢复完成 [run_id={}] [trace_id={}]",
        recovery_run["id"],
        recovery_run["trace_id"],
    )
    logger.info("✅ DI 容器已初始化")

    set_message_queue(runtime_queue)
    logger.info("✅ Redis Streams 队列后端已连接")

    vector_store = app_container.vector_store
    vector_health = vector_store.health() if vector_store else {"status": "unhealthy"}
    if vector_health.get("status") != "healthy":
        raise RuntimeError("ChromaDB 未通过启动健康检查")
    logger.info("✅ ChromaDB 向量知识库已连接")

    worker = MessageQueueWorker(queue=runtime_queue, container=app_container, queue_backend=runtime_queue)
    consumer_task = asyncio.create_task(worker.start(), name="queue-consumer")
    logger.info("✅ 异步消息队列消费者已启动")

    # —— 启动定时任务调度器（Watcher 鹰眼巡检）——
    scheduler = TaskScheduler(container=app_container)
    await scheduler.start()
    logger.info("✅ APScheduler 定时任务调度器已启动")

    # —— 注册健康检查器 ——
    try:
        from src.memory_palace.core.health import get_health_registry

        registry = get_health_registry()
        # PG check
        if app_container:
            try:
                from src.memory_palace.core.health import DatabaseHealthChecker

                registry.register(
                    "postgresql", DatabaseHealthChecker(lambda: app_container.db_client.fetch_one("SELECT 1"))
                )
            except Exception:
                pass
        # Redis check
        if runtime_queue:
            try:
                from src.memory_palace.core.health import RedisHealthChecker

                registry.register(
                    "redis",
                    RedisHealthChecker(lambda: runtime_queue._client.ping() if runtime_queue._client else False),
                )
            except Exception:
                pass
        logger.info("✅ 健康检查器已注册")
    except Exception as e:
        logger.debug(f"健康检查器注册跳过: {e}")

    # —— 将公共对象挂到 app.state，供路由层访问 ——
    app.state.message_queue = runtime_queue
    app.state.message_worker = worker
    app.state.db_client = app_container.db_client
    app.state.vector_store = vector_store
    app.state.container = app_container
    app.state.scheduler = scheduler
    app.state.runtime_instance_id = uuid.uuid4().hex

    yield  # ← FastAPI 在此处理请求

    # ── 优雅关机 ──────────────────────────────────────────────────────────────
    logger.info("🛑 收到关机信号，开始优雅退出...")

    # 停止接收新任务
    scheduler.shutdown()

    # 记录死信队列内容
    if hasattr(worker, "_dead_letter_queue") and worker._dead_letter_queue:
        logger.error(
            f"⚠️ 死信队列包含 {len(worker._dead_letter_queue)} 条未发送回复: "
            f"{[d['msg_id'] for d in worker._dead_letter_queue]}"
        )

    # 停止领取新消息并取消阻塞中的消费循环。
    worker.stop()
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    # 已领取消息继续执行；超时取消时不 ACK，由 Redis pending 在重启后回收。
    drain_timeout = float(os.environ.get("MEMORY_PALACE_WORKER_DRAIN_TIMEOUT", "30"))
    drained = await worker.drain(timeout=drain_timeout)
    if drained:
        logger.info("✅ 已领取消息已全部处理完成")
    else:
        logger.warning("⚠️ 消息排空超时，未完成任务将由 Redis pending 恢复")

    # 关闭短信/语音线程池，避免 Gunicorn 和测试容器退出时悬挂。
    try:
        from src.memory_palace.tools.sms_client import sms_client

        sms_client.close(wait=True)
        logger.info("✅ 通知线程池已关闭")
    except Exception as e:
        logger.warning(f"通知线程池关闭异常（不影响退出）: {e}")

    # 释放正式持久化客户端与 Redis 连接。
    try:
        from src.memory_palace.knowledge.vector_store import close_vector_client

        await runtime_queue.close()
        await app_container.db_client.close()
        close_vector_client()
        logger.info("✅ 数据客户端已关闭")
    except Exception as e:
        logger.warning(f"数据客户端关闭异常（不影响退出）: {e}")

    logger.info("👋 Memory Palace OS 已安全退出")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. FastAPI 应用实例
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = FastAPI(
    title="Memory Palace OS",
    description="文旅多智能体运营系统 · 企微 Webhook 接入网关",
    version="1.0.0",
    lifespan=lifespan,
    # 生产环境关闭 Swagger UI（防止泄露接口结构）
    docs_url="/docs" if __debug__ and not _DEMO_MODE else None,
    redoc_url=None,
    openapi_url=None if _DEMO_MODE else "/openapi.json",
)
from src.memory_palace.api.errors import install_error_handlers

install_error_handlers(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 限流（生产环境自动启用，demo 模式跳过）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not _DEMO_MODE:
    try:
        from src.memory_palace.api.rate_limit import create_limiter

        limiter = create_limiter()
        if limiter:
            app.state.limiter = limiter
            logger.info("✅ API 限流已启用")
    except Exception as e:
        logger.debug(f"API 限流未启用: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 路由挂载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if _DEMO_MODE:
    from src.memory_palace.demo.router import router as enterprise_demo_router

    app.include_router(enterprise_demo_router)

    @app.get("/demo", include_in_schema=False)
    async def enterprise_demo_console():
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "demo_console.html",
            media_type="text/html; charset=utf-8",
        )

    logger.info("🎮 DEMO_MODE 已激活 — 企业演示控制台与场景 API 可用")
else:
    from src.memory_palace.api import v1_router, v2_router
    from src.memory_palace.core.gateway import router as webhook_router

    app.include_router(webhook_router, prefix="/webhook", tags=["企微网关"])
    app.include_router(v1_router, tags=["API v1"])
    app.include_router(v2_router, tags=["API v2"])

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/admin/", status_code=302)

    @app.get("/admin", include_in_schema=False)
    async def admin_redirect():
        return RedirectResponse(url="/admin/index.html", status_code=302)

    @app.get("/admin/events", include_in_schema=False)
    @app.get("/admin/tasks", include_in_schema=False)
    @app.get("/admin/approvals", include_in_schema=False)
    async def admin_business_collection():
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/admin/events/{event_id}", include_in_schema=False)
    async def admin_event_resource(event_id: str):
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/admin/tasks/{task_id}", include_in_schema=False)
    async def admin_task_resource(task_id: str):
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/admin/approvals/{approval_id}", include_in_schema=False)
    async def admin_approval_resource(approval_id: str):
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/assistant", include_in_schema=False)
    async def assistant_redirect():
        return RedirectResponse(url="/assistant/", status_code=302)

    @app.get("/assistant/work/{resource_type}/{resource_id}", include_in_schema=False)
    async def assistant_work_resource(resource_type: str, resource_id: str):
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "assistant" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/assistant/knowledge/sop/{sop_id}", include_in_schema=False)
    async def assistant_sop_resource(sop_id: int):
        return FileResponse(
            Path(__file__).resolve().parent / "static" / "assistant" / "index.html",
            media_type="text/html; charset=utf-8",
        )

    @app.get("/simulator/wecom", include_in_schema=False)
    async def wecom_simulator_redirect():
        return RedirectResponse(url="/simulator/wecom/", status_code=302)

    app.mount("/assistant", StaticFiles(directory="static/assistant", html=True), name="assistant_static")
    app.mount(
        "/simulator/wecom",
        StaticFiles(directory="static/simulator/wecom", html=True),
        name="wecom_simulator_static",
    )
    app.mount("/shared", StaticFiles(directory="static/shared"), name="client_shared_static")
    app.mount("/admin", StaticFiles(directory="static", html=True), name="admin_static")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 健康检查（运维必备，容器探针用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.get("/health", tags=["运维"])
async def health_check():
    """
    Kubernetes / Docker 健康探针端点。
    返回队列积压深度，便于运维监控。
    """
    runtime_queue = getattr(app.state, "message_queue", IN_MEMORY_QUEUE)
    if hasattr(runtime_queue, "get_depth"):
        queue_size = await runtime_queue.get_depth()
    else:
        queue_size = runtime_queue.qsize()
    status = "degraded" if queue_size > 500 else "ok"
    return {
        "status": status,
        "queue_depth": queue_size,
        "queue_capacity": getattr(runtime_queue, "maxsize", None),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 本地开发直接运行入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式热重载
        log_level="info",
        access_log=True,
    )
