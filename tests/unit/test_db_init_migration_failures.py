import sqlite3

import pytest

from src.memory_palace.knowledge import db_init
from src.memory_palace.knowledge.db_client import AsyncDBClient


@pytest.mark.asyncio
async def test_sqlite_initialization_propagates_non_duplicate_column_migration_errors(
    tmp_path,
    monkeypatch,
):
    database = AsyncDBClient(tmp_path / "failed-column-migration.db")
    original_execute = db_init.aiosqlite.Connection.execute

    async def fail_one_column_migration(connection, sql, parameters=None):
        if "ALTER TABLE sessions ADD COLUMN agent_name" in sql:
            raise sqlite3.OperationalError("disk I/O error")
        if parameters is None:
            return await original_execute(connection, sql)
        return await original_execute(connection, sql, parameters)

    monkeypatch.setattr(
        db_init.aiosqlite.Connection,
        "execute",
        fail_one_column_migration,
    )

    try:
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            await db_init.init_database(database)
    finally:
        await database.close()
