import asyncio
import time

import pytest

from src.memory_palace.core.permissions import PermissionEngine
from src.memory_palace.core.event_dossier import build_event_dossier
from src.memory_palace.core.task_graph import TaskGraph
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.scenic.operations import (
    Actor,
    Command,
    ScenicAreaOperations,
    ScenicCommandConflict,
)


class VectorStoreStub:
    backend_mode = "pgvector_test_adapter"

    def __init__(self):
        self.documents = {}
        self.fail_source_type = None

    def upsert_experience(self, content, metadata, doc_id, strict=False):
        if metadata.get("source_type") == self.fail_source_type:
            raise RuntimeError(f"{self.fail_source_type} vector write failed")
        self.documents[doc_id] = {"content": content, "metadata": dict(metadata)}
        return True

    def query_experience(
        self,
        text,
        top_k=3,
        threshold=0.0,
        *,
        venue_id,
        source_types=None,
        strict=False,
    ):
        allowed = {str(item).upper() for item in source_types} if source_types else None
        return [
            {
                "id": doc_id,
                "content": document["content"],
                "metadata": document["metadata"],
                "score": 0.94,
            }
            for doc_id, document in self.documents.items()
            if document["metadata"].get("venue_id") == venue_id
            and (
                not allowed
                or str(document["metadata"].get("source_type") or "").upper() in allowed
            )
        ][:top_k]


async def build_operations(tmp_path):
    database = AsyncDBClient(tmp_path / "scenic.db")
    await init_database(database)
    vector_store = VectorStoreStub()
    task_graph = TaskGraph(database)
    permission_engine = PermissionEngine(database)
    operations = ScenicAreaOperations(
        database=database,
        vector_store=vector_store,
        task_graph=task_graph,
        permission_engine=permission_engine,
    )
    await operations.bootstrap(
        venue_id="venue-scenic",
        venue_name="云栖山景区",
        account_password="Scenic-Local-2026!",
    )
    return operations, database


def actor(username, role, user_id=None):
    return Actor(
        user_id=user_id or f"user-{username}",
        username=username,
        role=role,
        venue_id="venue-scenic",
    )


@pytest.mark.asyncio
async def test_story_signals_create_real_alerts_once(tmp_path):
    operations, database = await build_operations(tmp_path)
    try:
        prepared = await operations.execute(
            actor("simulation-ops", "admin"),
            Command("PREPARE_SCENARIO", {}, "prepare-story-1"),
        )
        stepped = await operations.execute(
            actor("simulation-ops", "admin"),
            Command("CLOCK_STEP", {"seconds": 30}, "step-story-1"),
        )
        replay = await operations.execute(
            actor("simulation-ops", "admin"),
            Command("CLOCK_STEP", {"seconds": 30}, "step-story-1"),
        )

        assert replay == stepped
        assert prepared["scenario_key"] == "rain_vehicle_east_gate"
        snapshot = await operations.snapshot(actor("wangfang", "manager"))
        assert {item["source_type"] for item in snapshot["signals"]} == {
            "WEATHER",
            "DEVICE",
            "CROWD",
        }
        assert {item["rule_code"] for item in snapshot["alerts"]} == {
            "VEHICLE_12_RIGHT_REAR_WHEEL",
            "EAST_GATE_CAPACITY",
        }
        assert [event["sequence"] for event in await operations.events_since(
            actor("wangfang", "manager"), after_sequence=0
        )] == list(range(1, snapshot["latest_sequence"] + 1))

        with pytest.raises(ScenicCommandConflict):
            await operations.execute(
                actor("simulation-ops", "admin"),
                Command("CLOCK_STEP", {"seconds": 1}, "step-story-1"),
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_incident_cannot_skip_lifecycle_or_close_without_evidence(tmp_path):
    operations, database = await build_operations(tmp_path)
    try:
        await operations.execute(
            actor("simulation-ops", "admin"),
            Command("PREPARE_SCENARIO", {}, "prepare-story-2"),
        )
        await operations.execute(
            actor("simulation-ops", "admin"),
            Command("CLOCK_STEP", {"seconds": 2}, "step-story-2"),
        )
        snapshot = await operations.snapshot(actor("wangfang", "manager"))
        alert_id = snapshot["alerts"][0]["id"]
        converted = await operations.execute(
            actor("wangfang", "manager", "scenic-wangfang"),
            Command("CONVERT_ALERT", {"alert_ids": [alert_id]}, "convert-story-2"),
        )

        assert converted["lifecycle"] == "DETECTED"
        with pytest.raises(ScenicCommandConflict, match="RESOLVED"):
            await operations.execute(
                actor("wangfang", "manager", "scenic-wangfang"),
                Command("CLOSE_INCIDENT", {"incident_id": converted["incident_id"]}, "close-too-soon"),
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_rain_vehicle_and_east_gate_story_closes_with_auditable_dossier(tmp_path):
    operations, database = await build_operations(tmp_path)
    try:
        ops = actor("simulation-ops", "admin", "scenic-simulation-ops")
        manager = actor("wangfang", "manager", "scenic-wangfang")
        reporter = actor("liming", "operator", "scenic-liming")
        await operations.execute(ops, Command("PREPARE_SCENARIO", {}, "prepare-full-story"))
        await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 2}, "step-to-fault"))
        alert_id = (await operations.snapshot(manager))["alerts"][0]["id"]
        incident = await operations.execute(
            manager,
            Command("CONVERT_ALERT", {"alert_ids": [alert_id]}, "convert-full-story"),
        )
        now = time.time()
        await database.execute(
            """
            INSERT INTO message_attachments (
                id, business_id, venue_id, owner_user_id, original_name,
                content_type, size_bytes, sha256, scan_status, scan_engine,
                storage_key, external_ref, created_at
            ) VALUES ('photo-wheel-12', 'FJ-WHEEL-12', 'venue-scenic',
                      'scenic-liming', 'vehicle-12-wheel.jpg', 'image/jpeg',
                      128, 'abc123', 'CLEAN', 'TEST', 'test/wheel.jpg',
                      'attachment:photo-wheel-12', ?)
            """,
            (now,),
        )
        evidence = await operations.execute(
            reporter,
            Command(
                "ADD_EVIDENCE",
                {
                    "incident_id": incident["incident_id"],
                    "text": "右后轮异响并伴随明显振动，现场已设置停运标识。",
                    "attachment_id": "photo-wheel-12",
                },
                "liming-evidence",
            ),
        )
        assert evidence["attachment_id"] == "photo-wheel-12"

        retrieval = await operations.execute(
            manager,
            Command(
                "RETRIEVE_SOP",
                {"incident_id": incident["incident_id"], "query": "雨后观光车复运检查和客流分流"},
                "retrieve-rain-sop",
            ),
        )
        assert retrieval["backend"] == "pgvector_test_adapter"
        assert retrieval["hits"][0]["source_type"] == "SOP"
        assert retrieval["lifecycle"] == "TRIAGED"

        dispatched = await operations.execute(
            manager,
            Command("CREATE_REPAIR_TASK", {"incident_id": incident["incident_id"]}, "dispatch-repair"),
        )
        assert dispatched["lifecycle"] == "DISPATCHED"
        assert dispatched["task"]["assigned_user_id"] == "scenic-chenyu"
        approval_id = dispatched["approval_id"]
        approved = await operations.permission_engine.approve(
            approval_id,
            reviewer="scenic-wangfang",
            comment="继续停运 12 号车并启用 7 号备用车",
            venue_id="venue-scenic",
        )
        assert approved is True

        repair_task_id = dispatched["task"]["id"]
        await operations.task_graph.start_task(repair_task_id, agent_name="field-technician")
        assert await operations.reconcile_incident("venue-scenic", incident["incident_id"]) == "ACKNOWLEDGED"
        acknowledged = await database.fetch_one(
            "SELECT status FROM scenic_notification_receipts WHERE task_id = ?",
            (repair_task_id,),
        )
        assert acknowledged["status"] == "ACKNOWLEDGED"
        await operations.task_graph.complete_task(
            repair_task_id,
            result={
                "summary": "确认右后轮轴承异常，车辆保持停运，备用 7 号车检查合格。",
                "vehicle_12": "ISOLATED",
                "backup_vehicle_7": "READY",
            },
        )
        assert await operations.reconcile_incident("venue-scenic", incident["incident_id"]) == "MITIGATING"
        receipt = await database.fetch_one(
            "SELECT status, result_json FROM scenic_notification_receipts WHERE task_id = ?",
            (repair_task_id,),
        )
        assert receipt["status"] == "RECEIPT_RECORDED"
        assert "backup_vehicle_7" in receipt["result_json"]

        await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 28}, "step-to-crowd"))
        diversion = await operations.execute(
            manager,
            Command("CREATE_DIVERSION_TASK", {"incident_id": incident["incident_id"]}, "dispatch-diversion"),
        )
        assert diversion["task"]["assigned_user_id"] == "scenic-liming"
        await operations.task_graph.start_task(diversion["task"]["id"], agent_name="field-operator")
        await operations.task_graph.complete_task(
            diversion["task"]["id"],
            result={"summary": "东门启用单向分流，客流引导至镜湖游览区。"},
        )
        await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 60}, "step-to-recovery"))

        resolved = await operations.execute(
            manager,
            Command("RESOLVE_INCIDENT", {"incident_id": incident["incident_id"]}, "resolve-full-story"),
        )
        assert resolved["lifecycle"] == "RESOLVED"
        operations.vector_store.fail_source_type = "CASE"
        with pytest.raises(RuntimeError, match="CASE vector write failed"):
            await operations.execute(
                manager,
                Command("CLOSE_INCIDENT", {"incident_id": incident["incident_id"]}, "close-full-story"),
            )
        assert (await operations.snapshot(manager))["incidents"][0]["lifecycle"] == "RESOLVED"
        operations.vector_store.fail_source_type = None
        closed = await operations.execute(
            manager,
            Command("CLOSE_INCIDENT", {"incident_id": incident["incident_id"]}, "close-full-story"),
        )
        assert closed == {
            "incident_id": incident["incident_id"],
            "lifecycle": "CLOSED",
            "dossier_ready": True,
        }
        final = await operations.snapshot(manager)
        dossier = final["incidents"][0]
        assert dossier["lifecycle"] == "CLOSED"
        assert len(dossier["tasks"]) == 2
        assert dossier["approvals"][0]["execution_status"] == "SUCCEEDED"
        assert dossier["evidence"][0]["attachment_id"] == "photo-wheel-12"
        assert dossier["knowledge_hits"][0]["dimension"] == 1024
        assert all(alert["status"] == "RECOVERED" for alert in final["alerts"])
        event = await database.fetch_one(
            "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
            ("venue-scenic", incident["event_id"]),
        )
        formal_dossier = await build_event_dossier(
            database,
            event=event,
            venue_id="venue-scenic",
        )
        assert formal_dossier["attachments"][0]["attachment_id"] == "photo-wheel-12"
        assert formal_dossier["field_evidence"][0]["submitted_by"]["name"] == "李明"
        assert formal_dossier["references"][0]["title"] == "雨后观光车复运与分流 SOP"
        journey_types = {
            item["technical"]["activity_type"]
            for item in formal_dossier["journey_timeline"]
        }
        assert {"FIELD_EVIDENCE_ADDED", "KNOWLEDGE_RETRIEVED"} <= journey_types
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_story_sop_stays_draft_when_vector_indexing_fails(tmp_path):
    operations, database = await build_operations(tmp_path)
    operations.vector_store.fail_source_type = "SOP"
    try:
        with pytest.raises(RuntimeError, match="SOP vector write failed"):
            await operations.execute(
                actor("simulation-ops", "admin"),
                Command("PREPARE_SCENARIO", {}, "prepare-with-vector-failure"),
            )
        sop = await database.fetch_one(
            "SELECT id, status, published_at FROM sop_documents WHERE venue_id = ?",
            ("venue-scenic",),
        )
        version = await database.fetch_one(
            "SELECT status FROM sop_versions WHERE venue_id = ? AND sop_id = ?",
            ("venue-scenic", sop["id"]),
        )
        assert sop["status"] == "DRAFT"
        assert sop["published_at"] is None
        assert version["status"] == "DRAFT"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_failed_command_keeps_evidence_and_retries_with_same_idempotency_key(tmp_path):
    operations, database = await build_operations(tmp_path)
    attempts = 0

    async def transient_probe(_actor, payload, _idempotency_key):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary adapter failure")
        return {"recovered": True, "value": payload["value"]}

    operations._command_transient_probe = transient_probe
    command = Command("TRANSIENT_PROBE", {"value": 12}, "retry-command-12")
    try:
        with pytest.raises(RuntimeError, match="temporary adapter failure"):
            await operations.execute(actor("simulation-ops", "admin"), command)
        failed = await database.fetch_one(
            "SELECT status, error_type, error_message FROM scenic_commands WHERE idempotency_key = ?",
            (command.idempotency_key,),
        )
        assert failed == {
            "status": "FAILED",
            "error_type": "RuntimeError",
            "error_message": "temporary adapter failure",
        }

        assert await operations.execute(actor("simulation-ops", "admin"), command) == {
            "recovered": True,
            "value": 12,
        }
        succeeded = await database.fetch_one(
            "SELECT status, error_type, error_message FROM scenic_commands WHERE idempotency_key = ?",
            (command.idempotency_key,),
        )
        assert succeeded == {
            "status": "SUCCEEDED",
            "error_type": None,
            "error_message": None,
        }
        with pytest.raises(ScenicCommandConflict, match="another command"):
            await operations.execute(
                actor("simulation-ops", "admin"),
                Command("TRANSIENT_PROBE", {"value": 13}, command.idempotency_key),
            )
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_concurrent_runtime_cannot_execute_same_idempotency_key_twice(tmp_path):
    operations, database = await build_operations(tmp_path)
    competing = ScenicAreaOperations(
        database=database,
        vector_store=operations.vector_store,
        task_graph=operations.task_graph,
        permission_engine=operations.permission_engine,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def slow_probe(_actor, _payload, _idempotency_key):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"completed": True}

    operations._command_slow_probe = slow_probe
    competing._command_slow_probe = slow_probe
    command = Command("SLOW_PROBE", {}, "concurrent-command")
    first = asyncio.create_task(operations.execute(actor("simulation-ops", "admin"), command))
    try:
        await entered.wait()
        with pytest.raises(ScenicCommandConflict, match="already processing"):
            await competing.execute(actor("simulation-ops", "admin"), command)
        release.set()
        assert await first == {"completed": True}
        assert calls == 1
    finally:
        release.set()
        await database.close()


@pytest.mark.asyncio
async def test_dispatched_incident_recovers_after_app_restart_and_closes(tmp_path):
    operations, database = await build_operations(tmp_path)
    ops = actor("simulation-ops", "admin", "scenic-simulation-ops")
    manager = actor("wangfang", "manager", "scenic-wangfang")
    reporter = actor("liming", "operator", "scenic-liming")
    try:
        await operations.execute(ops, Command("PREPARE_SCENARIO", {}, "restart-prepare"))
        await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 2}, "restart-fault"))
        alert_id = (await operations.snapshot(manager))["alerts"][0]["id"]
        incident = await operations.execute(
            manager,
            Command("CONVERT_ALERT", {"alert_ids": [alert_id]}, "restart-convert"),
        )
        await database.execute(
            """
            INSERT INTO message_attachments (
                id, business_id, venue_id, owner_user_id, original_name,
                content_type, size_bytes, sha256, scan_status, scan_engine,
                storage_key, external_ref, created_at
            ) VALUES ('restart-photo', 'FJ-RESTART', 'venue-scenic', 'scenic-liming',
                      'wheel.png', 'image/png', 16, 'restart-sha', 'PASSED',
                      'MVP_SIGNATURE_SCAN_V1', 'restart/photo.png',
                      'attachment:restart-photo', ?)
            """,
            (time.time(),),
        )
        await operations.execute(
            reporter,
            Command(
                "ADD_EVIDENCE",
                {
                    "incident_id": incident["incident_id"],
                    "text": "右后轮异常，车辆已隔离。",
                    "attachment_id": "restart-photo",
                },
                "restart-evidence",
            ),
        )
        await operations.execute(
            manager,
            Command(
                "RETRIEVE_SOP",
                {"incident_id": incident["incident_id"], "query": "雨后观光车复运"},
                "restart-sop",
            ),
        )
        dispatched = await operations.execute(
            manager,
            Command(
                "CREATE_REPAIR_TASK",
                {"incident_id": incident["incident_id"]},
                "restart-dispatch",
            ),
        )
        assert dispatched["lifecycle"] == "DISPATCHED"

        recovered_graph = TaskGraph(database)
        await recovered_graph.reload_from_db()
        recovered_permissions = PermissionEngine(database)
        await recovered_permissions.reload_from_db()
        recovered_operations = ScenicAreaOperations(
            database=database,
            vector_store=VectorStoreStub(),
            task_graph=recovered_graph,
            permission_engine=recovered_permissions,
        )
        recovered_task = await recovered_graph.get_task(dispatched["task"]["id"])
        assert recovered_task is not None
        assert recovered_task.due_at == dispatched["task"]["due_at"]
        assert recovered_task.result_schema_json == dispatched["task"]["result_schema_json"]

        assert await recovered_permissions.approve(
            dispatched["approval_id"],
            reviewer="scenic-wangfang",
            comment="重启后继续停运并启用备用车辆",
            venue_id="venue-scenic",
        ) is True
        await recovered_graph.start_task(recovered_task.id, agent_name="field-technician")
        await recovered_operations.reconcile_incident("venue-scenic", incident["incident_id"])
        await recovered_graph.complete_task(
            recovered_task.id,
            result={
                "summary": "12 号车保持隔离，7 号备用车可用。",
                "vehicle_12": "ISOLATED",
                "backup_vehicle_7": "READY",
                "inspection_items": ["右后轮", "制动", "底盘"],
            },
        )
        assert await recovered_operations.reconcile_incident(
            "venue-scenic", incident["incident_id"]
        ) == "MITIGATING"
        await recovered_operations.execute(
            ops, Command("CLOCK_STEP", {"seconds": 28}, "restart-crowd")
        )
        diversion = await recovered_operations.execute(
            manager,
            Command(
                "CREATE_DIVERSION_TASK",
                {"incident_id": incident["incident_id"]},
                "restart-diversion",
            ),
        )
        await recovered_graph.start_task(diversion["task"]["id"], agent_name="field-operator")
        await recovered_graph.complete_task(
            diversion["task"]["id"],
            result={
                "summary": "东门单向分流完成。",
                "diversion_action": "ONE_WAY_DIVERSION",
                "risk_status": "STABLE",
            },
        )
        await recovered_operations.reconcile_incident("venue-scenic", incident["incident_id"])
        await recovered_operations.execute(
            ops, Command("CLOCK_STEP", {"seconds": 60}, "restart-recovery")
        )
        await recovered_operations.execute(
            manager,
            Command(
                "RESOLVE_INCIDENT",
                {"incident_id": incident["incident_id"]},
                "restart-resolve",
            ),
        )
        closed = await recovered_operations.execute(
            manager,
            Command(
                "CLOSE_INCIDENT",
                {"incident_id": incident["incident_id"]},
                "restart-close",
            ),
        )
        assert closed["lifecycle"] == "CLOSED"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_high_risk_dispatch_cooldown_never_leaves_an_orphan_task(tmp_path):
    operations, database = await build_operations(tmp_path)
    try:
        ops = actor("simulation-ops", "admin", "scenic-simulation-ops")
        manager = actor("wangfang", "manager", "scenic-wangfang")
        reporter = actor("liming", "operator", "scenic-liming")

        async def triaged_incident(label: str) -> dict:
            await operations.execute(ops, Command("PREPARE_SCENARIO", {}, f"prepare-{label}"))
            await operations.execute(ops, Command("CLOCK_STEP", {"seconds": 2}, f"step-{label}"))
            snapshot = await operations.snapshot(manager)
            alert = next(
                item
                for item in snapshot["alerts"]
                if item["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL"
                and item["status"] == "ACTIVE"
            )
            incident = await operations.execute(
                manager,
                Command("CONVERT_ALERT", {"alert_ids": [alert["id"]]}, f"convert-{label}"),
            )
            attachment_id = f"photo-{label}"
            await database.execute(
                """
                INSERT INTO message_attachments (
                    id, business_id, venue_id, owner_user_id, original_name,
                    content_type, size_bytes, sha256, scan_status, scan_engine,
                    storage_key, external_ref, created_at
                ) VALUES (?, ?, 'venue-scenic', 'scenic-liming',
                          'vehicle-12-wheel.png', 'image/png', 128, 'abc123',
                          'CLEAN', 'TEST', ?, ?, ?)
                """,
                (
                    attachment_id,
                    f"FJ-WHEEL-{label}",
                    f"test/wheel-{label}.png",
                    f"attachment:{attachment_id}",
                    time.time(),
                ),
            )
            await operations.execute(
                reporter,
                Command(
                    "ADD_EVIDENCE",
                    {
                        "incident_id": incident["incident_id"],
                        "text": "右后轮异响并伴随明显振动，现场已设置停运标识。",
                        "attachment_id": attachment_id,
                    },
                    f"evidence-{label}",
                ),
            )
            triaged = await operations.execute(
                manager,
                Command(
                    "RETRIEVE_SOP",
                    {
                        "incident_id": incident["incident_id"],
                        "query": "雨后观光车复运检查和东门客流分流",
                    },
                    f"retrieve-{label}",
                ),
            )
            assert triaged["lifecycle"] == "TRIAGED"
            return incident

        first = await triaged_incident("cooldown-a")
        dispatched = await operations.execute(
            manager,
            Command("CREATE_REPAIR_TASK", {"incident_id": first["incident_id"]}, "dispatch-a"),
        )
        assert dispatched["lifecycle"] == "DISPATCHED"
        assert await operations.permission_engine.approve(
            dispatched["approval_id"],
            reviewer="scenic-wangfang",
            comment="继续停运 12 号车并启用 7 号备用车",
            venue_id="venue-scenic",
        )
        assert (
            operations.permission_engine.cooldown_remaining(
                "record_manager_decision", "venue-scenic"
            )
            > 0
        )

        second = await triaged_incident("cooldown-b")
        before = await database.fetch_one(
            "SELECT COUNT(*) AS total FROM tasks WHERE venue_id = ? AND event_id = ?",
            ("venue-scenic", second["event_id"]),
        )
        assert int(before["total"]) == 0

        with pytest.raises(ScenicCommandConflict, match="did not enter approval"):
            await operations.execute(
                manager,
                Command("CREATE_REPAIR_TASK", {"incident_id": second["incident_id"]}, "dispatch-b"),
            )

        after = await database.fetch_one(
            "SELECT COUNT(*) AS total FROM tasks WHERE venue_id = ? AND event_id = ?",
            ("venue-scenic", second["event_id"]),
        )
        assert int(after["total"]) == 0
        incident_row = await database.fetch_one(
            "SELECT lifecycle FROM scenic_incidents WHERE incident_id = ?",
            (second["incident_id"],),
        )
        assert incident_row["lifecycle"] == "TRIAGED"
    finally:
        await database.close()
