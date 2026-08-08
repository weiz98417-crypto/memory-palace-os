"""Redis Streams message queue implementing MessageQueueProtocol for production."""
from collections import deque
import json
import os
import hashlib
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

import redis.asyncio as redis
from loguru import logger
from redis.exceptions import TimeoutError as RedisTimeoutError

from .sensitive_output import public_error_message

STREAM_KEY = "memory_palace:messages"
DEAD_LETTER_KEY = "memory_palace:dead_letter"
GROUP_NAME = "mp_workers"
CONSUMER_NAME = "worker_1"
MAX_RETRIES = 3
DEFAULT_PENDING_IDLE_MS = 300_000


def _redis_field(mapping: Mapping[Any, Any], name: str, default: Any = None) -> Any:
    if name in mapping:
        return mapping[name]
    encoded_name = name.encode()
    if encoded_name in mapping:
        return mapping[encoded_name]
    return default


def _decode_redis_text(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


class RedisStreamsQueue:
    """Redis Streams-based queue with consumer group and dead letter support."""

    backend_name = "redis_streams"

    def __init__(self, url: str = ""):
        self.url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.pending_idle_ms = max(
            1,
            int(os.environ.get("REDIS_PENDING_IDLE_MS", str(DEFAULT_PENDING_IDLE_MS))),
        )
        self._client: redis.Redis | None = None
        self._initialized = False
        self._startup_recovery_buffer: deque[Dict[str, Any]] = deque()
        self._recovered_message_ids: set[str] = set()
        self._recovery_observer: Callable[[str, str], Awaitable[None]] | None = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=False)
            # Create consumer group (idempotent — MKSTREAM creates the stream)
            try:
                await self._client.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            self._initialized = True
            logger.info(f"Redis Streams 队列已连接: {self.url}")

    async def connect(self) -> None:
        """建立连接并验证 Redis 可用。"""
        await self._ensure_client()
        await self._client.ping()

    def set_recovery_observer(
        self,
        observer: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Observe recovered-message claim/ACK counters without retaining payloads."""
        self._recovery_observer = observer

    async def prepare_startup_recovery(self) -> Dict[str, Any]:
        """Claim pending messages from the previous process before reading new work."""
        await self._ensure_client()
        pending_info = await self._client.xpending(STREAM_KEY, GROUP_NAME)
        pending_count = int(_redis_field(pending_info, "pending", 0))
        if pending_count <= 0:
            return {"status": "AVAILABLE", "pending": 0, "claimed": 0}
        if not hasattr(self._client, "xautoclaim"):
            raise RuntimeError(
                "Redis startup recovery requires XAUTOCLAIM when pending messages exist"
            )

        startup_idle_ms = max(0, int(os.environ.get("REDIS_STARTUP_CLAIM_IDLE_MS", "0")))
        claim_limit = max(1, int(os.environ.get("REDIS_STARTUP_CLAIM_LIMIT", "10000")))
        if pending_count > claim_limit:
            raise RuntimeError(
                "Redis startup recovery pending count exceeds the configured claim limit"
            )
        claimed_count = 0
        cursor: Any = "0-0"
        seen_ids: set[str] = set()
        while claimed_count < pending_count:
            claimed_before = claimed_count
            claimed = await self._client.xautoclaim(
                STREAM_KEY,
                GROUP_NAME,
                CONSUMER_NAME,
                min_idle_time=startup_idle_ms,
                start_id=cursor,
                count=min(100, claim_limit - claimed_count),
            )
            next_cursor = claimed[0] if claimed else "0-0"
            entries = claimed[1] if len(claimed) > 1 else []
            for message_id, fields in entries:
                decoded_id = str(_decode_redis_text(message_id))
                if decoded_id in seen_ids:
                    continue
                seen_ids.add(decoded_id)
                message = self._decode_message(message_id, fields)
                message["_recovered"] = True
                self._startup_recovery_buffer.append(message)
                self._recovered_message_ids.add(decoded_id)
                claimed_count += 1
                if claimed_count >= claim_limit:
                    break
            decoded_cursor = str(_decode_redis_text(next_cursor))
            if decoded_cursor == "0-0" or not entries:
                break
            if decoded_cursor == str(cursor) and claimed_count == claimed_before:
                break
            cursor = decoded_cursor

        if claimed_count != pending_count:
            self._startup_recovery_buffer.clear()
            self._recovered_message_ids.clear()
            raise RuntimeError(
                "Redis pending messages were not fully claimed during startup recovery"
            )

        return {
            "status": "AVAILABLE",
            "pending": pending_count,
            "claimed": claimed_count,
        }

    async def _notify_recovery(self, event: str, message_id: str) -> None:
        if self._recovery_observer is None:
            return
        try:
            await self._recovery_observer(event, message_id)
        except Exception as exc:
            logger.warning("Redis 恢复审计计数写入失败: {}", type(exc).__name__)

    async def get_depth(self) -> int:
        """Return pending plus undelivered messages, excluding completed history."""
        await self._ensure_client()
        pending_info = await self._client.xpending(STREAM_KEY, GROUP_NAME)
        groups = await self._client.xinfo_groups(STREAM_KEY)
        group_info = next(
            (
                group
                for group in groups
                if _decode_redis_text(_redis_field(group, "name")) == GROUP_NAME
            ),
            {},
        )
        pending = int(_redis_field(pending_info, "pending", 0))
        lag = int(_redis_field(group_info, "lag", 0) or 0)
        return pending + lag

    async def diagnostics(self) -> Dict[str, Any]:
        """Return a stable operational view without exposing Redis internals to callers."""
        await self._ensure_client()
        connected = bool(await self._client.ping())
        stream_depth = int(await self._client.xlen(STREAM_KEY))
        dead_letter_depth = int(await self._client.xlen(DEAD_LETTER_KEY))
        pending_info = await self._client.xpending(STREAM_KEY, GROUP_NAME)
        groups = await self._client.xinfo_groups(STREAM_KEY)
        group_info = next(
            (
                group
                for group in groups
                if _decode_redis_text(_redis_field(group, "name")) == GROUP_NAME
            ),
            {},
        )
        consumers = await self._client.xinfo_consumers(STREAM_KEY, GROUP_NAME)
        return {
            "backend": "redis_streams",
            "connected": connected,
            "stream": STREAM_KEY,
            "group": GROUP_NAME,
            "stream_depth": stream_depth,
            "pending": int(_redis_field(pending_info, "pending", 0)),
            "lag": int(_redis_field(group_info, "lag", 0) or 0),
            "consumers": [
                {
                    "name": _decode_redis_text(_redis_field(consumer, "name", "")),
                    "pending": int(_redis_field(consumer, "pending", 0)),
                    "idle_ms": int(_redis_field(consumer, "idle", 0)),
                }
                for consumer in consumers
            ],
            "dead_letter_stream": DEAD_LETTER_KEY,
            "dead_letter_depth": dead_letter_depth,
        }

    async def list_dead_letters(self, limit: int = 20) -> list[Dict[str, Any]]:
        """Return newest dead letters in a backend-neutral representation."""
        await self._ensure_client()
        entries = await self._client.xrevrange(DEAD_LETTER_KEY, count=limit)
        dead_letters = []
        for message_id, fields in entries:
            decoded_id = _decode_redis_text(message_id)
            raw_data = _decode_redis_text(_redis_field(fields, "data", "{}"))
            try:
                message = json.loads(raw_data)
            except (TypeError, json.JSONDecodeError):
                message = {}
            if isinstance(message, dict):
                message = {key: value for key, value in message.items() if not key.startswith("_")}
            else:
                message = {}
            dead_letters.append(
                {
                    "id": decoded_id,
                    "created_at_ms": int(decoded_id.split("-", 1)[0]),
                    "message": message,
                    "error": _decode_redis_text(_redis_field(fields, "error", "")),
                    "retries": int(_decode_redis_text(_redis_field(fields, "retries", "0")) or 0),
                }
            )
        return dead_letters

    async def retry_dead_letter(self, dead_letter_id: str) -> Dict[str, Any] | None:
        """Atomically requeue one dead letter and prevent duplicate manual retries."""
        await self._ensure_client()
        entries = await self._client.xrange(
            DEAD_LETTER_KEY,
            min=dead_letter_id,
            max=dead_letter_id,
            count=1,
        )
        if not entries:
            return None

        _entry_id, fields = entries[0]
        raw_data = _decode_redis_text(_redis_field(fields, "data", "{}"))
        try:
            message = json.loads(raw_data)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("死信业务载荷不是合法 JSON") from exc
        if not isinstance(message, dict):
            raise ValueError("死信业务载荷必须是对象")

        message.pop("_redis_msg_id", None)
        message.pop("_recovered", None)
        message["_retries"] = 0
        message["_dead_letter_retry_id"] = dead_letter_id
        payload = json.dumps(message, ensure_ascii=False)
        retry_guard_key = f"memory_palace:dead_letter_retry:{dead_letter_id}"
        script = """
        if redis.call('EXISTS', KEYS[3]) == 1 then
            return redis.error_reply('ALREADY_RETRIED')
        end
        redis.call('SET', KEYS[3], '1', 'EX', 86400)
        local new_id = redis.call('XADD', KEYS[1], '*', 'data', ARGV[1])
        redis.call('XDEL', KEYS[2], ARGV[2])
        return new_id
        """
        new_message_id = await self._client.eval(
            script,
            3,
            STREAM_KEY,
            DEAD_LETTER_KEY,
            retry_guard_key,
            payload,
            dead_letter_id,
        )
        return {
            "dead_letter_id": dead_letter_id,
            "stream_message_id": _decode_redis_text(new_message_id),
            "message_id": message.get("msg_id", ""),
        }

    async def put(self, message: Dict[str, Any]) -> Optional[str]:
        await self._ensure_client()
        payload = json.dumps(message, ensure_ascii=False)
        business_message_id = str(message.get("msg_id") or "")
        if not business_message_id:
            stream_message_id = await self._client.xadd(STREAM_KEY, {"data": payload})
            return str(_decode_redis_text(stream_message_id))
        dedup_digest = hashlib.sha256(business_message_id.encode()).hexdigest()
        dedup_key = f"memory_palace:dedup:{dedup_digest}"
        dedup_ttl = max(1, int(os.environ.get("REDIS_DEDUP_TTL_SECONDS", "300")))
        script = """
        if not redis.call('SET', KEYS[2], '1', 'EX', ARGV[2], 'NX') then
            return false
        end
        return redis.call('XADD', KEYS[1], '*', 'data', ARGV[1])
        """
        stream_message_id = await self._client.eval(
            script,
            2,
            STREAM_KEY,
            dedup_key,
            payload,
            dedup_ttl,
        )
        return (
            str(_decode_redis_text(stream_message_id))
            if stream_message_id is not None
            else None
        )

    async def retry(self, message: Dict[str, Any], source_message_id: str) -> str:
        """Atomically enqueue the next attempt and acknowledge the failed attempt."""
        await self._ensure_client()
        next_message = dict(message)
        next_message.pop("_redis_msg_id", None)
        next_message.pop("_recovered", None)
        next_message["_retries"] = int(next_message.get("_retries", 0)) + 1
        next_message["_retry_of_stream_id"] = source_message_id
        payload = json.dumps(next_message, ensure_ascii=False)
        script = """
        local new_id = redis.call('XADD', KEYS[1], '*', 'data', ARGV[1])
        redis.call('XACK', KEYS[1], ARGV[2], ARGV[3])
        return new_id
        """
        new_message_id = await self._client.eval(
            script,
            1,
            STREAM_KEY,
            payload,
            GROUP_NAME,
            source_message_id,
        )
        if source_message_id in self._recovered_message_ids:
            self._recovered_message_ids.discard(source_message_id)
            await self._notify_recovery("ack", source_message_id)
        return _decode_redis_text(new_message_id)

    async def get(self) -> Dict[str, Any]:
        await self._ensure_client()
        while True:
            if self._startup_recovery_buffer:
                return self._startup_recovery_buffer.popleft()
            recovered_message = await self._claim_stale_pending()
            if recovered_message is not None:
                logger.warning(
                    "Redis Streams 回收超时 pending 消息: "
                    f"{recovered_message['_redis_msg_id']}"
                )
                return recovered_message
            try:
                results = await self._client.xreadgroup(
                    GROUP_NAME, CONSUMER_NAME,
                    {STREAM_KEY: ">"}, count=1, block=5000
                )
            except RedisTimeoutError:
                continue
            if results:
                for stream, entries in results:
                    for msg_id, fields in entries:
                        return self._decode_message(msg_id, fields)

    async def _claim_stale_pending(self) -> Dict[str, Any] | None:
        if not hasattr(self._client, "xautoclaim"):
            return None
        claimed = await self._client.xautoclaim(
            STREAM_KEY,
            GROUP_NAME,
            CONSUMER_NAME,
            min_idle_time=self.pending_idle_ms,
            start_id="0-0",
            count=1,
        )
        entries = claimed[1] if len(claimed) > 1 else []
        if not entries:
            return None
        message_id, fields = entries[0]
        message = self._decode_message(message_id, fields)
        message["_recovered"] = True
        decoded_id = str(message["_redis_msg_id"])
        if decoded_id not in self._recovered_message_ids:
            self._recovered_message_ids.add(decoded_id)
            await self._notify_recovery("claim", decoded_id)
        return message

    @staticmethod
    def _decode_message(message_id: Any, fields: Mapping[Any, Any]) -> Dict[str, Any]:
        raw_data = _decode_redis_text(_redis_field(fields, "data", "{}"))
        message = json.loads(raw_data)
        message["_redis_msg_id"] = _decode_redis_text(message_id)
        return message

    def task_done(self) -> None:
        pass  # ACK handled by queue_worker after processing

    async def ack(self, msg_id: str) -> None:
        """Acknowledge message after successful processing."""
        await self._ensure_client()
        acknowledged = await self._client.xack(STREAM_KEY, GROUP_NAME, msg_id)
        if acknowledged and msg_id in self._recovered_message_ids:
            self._recovered_message_ids.discard(msg_id)
            await self._notify_recovery("ack", msg_id)

    async def dead_letter(self, message: Dict[str, Any], error: str) -> str:
        """Move failed message to dead letter stream after max retries."""
        await self._ensure_client()
        payload = {
            "data": json.dumps(message, ensure_ascii=False),
            "error": public_error_message(error, context="queue")
            or "任务处理失败，请携带 Trace ID 排查后重试。",
            "retries": str(message.get("_retries", MAX_RETRIES)),
        }
        message_id = await self._client.xadd(DEAD_LETTER_KEY, payload)
        return str(_decode_redis_text(message_id))

    def qsize(self) -> int:
        return 0  # Redis Streams don't expose exact queue depth; use XLEN async

    def empty(self) -> bool:
        return False  # Always assume messages may arrive

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
