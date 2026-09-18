import pytest

from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


class RecordingPostgresDatabase:
    def __init__(self):
        self._pool = object()
        self.statements = []

    async def execute(self, sql, parameters=()):
        self.statements.append(sql)
        return 0

    async def fetch_all(self, sql, parameters=()):
        return []

    async def fetch_one(self, sql, parameters=()):
        if "pg_extension" in sql:
            return {"extversion": "0.8.1"}
        if "vector_index_versions" in sql:
            return {
                "index_name": "knowledge_vectors_bge_m3_v1",
                "model_name": "BAAI/bge-m3",
                "model_version": "local-bge-m3-1024-v1",
                "dimension": 1024,
                "status": "READY",
            }
        return None


@pytest.mark.asyncio
async def test_sqlite_initialization_creates_retrieval_snapshot_table_and_indexes(tmp_path):
    database = AsyncDBClient(tmp_path / "retrieval-schema.db")
    await init_database(database)

    try:
        columns = await database.fetch_all(
            "PRAGMA table_info('knowledge_retrieval_snapshots')"
        )
        indexes = await database.fetch_all(
            "PRAGMA index_list('knowledge_retrieval_snapshots')"
        )

        assert {column["name"] for column in columns} >= {
            "id",
            "venue_id",
            "trace_id",
            "message_id",
            "attempts_json",
            "references_json",
            "status",
            "latency_ms",
        }
        assert {index["name"] for index in indexes} >= {
            "idx_knowledge_retrieval_trace",
            "idx_knowledge_retrieval_message",
        }
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_postgres_initialization_declares_retrieval_snapshot_table_and_indexes():
    database = RecordingPostgresDatabase()

    await init_database(database)

    statements = "\n".join(database.statements)
    assert "CREATE TABLE IF NOT EXISTS knowledge_retrieval_snapshots" in statements
    assert "similarity_threshold DOUBLE PRECISION NOT NULL" in statements
    assert (
        "idx_knowledge_retrieval_trace ON "
        "knowledge_retrieval_snapshots(venue_id, trace_id, started_at)"
    ) in statements
    assert (
        "idx_knowledge_retrieval_message ON "
        "knowledge_retrieval_snapshots(venue_id, message_id, started_at)"
    ) in statements
