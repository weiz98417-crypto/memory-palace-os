"""Live acceptance gate: the real trunk, scored by DeepEval.

No credential means failure, never a skip. The candidate text is produced by the same
`IncidentCommand` the product uses, so this gate exercises the real chain rather than a
checked-in fixture.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from src.memory_palace.agent_contracts.models import (
    CommandMode,
    FieldEvidence,
    HistoricalCase,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.contracts import IncidentCommandRequest
from src.memory_palace.incident.runtime import build_incident_agent_registry
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database

from .contracts import ContractViolation, load_golden_cases


def _knowledge(case: dict[str, Any]) -> VerifiedKnowledge:
    hits = [
        KnowledgeHit(
            vector_doc_id=f"eval:{hit['source_id']}",
            source_id=str(hit["source_id"]),
            source_type=str(hit.get("source_type") or "SOP").upper(),
            source_label=str(hit.get("source_type") or "SOP").upper(),
            title=str(hit.get("title") or ""),
            version=str(hit.get("version") or ""),
            vector_score=float(hit.get("vector_score") or 0.8),
            rerank_score=hit.get("rerank_score"),
            excerpt=str(hit.get("excerpt") or ""),
            content_sha256=f"eval-{hit['source_id']}",
        )
        for hit in case["knowledge_hits"]
    ]
    cases = [
        {
            "case_id": hit.source_id,
            "business_id": f"EVAL-{hit.source_id}",
            "title": hit.title,
            "outcome": hit.excerpt,
            "closed_at": 1785283200.0,
            "excerpt": hit.excerpt,
        }
        for hit in hits
        if hit.source_type == "CASE"
    ]
    return VerifiedKnowledge(
        retrieval_snapshot_id=f"eval:{case['id']}",
        sop_hits=[hit for hit in hits if hit.source_type == "SOP"],
        experience_hits=[hit for hit in hits if hit.source_type == "EXPERIENCE_CARD"],
        historical_cases=[HistoricalCase(**item) for item in cases],
    )


def _request(case: dict[str, Any], *, trace_id: str) -> IncidentCommandRequest:
    context = case["incident_context"]
    return IncidentCommandRequest(
        mode=CommandMode.ADVICE,
        trace_id=trace_id,
        idempotency_key=f"eval:{case['id']}:ADVICE:1",
        incident=IncidentSnapshot(
            incident_id=f"eval-incident-{case['id']}",
            event_id=f"eval-event-{case['id']}",
            business_id=f"EVAL-{case['id']}",
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
                evidence_id=f"eval-evidence-{case['id']}",
                evidence_type="OBSERVATION",
                text=str(context.get("field_evidence") or ""),
                submitted_by="eval-operator",
                submitted_at=1785283200.0,
            )
        ],
        knowledge=_knowledge(case),
    )


async def _run_case(case: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
    return await asyncio.wait_for(
        _run_case_inner(case, trace_id=trace_id), timeout=240
    )


async def _run_case_inner(case: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        database = AsyncDBClient(Path(tmp) / "eval.db")
        await init_database(database)
        command = PydanticAIIncidentCommand(
            agent_registry=build_incident_agent_registry(),
            call_recorder=LLMCallLogRecorder(database),
            config=IncidentCommandConfig(),
        )
        result = await command.execute(_request(case, trace_id=trace_id))
        rows = await database.fetch_all(
            "SELECT agent_id, model_name, total_tokens, is_mock FROM llm_call_logs "
            "WHERE venue_id = ?",
            (case["incident_context"]["venue_id"],),
        )
        await database.close()
    return {
        "outcome": result.outcome,
        "advice": result.advice.model_dump(mode="json") if result.advice else None,
        "degradations": [d.model_dump(mode="json") for d in result.degradations],
        "call_refs": [ref.model_dump(mode="json") for ref in result.call_refs],
        "call_rows": [dict(row) for row in rows],
    }


def _assert_real_calls(observed: dict[str, Any]) -> None:
    rows = observed["call_rows"]
    if len(rows) < 3:
        raise ContractViolation(
            f"live evaluation needs three real call records, got {len(rows)}"
        )
    for row in rows:
        if bool(row["is_mock"]):
            raise ContractViolation("live evaluation recorded a mocked call")
        if not str(row["model_name"]) or str(row["model_name"]) == "unknown":
            raise ContractViolation(f"{row['agent_id']} recorded no model name")
    if not any(int(row["total_tokens"]) > 0 for row in rows):
        raise ContractViolation("live evaluation saw no measured token usage at all")


def _assert_case_contract(case: dict[str, Any], observed: dict[str, Any]) -> None:
    advice = observed["advice"]
    if advice is None:
        raise ContractViolation(f"{case['id']} produced no advice")
    expected = case["expected"]
    if advice["evidence_status"] != expected["evidence_status"]:
        raise ContractViolation(
            f"{case['id']} evidence_status={advice['evidence_status']} "
            f"expected {expected['evidence_status']}"
        )
    cited = {citation["source_id"] for citation in advice["citations"]}
    missing = set(expected.get("must_cite_source_ids") or []) - cited
    if missing:
        raise ContractViolation(f"{case['id']} did not cite {sorted(missing)}")
    text = advice["advice_text"]
    for forbidden in expected.get("forbidden_substrings") or []:
        if forbidden in text:
            raise ContractViolation(f"{case['id']} contained forbidden text {forbidden!r}")


def run_live(report_path: str | None = None) -> dict[str, Any]:
    """Run the real trunk per golden case and score it with DeepEval."""

    from .run_deepeval import _build_judge, _measure_grounded, _measure_no_evidence
    from .contracts import require_model_credential

    api_key = require_model_credential()
    judge = _build_judge(api_key)
    cases = load_golden_cases()
    results: list[dict[str, Any]] = []
    all_success = True

    for index, case in enumerate(cases):
        trace_id = f"{index + 1:08x}" * 4
        observed = asyncio.run(_run_case(case, trace_id=trace_id))
        _assert_real_calls(observed)
        _assert_case_contract(case, observed)

        judged_case = dict(case)
        judged_case["calibration_observation"] = {
            "candidate_kind": "LIVE_MODEL_OUTPUT",
            "evidence_status": observed["advice"]["evidence_status"],
            "answer": observed["advice"]["advice_text"],
            "citations": [
                citation["source_id"] for citation in observed["advice"]["citations"]
            ],
        }
        if observed["advice"]["evidence_status"] == "GROUNDED":
            metric = _measure_grounded(judged_case, judge)
        else:
            metric = _measure_no_evidence(judged_case, judge)
        all_success = all_success and bool(metric["success"])
        results.append(
            {
                "case_id": case["id"],
                "scenario_type": case["scenario_type"],
                "candidate_kind": "LIVE_MODEL_OUTPUT",
                "outcome": observed["outcome"],
                "call_records": len(observed["call_rows"]),
                "measured_token_rows": sum(
                    1 for row in observed["call_rows"] if int(row["total_tokens"]) > 0
                ),
                "degradations": [
                    {**d, "advice": observed["advice"]} for d in observed["degradations"]
                ],
                **metric,
            }
        )

    report = {
        "mode": "live",
        "candidate_source": "REAL_INCIDENT_COMMAND",
        "candidate_not_model_output": False,
        "judge_model": __import__("os").environ.get("SCENIC_EVAL_MODEL")
        or __import__("os").environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash",
        "results": results,
        "success": all_success,
    }
    if report_path:
        from .run_deepeval import _write_report

        _write_report(report_path, report)
    return report


__all__ = ["run_live"]
