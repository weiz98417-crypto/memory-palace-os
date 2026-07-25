"""
Database client protocol — defines the interface both PostgresDBClient and
SQLiteDBClient must implement. Used by the DI container to dispatch backends.
"""
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class AsyncDBClientProtocol(Protocol):
    """Async database client interface (fetch_one, fetch_all, execute, transaction, close)."""

    async def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[Dict[str, Any]]:
        ...

    async def fetch_all(self, sql: str, parameters: tuple = ()) -> list[Dict[str, Any]]:
        ...

    async def execute(self, sql: str, parameters: tuple = ()) -> int:
        ...

    async def close(self) -> None:
        ...
