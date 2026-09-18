"""Redis Streams notification Adapter with PostgreSQL replay semantics."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from loguru import logger


class RedisSituationBus:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._client = None
        self._available = True

    async def _connection(self):
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self.url, decode_responses=True)
        return self._client

    @staticmethod
    def stream_name(venue_id: str) -> str:
        return f"memory-palace:scenic:situation:{venue_id}"

    async def publish(self, event: dict[str, Any]) -> None:
        try:
            client = await self._connection()
            await client.xadd(
                self.stream_name(str(event["venue_id"])),
                {
                    "sequence": str(event["sequence"]),
                    "event": json.dumps(event, ensure_ascii=False, sort_keys=True),
                },
                maxlen=10000,
                approximate=True,
            )
            self._available = True
        except Exception as exc:
            self._available = False
            logger.warning("scenic Redis publish unavailable; SSE will poll PostgreSQL: {}", exc)

    async def wait(self, venue_id: str, last_stream_id: str, timeout_ms: int = 15000) -> str:
        try:
            client = await self._connection()
            messages = await client.xread(
                {self.stream_name(venue_id): last_stream_id},
                count=1,
                block=timeout_ms,
            )
            self._available = True
            if not messages or not messages[0][1]:
                return last_stream_id
            return str(messages[0][1][-1][0])
        except Exception as exc:
            self._available = False
            logger.warning("scenic Redis wait unavailable; SSE will poll PostgreSQL: {}", exc)
            await asyncio.sleep(min(timeout_ms / 1000, 1.0))
            return last_stream_id

    async def health(self) -> dict[str, Any]:
        try:
            client = await self._connection()
            await client.ping()
            self._available = True
        except Exception as exc:
            self._available = False
            return {"status": "degraded", "backend": "redis_streams", "error_type": type(exc).__name__}
        return {"status": "healthy", "backend": "redis_streams"}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class ScenicSimulationRuntime:
    """Drive playing simulation clocks using a one-second wall-clock tick."""

    def __init__(self, operations) -> None:
        self.operations = operations
        self._task = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="scenic-simulation-clock")

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.operations.advance_playing_clocks()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("scenic simulation tick failed: {}", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            await self._task
            self._task = None
