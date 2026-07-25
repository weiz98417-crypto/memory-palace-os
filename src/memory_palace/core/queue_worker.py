      
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

from src.memory_palace.core.orchestrator import Orchestrator


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 消息去重窗口（防止企微重试导致同一条消息被处理多次）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DEDUP_WINDOW_SECONDS = 60        # 60 秒内相同 msg_id 视为重复
_dedup_cache: dict[str, float] = {}   # {msg_id: 首次处理时间戳}


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
        self._orchestrator = orchestrator or Orchestrator()
        self._container = container
        self._semaphore = asyncio.Semaphore(concurrency)
        self._running = True
        self._dead_letter_queue: list[dict] = []   # 死信队列 stub

    # ── 公共接口 ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """主消费循环，被 asyncio.create_task 调用"""
        backend = "Redis" if self.queue_backend else "InMemory"
        logger.info(f"🔄 队列消费者启动 [{backend}]，并发度: {self.concurrency}")
        while self._running:
            try:
                message = await self.queue.get()
                # 每条消息独立 Task，不阻塞主循环
                asyncio.create_task(self._handle_with_semaphore(message))
            except asyncio.CancelledError:
                logger.info("🛑 队列消费者收到取消信号，退出消费循环")
                break
            except Exception as e:
                logger.error(f"❌ 队列消费循环异常: {e}")
                await asyncio.sleep(1)   # 短暂等待，避免异常快速重试

    def stop(self) -> None:
        """外部停止信号（优雅关机时调用）"""
        self._running = False

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    async def _handle_with_semaphore(self, message: dict) -> None:
        """用信号量控制并发，处理完后通知队列 task_done（支持 queue.join()）"""
        async with self._semaphore:
            try:
                await self._process_message(message)
            except Exception as e:
                logger.error(f"❌ 消息处理失败 [msg_id={message.get('msg_id')}]: {e}")
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

        # —— 去重 ——
        if _is_duplicate(msg_id):
            logger.warning(f"⚠️  重复消息已丢弃 [msg_id={msg_id}]（企微重试）")
            return

        # —— 派发 ——
        start = time.time()
        logger.info(
            f"📨 开始处理消息 [msg_id={msg_id}] "
            f"[from={message.get('from_user')}] "
            f"[type={message.get('msg_type')}]"
        )

        result = await self._orchestrator.dispatch(message)

        # —— 发送回复到企微用户 ——
        if result and isinstance(result, dict):
            reply_text = result.get("reply_text")
            from_user = message.get("from_user")
            trace_id = result.get("trace_id", msg_id)

            # Demo 模式: 存储结果供轮询
            try:
                from src.memory_palace.core.gateway import demo_store_result
                demo_store_result(trace_id, {
                    "reply_text": reply_text or "(no reply)",
                    "route": result.get("route", {}).get("target_agent", "unknown"),
                    "intent": result.get("route", {}).get("intent", "unknown"),
                    "status": result.get("status", "unknown"),
                })
                logger.info(f"[Trace-{trace_id}] Demo 结果已存储")
            except ImportError:
                pass  # 非 demo 模式，忽略

            if reply_text and from_user and self._container:
                try:
                    wc = self._container.wechat_client
                    if wc:
                        await wc.send_text(from_user, reply_text)
                        logger.info(f"[Trace-{trace_id}] 回复已发送 to={from_user}")
                except Exception as e:
                    logger.error(f"[Trace-{trace_id}] 企微回复发送失败: {e}")
                    self._dead_letter_queue.append({
                        "msg_id": msg_id, "from_user": from_user,
                        "reply_text": reply_text, "error": str(e),
                    })
            elif reply_text and not self._container:
                logger.debug(f"[Trace-{trace_id}] 无容器注入，跳过回复发送")

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

    