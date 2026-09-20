from __future__ import annotations

import json

import httpx
import pytest

from src.memory_palace.agent_contracts.models import CommandMode
from src.memory_palace.incident.contracts import IncidentCommandResult
from src.memory_palace.skills.commander.contracts import DispatchDraft, PlannedAction
from tests.integration.test_scenic_api import build_app, login
from tests.integration.test_scenic_incident_advice_api import (
    _add_verified_hit,
    _advice_runtime,
    _open_incident,
)

pytestmark = pytest.mark.asyncio


class DispatchStub:
    def __init__(self, result: IncidentCommandResult | Exception) -> None:
        self.result = result
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _draft(request) -> DispatchDraft:
    return DispatchDraft(
        summary="停运故障车并启用备用车辆",
        priority=request.incident.priority,
        immediate_actions=[
            PlannedAction(action_code="CONTINUE_SUSPENSION", description="保持故障车停运"),
            PlannedAction(action_code="ACTIVATE_BACKUP_VEHICLE", description="启用备用车辆"),
        ],
        required_tools=["send_in_app_alert"],
        next_step_check="核对检修回执和审批状态",
        risk_reason="高风险车辆决策不可由模型取消审批",
        requires_human_approval=False,
    )


async def _prepare_ready_incident(app, database, client, manager, operations_headers):
    incident_id = await _open_incident(client, operations_headers, manager)
    evidence = await client.post(
        "/scenic/commands",
        headers={**manager, "Idempotency-Key": "dispatch-evidence"},
        json={
            "kind": "ADD_EVIDENCE",
            "payload": {"incident_id": incident_id, "text": "右后轮异常，现场已停运。"},
        },
    )
    assert evidence.status_code == 200, evidence.text
    retrieval = await client.post(
        "/scenic/commands",
        headers={**manager, "Idempotency-Key": "dispatch-retrieve"},
        json={
            "kind": "RETRIEVE_SOP",
            "payload": {
                "incident_id": incident_id,
                "query": "雨后观光车复运检查和客流分流",
            },
        },
    )
    assert retrieval.status_code == 200, retrieval.text
    queued = await client.post(
        f"/scenic/incidents/{incident_id}/advice", headers=manager
    )
    run_id = queued.json()["advice_run_id"]
    await client.post("/operations/scenic/advice-runs/process", headers=operations_headers)
    decided = await client.post(
        "/scenic/commands",
        headers={**manager, "Idempotency-Key": "dispatch-advice-adopt"},
        json={
            "kind": "DECIDE_ADVICE",
            "payload": {
                "incident_id": incident_id,
                "advice_run_id": run_id,
                "decision": "ADOPT",
                "expected_state": "READY",
            },
        },
    )
    assert decided.status_code == 200, decided.text
    return incident_id


async def test_dispatch_draft_runs_through_agent_before_task_creation(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            operations_headers = await login(client, "simulation-ops")
            manager = await login(client, "wangfang")
            incident_id = await _prepare_ready_incident(
                app, database, client, manager, operations_headers
            )

            requests = []
            class Stub:
                async def execute(self, request):
                    requests.append(request)
                    return IncidentCommandResult(
                        command_id="dispatch-command",
                        mode=CommandMode.DISPATCH_DRAFT,
                        trace_id=request.trace_id,
                        idempotency_key=request.idempotency_key,
                        outcome="READY",
                        context=request.prior.context,
                        routing=request.prior.routing,
                        dispatch_draft=DispatchDraft(
                            summary="停运故障车并启用备用车辆",
                            priority=request.incident.priority,
                            immediate_actions=[
                                PlannedAction(
                                    action_code="CONTINUE_SUSPENSION",
                                    description="保持故障车停运",
                                )
                            ],
                            required_tools=["send_in_app_alert"],
                            next_step_check="核对审批",
                            risk_reason="高风险",
                            requires_human_approval=False,
                        ),
                    )

            app.state.scenic_operations.incident_command = Stub()
            dispatched = await client.post(
                "/scenic/commands",
                headers={**manager, "Idempotency-Key": "dispatch-create-task"},
                json={"kind": "CREATE_REPAIR_TASK", "payload": {"incident_id": incident_id}},
            )
            assert dispatched.status_code == 200, dispatched.text
            body = dispatched.json()
            assert body["dispatch_draft"]["summary"] == "停运故障车并启用备用车辆"
            assert body["approval_id"]

            run = await database.fetch_one(
                """
                SELECT * FROM scenic_commands
                WHERE venue_id = ? AND command_type = 'DRAFT_DISPATCH'
                """,
                ("venue-scenic",),
            )
            assert run["status"] == "READY"
            assert run["idempotency_key"] == f"dispatch:{incident_id}:DISPATCH_DRAFT:1"

            snapshot = await client.get("/scenic/snapshot", headers=manager)
            projected = snapshot.json()["incidents"][0]
            assert projected["dispatch_draft"]["summary"] == "停运故障车并启用备用车辆"
            assert projected["lifecycle"] == "DISPATCHED"
    finally:
        await database.close()

async def test_dispatch_draft_failure_does_not_create_task_or_approval(tmp_path, monkeypatch):
    app, database = await build_app(tmp_path, monkeypatch)
    _advice_runtime(app, database)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 32000))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            operations_headers = await login(client, "simulation-ops")
            manager = await login(client, "wangfang")
            incident_id = await _prepare_ready_incident(
                app, database, client, manager, operations_headers
            )

            class FailingStub:
                async def execute(self, request):
                    raise RuntimeError("commander unavailable")

            app.state.scenic_operations.incident_command = FailingStub()
            failed = await client.post(
                "/scenic/commands",
                headers={**manager, "Idempotency-Key": "dispatch-failure"},
                json={"kind": "CREATE_REPAIR_TASK", "payload": {"incident_id": incident_id}},
            )
            assert failed.status_code == 409
            task_count = await database.fetch_one(
                "SELECT COUNT(*) AS total FROM tasks WHERE venue_id = 'venue-scenic'"
            )
            approval_count = await database.fetch_one(
                "SELECT COUNT(*) AS total FROM approval_requests WHERE venue_id = 'venue-scenic'"
            )
            assert int(task_count["total"]) == 0
            assert int(approval_count["total"]) == 0
            run = await database.fetch_one(
                """
                SELECT * FROM scenic_commands
                WHERE venue_id = 'venue-scenic' AND command_type = 'DRAFT_DISPATCH'
                """
            )
            assert run["status"] == "FAILED"
    finally:
        await database.close()