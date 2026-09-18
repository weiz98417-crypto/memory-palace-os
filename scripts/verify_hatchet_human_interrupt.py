"""Verify the durable human interrupt: pause on decision, resume on push."""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, ".")

from scripts.verify_hatchet_advice_path import call, login  # noqa: E402

BASE = os.environ.get("SCENIC_E2E_BASE_URL", "http://127.0.0.1:8090")


def main() -> int:
    stamp = str(int(time.time()))
    password = os.environ["SCENIC_ACCOUNT_PASSWORD"]
    ops = login(BASE, "simulation-ops", password)
    manager = login(BASE, "wangfang", password)

    call(BASE, "POST", "/operations/scenic/commands", token=ops,
         headers={"Idempotency-Key": "hi-prepare-" + stamp},
         body={"kind": "PREPARE_SCENARIO", "payload": {}})
    call(BASE, "POST", "/operations/scenic/commands", token=ops,
         headers={"Idempotency-Key": "hi-step-" + stamp},
         body={"kind": "CLOCK_STEP", "payload": {"seconds": 2}})
    _, snapshot = call(BASE, "GET", "/scenic/snapshot", token=manager)
    alert = next(a for a in snapshot["alerts"] if a["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL")
    _, converted = call(BASE, "POST", "/scenic/commands", token=manager,
                        headers={"Idempotency-Key": "hi-convert-" + stamp},
                        body={"kind": "CONVERT_ALERT", "payload": {"alert_ids": [alert["id"]]}})
    incident_id = converted["incident_id"]
    call(BASE, "POST", "/scenic/commands", token=manager,
         headers={"Idempotency-Key": "hi-sop-" + stamp},
         body={"kind": "RETRIEVE_SOP",
               "payload": {"incident_id": incident_id,
                           "query": "\u96e8\u540e\u89c2\u5149\u8f66\u8f6e\u5f02\u54cd\u5e94\u8be5\u600e\u4e48\u5904\u7f6e\uff1f"}})

    _, queued = call(BASE, "POST", "/scenic/incidents/" + incident_id + "/advice", token=manager)
    run_id = queued["advice_run_id"]
    print("incident:", incident_id)
    print("run:", run_id)

    deadline = time.time() + 300
    state = "PENDING"
    while time.time() < deadline:
        _, run = call(BASE, "GET", "/scenic/incidents/" + incident_id + "/advice/" + run_id, token=manager)
        state = run.get("state")
        if state in {"READY", "FAILED", "SUPERSEDED"}:
            break
        time.sleep(8)
    print("advice state before decision:", state)
    if state != "READY":
        print("INTERRUPT_FAILED: advice never became ready")
        return 1

    # The durable workflow is now paused on the decision event. Push it through the
    # normal human gate and let the workflow resume.
    status, decided = call(BASE, "POST", "/scenic/commands", token=manager,
                           headers={"Idempotency-Key": "hi-decide-" + stamp},
                           body={"kind": "DECIDE_ADVICE",
                                 "payload": {"incident_id": incident_id,
                                             "advice_run_id": run_id,
                                             "decision": "ADOPT"}})
    print("decision:", status, json.dumps(decided, ensure_ascii=False)[:200])
    if status != 200:
        print("INTERRUPT_FAILED: decision rejected")
        return 1

    time.sleep(15)
    _, final = call(BASE, "GET", "/scenic/incidents/" + incident_id + "/advice/" + run_id, token=manager)
    print("final advice state:", final.get("state"))
    print("decision recorded:", bool((decided.get("advice_run_id"))))
    print("HUMAN_INTERRUPT_OK" if final.get("state") == "READY" else "HUMAN_INTERRUPT_FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
