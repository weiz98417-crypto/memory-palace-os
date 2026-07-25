"""Message queue protocol for backend switching (Redis Streams / asyncio.Queue)."""
from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class MessageQueueProtocol(Protocol):
    """Async message queue interface (put, get, task_done, qsize, empty)."""

    async def put(self, message: Dict[str, Any]) -> None:
        ...

    async def get(self) -> Dict[str, Any]:
        ...

    def task_done(self) -> None:
        ...

    def qsize(self) -> int:
        ...

    def empty(self) -> bool:
        ...
