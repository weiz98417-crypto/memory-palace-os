from fastapi import FastAPI
from fastapi.testclient import TestClient
import importlib
import sys
import time


def test_demo_api_lists_the_four_enterprise_scenarios():
    from src.memory_palace.demo.router import router

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/demo/scenarios")

    assert response.status_code == 200
    payload = response.json()
    assert [scenario["id"] for scenario in payload] == [
        "emergency-p0",
        "knowledge-rain",
        "persona-mentor",
        "weekend-night-plan",
    ]
    assert all(scenario["status"] == "IDLE" for scenario in payload)
    assert all(scenario["execution_mode"] == "DEMO_ADAPTER" for scenario in payload)


def test_demo_run_can_advance_one_auditable_step():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import ScenarioController

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    from src.memory_palace.demo.scenario_controller import get_scenario_controller

    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        created = client.post("/demo/scenarios/emergency-p0/runs")
        assert created.status_code == 201
        initial = created.json()

        advanced = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "step", "expected_version": initial["version"]},
        )

    assert advanced.status_code == 200
    run = advanced.json()
    assert run["status"] == "PAUSED"
    assert run["progress"] == {"completed": 1, "total": 7}
    assert run["steps"][0]["step_id"] == "receive-message"
    assert run["steps"][0]["actor"] == "Gateway"
    assert run["steps"][0]["status"] == "SUCCESS"
    assert run["steps"][0]["execution_mode"] == "DEMO_ADAPTER"
    assert run["steps"][0]["input_summary"]
    assert run["steps"][0]["output_summary"]


def test_demo_play_completes_the_p0_evidence_chain():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/emergency-p0/runs").json()
        started = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )
        assert started.status_code == 200

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/demo/runs/{initial['run_id']}").json()
            if run["status"] == "COMPLETED":
                break
            time.sleep(0.01)

    assert run["status"] == "COMPLETED"
    assert run["progress"] == {"completed": 7, "total": 7}
    assert [step["actor"] for step in run["steps"]] == [
        "Gateway",
        "Router_Agent",
        "MemoryOps_Agent",
        "Commander_Agent",
        "Notification_Gateway",
        "Watcher_Agent",
        "Audit_Service",
    ]
    assert run["steps"][2]["citations"]
    assert all(step["execution_mode"] == "DEMO_ADAPTER" for step in run["steps"])


def test_demo_controls_pause_stop_and_reset_without_losing_boundaries():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0.1)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/emergency-p0/runs").json()
        original_trace_id = initial["trace_id"]
        client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )

        deadline = time.monotonic() + 2
        running = initial
        while time.monotonic() < deadline:
            running = client.get(f"/demo/runs/{initial['run_id']}").json()
            if running["progress"]["completed"] >= 1:
                break
            time.sleep(0.01)

        paused_response = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "pause", "expected_version": running["version"]},
        )
        assert paused_response.status_code == 200
        paused = paused_response.json()
        assert paused["status"] == "PAUSED"
        frozen_progress = paused["progress"]["completed"]
        time.sleep(0.12)
        assert client.get(f"/demo/runs/{initial['run_id']}").json()["progress"]["completed"] == frozen_progress

        stopped = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "stop", "expected_version": paused["version"]},
        ).json()
        assert stopped["status"] == "STOPPED"
        assert len(stopped["steps"]) == frozen_progress

        reset = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "reset", "expected_version": stopped["version"]},
        ).json()

    assert reset["status"] == "IDLE"
    assert reset["trace_id"] != original_trace_id
    assert reset["progress"] == {"completed": 0, "total": 7}
    assert reset["steps"] == []


def test_demo_version_conflict_returns_the_latest_run_without_repeating_action():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/emergency-p0/runs").json()
        advanced = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "step", "expected_version": initial["version"]},
        ).json()
        conflict = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "reset", "expected_version": initial["version"]},
        )

    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["code"] == "RUN_VERSION_CONFLICT"
    assert detail["latest_run"]["version"] == advanced["version"]
    assert detail["latest_run"]["status"] == "PAUSED"
    assert detail["latest_run"]["progress"]["completed"] == 1


def test_demo_stop_from_idle_returns_state_conflict():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/emergency-p0/runs").json()
        response = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "stop", "expected_version": initial["version"]},
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RUN_STATE_CONFLICT"
    assert detail["latest_run"]["status"] == "IDLE"


def test_knowledge_rain_scenario_returns_cited_operational_advice():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/knowledge-rain/runs").json()
        started = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )
        assert started.status_code == 200

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/demo/runs/{initial['run_id']}").json()
            if run["status"] == "COMPLETED":
                break
            time.sleep(0.01)

    assert run["status"] == "COMPLETED"
    assert run["progress"]["total"] == 5
    citations = [citation for step in run["steps"] for citation in step["citations"]]
    assert {citation["id"] for citation in citations} >= {
        "SOP-RAIN-003",
        "SOP-CROWD-006",
    }
    evidence_text = " ".join(step["output_summary"] for step in run["steps"])
    assert "地面防滑" in evidence_text
    assert "临时围挡" in evidence_text
    assert "客流监测" in evidence_text


def test_persona_mentor_scenario_creates_traceable_experience_and_answer():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/persona-mentor/runs").json()
        started = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )
        assert started.status_code == 200

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/demo/runs/{initial['run_id']}").json()
            if run["status"] == "COMPLETED":
                break
            time.sleep(0.01)

    assert run["status"] == "COMPLETED"
    assert run["progress"]["total"] == 6
    experience_entries = [
        citation
        for step in run["steps"]
        for citation in step["citations"]
        if citation["id"].startswith("EXP-ZHANG-") and {"trigger", "behavior", "reason"} <= citation.keys()
    ]
    assert len(experience_entries) >= 3
    evidence_text = " ".join(step["output_summary"] for step in run["steps"])
    assert "张师傅数字分身" in evidence_text
    assert "我会先" in evidence_text


def test_weekend_plan_scenario_recovers_one_deterministic_failure():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/weekend-night-plan/runs").json()
        started = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )
        assert started.status_code == 200

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/demo/runs/{initial['run_id']}").json()
            if run["status"] == "COMPLETED":
                break
            time.sleep(0.01)

    assert run["status"] == "COMPLETED"
    assert run["progress"]["total"] == 6
    recovered_steps = [step for step in run["steps"] if step["retry_count"] > 0]
    assert len(recovered_steps) == 1
    assert recovered_steps[0]["status"] == "SUCCESS"
    assert recovered_steps[0]["retry_count"] == 1
    assert recovered_steps[0]["recovery_summary"]
    evidence_text = " ".join(step["output_summary"] for step in run["steps"])
    for task_name in ["客流预测", "人员排班", "设备检查", "应急预案", "复盘任务"]:
        assert task_name in evidence_text


def test_weekend_plan_report_preserves_the_failed_attempt_before_recovery():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/weekend-night-plan/runs").json()
        started = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "play", "expected_version": initial["version"]},
        )
        assert started.status_code == 200

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/demo/runs/{initial['run_id']}").json()
            if run["status"] == "COMPLETED":
                break
            time.sleep(0.01)
        report_response = client.get(f"/demo/runs/{initial['run_id']}/report")

    assert run["status"] == "COMPLETED"
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["schema_version"] == "enterprise-demo-report/v1"
    assert report["evidence_count"] == len(report["run"]["steps"])
    recovery_attempts = [step for step in report["run"]["steps"] if step["step_id"] == "recover-equipment-check"]
    assert [step["status"] for step in recovery_attempts] == ["FAILED", "SUCCESS"]
    assert [step["attempt"] for step in recovery_attempts] == [1, 2]
    assert recovery_attempts[0]["error"]
    assert [call["status"] for call in recovery_attempts[0]["tool_calls"]] == ["TEMPORARY_TIMEOUT"]
    assert recovery_attempts[1]["retry_count"] == 1
    assert recovery_attempts[1]["recovery_summary"]
    assert [call["status"] for call in recovery_attempts[1]["tool_calls"]] == ["SUCCESS"]


def test_demo_environment_truthfully_labels_runtime_and_extension_points():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/demo/environment")

    assert response.status_code == 200
    environment = response.json()
    assert environment["demo_mode"] is True
    assert environment["security_mode"] == "LOCAL_DEMO_SIMPLIFIED_AUTH"
    assert environment["scenario_data_version"] == {
        "emergency-p0": 1,
        "knowledge-rain": 1,
        "persona-mentor": 1,
        "weekend-night-plan": 1,
    }
    capabilities = {item["id"]: item for item in environment["capabilities"]}
    assert capabilities["demo-runtime"]["claim_level"] == "DEMO_IMPLEMENTATION"
    assert capabilities["demo-runtime"]["status"] == "READY"
    assert capabilities["real-llm"]["claim_level"] == "OPTIONAL_CONNECTION"
    assert capabilities["real-llm"]["status"] == "NOT_CONFIGURED"
    assert capabilities["enterprise-ha"]["claim_level"] == "PRODUCTION_EXTENSION"


def test_demo_report_serializes_the_authoritative_run_evidence():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        initial = client.post("/demo/scenarios/emergency-p0/runs").json()
        advanced = client.post(
            f"/demo/runs/{initial['run_id']}/actions",
            json={"action": "step", "expected_version": initial["version"]},
        ).json()
        response = client.get(f"/demo/runs/{initial['run_id']}/report")

    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == "enterprise-demo-report/v1"
    assert report["run"]["version"] == advanced["version"]
    assert report["run"]["trace_id"] == advanced["trace_id"]
    assert report["evidence_count"] == 1
    assert report["execution_modes"] == ["DEMO_ADAPTER"]
    assert "模拟" in report["disclaimer"]


def test_all_scenarios_are_deterministic_across_five_runs():
    from src.memory_palace.demo.router import router
    from src.memory_palace.demo.scenario_controller import (
        ScenarioController,
        get_scenario_controller,
    )

    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)
    scenario_ids = [
        "emergency-p0",
        "knowledge-rain",
        "persona-mentor",
        "weekend-night-plan",
    ]

    with TestClient(app) as client:
        for scenario_id in scenario_ids:
            expected_evidence = None
            for _ in range(5):
                initial = client.post(f"/demo/scenarios/{scenario_id}/runs").json()
                started = client.post(
                    f"/demo/runs/{initial['run_id']}/actions",
                    json={"action": "play", "expected_version": initial["version"]},
                )
                assert started.status_code == 200

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    run = client.get(f"/demo/runs/{initial['run_id']}").json()
                    if run["status"] == "COMPLETED":
                        break
                    time.sleep(0.005)

                assert run["status"] == "COMPLETED"
                evidence = [(step["step_id"], step["output_summary"], step["retry_count"]) for step in run["steps"]]
                if expected_evidence is None:
                    expected_evidence = evidence
                assert evidence == expected_evidence


def test_main_app_exposes_the_enterprise_demo_page_and_api(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    sys.modules.pop("main", None)
    application = importlib.import_module("main").app

    with TestClient(application, raise_server_exceptions=False) as client:
        page = client.get("/demo")
        scenarios = client.get("/demo/scenarios")
        blocked_routes = [
            client.get("/api/v1/admin/approvals"),
            client.post("/demo/send", json={}),
            client.get("/webhook"),
            client.get("/admin"),
            client.get("/docs"),
            client.get("/openapi.json"),
        ]

    assert page.status_code == 200
    assert "Memory Palace OS" in page.text
    assert scenarios.status_code == 200
    assert len(scenarios.json()) == 4
    assert all(response.status_code == 404 for response in blocked_routes)
