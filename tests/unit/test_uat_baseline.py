from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from src.memory_palace.operations.uat_baseline import collect_uat_baseline_snapshot


class _BaselineSnapshot:
    async def fetch_one(self, sql: str, parameters: tuple = ()):
        if "FROM venues" in sql:
            return {
                "id": parameters[0],
                "name": "悦山景区",
                "status": "ACTIVE",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        if "COUNT(*)" in sql:
            return {"count": 0}
        return None

    async def fetch_all(self, sql: str, parameters: tuple = ()):
        if "FROM system_settings" in sql:
            return [
                {
                    "setting_key": "organization_name",
                    "setting_value": "悦山文旅集团",
                    "value_type": "string",
                    "updated_at": 1.0,
                }
            ]
        return []


class _SnapshotDatabase:
    @asynccontextmanager
    async def read_snapshot(self):
        yield _BaselineSnapshot()


@pytest.mark.asyncio
async def test_uat_process_counts_exclude_sop_knowledge_index() -> None:
    snapshot = await collect_uat_baseline_snapshot(
        _SnapshotDatabase(),
        venue_id="venue-yueshan",
    )

    assert "knowledge_documents" not in snapshot["process_counts"]
    assert "non_sop_knowledge_documents" in snapshot["process_counts"]
    assert "knowledge_retrieval_snapshots" in snapshot["process_counts"]
