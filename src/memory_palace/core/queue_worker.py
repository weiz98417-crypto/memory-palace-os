      
"""
queue_worker.py · 异步消息队列消费者
=====================================
职责：
  - 持续消费 asyncio.Queue 中的企微消息
  - 将消息派发给 Orchestrator（多 Agent 流转中枢）
  - 企微 5 秒响应限制的核心解耦点：
      gateway.py 在 <1s 内把消息入队并立即回 "success"
      本 Worker 在后台异步处理，不阻塞 HTTP 响应
  - 预留 Redis 迁移接口：将来只需替换 _fetch_message 方法

架构关系：
  企微 Webhook → gateway.py (HTTP)
                      ↓  put_nowait
               asyncio.Queue  ← 本模块消费
                      ↓  dispatch
               orchestrator.py → Router/Commander/MemoryOps/Persona/Watcher

消息格式（队列内的标准 dict）：
  {
    "msg_id":    str,   # 企微消息 ID（去重用）
    "from_user": str,   # 发送者 UserID
    "to_user":   str,   # 接收者（企微 AgentID）
    "msg_type":  str,   # text / image / event / ...
    "content":   str,   # 消息正文（event 类型为事件 key）
    "timestamp": float, # 入队时间戳（UTC，用于 SLA 超时计算）
    "raw_xml":   str,   # 原始 XML（留存审计）
  }
"""

import asyncio
import time
from typing import Optional

from loguru import logger

from src.memory_palace.core.message_runs import MessageRunRepository
from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.redis_queue import MAX_RETRIES
from src.memory_palace.core.sensitive_output import (
    public_error_message,
    sanitize_public_value,
)
from src.memory_palace.knowledge.push_logger import (
    record_reply_delivery,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 消息去重窗口（防止企微重试导致同一条消息被处理多次）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DEDUP_WINDOW_SECONDS = 60        # 60 秒内相同 msg_id 视为重复
_dedup_cache: dict[str, float] = {}   # {msg_id: 首次处理时间戳}
_DELIVERY_RESUME_STATUSES = {
    "PROCESSING",
    "RECOVERING",
    "RETRYING",
    "RETRY_REQUIRED",
    "DEAD_LETTERED",
    "COMPLETED",
}


class MessageProcessingFailure(RuntimeError):
    def __init__(self, message: str, result: Optional[dict] = None) -> None:
        super().__init__(message)
        self.result = result


class MessageDeliveryFailure(MessageProcessingFailure):
    def __init__(self, message: str, *, auto_retry: bool) -> None:
        super().__init__(message)
        self.public_message = message
        self.auto_retry = auto_retry


class MessagePolicyFailure(MessageDeliveryFailure):
    """Terminal channel rejection that must be acknowledged without retry."""


REAL_WECOM_DISABLED_ERROR = (
    "真实企业微信投递已按项目策略禁用；请通过企微模拟器完成业务链路。"
)


def _message_channel(message: dict) -> str:
    metadata = message.get("metadata") or {}
    return str(message.get("channel") or metadata.get("channel") or "LEGACY").upper()


def _saved_result_for_delivery(run: Optional[dict], *, delivery_only: bool) -> Optional[dict]:
    if not run:
        return None
    result = run.get("result")
    if not isinstance(result, dict) or not result:
        return None
    if str(result.get("status") or "").lower() in {"failed", "error"}:
        return None
    run_status = str(run.get("status") or "").upper()
    has_deliverable_output = bool(run.get("reply_text")) or bool(result.get("business_cards")) or (
        str(result.get("status") or "").lower()
        in {"processed", "completed", "success", "succeeded"}
    )
    if not has_deliverable_output:
        return None
    if delivery_only or run_status in _DELIVERY_RESUME_STATUSES:
        return result
    return None


def _public_scalar(value: object) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    sanitized = sanitize_public_value(value)
    return str(sanitized).strip() if sanitized is not None else ""


def _is_duplicate(msg_id: str) -> bool:
    """检查消息是否在去重窗口内已处理过"""
    now = time.time()
    # 清理过期记录（避免内存无限增长）
    expired = [k for k, v in _dedup_cache.items() if now - v > _DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _dedup_cache[k]

    if msg_id in _dedup_cache:
        return True

    _dedup_cache[msg_id] = now
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Worker 主体
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MessageQueueWorker:
    """
    异步消息队列消费者。
    在 main.py lifespan 中以 asyncio.create_task 方式运行。
    """

    def __init__(
        self,
        queue: asyncio.Queue,
        concurrency: int = 5,           # 并发处理的消息数（文旅场景不需要太高）
        orchestrator: Optional[Orchestrator] = None,
        container = None,               # AppContainer (optional)
        queue_backend = None,           # RedisStreamsQueue or None (for asyncio.Queue)
    ):
        self.queue = queue
        self.queue_backend = queue_backend
        self.concurrency = concurrency
        self._orchestrator = orchestrator or Orchestrator(container=container)
        self._container = container
        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = False
        self._started_at: Optional[float] = None
        self._inflight_tasks: set[asyncio.Task] = set()
        self._dead_letter_queue: list[dict] = []   # 死信队列 stub

    # ── 公共接口 ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """主消费循环，被 asyncio.create_task 调用"""
        backend = "Redis" if self.queue_backend else "InMemory"
        logger.info(f"🔄 队列消费者启动 [{backend}]，并发度: {self.concurrency}")
        self._running = True
        self._started_at = time.time()
        try:
            while self._running:
                try:
                    message = await self.queue.get()
                    # 每条消息独立 Task，不阻塞主循环
                    task = asyncio.create_task(self._handle_with_semaphore(message))
                    self._inflight_tasks.add(task)
                    task.add_done_callback(self._inflight_tasks.discard)
                except asyncio.CancelledError:
                    logger.info("🛑 队列消费者收到取消信号，退出消费循环")
                    break
                except Exception as e:
                    logger.error(f"❌ 队列消费循环异常: {e}")
                    await asyncio.sleep(1)   # 短暂等待，避免异常快速重试
        finally:
            self._running = False

    def stop(self) -> None:
        """外部停止信号（优雅关机时调用）"""
        self._running = False

    def diagnostics(self) -> dict[str, object]:
        """Return a stable worker state without exposing queued message data."""

        backend = "in_memory"
        if self.queue_backend is not None:
            backend = str(getattr(self.queue_backend, "backend_name", "unknown"))
        return {
            "status": "RUNNING" if self._running else "STOPPED",
            "running": self._running,
            "backend": backend,
            "concurrency": self.concurrency,
            "inflight": sum(not task.done() for task in self._inflight_tasks),
            "started_at": self._started_at,
        }

    async def drain(self, timeout: float = 30.0) -> bool:
        """等待已领取消息完成；超时任务取消后由 Redis pending 在重启时回收。"""
        self.stop()
        tasks = tuple(task for task in self._inflight_tasks if not task.done())
        if not tasks:
            return True

        done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        if not pending:
            return True

        logger.warning("消息 Worker 排空超时，取消 {} 个任务并保留 Redis pending", len(pending))
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        return False

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    async def _handle_with_semaphore(self, message: dict) -> None:
        """用信号量控制并发，处理完后通知队列 task_done（支持 queue.join()）"""
        async with self._semaphore:
            backend = self.queue_backend or self.queue
            redis_message_id = message.get("_redis_msg_id")
            repository = None
            if self._container and getattr(self._container, "db_client", None):
                repository = MessageRunRepository(self._container.db_client)
            try:
                await self._process_message(message)
                if redis_message_id and hasattr(backend, "ack"):
                    await backend.ack(redis_message_id)
            except Exception as e:
                logger.error(
                    "❌ 消息处理失败 [msg_id={}] [error_type={}]",
                    message.get("msg_id"),
                    type(e).__name__,
                )
                retry_count = int(message.get("_retries", 0))
                delivery_failure = isinstance(e, MessageDeliveryFailure)
                if delivery_failure:
                    message["_delivery_only"] = True
                result = getattr(e, "result", None)
                result = sanitize_public_value(result) if result is not None else None
                if not isinstance(result, dict):
                    result = None
                error = getattr(e, "public_message", None) or public_error_message(e, context="queue") or (
                    "任务处理失败，请携带 Trace ID 排查后重试。"
                )
                if isinstance(e, MessagePolicyFailure):
                    if repository:
                        await repository.mark_failed(message.get("msg_id"), error)
                    if redis_message_id and hasattr(backend, "ack"):
                        await backend.ack(redis_message_id)
                    return
                requires_manual_retry = delivery_failure and not e.auto_retry
                if requires_manual_retry and redis_message_id and hasattr(backend, "dead_letter"):
                    try:
                        dead_letter_id = await backend.dead_letter(message, error)
                        if repository:
                            await repository.mark_retry_required(
                                message.get("msg_id"),
                                error,
                                dead_letter_id=dead_letter_id,
                            )
                        await backend.ack(redis_message_id)
                    except Exception as dead_letter_error:
                        logger.error(
                            "❌ 消息转入死信失败 [msg_id={}]: {}",
                            message.get("msg_id"),
                            type(dead_letter_error).__name__,
                        )
                elif redis_message_id and hasattr(backend, "retry") and retry_count < MAX_RETRIES:
                    if repository:
                        await repository.mark_retrying(message.get("msg_id"), error, result)
                    try:
                        await backend.retry(message, redis_message_id)
                    except Exception as retry_error:
                        logger.error(
                            "❌ 消息重试入队失败 [msg_id={}]: {}",
                            message.get("msg_id"),
                            type(retry_error).__name__,
                        )
                elif redis_message_id and hasattr(backend, "dead_letter"):
                    if repository:
                        await repository.mark_retrying(message.get("msg_id"), error, result)
                    try:
                        dead_letter_id = await backend.dead_letter(message, error)
                        if repository:
                            await repository.mark_retry_required(
                                message.get("msg_id"),
                                error,
                                dead_letter_id=dead_letter_id,
                                result=result,
                            )
                        await backend.ack(redis_message_id)
                    except Exception as dead_letter_error:
                        logger.error(
                            "❌ 消息转入死信失败 [msg_id={}]: {}",
                            message.get("msg_id"),
                            type(dead_letter_error).__name__,
                        )
                elif repository:
                    await repository.mark_retry_required(
                        message.get("msg_id"),
                        error,
                        result=result,
                    )
            finally:
                self.queue.task_done()   # 必须调用，否则 queue.join() 永远不会返回

    async def _process_message(self, message: dict) -> None:
        """
        单条消息处理逻辑：
          1. 去重检查
          2. 派发给 Orchestrator
          3. 记录处理耗时（SLA 监控）
        """
        msg_id = message.get("msg_id", "unknown")
        enqueue_time = message.get("timestamp", time.time())
        repository = None
        if self._container and getattr(self._container, "db_client", None):
            repository = MessageRunRepository(self._container.db_client)

        if _message_channel(message) == "WECOM":
            await self._reject_real_wecom(message, repository)

        # —— 去重 ——
        is_retry = int(message.get("_retries", 0)) > 0 or bool(message.get("_dead_letter_retry_id"))
        if not is_retry and _is_duplicate(msg_id):
            logger.warning(f"⚠️  重复消息已丢弃 [msg_id={msg_id}]（企微重试）")
            return

        # —— 派发 ——
        start = time.time()
        logger.info(
            f"📨 开始处理消息 [msg_id={msg_id}] "
            f"[from={message.get('from_user')}] "
            f"[type={message.get('msg_type')}]"
        )

        saved_result = None
        if repository:
            stored_run = await repository.get(msg_id)
            stored_status = str((stored_run or {}).get("status") or "").upper()
            if stored_status in {"COMPLETED", "RETRY_REQUIRED", "DEAD_LETTERED"}:
                logger.info(
                    "消息运行记录已进入不可领取状态，跳过重复执行 [msg_id={}] [status={}]",
                    msg_id,
                    stored_status,
                )
                return
            saved_result = _saved_result_for_delivery(
                stored_run,
                delivery_only=bool(message.get("_delivery_only")),
            )
            resumes_saved_delivery = isinstance(saved_result, dict) and (
                bool(message.get("_delivery_only"))
                or bool(message.get("_recovered"))
                or stored_status in {"RETRYING", "RECOVERING"}
            )
            if isinstance(saved_result, dict) and not resumes_saved_delivery:
                logger.info(
                    "消息已有运行中结果，跳过重复执行 [msg_id={}] [status={}]",
                    msg_id,
                    stored_status,
                )
                return
            if resumes_saved_delivery:
                await repository.mark_processing(
                    msg_id,
                    recovering=bool(message.get("_recovered")),
                )
            elif not await repository.claim_processing(
                msg_id,
                recovering=bool(message.get("_recovered")),
                expected_status=stored_status,
            ):
                logger.info(
                    "消息处理权已被其他 Worker 领取，跳过重复执行 [msg_id={}] [status={}]",
                    msg_id,
                    stored_status,
                )
                return

        result = saved_result
        if message.get("_delivery_only") and not isinstance(result, dict):
            raise MessageProcessingFailure("已保存的助手回复无法恢复，请人工重试。")

        if not isinstance(result, dict):
            try:
                result = await self._orchestrator.dispatch(message)
            except Exception:
                raise

        if isinstance(result, dict) and str(result.get("status", "")).lower() == "failed":
            error = result.get("error") or result.get("reply_text") or "Agent execution failed"
            raise MessageProcessingFailure(error, result)

        if repository:
            await repository.save_result(msg_id, result or {})
        message["_delivery_only"] = True

        await self._deliver_result(message, result or {}, repository)

        if repository:
            await repository.mark_completed(msg_id, result or {})

        # —— 记录结果供旧演示接口轮询 ——
        if result and isinstance(result, dict):
            reply_text = result.get("reply_text")
            trace_id = result.get("trace_id", msg_id)
            try:
                from src.memory_palace.core.gateway import demo_store_result
                demo_store_result(trace_id, {
                    "reply_text": reply_text or "(no reply)",
                    "route": result.get("route", {}).get("target_agent", "unknown"),
                    "intent": result.get("route", {}).get("intent", "unknown"),
                    "status": result.get("status", "unknown"),
                })
                logger.info(f"[Trace-{trace_id}] 处理结果已持久化")
            except ImportError:
                pass  # 非 demo 模式，忽略

        elapsed_ms = (time.time() - start) * 1000
        queue_wait_ms = (time.time() - enqueue_time) * 1000

        logger.info(
            f"✅ 消息处理完成 [msg_id={msg_id}] "
            f"处理耗时={elapsed_ms:.0f}ms  队列等待={queue_wait_ms:.0f}ms"
        )

        # —— SLA 预警（队列等待 > 10 秒说明积压严重）——
        if queue_wait_ms > 10_000:
            logger.warning(
                f"🚨 SLA 预警：消息在队列中等待 {queue_wait_ms:.0f}ms，"
                f"当前队列深度: {self.queue.qsize()}"
            )

        # —— 死信队列内容日志（关机时汇总输出）——
        if self._dead_letter_queue:
            logger.debug(f"死信队列当前深度: {len(self._dead_letter_queue)}")

    async def _reject_real_wecom(
        self,
        message: dict,
        repository: Optional[MessageRunRepository],
    ) -> None:
        """Reject legacy real-WeCom queue items before any agent or tool side effect."""
        if repository:
            metadata = message.get("metadata") or {}
            msg_id = str(message.get("msg_id") or "unknown")
            trace_id = str(message.get("trace_id") or msg_id)
            venue_id = str(message.get("venue_id") or metadata.get("venue_id") or "")
            user_id = str(message.get("from_user") or "")
            recipient = metadata.get("external_user_id") or message.get("external_user_id") or user_id
            await record_reply_delivery(
                message_id=msg_id,
                trace_id=trace_id,
                venue_id=venue_id,
                user_id=user_id,
                channel="WECOM",
                recipient=recipient,
                reply_text="",
                delivery_status="DISABLED_BY_POLICY",
                delivery_error=REAL_WECOM_DISABLED_ERROR,
                database=self._container.db_client,
            )
            await repository.mark_delivery(
                msg_id,
                "DISABLED_BY_POLICY",
                error=REAL_WECOM_DISABLED_ERROR,
            )
        raise MessagePolicyFailure(REAL_WECOM_DISABLED_ERROR, auto_retry=False)

    async def _deliver_result(
        self,
        message: dict,
        result: dict,
        repository: Optional[MessageRunRepository],
    ) -> None:
        msg_id = message.get("msg_id", "unknown")
        metadata = message.get("metadata") or {}
        channel = _message_channel(message)
        reply_text = _public_scalar(result.get("reply_text"))
        delivery_text = reply_text
        trace_id = str(result.get("trace_id") or message.get("trace_id") or msg_id)
        venue_id = str(message.get("venue_id") or metadata.get("venue_id") or "")
        user_id = str(message.get("from_user") or "")
        recipient = metadata.get("external_user_id") or message.get("external_user_id") or user_id

        if not repository:
            return

        if channel in {"WEB", "WECOM_SIMULATOR"}:
            await repository.mark_delivery(msg_id, "PERSISTED")
            if reply_text:
                await record_reply_delivery(
                    message_id=msg_id,
                    trace_id=trace_id,
                    venue_id=venue_id,
                    user_id=user_id,
                    channel=channel,
                    recipient=recipient,
                    reply_text=reply_text,
                    delivery_status="PERSISTED",
                    database=self._container.db_client,
                )
            logger.debug(f"[Trace-{trace_id}] {channel} 回复已持久化，等待客户端轮询")
            return

        if channel != "WECOM":
            await repository.mark_delivery(msg_id, "PERSISTED")
            return

        error = REAL_WECOM_DISABLED_ERROR
        await record_reply_delivery(
            message_id=msg_id,
            trace_id=trace_id,
            venue_id=venue_id,
            user_id=user_id,
            channel=channel,
            recipient=recipient,
            reply_text=delivery_text,
            delivery_status="DISABLED_BY_POLICY",
            delivery_error=error,
            database=self._container.db_client,
        )
        await repository.mark_delivery(msg_id, "DISABLED_BY_POLICY", error=error)
        raise MessagePolicyFailure(error, auto_retry=False)

    # ── Redis 迁移预留接口 ────────────────────────────────────────────────────
    # 将来迁移到 Redis 时，只需重写以下两个方法，上层逻辑不变：
    #
    # async def _fetch_message(self) -> dict:
    #     """从 Redis Stream 或 List 拉取消息"""
    #     ...
    #
    # async def _ack_message(self, msg_id: str) -> None:
    #     """确认消息已处理（Redis Stream XACK）"""
    #     ...


# ─────────────────────────────────────────────────────────────────────────────
# 队列访问函数（供 API 端点使用）
# ─────────────────────────────────────────────────────────────────────────────

_global_queue: Optional[asyncio.Queue] = None


def set_message_queue(queue: asyncio.Queue) -> None:
    """设置全局消息队列（main.py lifespan 中调用）"""
    global _global_queue
    _global_queue = queue


def get_message_queue() -> Optional[asyncio.Queue]:
    """获取全局消息队列"""
    return _global_queue
