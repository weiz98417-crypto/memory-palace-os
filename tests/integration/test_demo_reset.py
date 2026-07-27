from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory_palace.demo.router import router
from src.memory_palace.demo.scenario_controller import (
    ScenarioController,
    get_scenario_controller,
)


def test_reset_is_isolated_to_the_selected_scenario_run():
    app = FastAPI()
    controller = ScenarioController(step_delay_scale=0)
    app.dependency_overrides[get_scenario_controller] = lambda: controller
    app.include_router(router)

    with TestClient(app) as client:
        emergency = client.post("/demo/scenarios/emergency-p0/runs").json()
        emergency = client.post(
            f"/demo/runs/{emergency['run_id']}/actions",
            json={"action": "step", "expected_version": emergency["version"]},
        ).json()
        knowledge = client.post("/demo/scenarios/knowledge-rain/runs").json()
        knowledge = client.post(
            f"/demo/runs/{knowledge['run_id']}/actions",
            json={"action": "step", "expected_version": knowledge["version"]},
        ).json()

        reset = client.post(
            f"/demo/runs/{emergency['run_id']}/actions",
            json={"action": "reset", "expected_version": emergency["version"]},
        ).json()
        untouched = client.get(f"/demo/runs/{knowledge['run_id']}").json()
        statuses = {scenario["id"]: scenario["status"] for scenario in client.get("/demo/scenarios").json()}

    assert reset["status"] == "IDLE"
    assert reset["steps"] == []
    assert reset["trace_id"] != emergency["trace_id"]
    assert untouched == knowledge
    assert statuses["emergency-p0"] == "IDLE"
    assert statuses["knowledge-rain"] == "PAUSED"
