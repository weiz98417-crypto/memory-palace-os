from __future__ import annotations

import json
import time

import httpx
import pytest

from tests.integration.test_scenic_api import build_app, login

pytestmark = pytest.mark.asyncio


async def _seed_retrieval(
    database,
    *,
    venue_id: str,
    query: str,
    incident_id: str,
    created_at: float,
    suffix: str,
) -> str:
    command_id = f"gap-command-{suffix}"
    await database.execute(
        """
        INSERT INTO scenic_commands (
            id, venue_id, command_type, idempotency_key, request_hash,
            status, request_json, response_json, created_at, updated_at
        ) VALUES (?, ?, 'RETRIEVE_SOP', ?, ?, 'SUCCEEDED', ?, ?, ?, ?)
        """,
        (
            command_id,
            venue_id,
            f"gap-key-{suffix}",
            f"hash-{suffix}",
            json.dumps(
                {
                    "type": "RETRIEVE_SOP",
                    "payload": {"incident_id": incident_id, "query": query},
                }
            ),
            json.dumps(
                {
                    "hits": [],
                    "evidence_status": "NO_EVIDENCE",
                    "missing_reason": "NO_VERIFIED_SOP",
                }
            ),
            created_at,
            created_at,
        ),
    )
    return command_id


async def test_gaps_aggregate_facts_are_role_gated_tenant_scoped_and_reopen(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        now = time.time()
        await _seed_retrieval(
            database,
            venue_id="venue-scenic",
            query="雨后  轮组异响！",
            incident_id="incident-a",
            created_at=now - 2,
            suffix="a",
        )
        await _seed_retrieval(
            database,
            venue_id="venue-scenic",
            query="雨后 轮组异响",
            incident_id="incident-b",
            created_at=now - 1,
            suffix="b",
        )
        await _seed_retrieval(
            database,
            venue_id="venue-other",
            query="雨后 轮组异响",
            incident_id="incident-other",
            created_at=now,
            suffix="other",
        )

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            manager = await login(client, "wangfang")
            operator = await login(client, "liming")

            forbidden = await client.get("/scenic/knowledge-gaps", headers=operator)
            assert forbidden.status_code == 403

            listed = await client.get("/scenic/knowledge-gaps", headers=manager)
            assert listed.status_code == 200, listed.text
            payload = listed.json()
            assert payload["total"] == 1
            gap = payload["items"][0]
            assert gap["status"] == "OPEN"
            assert gap["occurrence_count"] == 2
            assert set(gap["incident_ids"]) == {"incident-a", "incident-b"}
            gap_id = gap["gap_id"]

            forbidden_write = await client.post(
                f"/scenic/knowledge-gaps/{gap_id}/acknowledge",
                headers={**operator, "Idempotency-Key": "gap-forbidden-1"},
            )
            assert forbidden_write.status_code == 403

            acknowledged = await client.post(
                f"/scenic/knowledge-gaps/{gap_id}/acknowledge",
                headers={**manager, "Idempotency-Key": "gap-ack-1"},
            )
            assert acknowledged.status_code == 200, acknowledged.text
            assert acknowledged.json()["status"] == "ACKNOWLEDGED"

            resolved = await client.post(
                f"/scenic/knowledge-gaps/{gap_id}/resolve",
                headers={**manager, "Idempotency-Key": "gap-resolve-1"},
                json={"resolution_type": "NEW_SOP", "note": "已补轮胎异常 SOP"},
            )
            assert resolved.status_code == 200, resolved.text
            assert resolved.json()["status"] == "RESOLVED"

            blocked_acknowledge = await client.post(
                f"/scenic/knowledge-gaps/{gap_id}/acknowledge",
                headers={**manager, "Idempotency-Key": "gap-ack-after-resolve"},
            )
            assert blocked_acknowledge.status_code == 409

            await _seed_retrieval(
                database,
                venue_id="venue-scenic",
                query="雨后 轮组异响",
                incident_id="incident-c",
                created_at=time.time() + 60,
                suffix="c",
            )
            reopened = await client.get(
                f"/scenic/knowledge-gaps/{gap_id}", headers=manager
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["status"] == "REOPENED"
            assert reopened.json()["occurrence_count"] == 3

            manual_reopen = await client.post(
                f"/scenic/knowledge-gaps/{gap_id}/reopen",
                headers={**manager, "Idempotency-Key": "gap-reopen-1"},
            )
            assert manual_reopen.status_code == 200, manual_reopen.text
            assert manual_reopen.json()["status"] == "OPEN"

        annotation = await database.fetch_one(
            "SELECT * FROM scenic_knowledge_gap_annotations WHERE gap_id = ?", (gap_id,)
        )
        assert annotation is not None
        assert annotation["status"] == "OPEN"
        audits = await database.fetch_all(
            "SELECT action FROM audit_logs WHERE resource_id = ? ORDER BY created_at", (gap_id,)
        )
        assert {row["action"] for row in audits} == {
            "SCENIC_KNOWLEDGE_GAP_ACKNOWLEDGED",
            "SCENIC_KNOWLEDGE_GAP_RESOLVED",
            "SCENIC_KNOWLEDGE_GAP_REOPENED",
        }
        resolved_audit = await database.fetch_one(
            """
            SELECT metadata_json FROM audit_logs
            WHERE resource_id = ? AND action = 'SCENIC_KNOWLEDGE_GAP_RESOLVED'
            """,
            (gap_id,),
        )
        resolution_metadata = json.loads(resolved_audit["metadata_json"])
        assert resolution_metadata["resolution_type"] == "NEW_SOP"
        assert resolution_metadata["resolution_note"] == "已补轮胎异常 SOP"
        assert resolution_metadata["previous_status"] == "ACKNOWLEDGED"
    finally:
        await database.close()


async def test_topic_governance_supports_assign_rename_merge_split_and_audit(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        now = time.time()
        await _seed_retrieval(
            database,
            venue_id="venue-scenic",
            query="轮组异响",
            incident_id="incident-wheel",
            created_at=now,
            suffix="wheel",
        )
        await _seed_retrieval(
            database,
            venue_id="venue-scenic",
            query="东门分流",
            incident_id="incident-crowd",
            created_at=now,
            suffix="crowd",
        )
        await database.execute(
            """
            INSERT INTO scenic_knowledge_gap_topics (
                id, venue_id, name, status, created_by, created_at, updated_at
            ) VALUES ('other-topic', 'venue-other', '其它场地主题', 'ACTIVE',
                      'other-user', ?, ?)
            """,
            (now, now),
        )

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            manager = await login(client, "wangfang")
            gaps = (await client.get("/scenic/knowledge-gaps", headers=manager)).json()["items"]
            wheel_gap = next(item for item in gaps if item["normalized_query"] == "轮组异响")
            crowd_gap = next(item for item in gaps if item["normalized_query"] == "东门分流")

            topic_a = await client.post(
                "/scenic/knowledge-topics",
                headers={**manager, "Idempotency-Key": "topic-a-0001"},
                json={"name": "车辆知识"},
            )
            topic_b = await client.post(
                "/scenic/knowledge-topics",
                headers={**manager, "Idempotency-Key": "topic-b-0001"},
                json={"name": "现场处置"},
            )
            assert topic_a.status_code == 200, topic_a.text
            assert topic_b.status_code == 200, topic_b.text
            topic_a_id = topic_a.json()["topic_id"]
            topic_b_id = topic_b.json()["topic_id"]

            assigned = await client.post(
                f"/scenic/knowledge-topics/{topic_a_id}/assign",
                headers={**manager, "Idempotency-Key": "topic-assign-a-0001"},
                json={"gap_id": wheel_gap["gap_id"]},
            )
            assert assigned.status_code == 200, assigned.text

            renamed = await client.post(
                f"/scenic/knowledge-topics/{topic_a_id}/rename",
                headers={**manager, "Idempotency-Key": "topic-rename-a-0001"},
                json={"name": "车辆与轮胎知识"},
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["name"] == "车辆与轮胎知识"

            merged = await client.post(
                f"/scenic/knowledge-topics/{topic_a_id}/merge",
                headers={**manager, "Idempotency-Key": "topic-merge-a-0001"},
                json={"target_topic_id": topic_b_id},
            )
            assert merged.status_code == 200, merged.text
            assert merged.json()["status"] == "MERGED"
            assert merged.json()["merged_into_topic_id"] == topic_b_id

            await client.post(
                "/scenic/knowledge-topics",
                headers={**manager, "Idempotency-Key": "topic-existing-split-name"},
                json={"name": "轮胎专项"},
            )
            conflicting_split = await client.post(
                f"/scenic/knowledge-topics/{topic_b_id}/split",
                headers={**manager, "Idempotency-Key": "topic-split-conflict"},
                json={"name": "轮胎专项", "gap_ids": [wheel_gap["gap_id"]]},
            )
            assert conflicting_split.status_code == 409

            split = await client.post(
                f"/scenic/knowledge-topics/{topic_b_id}/split",
                headers={**manager, "Idempotency-Key": "topic-split-b-0001"},
                json={"name": "轮胎专项-新", "gap_ids": [wheel_gap["gap_id"]]},
            )
            assert split.status_code == 200, split.text
            split_topic_id = split.json()["topic_id"]

            topics = (await client.get("/scenic/knowledge-topics", headers=manager)).json()
            by_id = {item["topic_id"]: item for item in topics["items"]}
            assert "other-topic" not in by_id
            assert by_id[topic_a_id]["status"] == "MERGED"
            assert by_id[split_topic_id]["member_count"] == 1
            assert by_id[topic_b_id]["member_count"] == 0
            assert by_id[split_topic_id]["name"] == "轮胎专项-新"

            crowd_assignment = await client.post(
                f"/scenic/knowledge-topics/{topic_b_id}/assign",
                headers={**manager, "Idempotency-Key": "topic-assign-b-0001"},
                json={"gap_id": crowd_gap["gap_id"]},
            )
            assert crowd_assignment.status_code == 200, crowd_assignment.text

        actions = await database.fetch_all(
            "SELECT action FROM audit_logs WHERE resource_type IN ('scenic_knowledge_gap_topic', 'scenic_knowledge_gap') ORDER BY created_at"
        )
        action_names = {row["action"] for row in actions}
        assert "SCENIC_KNOWLEDGE_TOPIC_RENAMED" in action_names
        assert "SCENIC_KNOWLEDGE_TOPICS_MERGED" in action_names
        assert "SCENIC_KNOWLEDGE_TOPIC_SPLIT" in action_names
        assert "SCENIC_KNOWLEDGE_GAP_ASSIGNED" in action_names
    finally:
        await database.close()