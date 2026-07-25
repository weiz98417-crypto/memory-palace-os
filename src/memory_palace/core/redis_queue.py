"""Redis Streams message queue implementing MessageQueueProtocol for production."""
import json
import os
from typing import Any, Dict

import redis.asyncio as redis
from loguru import logger

STREAM_KEY = "memory_palace:messages"
DEAD_LETTER_KEY = "memory_palace:dead_letter"
GROUP_NAME = "mp_workers"
CONSUMER_NAME = "worker_1"
MAX_RETRIES = 3


class RedisStreamsQueue:
    """Redis Streams-based queue with consumer group and dead letter support."""

    def __init__(self, url: str = ""):
        self.url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._client: redis.Redis | None = None
        self._initialized = False

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

    async def put(self, message: Dict[str, Any]) -> None:
        await self._ensure_client()
        payload = {"data": json.dumps(message, ensure_ascii=False)}
        await self._client.xadd(STREAM_KEY, payload)

    async def get(self) -> Dict[str, Any]:
        await self._ensure_client()
        while True:
            results = await self._client.xreadgroup(
                GROUP_NAME, CONSUMER_NAME,
                {STREAM_KEY: ">"}, count=1, block=5000
            )
            if results:
                for stream, entries in results:
                    for msg_id, fields in entries:
                        data = fields.get(b"data", b"{}")
                        message = json.loads(data)
                        message["_redis_msg_id"] = msg_id.decode()
                        return message

    def task_done(self) -> None:
        pass  # ACK handled by queue_worker after processing

    async def ack(self, msg_id: str) -> None:
        """Acknowledge message after successful processing."""
        await self._ensure_client()
        await self._client.xack(STREAM_KEY, GROUP_NAME, msg_id)

    async def dead_letter(self, message: Dict[str, Any], error: str) -> None:
        """Move failed message to dead letter stream after max retries."""
        await self._ensure_client()
        payload = {
            "data": json.dumps(message, ensure_ascii=False),
            "error": error,
            "retries": str(message.get("_retries", MAX_RETRIES)),
        }
        await self._client.xadd(DEAD_LETTER_KEY, payload)

    def qsize(self) -> int:
        return 0  # Redis Streams don't expose exact queue depth; use XLEN async

    def empty(self) -> bool:
        return False  # Always assume messages may arrive

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
