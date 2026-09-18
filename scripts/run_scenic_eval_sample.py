"""Deep gate: run the real trunk over a sample and assert the grounded contract."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, "/app")

from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.model_policy import DatabaseModelPreflight
from src.memory_palace.incident.runtime import build_incident_agent_registry
from src.memory_palace.incident.contracts import IncidentCommandRequest
from src.memory_palace.agent_contracts.models import (
    CommandMode,
    FieldEvidence,
    HistoricalCase,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database


def _knowledge(case: dict) -> VerifiedKnowledge:
    hits = [
        KnowledgeHit(
            vector_doc_id="eval:" + str(hit["source_id"]),
            source_id=str(hit["source_id"]),
            source_type=str(hit.get("source_type") or "SOP").upper(),
            source_label=str(hit.get("source_type") or "SOP").upper(),
            title=str(hit.get("title") or ""),
            version=str(hit.get("version") or ""),
            vector_score=float(hit.get("vector_score") or 0.8),
            rerank_score=hit.get("rerank_score"),
            excerpt=str(hit.get("excerpt") or ""),
            content_sha256="eval-" + str(hit["source_id"]),
        )
        for hit in case["knowledge_hits"]
    ]
    historical = [
        HistoricalCase(
            case_id=hit.source_id,
            business_id="EVAL-" + hit.source_id,
            title=hit.title,
            outcome=hit.excerpt,
            closed_at=1785283200.0,
            excerpt=hit.excerpt,
        )
        for hit in hits
        if hit.source_type == "CASE"
    ]
    return VerifiedKnowledge(
        retrieval_snapshot_id="eval:" + case["id"],
        sop_hits=[hit for hit in hits if hit.source_type == "SOP"],
        experience_hits=[hit for hit in hits if hit.source_type == "EXPERIENCE_CARD"],
        historical_cases=historical,
    )


def _request(case: dict, trace_id: str, attempt: int) -> IncidentCommandRequest:
    context = case["incident_context"]
    return IncidentCommandRequest(
        mode=CommandMode.ADVICE,
        trace_id=trace_id,
        idempotency_key="eval:" + case["id"] + ":ADVICE:" + str(attempt),
        attempt=attempt,
        incident=IncidentSnapshot(
            incident_id="eval-incident-" + case["id"],
            event_id="eval-event-" + case["id"],
            business_id="EVAL-" + case["id"],
            venue_id=str(context["venue_id"]),
            run_id="eval-run",
            lifecycle="OPEN",
            priority="P1",
            title=str(context["incident_title"]),
            event_type=str(case["scenario_type"]),
            raw_text=str(context.get("field_evidence") or context["incident_title"]),
            conversion_reason="EVALUATION_FIXTURE",
            occurred_at=1785283200.0,
        ),
        field_evidence=[
            FieldEvidence(
                evidence_id="eval-evidence-" + case["id"],
                evidence_type="OBSERVATION",
                text=str(context.get("field_evidence") or ""),
                submitted_by="eval-operator",
                submitted_at=1785283200.0,
            )
        ],
        knowledge=_knowledge(case),
    )


async def _run_case(case: dict, semaphore: asyncio.Semaphore, attempt: int) -> dict:
    async with semaphore:
        started = time.time()
        scratch = tempfile.TemporaryDirectory()
        database = AsyncDBClient(pathlib.Path(scratch.name) / "eval.db")
        await init_database(database)
        command = PydanticAIIncidentCommand(
            agent_registry=build_incident_agent_registry(),
            call_recorder=LLMCallLogRecorder(database),
            config=IncidentCommandConfig(),
            preflight=DatabaseModelPreflight(database),
        )
        try:
            result = await command.execute(
                _request(case, trace_id=case["trace_id"], attempt=attempt)
            )
            rows = await database.fetch_all(
                "SELECT agent_id, model_name, total_tokens, is_mock FROM llm_call_logs"
            )
        except Exception as exc:
            await database.close()
            scratch.cleanup()
            return {
                "case_id": case["id"],
                "error": type(exc).__name__ + ": " + str(exc)[:200],
                "latency": round(time.time() - started, 1),
            }
        await database.close()
        scratch.cleanup()
        advice = result.advice
        return {
            "case_id": case["id"],
            "scenario_type": case["scenario_type"],
            "expected_status": case["expected"]["evidence_status"],
            "expected_ids": case["expected"]["must_cite_source_ids"],
            "outcome": result.outcome,
            "evidence_status": advice.evidence_status if advice else None,
            "advice_text": advice.advice_text if advice else None,
            "citations": [c.source_id for c in (advice.citations if advice else [])],
            "degradations": [d.code for d in result.degradations],
            "call_refs": len(result.call_refs),
            "real_calls": sum(1 for r in rows if not bool(r["is_mock"])),
            "token_rows": sum(1 for r in rows if int(r["total_tokens"]) > 0),
            "latency": round(time.time() - started, 1),
        }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="/app/evals/scenic_agent/sample_100_cases.json")
    parser.add_argument("--report", default="/tmp/sample-run.json")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    payload = json.loads(pathlib.Path(args.cases).read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.limit:
        cases = cases[: args.limit]
    for index, case in enumerate(cases):
        case["trace_id"] = format(index + 1, "08x") * 4
    print("cases:", len(cases), "| concurrency:", args.concurrency)

    semaphore = asyncio.Semaphore(args.concurrency)
    started = time.time()
    attempt = 1
    results = await asyncio.gather(
        *[_run_case(case, semaphore, attempt) for case in cases]
    )

    def _pass(item: dict) -> bool:
        if item.get("error"):
            return False
        status = item.get("expected_status")
        if status == "GROUNDED":
            if item.get("evidence_status") != "GROUNDED":
                return False
            return any(cid in (item.get("citations") or []) for cid in item.get("expected_ids") or [])
        # NO_EVIDENCE: the contract fixes the refusal wording and forbids citations.
        return (
            item.get("evidence_status") == "NO_EVIDENCE"
            and not (item.get("citations") or [])
            and "\u6ca1\u6709\u4f9d\u636e" == (item.get("advice_text") or "")
        )

    passed = [item for item in results if _pass(item)]
    failed = [item for item in results if not _pass(item)]
    report = {
        "mode": "sample_full_trunk",
        "cases": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": round(len(passed) / max(1, len(results)), 4),
        "elapsed_seconds": round(time.time() - started, 1),
        "results": results,
        "failures": failed,
    }
    pathlib.Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("passed:", len(passed), "/", len(results), "| elapsed:", report["elapsed_seconds"], "s")
    for item in failed[:10]:
        print("  FAIL", item["case_id"], item.get("error") or (
            "expected " + str(item.get("expected_status"))
            + " got " + str(item.get("evidence_status"))
            + " citations=" + str(item.get("citations"))
        ))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
