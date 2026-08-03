"""
PostgreSQL async database client using asyncpg.
Implements the same interface as AsyncDBClient (fetch_one, fetch_all, execute, close)
so the DI container can swap backends transparently.
"""
import os
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import asyncpg
from loguru import logger


def _rowcount(result: str) -> int:
    try:
        return int(result.split()[-1]) if result else 0
    except (ValueError, IndexError):
        return 0


class _PostgresTransaction:
    """Database interface bound to one asyncpg transaction connection."""

    def __init__(self, connection: asyncpg.Connection):
        self._connection = connection

    async def execute(self, sql: str, parameters: tuple = ()) -> int:
        sql, params = PostgresDBClient._translate(sql, parameters)
        return _rowcount(await self._connection.execute(sql, *params))

    async def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[Dict[str, Any]]:
        sql, params = PostgresDBClient._translate(sql, parameters)
        row = await self._connection.fetchrow(sql, *params)
        return dict(row) if row else None

    async def fetch_all(self, sql: str, parameters: tuple = ()) -> List[Dict[str, Any]]:
        sql, params = PostgresDBClient._translate(sql, parameters)
        rows = await self._connection.fetch(sql, *params)
        return [dict(row) for row in rows]


class PostgresDBClient:
    """PostgreSQL client with asyncpg connection pool."""

    backend_name = "postgresql"

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "postgresql://localhost:5432/memory_palace")
        self._pool: Optional[asyncpg.Pool] = None

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            password = os.environ.get("PGPASSWORD")
            self._pool = await asyncpg.create_pool(
                self.dsn,
                password=password or None,
                min_size=5,
                max_size=20,
                command_timeout=30,
            )
            logger.info(f"PostgreSQL 连接池已创建: {self.dsn.split('@')[-1] if '@' in self.dsn else self.dsn}")
        return self._pool

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def execute(self, sql: str, parameters: tuple = ()) -> int:
        pool = await self._ensure_pool()
        sql, params = self._translate(sql, parameters)
        async with pool.acquire() as conn:
            result = await conn.execute(sql, *params)
            return _rowcount(result)

    async def fetch_one(self, sql: str, parameters: tuple = ()) -> Optional[Dict[str, Any]]:
        pool = await self._ensure_pool()
        sql, params = self._translate(sql, parameters)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return dict(row) if row else None

    async def fetch_all(self, sql: str, parameters: tuple = ()) -> List[Dict[str, Any]]:
        pool = await self._ensure_pool()
        sql, params = self._translate(sql, parameters)
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    @asynccontextmanager
    async def transaction(self):
        """Yield the database interface bound to one asyncpg transaction."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield _PostgresTransaction(conn)

    @asynccontextmanager
    async def read_snapshot(self):
        """Yield one read-only repeatable-read PostgreSQL snapshot."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                yield _PostgresTransaction(conn)

    @staticmethod
    def _translate(sql: str, params: tuple) -> tuple[str, tuple]:
        """Translate SQLite ? placeholders to PostgreSQL $1, $2, ..."""
        if '?' not in sql:
            return sql, params
        count = 0

        def replacer(match):
            nonlocal count
            count += 1
            return f"${count}"

        translated = re.sub(r'\?', replacer, sql)
        return translated, params
