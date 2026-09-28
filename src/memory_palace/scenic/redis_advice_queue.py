"""Redis Streams transport for durable advice-run wakeups."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Mapping

import redis.asyncio as redis


ADVICE_STREAM_KEY = "memory_palace:advice_runs"
ADVICE_GROUP_NAME = "mp_advice_workers"
ADVICE_DEAD_LETTER_KEY = f"{ADVICE_STREAM_KEY}:dead"
DEFAULT_ADVICE_PENDING_IDLE_MS = 300_000


def _text(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


def _field(fields: Mapping[Any, Any], name: str) -> Any:
    return fields.get(name, fields.get(name.encode()))


class RedisAdviceQueue:
    """At-least-once advice queue isolated from employee message traffic."""

    backend_name = "redis_advice_streams"

    def __init__(
        self,
        url: str = "",
        *,
        client: Any = None,
        consumer_name: str = "",
    ) -> None:
        self.url = url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.consumer_name = consumer_name or f"advice-{uuid.uuid4().hex}"
        self.pending_idle_ms = max(
            1,
            int(
                os.environ.get(
                    "ADVICE_PENDING_IDLE_MS", str(DEFAULT_ADVICE_PENDING_IDLE_MS)
                )
            ),
        )
        self._client = client
        self._initialized = client is not None

    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = redis.from_url(self.url, decode_responses=False)
        if self._initialized:
            return
        try:
            await self._client.xgroup_create(
                ADVICE_STREAM_KEY, ADVICE_GROUP_NAME, id="0", mkstream=True
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._initialized = True

    async def connect(self) -> None:
        await self._ensure_client()
        await self._client.ping()

    async def enqueue(self, message: dict[str, Any]) -> None:
        await self._ensure_client()
        run_id = str(message.get("advice_run_id") or "")
        if not run_id:
            raise ValueError("advice_run_id is required")
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(run_id.encode()).hexdigest()
        dedup_key = f"memory_palace:advice_dispatch:{digest}"
        script = """
        local existing = redis.call('GET', KEYS[2])
        if existing then
            return existing
        end
        local message_id = redis.call('XADD', KEYS[1], '*', 'data', ARGV[1])
        redis.call('SET', KEYS[2], message_id, 'PX', ARGV[2])
        return message_id
        """
        dedup_ttl_ms = max(
            1,
            int(os.environ.get("ADVICE_DISPATCH_DEDUP_TTL_SECONDS", "86400"))
            * 1000,
        )
        await self._client.eval(
            script, 2, ADVICE_STREAM_KEY, dedup_key, payload, str(dedup_ttl_ms)
        )

    async def claim(self) -> dict[str, Any] | None:
        await self._ensure_client()
        if hasattr(self._client, "xautoclaim"):
            claimed = await self._client.xautoclaim(
                ADVICE_STREAM_KEY,
                ADVICE_GROUP_NAME,
                self.consumer_name,
                min_idle_time=self.pending_idle_ms,
                start_id="0-0",
                count=1,
            )
            entries = claimed[1] if len(claimed) > 1 else []
            if entries:
                message = await self._claim_entry(*entries[0], recovered=True)
                return message
        rows = await self._client.xreadgroup(
            ADVICE_GROUP_NAME,
            self.consumer_name,
            {ADVICE_STREAM_KEY: ">"},
            count=1,
            block=1000,
        )
        for _stream, entries in rows or []:
            if entries:
                return await self._claim_entry(*entries[0], recovered=False)
        return None

    async def _claim_entry(self, message_id: Any, fields: Mapping[Any, Any], *, recovered: bool) -> dict[str, Any] | None:
        try:
            message = self._decode(message_id, fields)
        except Exception:
            # 毒消息：不能留在 PEL 里被 XAUTOCLAIM 每 300 秒重新捞起无限空转。
            # 运行事实在 scenic_commands 里是持久的，丢失唤醒消息可由启动对账兜底。
            await self._dead_letter(message_id, fields)
            return None
        if recovered:
            message["_recovered"] = True
        return message

    async def _dead_letter(self, message_id: Any, fields: Mapping[Any, Any]) -> None:
        raw = _text(_field(fields, "data"))
        try:
            await self._client.xadd(
                ADVICE_DEAD_LETTER_KEY,
                {
                    "data": raw if isinstance(raw, str) else "",
                    "error": "decode_failed",
                    "original_id": str(_text(message_id)),
                },
            )
        except Exception:
            pass  # 死信写失败时不阻塞 ACK；唤醒丢失由持久层启动对账兜底
        await self._client.xack(
            ADVICE_STREAM_KEY, ADVICE_GROUP_NAME, str(_text(message_id))
        )

    async def ack(self, message: dict[str, Any]) -> None:
        await self._ensure_client()
        message_id = str(message.get("_redis_message_id") or "")
        if message_id:
            await self._client.xack(
                ADVICE_STREAM_KEY, ADVICE_GROUP_NAME, message_id
            )

    @staticmethod
    def _decode(message_id: Any, fields: Mapping[Any, Any]) -> dict[str, Any]:
        payload = json.loads(_text(_field(fields, "data")) or "{}")
        payload["_redis_message_id"] = str(_text(message_id))
        return payload

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "aclose"):
            await self._client.aclose()
        self._client = None
        self._initialized = False


__all__ = [
    "ADVICE_DEAD_LETTER_KEY",
    "ADVICE_GROUP_NAME",
    "ADVICE_STREAM_KEY",
    "RedisAdviceQueue",
]
