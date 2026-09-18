"""Run the real scenic Agent prototype end to end."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from scripts.scenic_e2e_journey import JourneyError, ScenicClient
from src.memory_palace.core.event_dossier import build_event_dossier
from src.memory_palace.knowledge.postgres_client import PostgresDBClient

from .contracts import PrototypeRequest
from .db import PrototypeDB, secret_from_env
from .worker import APPROVAL_EVENT_KEY, hatchet, workflow


async def _wait_for_activity(db: PrototypeDB, venue_id: str, event_id: str, activity_type: str):
    deadline = time.time() + 300
    while time.time() < deadline:
        activity = await db.fetch_activity(venue_id, event_id, activity_type)
        if activity:
            return activity
        await asyncio.sleep(2)
    raise TimeoutError(f"timed out waiting for {activity_type}")


async def _wait_for_model_calls(db: PrototypeDB, venue_id: str, trace_id: str):
    deadline = time.time() + 300
    while time.time() < deadline:
        calls = await db.fetch_model_calls(venue_id, trace_id)
        if len(calls) >= 4:
            return calls
        await asyncio.sleep(2)
    raise TimeoutError("timed out waiting for four model call records")


def _extract_task_result(payload: dict[str, Any]) -> dict[str, Any]:
    if "result" in payload and "decision" in payload:
        return payload
    for value in payload.values():
        if isinstance(value, dict) and "result" in value:
            return value
    raise RuntimeError(f"Hatchet result did not contain the prototype task result: {sorted(payload)}")


async def _jaeger_ops(trace_id: str) -> list[str]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"http://jaeger:16686/api/traces/{trace_id}")
        response.raise_for_status()
        payload = response.json()
    if not payload.get("data"):
        raise RuntimeError(f"Jaeger has no trace {trace_id}")
    return [str(span.get("operationName")) for span in payload["data"][0].get("spans", [])]


async def run(args: argparse.Namespace) -> dict[str, Any]:
    password = secret_from_env("SCENIC_ACCOUNT_PASSWORD")
    db = PrototypeDB(
        os.environ.get("DATABASE_URL", "postgresql://mp_user@postgres:5432/memory_palace"),
        password=os.environ.get("PGPASSWORD") or secret_from_env("POSTGRES_PASSWORD"),
    )
    await db.connect()
    client = ScenicClient(args.base_url, password)
    evidence: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "steps": [],
    }

    def record(step: str, detail: dict[str, Any]) -> None:
        evidence["steps"].append(
            {
                "step": step,
                "at": datetime.now(timezone.utc).isoformat(),
                "detail": detail,
            }
        )

    try:
        for username in ("wangfang", "liming"):
            client.login(username)
        alert_id = await db.seed_vehicle_alert(
            venue_id="venue-hq",
            run_label=f"ticket08-{int(time.time())}",
        )
        incident = client.command(
            "wangfang",
            "CONVERT_ALERT",
            {"alert_ids": [alert_id]},
            "prototype-convert",
        )
        record(
            "fixture_seeded",
            {"source": "scenic_situation_alerts", "fixture_only": True, "alert_id": alert_id},
        )
        attachment = client.upload_attachment("liming", args.attachment)
        attachment_id = attachment.get("id") or attachment.get("attachment_id")
        if not attachment_id:
            raise RuntimeError("attachment upload returned no id")
        client.command(
            "liming",
            "ADD_EVIDENCE",
            {
                "incident_id": incident["incident_id"],
                "text": "右后轮异响并伴随明显振动，现场已设置停运标识，等待原型 Agent 复核。",
                "attachment_id": attachment_id,
            },
            "prototype-evidence",
        )
        retrieval = client.command(
            "wangfang",
            "RETRIEVE_SOP",
            {
                "incident_id": incident["incident_id"],
                "query": "雨后观光车复运检查和东门客流分流",
            },
            "prototype-retrieve",
        )
        hit = (retrieval.get("hits") or [None])[0]
        if not hit:
            raise RuntimeError("formal SOP retrieval returned no hit")

        close_before = None
        try:
            client.command(
                "wangfang",
                "CLOSE_INCIDENT",
                {"incident_id": incident["incident_id"]},
                "prototype-close-before",
            )
        except JourneyError as exc:
            close_before = str(exc)
        if not close_before:
            raise RuntimeError("closure gate unexpectedly allowed closure before agent tasks")

        request = PrototypeRequest(
            venue_id="venue-hq",
            incident_id=str(incident["incident_id"]),
            event_id=str(incident["event_id"]),
            query="雨后观光车复运检查和东门客流分流",
            field_evidence="右后轮异响并伴随明显振动，现场已设置停运标识。",
            incident_title="雨后 12 号观光车右后轮异常",
            priority="P1",
            sop_hit={
                "source_id": str(hit["source_id"]),
                "title": str(hit["title"]),
                "version": str(hit["source_version"]),
                "score": float(hit["score"]),
            },
            attempt=1,
        )
        run_ref = workflow.run(request, wait_for_result=False)
        evidence["hatchet_run_id"] = str(run_ref.workflow_run_id)
        record("workflow_started", {"hatchet_run_id": evidence["hatchet_run_id"]})

        ready_activity = await _wait_for_activity(db, request.venue_id, request.event_id, "ADVICE_READY")
        trace_id = str(ready_activity["trace_id"])
        calls = await _wait_for_model_calls(db, request.venue_id, trace_id)
        before_decision = await db.fetch_activity(request.venue_id, request.event_id, "ADVICE_DECIDED")
        if before_decision:
            raise RuntimeError("workflow resumed before the human decision event")
        paused_at = time.time()
        record(
            "human_interrupt_paused",
            {
                "trace_id": trace_id,
                "advice_activity_id": ready_activity["id"],
                "model_call_count": len(calls),
                "paused_at": paused_at,
            },
        )
        await asyncio.sleep(3)

        hatchet.event.push(
            APPROVAL_EVENT_KEY,
            {
                "decision": "ADOPT",
                "decided_by": "scenic-wangfang",
                "reason": "原型人工审批",
            },
            scope=request.incident_id,
        )
        raw_result = await asyncio.wait_for(run_ref.aio_result(), timeout=180)
        result = _extract_task_result(raw_result)
        decided_activity = await _wait_for_activity(db, request.venue_id, request.event_id, "ADVICE_DECIDED")
        record(
            "human_interrupt_resumed",
            {
                "decision_activity_id": decided_activity["id"],
                "pause_duration_seconds": round(time.time() - paused_at, 3),
                "workflow_result": result,
            },
        )

        trace_id = str(result["result"]["trace_id"])
        calls = await _wait_for_model_calls(db, request.venue_id, trace_id)
        real_calls = [
            {
                "id": call["id"],
                "agent_id": call["agent_id"],
                "model_name": call["model_name"],
                "status": call["status"],
                "prompt_tokens": call["prompt_tokens"],
                "completion_tokens": call["completion_tokens"],
                "total_tokens": call["total_tokens"],
                "latency_seconds": call["latency_seconds"],
                "request_id": call["request_id"],
                "is_mock": call["is_mock"],
                "trace_id": call["trace_id"],
            }
            for call in calls
        ]
        if len(real_calls) != 4 or any(call["is_mock"] for call in real_calls):
            raise RuntimeError("prototype did not produce four honest real model calls")
        if any(call["total_tokens"] <= 0 or call["latency_seconds"] <= 0 for call in real_calls):
            raise RuntimeError("real model call token/latency evidence is incomplete")

        event_id = request.event_id
        event = await db.fetch_one(
            "SELECT * FROM confirmed_events WHERE event_id = $1",
            event_id,
        )
        if not event:
            raise RuntimeError("prototype event disappeared")
        dossier_db = PostgresDBClient(dsn=db.dsn)
        try:
            dossier = await build_event_dossier(dossier_db, event=event, venue_id=request.venue_id)
        finally:
            await dossier_db.close()
        if len(dossier.get("model_calls") or []) < 4:
            raise RuntimeError("dossier did not expose model call evidence")
        if not any(
            str(reference.get("technical", {}).get("resource_id")) == str(hit["source_id"])
            for reference in dossier.get("references", [])
        ):
            raise RuntimeError("dossier did not expose the verified SOP reference")

        ops = await _jaeger_ops(trace_id)
        required_ops = {
            "scenic.incident_command",
            "scenic.agent.context_trigger",
            "scenic.agent.router",
            "scenic.agent.memory_ops",
            "scenic.agent.commander",
        }
        if not required_ops.issubset(set(ops)) or ops.count("gen_ai.chat") < 4:
            raise RuntimeError(f"Jaeger trace is incomplete: {sorted(set(ops))}")

        close_after = None
        try:
            client.command(
                "wangfang",
                "CLOSE_INCIDENT",
                {"incident_id": request.incident_id},
                "prototype-close-after",
            )
        except JourneyError as exc:
            close_after = str(exc)
        if not close_after:
            raise RuntimeError("closure gate was bypassed after agent execution")

        evidence.update(
            {
                "incident_id": request.incident_id,
                "event_id": request.event_id,
                "trace_id": trace_id,
                "model_calls": real_calls,
                "dossier": {
                    "model_call_count": len(dossier.get("model_calls") or []),
                    "reference_titles": [ref.get("title") for ref in dossier.get("references", [])],
                    "journey_timeline_types": [
                        entry.get("technical", {}).get("activity_type") for entry in dossier.get("journey_timeline", [])
                    ],
                },
                "jaeger_operations": sorted(set(ops)),
                "closure_gate": {
                    "before": close_before,
                    "after": close_after,
                    "bypassed": False,
                },
                "tei_evidence": result["result"]["tei_evidence"],
            }
        )
        record("closure_gate_verified", {"before": close_before, "after": close_after})
        return evidence
    finally:
        client.close()
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SCENIC_E2E_BASE_URL", "http://nginx"))
    parser.add_argument(
        "--attachment",
        type=Path,
        default=Path("/app/artifacts/scenic-e2e/synthetic-wheel-inspection.png"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("/evidence/ticket-08-evidence.json"),
    )
    args = parser.parse_args()
    evidence_path = args.evidence
    try:
        evidence = asyncio.run(run(args))
    except Exception as exc:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(
                {"failed": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"incident_id": evidence["incident_id"], "trace_id": evidence["trace_id"], "evidence": str(evidence_path)},
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
