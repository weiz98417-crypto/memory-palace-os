from __future__ import annotations

import json
import os
import time
import uuid

import pytest

from src.memory_palace.knowledge.postgres_client import PostgresDBClient
from src.memory_palace.scenic.knowledge_gaps import KnowledgeGapRepository
from src.memory_palace.scenic.schema import init_scenic_schema

pytestmark = pytest.mark.asyncio

DSN = os.environ.get("SCENIC_TEST_POSTGRES_DSN")
if not DSN:
    pytest.skip(
        "SCENIC_TEST_POSTGRES_DSN is required for the PostgreSQL fact-source test",
        allow_module_level=True,
    )


async def test_knowledge_gap_repository_on_postgres_facts(tmp_path):
    database = PostgresDBClient(DSN)
    venue_id = f"venue-gap-pg-{uuid.uuid4().hex[:12]}"
    now = time.time()
    try:
        await init_scenic_schema(database)
        for suffix in ("one", "two"):
            await database.execute(
                """
                INSERT INTO scenic_commands (
                    id, venue_id, command_type, idempotency_key, request_hash,
                    status, request_json, response_json, created_at, updated_at
                ) VALUES (?, ?, 'RETRIEVE_SOP', ?, ?, 'SUCCEEDED', ?, ?, ?, ?)
                """,
                (
                    f"pg-gap-{suffix}",
                    venue_id,
                    f"pg-gap-key-{suffix}",
                    f"pg-gap-hash-{suffix}",
                    json.dumps(
                        {
                            "type": "RETRIEVE_SOP",
                            "payload": {
                                "incident_id": f"incident-{suffix}",
                                "query": "雨后  轮组异响！",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "hits": [],
                            "evidence_status": "NO_EVIDENCE",
                            "missing_reason": "NO_VERIFIED_SOP",
                        }
                    ),
                    now,
                    now,
                ),
            )

        repository = KnowledgeGapRepository(database)
        gaps = await repository.list_gaps(venue_id=venue_id)
        assert len(gaps) == 1
        assert gaps[0]["occurrence_count"] == 2
        gap_id = gaps[0]["gap_id"]

        acknowledged = await repository.acknowledge(
            venue_id=venue_id,
            gap_id=gap_id,
            actor_id="pg-manager",
            trace_id="pg-ack",
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        resolved = await repository.resolve(
            venue_id=venue_id,
            gap_id=gap_id,
            resolution_type="NEW_SOP",
            note="PostgreSQL resolution",
            actor_id="pg-manager",
            trace_id="pg-resolve",
        )
        assert resolved["status"] == "RESOLVED"

        topic = await repository.create_topic(
            venue_id=venue_id,
            name="PostgreSQL topic",
            actor_id="pg-manager",
            trace_id="pg-topic",
        )
        await repository.assign_gap(
            venue_id=venue_id,
            topic_id=topic["topic_id"],
            gap_id=gap_id,
            actor_id="pg-manager",
            trace_id="pg-assign",
        )
        assert (await repository.list_topics(venue_id=venue_id))[0]["member_count"] == 1
    finally:
        await database.execute(
            "DELETE FROM scenic_knowledge_gap_topic_members WHERE venue_id = ?",
            (venue_id,),
        )
        await database.execute(
            "DELETE FROM scenic_knowledge_gap_topics WHERE venue_id = ?", (venue_id,)
        )
        await database.execute(
            "DELETE FROM scenic_knowledge_gap_annotations WHERE venue_id = ?",
            (venue_id,),
        )
        await database.execute(
            "DELETE FROM scenic_commands WHERE venue_id = ?", (venue_id,)
        )
        await database.close()