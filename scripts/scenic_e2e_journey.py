"""Drive the complete scenic-area vertical story over the formal HTTP surfaces.

The script never writes business state directly: every step goes through an
authenticated HTTP endpoint, so running it exercises the same path the command
center, the field assistant, and the internal notification counterpart use.

Usage::

    $env:SCENIC_E2E_PASSWORD = "<shared demo password>"
    uv run --no-project --with-requirements requirements.txt \
        python scripts/scenic_e2e_journey.py --base-url http://127.0.0.1:18080
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTACHMENT = PROJECT_ROOT / "artifacts" / "scenic-e2e" / "synthetic-wheel-inspection.png"


class JourneyError(RuntimeError):
    """Raised when a business step does not produce the expected formal result."""


def _idempotency_key(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex}"[:120]


class ScenicClient:
    """Thin authenticated HTTP client for the formal scenic surfaces."""

    def __init__(self, base_url: str, password: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.tokens: dict[str, str] = {}

    def close(self) -> None:
        self.http.close()

    def login(self, username: str) -> dict[str, Any]:
        response = self.http.post(
            "/api/v1/auth/login",
            json={"username": username, "password": self.password},
        )
        if response.status_code >= 400:
            raise JourneyError(
                f"login failed for {username}: {response.status_code} {response.text[:200]}"
            )
        payload = response.json()
        self.tokens[username] = payload["access_token"]
        return payload["user"]

    def _headers(self, username: str, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.tokens[username]}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def command(self, username: str, kind: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
        response = self.http.post(
            "/api/v1/scenic/commands",
            json={"kind": kind, "payload": payload},
            headers=self._headers(username, _idempotency_key(label)),
        )
        if response.status_code >= 400:
            raise JourneyError(f"{kind} by {username} failed: {response.status_code} {response.text}")
        return response.json()

    def input_command(
        self, username: str, kind: str, payload: dict[str, Any], label: str
    ) -> dict[str, Any]:
        response = self.http.post(
            "/api/v1/operations/scenic/commands",
            json={"kind": kind, "payload": payload},
            headers=self._headers(username, _idempotency_key(label)),
        )
        if response.status_code >= 400:
            raise JourneyError(f"{kind} by {username} failed: {response.status_code} {response.text}")
        return response.json()

    def snapshot(self, username: str) -> dict[str, Any]:
        response = self.http.get("/api/v1/scenic/snapshot", headers=self._headers(username))
        response.raise_for_status()
        return response.json()

    def upload_attachment(self, username: str, path: Path) -> dict[str, Any]:
        response = self.http.post(
            "/api/v1/assistant/attachments",
            files={"file": (path.name, path.read_bytes(), "image/png")},
            headers=self._headers(username),
        )
        if response.status_code >= 400:
            raise JourneyError(f"attachment upload failed: {response.status_code} {response.text}")
        payload = response.json()
        attachment = payload.get("attachment") if isinstance(payload, dict) else None
        return attachment or payload

    def approve(self, username: str, approval_id: str, comment: str) -> dict[str, Any]:
        response = self.http.post(
            f"/api/v1/admin/approvals/{approval_id}/approve",
            json={"comment": comment},
            headers=self._headers(username),
        )
        if response.status_code >= 400:
            raise JourneyError(f"approval failed: {response.status_code} {response.text}")
        return response.json()

    def work(self, username: str) -> dict[str, Any]:
        response = self.http.get("/api/v1/assistant/work", headers=self._headers(username))
        response.raise_for_status()
        return response.json()

    def start_task(self, username: str, task_id: str) -> dict[str, Any]:
        response = self.http.post(
            f"/api/v1/assistant/work/tasks/{task_id}/start", headers=self._headers(username)
        )
        if response.status_code >= 400:
            raise JourneyError(f"task start failed: {response.status_code} {response.text}")
        return response.json()

    def complete_task(
        self, username: str, task_id: str, summary: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        response = self.http.post(
            f"/api/v1/assistant/work/tasks/{task_id}/complete",
            json={"summary": summary, "result": result},
            headers=self._headers(username),
        )
        if response.status_code >= 400:
            raise JourneyError(f"task completion failed: {response.status_code} {response.text}")
        return response.json()

    def sse_smoke(self, username: str, *, timeout: float = 20.0) -> dict[str, Any]:
        """Read the first situation frame from the SSE subscription."""
        deadline = time.time() + timeout
        with self.http.stream(
            "GET", "/api/v1/scenic/stream", headers=self._headers(username)
        ) as response:
            response.raise_for_status()
            event_name = None
            event_id = None
            for line in response.iter_lines():
                if time.time() > deadline:
                    raise JourneyError("SSE stream did not deliver a frame in time")
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                elif line.startswith("id: "):
                    event_id = int(line[len("id: ") :])
                elif line == "" and event_name and event_id is not None:
                    return {"event": event_name, "sequence": event_id}
        raise JourneyError("SSE stream closed before delivering a frame")


def _find_alert(snapshot: dict[str, Any], rule_code: str) -> dict[str, Any]:
    for alert in snapshot.get("alerts", []):
        if alert.get("rule_code") == rule_code:
            return alert
    raise JourneyError(f"alert {rule_code} is missing from the situation snapshot")


def _find_task(work: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in work.get("tasks", []):
        if task.get("id") == task_id:
            return task
    raise JourneyError(f"task {task_id} is missing from the field work list")


def run_journey(
    client: ScenicClient,
    *,
    attachment_path: Path | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    steps = evidence.setdefault("steps", [])

    def record(name: str, actor: str, detail: dict[str, Any]) -> None:
        steps.append(
            {
                "step": name,
                "actor": actor,
                "at": datetime.now(timezone.utc).isoformat(),
                "detail": detail,
            }
        )

    for username in ("simulation-ops", "wangfang", "liming", "chenyu"):
        identity = client.login(username)
        record(
            f"login:{username}",
            username,
            {"role": identity["role"], "venue_id": identity["venue_id"]},
        )

    prepared = client.input_command(
        "simulation-ops", "PREPARE_SCENARIO", {"scenario_key": "rain_vehicle_east_gate"}, "prepare"
    )
    record(
        "prepare_scenario",
        "simulation-ops",
        {"scenario_key": prepared.get("scenario_key"), "status": prepared.get("status")},
    )

    client.input_command("simulation-ops", "CLOCK_STEP", {"seconds": 2}, "step-fault")
    snapshot = client.snapshot("wangfang")
    device_alert = _find_alert(snapshot, "VEHICLE_12_RIGHT_REAR_WHEEL")
    record(
        "device_alert",
        "simulation-ops",
        {"alert_id": device_alert["id"], "severity": device_alert.get("severity")},
    )

    incident = client.command(
        "wangfang",
        "CONVERT_ALERT",
        {"alert_ids": [device_alert["id"]]},
        "convert-alert",
    )
    record(
        "convert_alert",
        "wangfang",
        {
            "incident_id": incident["incident_id"],
            "lifecycle": incident["lifecycle"],
            "priority": incident.get("priority", "P1"),
        },
    )

    attachment_id = None
    if attachment_path is not None and attachment_path.is_file():
        attachment = client.upload_attachment("liming", attachment_path)
        attachment_id = attachment.get("id") or attachment.get("attachment_id")
        if not attachment_id:
            raise JourneyError(f"attachment upload returned no identifier: {attachment}")
        if attachment.get("scan_status") not in {"PASSED", "CLEAN"}:
            raise JourneyError(f"attachment scan status is not usable: {attachment.get('scan_status')}")
        record("attach_photo", "liming", {"attachment_id": attachment_id})
    else:
        raise JourneyError(f"field evidence image is missing: {attachment_path}")

    field_evidence = client.command(
        "liming",
        "ADD_EVIDENCE",
        {
            "incident_id": incident["incident_id"],
            "text": "右后轮异响并伴随明显振动，现场已设置停运标识，等待检修班组复核。",
            "attachment_id": attachment_id,
        },
        "liming-evidence",
    )
    record(
        "field_evidence",
        "liming",
        {
            "evidence_id": field_evidence.get("id"),
            "attachment_id": field_evidence.get("attachment_id"),
        },
    )
    if field_evidence.get("attachment_id") != attachment_id:
        raise JourneyError("field evidence was recorded without the uploaded image")

    retrieval = client.command(
        "wangfang",
        "RETRIEVE_SOP",
        {"incident_id": incident["incident_id"], "query": "雨后观光车复运检查和东门客流分流"},
        "retrieve-sop",
    )
    hits = retrieval.get("hits") or []
    if not hits:
        raise JourneyError("SOP retrieval returned no hits from pgvector")
    record(
        "retrieve_sop",
        "wangfang",
        {
            "backend": retrieval.get("backend"),
            "top_hit": hits[0].get("id"),
            "top_score": hits[0].get("score"),
            "source_type": (hits[0].get("metadata") or {}).get("source_type"),
        },
    )

    # High-risk vehicle decisions are rate limited per venue, so a second journey inside the
    # cooldown window is refused by design. Wait the cooldown out and dispatch again.
    cooldown_wait = 65
    for attempt in (1, 2):
        try:
            dispatched = client.command(
                "wangfang",
                "CREATE_REPAIR_TASK",
                {"incident_id": incident["incident_id"]},
                "dispatch-repair",
            )
            break
        except JourneyError as exc:
            if attempt == 2 or "did not enter approval" not in str(exc):
                raise
            record(
                "dispatch_repair_cooldown",
                "wangfang",
                {"waited_seconds": cooldown_wait, "reason": str(exc)},
            )
            time.sleep(cooldown_wait)
    repair_task_id = dispatched["task"]["id"]
    approval_id = dispatched["approval_id"]
    record(
        "dispatch_repair",
        "wangfang",
        {
            "task_id": repair_task_id,
            "assigned_user_id": dispatched["task"]["assigned_user_id"],
            "approval_id": approval_id,
            "lifecycle": dispatched["lifecycle"],
        },
    )

    approval = client.approve(
        "wangfang", approval_id, "批准继续停运 12 号车并启用 7 号备用车。"
    )
    record(
        "approve_suspension",
        "wangfang",
        {"approved": approval.get("approved"), "approval_id": approval_id},
    )

    work = client.work("chenyu")
    task = _find_task(work, repair_task_id)
    started = client.start_task("chenyu", repair_task_id)
    record(
        "accept_repair_task",
        "chenyu",
        {"task_id": repair_task_id, "status": started["task"]["status"], "was": task["status"]},
    )
    completed = client.complete_task(
        "chenyu",
        repair_task_id,
        "确认右后轮轴承异常，12 号车保持停运，7 号备用车检查合格。",
        {
            "vehicle_12": "ISOLATED",
            "backup_vehicle_7": "READY",
            "inspection": "右后轮轴承间隙超标，制动与底盘无异常",
        },
    )
    record(
        "submit_repair_result",
        "chenyu",
        {"task_id": repair_task_id, "status": completed["task"]["status"]},
    )

    client.input_command("simulation-ops", "CLOCK_STEP", {"seconds": 30}, "step-crowd")
    snapshot = client.snapshot("wangfang")
    crowd_alert = _find_alert(snapshot, "EAST_GATE_CAPACITY")
    record(
        "crowd_alert",
        "simulation-ops",
        {"alert_id": crowd_alert["id"], "severity": crowd_alert.get("severity")},
    )

    diversion = client.command(
        "wangfang",
        "CREATE_DIVERSION_TASK",
        {"incident_id": incident["incident_id"]},
        "dispatch-diversion",
    )
    diversion_task_id = diversion["task"]["id"]
    record(
        "dispatch_diversion",
        "wangfang",
        {
            "task_id": diversion_task_id,
            "assigned_user_id": diversion["task"]["assigned_user_id"],
        },
    )
    client.start_task("liming", diversion_task_id)
    client.complete_task(
        "liming",
        diversion_task_id,
        "东门启用单向分流，游客引导至镜湖游览区，现场秩序恢复。",
        {"diversion_route": "EAST_GATE_TO_MIRROR_LAKE", "reported_crowd": "NORMAL"},
    )
    record("submit_diversion_receipt", "liming", {"task_id": diversion_task_id, "status": "DONE"})

    client.input_command("simulation-ops", "CLOCK_STEP", {"seconds": 60}, "step-recovery")
    resolved = client.command(
        "wangfang",
        "RESOLVE_INCIDENT",
        {"incident_id": incident["incident_id"]},
        "resolve-incident",
    )
    record("resolve_incident", "wangfang", {"lifecycle": resolved["lifecycle"]})
    closed = client.command(
        "wangfang",
        "CLOSE_INCIDENT",
        {"incident_id": incident["incident_id"]},
        "close-incident",
    )
    record(
        "close_incident",
        "wangfang",
        {"lifecycle": closed["lifecycle"], "dossier_ready": closed.get("dossier_ready")},
    )

    sse = client.sse_smoke("wangfang")
    record("sse_subscription", "wangfang", sse)

    final = client.snapshot("wangfang")
    dossier = next(
        (
            item
            for item in final.get("incidents", [])
            if item.get("incident_id") == incident["incident_id"]
        ),
        None,
    )
    if dossier is None:
        raise JourneyError("closed incident is missing from the final snapshot")
    if dossier.get("lifecycle") != "CLOSED":
        raise JourneyError(f"incident did not close: {dossier.get('lifecycle')}")

    tasks: dict[str, dict[str, Any]] = {}
    for field_user in ("chenyu", "liming"):
        for item in client.work(field_user).get("tasks", []):
            tasks[item["id"]] = item
    alerts = {item["id"]: item for item in final.get("alerts", [])}
    for task_id in (repair_task_id, diversion_task_id):
        observed = tasks.get(task_id)
        if observed is None:
            raise JourneyError(
                f"task {task_id} is missing from the field work lists; "
                f"known ids: {sorted(tasks)}"
            )
        if observed.get("status") != "DONE":
            raise JourneyError(f"task {task_id} is {observed.get('status')} after the journey")
    for alert_id in (device_alert["id"], crowd_alert["id"]):
        if alerts.get(alert_id, {}).get("status") != "RECOVERED":
            raise JourneyError(f"alert {alert_id} is not RECOVERED after the journey")

    evidence.update(
        {
        "incident_id": incident["incident_id"],
        "event_id": incident.get("event_id"),
        "final_state": {
            "incident_lifecycle": dossier.get("lifecycle"),
            "dossier_ready": closed.get("dossier_ready"),
            "tasks": {
                task_id: tasks[task_id]["status"]
                for task_id in (repair_task_id, diversion_task_id)
                if task_id in tasks
            },
            "alerts": {
                alert_id: alerts[alert_id]["status"]
                for alert_id in (device_alert["id"], crowd_alert["id"])
                if alert_id in alerts
            },
            "approval_id": approval_id,
            "knowledge_hits": len(hits),
            "latest_sequence": final.get("latest_sequence"),
            # Internal-channel receipts live in scenic_notification_receipts and are captured
            # by the database evidence export; the situation snapshot does not expose them.
        },
        }
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SCENIC_E2E_BASE_URL", "http://127.0.0.1:8090"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "scenic-e2e" / "journey-evidence.json",
    )
    parser.add_argument("--attachment", type=Path, default=DEFAULT_ATTACHMENT)
    args = parser.parse_args()

    password = os.environ.get("SCENIC_E2E_PASSWORD", "").strip()
    if not password:
        raise SystemExit("Set SCENIC_E2E_PASSWORD before running the journey")

    client = ScenicClient(args.base_url, password)
    failure: str | None = None
    evidence: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": client.base_url,
        "steps": [],
    }
    try:
        evidence = run_journey(client, attachment_path=args.attachment, evidence=evidence)
    except Exception as exc:  # noqa: BLE001 - the evidence package records the failure
        failure = f"{type(exc).__name__}: {exc}"
        evidence["failed"] = failure
    finally:
        client.close()

    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if failure is not None:
        raise SystemExit(f"scenic journey failed: {failure}")
    summary = {
        "incident_id": evidence["incident_id"],
        "final_state": evidence["final_state"],
        "steps": [step["step"] for step in evidence["steps"]],
        "evidence": str(args.evidence),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
