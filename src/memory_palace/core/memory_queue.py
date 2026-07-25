"""In-memory asyncio.Queue adapter implementing MessageQueueProtocol for DEMO_MODE."""
import asyncio
from typing import Any, Dict


class InMemoryQueue:
    """Wraps asyncio.Queue to implement MessageQueueProtocol."""

    def __init__(self, maxsize: int = 10000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, message: Dict[str, Any]) -> None:
        await self._queue.put(message)

    async def get(self) -> Dict[str, Any]:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()
