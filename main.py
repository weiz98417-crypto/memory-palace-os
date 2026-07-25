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
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

# ── 内部模块 ──────────────────────────────────────────────────────────────────
from src.memory_palace.config.env_validator import validate_env          # P0: 启动校验
from src.memory_palace.core.gateway import router as webhook_router      # 企微 Webhook 路由
from src.memory_palace.skills import _auto_register_skills             # Agent 注册
from src.memory_palace.core.queue_worker import MessageQueueWorker, set_message_queue  # 异步队列消费者
from src.memory_palace.core.scheduler import TaskScheduler               # Watcher 定时任务
from src.memory_palace.tools.logger_config import setup_logger           # 日志初始化
from src.memory_palace.api import v1_router, v2_router                  # API 路由层


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 0. 启动前：加载 .env + Fail-Fast 环境变量校验
#    所有必需 Key 缺失时直接 sys.exit(1)，不让残缺配置的服务跑起来
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from dotenv import load_dotenv
load_dotenv()           # 加载 .env 文件中的环境变量
# DEMO_MODE: 跳过环境变量严格校验，允许缺失 Key 运行时降级
if os.environ.get("DEMO_MODE", "").lower() != "true":
    validate_env()          # 内部会 sys.exit(1) + 打印缺失项
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
setup_logger()          # 初始化 loguru（多文件归档、自动旋转）


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 全局共享队列（asyncio.Queue）
#    gateway.py 只负责把消息 put 进来，queue_worker 消费并派发给 Orchestrator
#    maxsize 从环境变量 MEMORY_PALACE_QUEUE_MAXSIZE 读取，默认 10000
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_QUEUE_MAXSIZE = int(os.environ.get("MEMORY_PALACE_QUEUE_MAXSIZE", 10000))
MESSAGE_QUEUE: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)


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
    logger.info("🚀 Memory Palace OS 正在启动...")

    # —— 注册所有 Agent（触发 @register_skill 装饰器）——
    _auto_register_skills()
    logger.info("✅ Agent 技能注册完成")

    # —— 确保数据库表存在（幂等，先于 Phase 恢复）——
    from src.memory_palace.knowledge.db_init import init_database
    await init_database()
    logger.info("✅ 数据库表初始化完成")

    # [Phase 3] 恢复任务图
    try:
        from src.memory_palace.core.task_graph import task_graph
        await task_graph.reload_from_db()
        logger.info("✅ Task Graph 已从数据库恢复")
    except Exception as e:
        logger.warning(f"Task Graph 恢复失败（不影响启动）: {e}")

    # [Phase 2] 恢复权限引擎待审批请求
    try:
        from src.memory_palace.core.permissions import permission_engine
        await permission_engine.reload_from_db()
        logger.info("✅ Permission Engine 已恢复待审批请求")
    except Exception as e:
        logger.warning(f"Permission Engine 恢复失败（不影响启动）: {e}")

    # —— 初始化 DI 容器 ——
    try:
        from src.memory_palace.core.container import AppContainer
        app_container = AppContainer()
        logger.info("✅ DI 容器已初始化")
    except Exception as e:
        logger.warning(f"DI 容器初始化失败（降级运行）: {e}")
        app_container = None

    # —— 启动队列消费者（后台 Task）——
    set_message_queue(MESSAGE_QUEUE)
    # Redis queue backend (only when not in DEMO_MODE)
    queue_backend = None
    if os.environ.get("DEMO_MODE", "").lower() != "true":
        try:
            from src.memory_palace.core.redis_queue import RedisStreamsQueue
            queue_backend = RedisStreamsQueue()
            logger.info("✅ Redis Streams 队列后端已初始化")
        except Exception as e:
            logger.warning(f"Redis 队列后端初始化失败（降级到内存队列）: {e}")
    worker = MessageQueueWorker(queue=MESSAGE_QUEUE, container=app_container, queue_backend=queue_backend)
    consumer_task = asyncio.create_task(worker.start(), name="queue-consumer")
    logger.info("✅ 异步消息队列消费者已启动")

    # —— 启动定时任务调度器（Watcher 鹰眼巡检）——
    scheduler = TaskScheduler()
    scheduler.start()
    logger.info("✅ APScheduler 定时任务调度器已启动")

    # —— 注册健康检查器 ——
    try:
        from src.memory_palace.core.health import get_health_registry
        registry = get_health_registry()
        # PG check
        if os.environ.get("DEMO_MODE", "").lower() != "true" and app_container:
            try:
                from src.memory_palace.core.health import DatabaseHealthChecker
                registry.register("postgresql", DatabaseHealthChecker(
                    lambda: app_container.db_client.fetch_one("SELECT 1")
                ))
            except Exception: pass
        # Redis check
        if queue_backend:
            try:
                from src.memory_palace.core.health import RedisHealthChecker
                registry.register("redis", RedisHealthChecker(
                    lambda: queue_backend._client.ping() if queue_backend._client else False
                ))
            except Exception: pass
        logger.info("✅ 健康检查器已注册")
    except Exception as e:
        logger.debug(f"健康检查器注册跳过: {e}")

    # —— 将公共对象挂到 app.state，供路由层访问 ——
    app.state.message_queue = MESSAGE_QUEUE
    app.state.scheduler = scheduler

    yield  # ← FastAPI 在此处理请求

    # ── 优雅关机 ──────────────────────────────────────────────────────────────
    logger.info("🛑 收到关机信号，开始优雅退出...")

    # 关闭企微 HTTP 客户端
    try:
        from src.memory_palace.tools.wechat_client import get_wechat_client
        wc = get_wechat_client()
        if wc:
            await wc.close()
        logger.info("✅ 企微 HTTP 客户端已关闭")
    except Exception as e:
        logger.warning(f"企微客户端关闭异常（不影响退出）: {e}")

    # 停止接收新任务
    scheduler.shutdown()

    # 等待队列排空（最多 30 秒）
    try:
        await asyncio.wait_for(MESSAGE_QUEUE.join(), timeout=30.0)
        logger.info("✅ 消息队列已排空")
    except asyncio.TimeoutError:
        logger.warning(f"⚠️  队列排空超时，剩余 {MESSAGE_QUEUE.qsize()} 条消息未处理")

    # 记录死信队列内容
    if hasattr(worker, '_dead_letter_queue') and worker._dead_letter_queue:
        logger.error(f"⚠️ 死信队列包含 {len(worker._dead_letter_queue)} 条未发送回复: "
                     f"{[d['msg_id'] for d in worker._dead_letter_queue]}")

    # 取消消费者 Task
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

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
    docs_url="/docs" if __debug__ else None,
    redoc_url=None,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 限流（生产环境自动启用，demo 模式跳过）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

# 企微 Webhook（GET 验证 + POST 接收消息）
app.include_router(webhook_router, prefix="/webhook", tags=["企微网关"])

# API v1（管理端接口）
app.include_router(v1_router, tags=["API v1"])

# API v2（扩展接口）
app.include_router(v2_router, tags=["API v2"])

# Demo 消息入口（仅 DEMO_MODE=true 时可用）
if os.environ.get("DEMO_MODE", "").lower() == "true":
    from src.memory_palace.core.gateway import demo_router
    app.include_router(demo_router, tags=["Demo"])
    logger.info("🎮 DEMO_MODE 已激活 — /demo/send 端点可用")

# 管理大屏静态文件（/admin 重定向到 /admin/index.html，避免 307）
from fastapi.responses import RedirectResponse
@app.get("/admin", include_in_schema=False)
async def admin_redirect():
    return RedirectResponse(url="/admin/index.html", status_code=302)

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
    queue_size = MESSAGE_QUEUE.qsize()
    status = "degraded" if queue_size > 500 else "ok"
    return {
        "status": status,
        "queue_depth": queue_size,
        "queue_capacity": MESSAGE_QUEUE.maxsize,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 本地开发直接运行入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,          # 开发模式热重载
        log_level="info",
        access_log=True,
    )

    