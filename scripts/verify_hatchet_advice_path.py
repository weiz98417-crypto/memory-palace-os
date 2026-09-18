"""Verify the Hatchet advice path end to end against a running stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def call(base, method, path, *, token=None, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + "/api/v1" + path, data=data, method=method)
    request.headers["Content-Type"] = "application/json"
    if token:
        request.headers["Authorization"] = "Bearer " + token
    for key, value in (headers or {}).items():
        request.headers[key] = value
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", errors="replace")[:300]}


def login(base, username, password):
    status, payload = call(base, "POST", "/auth/login", body={"username": username, "password": password})
    if status != 200:
        raise SystemExit("login failed for " + username + ": " + str(payload))
    return payload["access_token"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("SCENIC_E2E_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    stamp = str(int(time.time()))

    password = os.environ["SCENIC_ACCOUNT_PASSWORD"]
    ops = login(base, "simulation-ops", password)
    manager = login(base, "wangfang", password)

    call(base, "POST", "/operations/scenic/commands", token=ops,
         headers={"Idempotency-Key": "hx-prepare-" + stamp},
         body={"kind": "PREPARE_SCENARIO", "payload": {}})
    call(base, "POST", "/operations/scenic/commands", token=ops,
         headers={"Idempotency-Key": "hx-step-" + stamp},
         body={"kind": "CLOCK_STEP", "payload": {"seconds": 2}})
    status, snapshot = call(base, "GET", "/scenic/snapshot", token=manager)
    alert = next(a for a in snapshot["alerts"] if a["rule_code"] == "VEHICLE_12_RIGHT_REAR_WHEEL")
    status, converted = call(base, "POST", "/scenic/commands", token=manager,
                            headers={"Idempotency-Key": "hx-convert-" + stamp},
                            body={"kind": "CONVERT_ALERT", "payload": {"alert_ids": [alert["id"]]}})
    if status != 200:
        print("convert failed:", json.dumps(converted, ensure_ascii=False)[:300])
        return 1
    incident_id = converted["incident_id"]
    print("incident:", incident_id)

    # The advice path grounds on `scenic_knowledge_hits`, so retrieve the SOP first. The
    # query must be natural Chinese: the index is Chinese and English transliteration
    # retrieves nothing.
    status, sop = call(base, "POST", "/scenic/commands", token=manager,
                       headers={"Idempotency-Key": "hx-sop-" + stamp},
                       body={"kind": "RETRIEVE_SOP",
                             "payload": {"incident_id": incident_id,
                                         "query": "\u96e8\u540e\u89c2\u5149\u8f66\u8f6e\u5f02\u54cd\u5e94\u8be5\u600e\u4e48\u5904\u7f6e\uff1f"}})
    hits = len(sop.get("hits") or []) if isinstance(sop, dict) else 0
    print("sop retrieval:", status, "| hits:", hits)
    if status != 200 or not hits:
        print("SOP_CONTEXT:", json.dumps(sop, ensure_ascii=False)[:300])

    status, queued = call(base, "POST", "/scenic/incidents/" + incident_id + "/advice", token=manager)
    if status != 200:
        print("enqueue failed:", json.dumps(queued, ensure_ascii=False)[:300])
        return 1
    run_id = queued["advice_run_id"]
    print("dispatched run:", run_id, "| state:", queued.get("state"))

    deadline = time.time() + args.timeout
    run = {}
    while time.time() < deadline:
        _, run = call(base, "GET", "/scenic/incidents/" + incident_id + "/advice/" + run_id, token=manager)
        state = run.get("state")
        print("  state:", state)
        if state in {"READY", "FAILED", "SUPERSEDED"}:
            break
        time.sleep(10)

    advice = (run.get("result") or {}).get("advice") or {}
    state = run.get("state")
    print("FINAL_STATE:", state)
    print("evidence_status:", advice.get("evidence_status"))
    print("citations:", [c.get("source_id") for c in advice.get("citations") or []])
    ok = state == "READY" and advice.get("evidence_status") == "GROUNDED"
    print("HATCHET_PATH_OK" if ok else "HATCHET_PATH_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
