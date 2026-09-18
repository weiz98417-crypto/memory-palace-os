"""HTTP entry point for the scenic Agent trunk (ticket m4-02)."""

from __future__ import annotations

import pytest

from src.memory_palace.agent_contracts.models import AgentRole
from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.scenic.advice_runs import (
    AdviceRunRepository,
    AdviceWorker,
    InMemoryAdviceQueue,
)
from tests.integration.test_scenic_api import build_app, login
from tests.unit.test_incident_command import (
    Registry,
    ScriptedAgent,
    _advice,
    _context,
    _routing,
)

pytestmark = pytest.mark.asyncio


def _trunk(database) -> PydanticAIIncidentCommand:
    agents = {
        AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
        AgentRole.ROUTER: ScriptedAgent([_routing()]),
        AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
        AgentRole.COMMANDER: ScriptedAgent([_advice()]),
    }
    return PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=LLMCallLogRecorder(database),
        config=IncidentCommandConfig(),
    )


def _advice_runtime(app, database):
    repository = AdviceRunRepository(database)
    queue = InMemoryAdviceQueue()
    command = _trunk(database)
    app.state.incident_command = command
    app.state.advice_repository = repository
    app.state.advice_queue = queue
    app.state.advice_worker = AdviceWorker(
        repository=repository,
        queue=queue,
        incident_command=command,
        sink=app.state.scenic_operations.advice_sink,
    )
    app.state.scenic_operations.advice_repository = repository
    return repository


async def _open_incident(client, operations_headers, manager_headers):
    prepared = await client.post(
        "/operations/scenic/commands",
        headers={**operations_headers, "Idempotency-Key": "trunk-prepare"},
        json={"kind": "PREPARE_SCENARIO", "payload": {}},
    )
    assert prepared.status_code == 200, prepared.text
    stepped = await client.post(
        "/operations/scenic/commands",
        headers={**operations_headers, "Idempotency-Key": "trunk-step"},
        json={"kind": "CLOCK_STEP", "payload": {"seconds": 2}},
    )
    assert stepped.status_code == 200, stepped.text
    situation = (await client.get("/scenic/snapshot", headers=manager_headers)).json()
    alert = next(
        item
        for item in situation["alerts"]
        if item["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL"
    )
    converted = await client.post(
        "/scenic/commands",
        headers={**manager_headers, "Idempotency-Key": "trunk-convert"},
        json={"kind": "CONVERT_ALERT", "payload": {"alert_ids": [alert["id"]]}},
    )
    assert converted.status_code == 200, converted.text
    return converted.json()["incident_id"]


async def _add_verified_hit(database, incident) -> None:
    await database.execute(
        """
        INSERT INTO scenic_knowledge_hits (
            id, venue_id, incident_id, query_text, vector_doc_id,
            source_type, source_id, source_version, score, backend,
            model_name, dimension, recorded_at, idempotency_key
        ) VALUES (?, ?, ?, ?, ?, 'SOP', '1', '1.0', 0.81,
            'postgresql_pgvector', 'BAAI/bge-m3', 1024, ?, ?)
        """,
        (
            f"hit-{incident['incident_id']}",
            incident["venue_id"],
            incident["incident_id"],
            "\u8f66\u8f6e\u5f02\u54cd",
            f"sop:{incident['venue_id']}:1",
            1785283200.0,
            f"hit-{incident['incident_id']}",
        ),
    )


async def test_advice_endpoint_returns_grounded_advice_and_writes_call_records(
    tmp_path, monkeypatch
):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        import httpx

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            incident_id = await _open_incident(
                client, operations_headers, manager_headers
            )
            incident = await database.fetch_one(
                "SELECT * FROM scenic_incidents WHERE incident_id = ?",
                (incident_id,),
            )
            await _add_verified_hit(database, incident)

            queued = await client.post(
                f"/scenic/incidents/{incident_id}/advice",
                headers=manager_headers,
            )
            assert queued.status_code == 200, queued.text
            run_id = queued.json()["advice_run_id"]
            assert queued.json()["state"] == "PENDING"

            pending = await client.get(
                f"/scenic/incidents/{incident_id}/advice/{run_id}",
                headers=manager_headers,
            )
            assert pending.status_code == 200
            assert pending.json()["state"] == "PENDING"

            processed = await client.post(
                "/operations/scenic/advice-runs/process",
                headers=operations_headers,
            )
            assert processed.status_code == 200, processed.text
            assert processed.json()["processed"] == [
                {
                    "advice_run_id": run_id,
                    "incident_id": incident_id,
                    "state": "READY",
                }
            ]

            run_response = await client.get(
                f"/scenic/incidents/{incident_id}/advice/{run_id}",
                headers=manager_headers,
            )
            snapshot = await client.get("/scenic/snapshot", headers=manager_headers)

        assert run_response.status_code == 200, run_response.text
        run = run_response.json()
        assert run["state"] == "READY"
        result = run["result"]
        assert result["mode"] == "ADVICE"
        assert result["outcome"] == "READY"
        assert result["advice"]["evidence_status"] == "GROUNDED"
        assert result["advice"]["citations"][0]["source_id"] == "1"
        assert result["advice"]["citations"][0]["rerank_score"] == 0.94
        assert result["degradations"] == []
        assert sorted(ref["agent_id"] for ref in result["call_refs"]) == [
            "ContextTrigger",
            "MemoryOps",
            "Router",
        ]

        projected = snapshot.json()["incidents"][0]["advice"]
        assert projected["status"] == "READY"
        assert projected["run_id"] == run_id

        rows = await database.fetch_all(
            "SELECT * FROM llm_call_logs WHERE trace_id = ? ORDER BY agent_id",
            (result["trace_id"],),
        )
        assert len(rows) == 3
        assert {row["agent_id"] for row in rows} == {
            "ContextTrigger",
            "Router",
            "MemoryOps",
        }
        assert all(bool(row["is_mock"]) is False for row in rows)
    finally:
        await database.close()


async def test_advice_endpoint_refuses_operators(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        import httpx

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            operator_headers = await login(client, "liming")
            incident_id = await _open_incident(
                client, operations_headers, manager_headers
            )
            response = await client.post(
                f"/scenic/incidents/{incident_id}/advice",
                headers=operator_headers,
            )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "SCENIC_ADVICE_ROLE_REQUIRED"
    finally:
        await database.close()


async def test_proceed_without_waiting_supersedes_and_keeps_the_late_result(
    tmp_path, monkeypatch
):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        import httpx

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            incident_id = await _open_incident(
                client, operations_headers, manager_headers
            )
            incident = await database.fetch_one(
                "SELECT * FROM scenic_incidents WHERE incident_id = ?",
                (incident_id,),
            )
            await _add_verified_hit(database, incident)
            queued = await client.post(
                f"/scenic/incidents/{incident_id}/advice",
                headers=manager_headers,
            )
            assert queued.status_code == 200, queued.text
            run_id = queued.json()["advice_run_id"]

            decided = await client.post(
                "/scenic/commands",
                headers={
                    **manager_headers,
                    "Idempotency-Key": "http-proceed-without-waiting",
                },
                json={
                    "kind": "DECIDE_ADVICE",
                    "payload": {
                        "incident_id": incident_id,
                        "advice_run_id": run_id,
                        "decision": "PROCEED_WITHOUT_WAITING",
                        "reason_code": "HUMAN_JUDGMENT",
                        "reason_text": "????????????",
                    },
                },
            )
            assert decided.status_code == 200, decided.text
            assert decided.json()["superseded"] is True
            assert decided.json()["advice_state"] == "SUPERSEDED"

            processed = await client.post(
                "/operations/scenic/advice-runs/process",
                headers=operations_headers,
            )
            assert processed.status_code == 200, processed.text
            assert processed.json()["processed"] == [
                {
                    "advice_run_id": run_id,
                    "incident_id": incident_id,
                    "state": "SUPERSEDED",
                }
            ]

            run_response = await client.get(
                f"/scenic/incidents/{incident_id}/advice/{run_id}",
                headers=manager_headers,
            )
            events = await database.fetch_all(
                "SELECT event_type FROM scenic_situation_events "
                "WHERE event_type LIKE 'ADVICE_%' ORDER BY sequence"
            )

        assert run_response.status_code == 200
        run = run_response.json()
        assert run["state"] == "SUPERSEDED"
        assert run["result"]["late_result"]["advice"]["evidence_status"] == "GROUNDED"
        # ADVICE_READY carries state=SUPERSEDED on the decision event, per the SSE
        # contract table in docs/architecture/incident-command-contract.md.
        event_types = [row["event_type"] for row in events]
        assert event_types[0] == "ADVICE_PENDING"
        assert "ADVICE_READY" in event_types
        assert "ADVICE_FAILED" not in event_types
    finally:
        await database.close()


async def test_adopt_requires_ready_grounded_advice(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        import httpx

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            incident_id = await _open_incident(
                client, operations_headers, manager_headers
            )
            queued = await client.post(
                f"/scenic/incidents/{incident_id}/advice",
                headers=manager_headers,
            )
            run_id = queued.json()["advice_run_id"]

            rejected = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-adopt-too-early"},
                json={
                    "kind": "DECIDE_ADVICE",
                    "payload": {
                        "incident_id": incident_id,
                        "advice_run_id": run_id,
                        "decision": "ADOPT",
                    },
                },
            )
            assert rejected.status_code == 409

            await client.post(
                "/operations/scenic/advice-runs/process",
                headers=operations_headers,
            )
            accepted = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-adopt-ready"},
                json={
                    "kind": "DECIDE_ADVICE",
                    "payload": {
                        "incident_id": incident_id,
                        "advice_run_id": run_id,
                        "decision": "ADOPT",
                    },
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["decision"] == "ADOPT"
            assert accepted.json()["superseded"] is False
    finally:
        await database.close()
