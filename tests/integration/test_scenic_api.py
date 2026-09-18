import time

import httpx
import pytest
from fastapi import FastAPI

from src.memory_palace.api.v1.endpoints.auth import router as auth_router
from src.memory_palace.api.v1.endpoints.admin import router as admin_router
from src.memory_palace.api.v1.endpoints.assistant import router as assistant_router
from src.memory_palace.api.v1.endpoints.attachments import router as attachments_router
from src.memory_palace.api.v1.endpoints.channels import router as channels_router
from src.memory_palace.api.v1.endpoints.scenic import router as scenic_router
from src.memory_palace.api.v1.endpoints.scenic import scenic_stream
from src.memory_palace.core.attachments import LocalAttachmentStore
from src.memory_palace.core.event_activities import append_event_activity
from src.memory_palace.core.permissions import PermissionEngine
from src.memory_palace.core.task_graph import TaskGraph
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.scenic.operations import Actor, Command, ScenicAreaOperations

from tests.integration.test_scenic_area_operations import VectorStoreStub


async def build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_PALACE_JWT_SECRET", "scenic-test-jwt-secret-longer-than-thirty-two")
    database = AsyncDBClient(tmp_path / "scenic-api.db")
    await init_database(database)
    operations = ScenicAreaOperations(
        database=database,
        vector_store=VectorStoreStub(),
        task_graph=TaskGraph(database),
        permission_engine=PermissionEngine(database),
    )
    await operations.bootstrap(
        venue_id="venue-scenic",
        venue_name="云栖山景区",
        account_password="Scenic-Local-2026!",
    )
    app = FastAPI()
    app.state.db_client = database
    app.state.scenic_operations = operations
    app.state.task_graph = operations.task_graph
    app.state.attachment_store = LocalAttachmentStore(tmp_path / "attachments")
    app.include_router(auth_router, prefix="/auth")
    app.include_router(scenic_router)
    app.include_router(attachments_router)
    app.include_router(assistant_router)
    app.include_router(admin_router)
    app.include_router(channels_router)
    return app, database


async def login(client, username):
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "Scenic-Local-2026!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_input_controls_are_local_and_identity_protected(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            manager_headers = await login(client, "wangfang")
            operations_headers = await login(client, "simulation-ops")
            body = {"kind": "PREPARE_SCENARIO", "payload": {}}
            forbidden = await client.post(
                "/operations/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "manager-prepare"},
                json=body,
            )
            assert forbidden.status_code == 403
            hidden_from_business = await client.post(
                "/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "business-prepare"},
                json=body,
            )
            assert hidden_from_business.status_code == 403
            remote_transport = httpx.ASGITransport(app=app, client=("192.168.10.20", 32000))
            async with httpx.AsyncClient(transport=remote_transport, base_url="http://test") as remote:
                remote_headers = await login(remote, "simulation-ops")
                remote_prepare = await remote.post(
                    "/operations/scenic/commands",
                    headers={**remote_headers, "Idempotency-Key": "remote-prepare"},
                    json=body,
                )
                assert remote_prepare.status_code == 403
            prepared = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "ops-prepare-1"},
                json=body,
            )
            assert prepared.status_code == 200, prepared.text
            snapshot = await client.get("/scenic/snapshot", headers=manager_headers)
            assert snapshot.status_code == 200
            assert snapshot.json()["run"]["scenario_key"] == "rain_vehicle_east_gate"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_snapshot_returns_backend_owned_next_actions(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            operations_headers = await login(client, "simulation-ops")
            prepared = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "next-actions-prepare"},
                json={"kind": "PREPARE_SCENARIO", "payload": {}},
            )
            assert prepared.status_code == 200
            stepped = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "next-actions-step"},
                json={"kind": "CLOCK_STEP", "payload": {"seconds": 2}},
            )
            assert stepped.status_code == 200
            manager_headers = await login(client, "wangfang")
            snapshot = await client.get("/scenic/snapshot", headers=manager_headers)
            assert snapshot.status_code == 200
            payload = snapshot.json()

        assert payload["next_actions"][0]["code"] == "CONVERT_ALERT"
        assert payload["next_actions"][0]["action"] == {
            "type": "COMMAND",
            "kind": "CONVERT_ALERT",
            "payload": {"alert_ids": [payload["alerts"][0]["id"]]},
        }
        assert payload["advice"] is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_advice_decision_rejects_missing_reason_and_is_visible_in_snapshot(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        operations = app.state.scenic_operations
        ops = Actor("scenic-simulation-ops", "simulation-ops", "admin", "venue-scenic")
        manager = Actor("scenic-wangfang", "wangfang", "manager", "venue-scenic")
        await operations.execute(ops, Command("PREPARE_SCENARIO", {}, "advice-prepare"))
        await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 2}, "advice-step"))
        snapshot = await operations.snapshot(manager)
        incident = await operations.execute(
            manager,
            Command(
                "CONVERT_ALERT",
                {"alert_ids": [snapshot["alerts"][0]["id"]]},
                "advice-convert",
            ),
        )
        await append_event_activity(
            database,
            venue_id="venue-scenic",
            event_id=incident["event_id"],
            activity_type="ADVICE_PENDING",
            trace_id="a" * 32,
            payload={"advice_run_id": "advice-run-1", "state": "PENDING"},
            idempotency_key="advice-pending-1",
        )
        await append_event_activity(
            database,
            venue_id="venue-scenic",
            event_id=incident["event_id"],
            activity_type="ADVICE_READY",
            trace_id="a" * 32,
            payload={
                "advice_run_id": "advice-run-1",
                "state": "READY",
                "evidence_status": "GROUNDED",
                "advice": "继续停运并检查右后轮。",
                "citations": [{"source_id": "1", "title": "复运 SOP", "version": "1.0"}],
            },
            idempotency_key="advice-ready-1",
        )

        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            manager_headers = await login(client, "wangfang")
            visible = await client.get("/scenic/snapshot", headers=manager_headers)
            assert visible.status_code == 200
            advice = visible.json()["advice"]
            assert advice["run_id"] == "advice-run-1"
            assert advice["allowed_actions"] == ["ADOPT", "IGNORE"]

            missing_reason = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "advice-ignore-missing-reason"},
                json={
                    "kind": "DECIDE_ADVICE",
                    "payload": {
                        "incident_id": incident["incident_id"],
                        "advice_run_id": "advice-run-1",
                        "decision": "IGNORE",
                        "expected_state": "READY",
                    },
                },
            )
            assert missing_reason.status_code == 422

            decided = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "advice-ignore-valid"},
                json={
                    "kind": "DECIDE_ADVICE",
                    "payload": {
                        "incident_id": incident["incident_id"],
                        "advice_run_id": "advice-run-1",
                        "decision": "IGNORE",
                        "expected_state": "READY",
                        "reason_code": "HUMAN_JUDGMENT",
                    },
                },
            )
            assert decided.status_code == 200, decided.text
            final = await client.get("/scenic/snapshot", headers=manager_headers)
            assert final.json()["advice"]["decision"]["decision"] == "IGNORE"
    finally:
        await database.close()

async def test_reconnect_reads_ordered_postgres_events_after_last_sequence(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "ops-prepare-2"},
                json={"kind": "PREPARE_SCENARIO", "payload": {}},
            )
            initial = await client.get("/scenic/snapshot", headers=manager_headers)
            cursor = initial.json()["latest_sequence"]
            await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "ops-step-2"},
                json={"kind": "CLOCK_STEP", "payload": {"seconds": 2}},
            )
            recovered = await client.get(
                f"/scenic/events?after_sequence={cursor}", headers=manager_headers
            )
            sequences = [item["sequence"] for item in recovered.json()["events"]]
            assert sequences == list(range(cursor + 1, max(sequences) + 1))
            assert {item["event_type"] for item in recovered.json()["events"]} >= {
                "SIGNAL_RECORDED",
                "ALERT_CREATED",
            }
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_full_story_uses_real_http_business_routes_and_internal_outbox(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            operations_headers = await login(client, "simulation-ops")
            manager_headers = await login(client, "wangfang")
            reporter_headers = await login(client, "liming")
            technician_headers = await login(client, "chenyu")

            prepared = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "http-prepare-story"},
                json={"kind": "PREPARE_SCENARIO", "payload": {}},
            )
            assert prepared.status_code == 200, prepared.text
            stepped = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "http-step-fault"},
                json={"kind": "CLOCK_STEP", "payload": {"seconds": 2}},
            )
            assert stepped.status_code == 200, stepped.text
            situation = (await client.get("/scenic/snapshot", headers=manager_headers)).json()
            vehicle_alert = next(
                item
                for item in situation["alerts"]
                if item["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL"
            )

            converted = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-convert-alert"},
                json={"kind": "CONVERT_ALERT", "payload": {"alert_ids": [vehicle_alert["id"]]}},
            )
            assert converted.status_code == 200, converted.text
            incident_id = converted.json()["incident_id"]

            uploaded = await client.post(
                "/assistant/attachments",
                headers=reporter_headers,
                files={"file": ("wheel-12.png", b"\x89PNG\r\n\x1a\nfield-photo", "image/png")},
            )
            assert uploaded.status_code == 201, uploaded.text
            attachment = uploaded.json()["attachment"]
            assert attachment["scan_status"] == "PASSED"
            evidence = await client.post(
                "/scenic/commands",
                headers={**reporter_headers, "Idempotency-Key": "http-field-evidence"},
                json={
                    "kind": "ADD_EVIDENCE",
                    "payload": {
                        "incident_id": incident_id,
                        "text": "12 号观光车右后轮异响并振动，已设置停运标识。",
                        "attachment_id": attachment["attachment_id"],
                    },
                },
            )
            assert evidence.status_code == 200, evidence.text

            retrieval = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-retrieve-sop"},
                json={
                    "kind": "RETRIEVE_SOP",
                    "payload": {"incident_id": incident_id, "query": "雨后观光车复运检查和东门分流"},
                },
            )
            assert retrieval.status_code == 200, retrieval.text
            assert retrieval.json()["hits"][0]["source_type"] == "SOP"

            dispatched = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-create-repair"},
                json={"kind": "CREATE_REPAIR_TASK", "payload": {"incident_id": incident_id}},
            )
            assert dispatched.status_code == 200, dispatched.text
            repair_task = dispatched.json()["task"]
            assert repair_task["due_at"] is not None
            assert repair_task["result_schema_json"]["required"] == [
                "vehicle_12",
                "backup_vehicle_7",
                "inspection_items",
            ]

            forbidden = await client.post(
                f"/work/tasks/{repair_task['id']}/start", headers=reporter_headers
            )
            assert forbidden.status_code == 404
            approval_required = await client.post(
                f"/work/tasks/{repair_task['id']}/start", headers=technician_headers
            )
            assert approval_required.status_code == 409
            assert approval_required.json()["detail"]["code"] == "TASK_APPROVAL_REQUIRED"
            approved = await client.post(
                f"/approvals/{dispatched.json()['approval_id']}/approve",
                headers=manager_headers,
                json={"comment": "继续停运 12 号车并启用 7 号备用车辆"},
            )
            assert approved.status_code == 200, approved.text
            started = await client.post(
                f"/work/tasks/{repair_task['id']}/start", headers=technician_headers
            )
            assert started.status_code == 200, started.text
            completed = await client.post(
                f"/work/tasks/{repair_task['id']}/complete",
                headers=technician_headers,
                json={
                    "summary": "确认右后轮轴承异常，12 号车继续停运，7 号备用车检查合格。",
                    "result": {
                        "vehicle_12": "ISOLATED",
                        "backup_vehicle_7": "READY",
                        "inspection_items": ["右后轮", "制动", "底盘", "备用车辆"],
                    },
                },
            )
            assert completed.status_code == 200, completed.text

            repair_outbox = await client.get(
                "/simulator/sessions/scenic-session-chenyu/outbox",
                headers=operations_headers,
                params={"user_id": "scenic-chenyu"},
            )
            assert repair_outbox.status_code == 200, repair_outbox.text
            notification_item = next(
                item
                for item in repair_outbox.json()["items"]
                if item["kind"] == "OUTBOUND_MESSAGE"
            )
            assert notification_item["receipt_status"] == "RECEIPT_RECORDED"
            assert notification_item["task_id"] == repair_task["id"]

            crowd_step = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "http-step-crowd"},
                json={"kind": "CLOCK_STEP", "payload": {"seconds": 28}},
            )
            assert crowd_step.status_code == 200, crowd_step.text
            diversion = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-create-diversion"},
                json={"kind": "CREATE_DIVERSION_TASK", "payload": {"incident_id": incident_id}},
            )
            assert diversion.status_code == 200, diversion.text
            diversion_task = diversion.json()["task"]
            assert diversion_task["dependencies"] == [repair_task["id"]]
            assert diversion_task["due_at"] is not None
            assert (
                await client.post(f"/work/tasks/{diversion_task['id']}/start", headers=reporter_headers)
            ).status_code == 200
            diversion_complete = await client.post(
                f"/work/tasks/{diversion_task['id']}/complete",
                headers=reporter_headers,
                json={
                    "summary": "东门启用单向分流，引导游客转往镜湖游览区。",
                    "result": {"diversion_action": "ONE_WAY_DIVERSION", "risk_status": "STABLE"},
                },
            )
            assert diversion_complete.status_code == 200, diversion_complete.text

            recovered = await client.post(
                "/operations/scenic/commands",
                headers={**operations_headers, "Idempotency-Key": "http-step-recovery"},
                json={"kind": "CLOCK_STEP", "payload": {"seconds": 60}},
            )
            assert recovered.status_code == 200, recovered.text
            resolved = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-resolve-incident"},
                json={"kind": "RESOLVE_INCIDENT", "payload": {"incident_id": incident_id}},
            )
            assert resolved.status_code == 200, resolved.text
            closed = await client.post(
                "/scenic/commands",
                headers={**manager_headers, "Idempotency-Key": "http-close-incident"},
                json={"kind": "CLOSE_INCIDENT", "payload": {"incident_id": incident_id}},
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["dossier_ready"] is True
            final = (await client.get("/scenic/snapshot", headers=manager_headers)).json()
            assert final["incidents"][0]["lifecycle"] == "CLOSED"
            assert all(item["status"] == "RECOVERED" for item in final["alerts"])
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_sse_exposes_advice_event_names(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    try:
        operations = app.state.scenic_operations
        actor = Actor("scenic-simulation-ops", "simulation-ops", "admin", "venue-scenic")
        await operations.execute(actor, Command("PREPARE_SCENARIO", {}, "advice-sse-prepare"))
        run = await operations._current_run("venue-scenic")
        cursor = (await operations.snapshot(actor))["latest_sequence"]
        await database.execute(
            """
            INSERT INTO scenic_situation_events (
                event_id, venue_id, run_id, event_type, resource_type, resource_id,
                payload_json, simulated_at, recorded_at
            ) VALUES (?, ?, ?, 'ADVICE_READY', 'scenic_advice', 'run-advice-sse',
                      ?, ?, ?)
            """,
            (
                "advice-sse-event-1",
                "venue-scenic",
                run["id"],
                '{"state":"READY","advice_run_id":"run-advice-sse"}',
                run["simulated_at"],
                time.time(),
            ),
        )

        class StreamRequest:
            def __init__(self, target_app):
                self.app = target_app

            async def is_disconnected(self):
                return False

        response = await scenic_stream(
            StreamRequest(app),
            after_sequence=cursor,
            last_event_id=str(cursor),
            principal={
                "user_id": "scenic-wangfang",
                "username": "wangfang",
                "role": "manager",
                "venue_id": "venue-scenic",
            },
        )
        frame = await anext(response.body_iterator)
        assert "event: ADVICE_READY\n" in frame
        await response.body_iterator.aclose()
    finally:
        await database.close()

@pytest.mark.asyncio
async def test_sse_resumes_from_last_event_and_falls_back_when_redis_fails(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)

    class StreamRequest:
        def __init__(self, target_app):
            self.app = target_app

        async def is_disconnected(self):
            return False

    class FailingBus:
        async def wait(self, venue_id, stream_id, timeout_ms):
            raise ConnectionError("redis unavailable")

    principal = {
        "user_id": "scenic-wangfang",
        "username": "wangfang",
        "role": "manager",
        "venue_id": "venue-scenic",
    }
    try:
        operations = app.state.scenic_operations
        operations_actor = Actor(
            "scenic-simulation-ops", "simulation-ops", "admin", "venue-scenic"
        )
        await operations.execute(
            operations_actor,
            Command("PREPARE_SCENARIO", {}, "sse-prepare-story"),
        )
        cursor = (await operations.snapshot(operations_actor))["latest_sequence"]
        await operations.execute(
            operations_actor,
            Command("CLOCK_STEP", {"seconds": 2}, "sse-step-story"),
        )
        response = await scenic_stream(
            StreamRequest(app),
            after_sequence=0,
            last_event_id=str(cursor),
            principal=principal,
        )
        resumed = await anext(response.body_iterator)
        assert resumed.startswith(f"id: {cursor + 1}\n")
        assert "event: situation\n" in resumed
        await response.body_iterator.aclose()

        latest = (await operations.snapshot(operations_actor))["latest_sequence"]
        app.state.scenic_situation_bus = FailingBus()

        async def no_wait(_seconds):
            return None

        monkeypatch.setattr("src.memory_palace.api.v1.endpoints.scenic.asyncio.sleep", no_wait)
        fallback_response = await scenic_stream(
            StreamRequest(app),
            after_sequence=latest,
            last_event_id=str(latest),
            principal=principal,
        )
        assert await anext(fallback_response.body_iterator) == ": keep-alive\n\n"
        await fallback_response.body_iterator.aclose()
    finally:
        await database.close()
