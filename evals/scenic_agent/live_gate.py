"""Live acceptance gate: the real trunk, scored by DeepEval.

No credential means failure, never a skip. The candidate text is produced by the same
`IncidentCommand` the product uses, so this gate exercises the real chain rather than a
checked-in fixture.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.memory_palace.agent_contracts.models import (
    AdviceDecisionRef,
    AgentRole,
    ClosureFacts,
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
from src.memory_palace.incident.contracts import IncidentCommandPrior, IncidentCommandRequest
from src.memory_palace.skills.context_trigger.contracts import ContextTriggerOutput
from src.memory_palace.skills.memory_ops.contracts import KnowledgeCitation, MemoryOpsOutput
from src.memory_palace.skills.router.contracts import RouterOutput
from src.memory_palace.incident.runtime import build_incident_agent_registry
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database

from .contracts import ContractViolation, load_deep_golden_cases, load_fast_golden_cases, load_golden_cases
from .metrics import METRIC_CATALOG, THRESHOLDS


@dataclass(frozen=True)
class _EvalDecision:
    allowed: bool
    code: str | None = None
    public_message: str = ""


class _EvalPreflight:
    """Deterministic fault injection for evaluation cases, never used in production."""

    def __init__(self, denials: dict[AgentRole, str]) -> None:
        self._denials = dict(denials)

    async def check(self, *, venue_id: str, role: AgentRole) -> _EvalDecision:
        code = self._denials.get(role)
        if code is None:
            return _EvalDecision(allowed=True)
        return _EvalDecision(
            allowed=False,
            code=code,
            public_message="评测故障注入：该环节按用例预期降级",
        )


def _fault_plan(case: dict[str, Any]) -> tuple[dict[AgentRole, float], dict[AgentRole, str]]:
    """Translate a case's declared degradation into a deterministic live fault."""

    degradations = set(case.get("allowed_degradations") or [])
    if not degradations:
        return {}, {}
    role = (
        AgentRole.MEMORY_OPS
        if case.get("artifact") == "ADVICE"
        else AgentRole.COMMANDER
    )
    timeouts: dict[AgentRole, float] = {}
    denials: dict[AgentRole, str] = {}
    if "TIMEOUT" in degradations:
        timeouts[role] = 0.001
    if "QUOTA_EXCEEDED" in degradations:
        denials[role] = "QUOTA_EXCEEDED"
    if "RETRIEVAL_FAILED" in degradations:
        denials[role] = "RETRIEVAL_FAILED"
    return timeouts, denials


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


def _v2_knowledge(case: dict[str, Any]) -> VerifiedKnowledge:
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
        for hit in case.get("knowledge_hits") or []
    ]
    return VerifiedKnowledge(
        retrieval_snapshot_id=f"eval:{case['id']}",
        sop_hits=[hit for hit in hits if hit.source_type == "SOP"],
        historical_cases=[
            HistoricalCase(
                case_id=hit.source_id,
                business_id=f"eval:{hit.source_id}",
                title=hit.title,
                outcome=hit.excerpt,
                closed_at=1785283200.0,
                excerpt=hit.excerpt,
            )
            for hit in hits
            if hit.source_type == "CASE"
        ],
        experience_hits=[hit for hit in hits if hit.source_type == "EXPERIENCE_CARD"],
    )


def _v2_snapshot(case: dict[str, Any]) -> IncidentSnapshot:
    context = case["incident_context"]
    return IncidentSnapshot(
        incident_id=f"eval-incident-{case['id']}",
        event_id=f"eval-event-{case['id']}",
        business_id=f"EVAL-{case['id']}",
        venue_id=str(context["venue_id"]),
        run_id="eval-run",
        lifecycle="OPEN",
        priority=str(case.get("expected_risk") or "P1"),
        title=str(context.get("incident_title") or case["query"]),
        event_type=str(case.get("category") or "EVAL"),
        raw_text=str(context.get("field_evidence") or case["query"]),
        conversion_reason="EVALUATION_FIXTURE",
        occurred_at=1785283200.0,
    )


def _v2_prior(case: dict[str, Any], knowledge: VerifiedKnowledge) -> IncidentCommandPrior:
    context = ContextTriggerOutput(
        normalized_summary=str(case["query"]),
        triggered=True,
        event_type=str(case.get("category") or "EVAL"),
        severity_hint=str(case.get("expected_risk") or "P1"),
        confidence=0.8,
        knowledge_refs=[hit.source_id for hit in knowledge.sop_hits + knowledge.experience_hits],
    )
    routing = RouterOutput(
        intent="incident_report",
        severity=str(case.get("expected_risk") or "P1"),
        summary=str(case["query"]),
        is_critical=str(case.get("expected_risk") or "P1") in {"P0", "P1"},
        confidence=0.8,
        risk_reason=str(case.get("failure_mode") or "evaluation"),
    )
    if knowledge.sop_hits or knowledge.experience_hits:
        citations = [
            KnowledgeCitation(
                source_id=hit.source_id,
                source_type=hit.source_type,
                title=hit.title,
                version=hit.version,
                vector_score=hit.vector_score,
                rerank_score=hit.rerank_score,
                excerpt=hit.excerpt,
            )
            for hit in (knowledge.sop_hits + knowledge.experience_hits)[:1]
        ]
        advice = MemoryOpsOutput(
            evidence_status="GROUNDED",
            advice_text="按已核验 SOP 执行。",
            citations=citations,
            confidence=0.8,
        )
    else:
        advice = MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text="没有依据",
            confidence=0.0,
            absence_reason="NO_VERIFIED_SOP",
        )
    return IncidentCommandPrior(
        context=context,
        routing=routing,
        advice_run_id=f"eval-{case['id']}-advice",
        advice=advice,
        advice_state="READY",
    )


def _v2_request(case: dict[str, Any], *, trace_id: str) -> IncidentCommandRequest:
    knowledge = _v2_knowledge(case)
    snapshot = _v2_snapshot(case)
    field_evidence = [
        FieldEvidence(
            evidence_id=f"eval-evidence-{case['id']}",
            evidence_type="OBSERVATION",
            text=str(case["incident_context"].get("field_evidence") or ""),
            submitted_by="eval-operator",
            submitted_at=1785283200.0,
        )
    ]
    artifact = case["artifact"]
    if artifact == "ADVICE":
        mode = CommandMode.ADVICE
        prior = None
        decision = None
        facts = None
    elif artifact == "DISPATCH_DRAFT":
        mode = CommandMode.DISPATCH_DRAFT
        prior = _v2_prior(case, knowledge)
        decision = AdviceDecisionRef(
            decision_id=f"eval-decision-{case['id']}",
            advice_run_id=prior.advice_run_id,
            incident_id=snapshot.incident_id,
            decision="ADOPT" if knowledge.sop_hits or knowledge.experience_hits else "PROCEED_WITHOUT_WAITING",
            decided_by="eval-manager",
            decided_at=1785283200.0,
            reason_ref="EVAL",
        )
        facts = None
    else:
        mode = CommandMode.CLOSURE_SUMMARY
        prior = _v2_prior(case, knowledge)
        decision = None
        facts = ClosureFacts(
            evidence_refs=["eval-evidence"],
            sop_hit_refs=[hit.source_id for hit in knowledge.sop_hits],
            completed_task_refs=["eval-task"],
            approval_refs=["eval-approval"],
            alert_recovery_refs=["eval-alert"],
        )
    return IncidentCommandRequest(
        mode=mode,
        trace_id=trace_id,
        idempotency_key=f"eval:{case['id']}:{mode.value}:1",
        incident=snapshot,
        field_evidence=field_evidence,
        knowledge=knowledge,
        prior=prior,
        advice_decision=decision,
        closure_facts=facts,
    )


def _assert_v2_contract(case: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    expected_artifact = case["artifact"]
    if observed["mode"] != expected_artifact:
        raise ContractViolation(f"{case['id']} returned {result.mode.value}, expected {expected_artifact}")
    if observed["outcome"] != case["expected_outcome"]:
        raise ContractViolation(
            f"{case['id']} outcome={observed['outcome']}, expected {case['expected_outcome']}"
        )
    artifact = observed["advice"] if expected_artifact == "ADVICE" else observed["dispatch_draft"] if expected_artifact == "DISPATCH_DRAFT" else observed["closure_summary"]
    if case["expected_outcome"] == "READY" and artifact is None:
        raise ContractViolation(f"{case['id']} did not return {expected_artifact}")
    if case["expected_outcome"] in {"FAILED", "DEGRADED"} and not observed["degradations"]:
        raise ContractViolation(f"{case['id']} did not report degradation/failure")
    if observed["advice"] is not None:
        if observed["advice"]["evidence_status"] != case["evidence_status"]:
            raise ContractViolation(
                f"{case['id']} evidence={observed['advice']['evidence_status']}, expected {case['evidence_status']}"
            )
        if case["evidence_status"] == "NO_EVIDENCE" and observed["advice"]["advice_text"] != "没有依据":
            raise ContractViolation(f"{case['id']} must say 没有依据")
    return {
        "metric": f"{expected_artifact}Contract",
        "score": 1.0,
        "threshold": 0.8,
        "success": True,
        "reason": "Observed result satisfied the Deep Golden artifact contract.",
    }

async def _run_case(case: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
    return await asyncio.wait_for(
        _run_case_inner(case, trace_id=trace_id), timeout=240
    )


async def _run_case_inner(case: dict[str, Any], *, trace_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        database = AsyncDBClient(Path(tmp) / "eval.db")
        try:
            await init_database(database)
            timeouts, denials = _fault_plan(case)
            command = PydanticAIIncidentCommand(
                agent_registry=build_incident_agent_registry(),
                call_recorder=LLMCallLogRecorder(database),
                config=IncidentCommandConfig(timeout_seconds=timeouts),
                preflight=_EvalPreflight(denials) if denials else None,
            )
            request = (
                _v2_request(case, trace_id=trace_id)
                if "artifact" in case
                else _request(case, trace_id=trace_id)
            )
            result = await command.execute(request)
            rows = await database.fetch_all(
                "SELECT agent_id, model_name, total_tokens, is_mock FROM llm_call_logs "
                "WHERE venue_id = ?",
                (case["incident_context"]["venue_id"],),
            )
        finally:
            await database.close()
    return {
        "mode": result.mode.value,
        "outcome": result.outcome,
        "artifact": result.advice and "ADVICE" or result.dispatch_draft and "DISPATCH_DRAFT" or result.closure_summary and "CLOSURE_SUMMARY",
        "advice": result.advice.model_dump(mode="json") if result.advice else None,
        "dispatch_draft": result.dispatch_draft.model_dump(mode="json") if result.dispatch_draft else None,
        "closure_summary": result.closure_summary.model_dump(mode="json") if result.closure_summary else None,
        "degradations": [d.model_dump(mode="json") for d in result.degradations],
        "call_refs": [ref.model_dump(mode="json") for ref in result.call_refs],
        "call_rows": [dict(row) for row in rows],
    }


def _assert_real_calls(observed: dict[str, Any], *, minimum_rows: int = 3) -> None:
    rows = observed["call_rows"]
    if len(rows) < minimum_rows:
        raise ContractViolation(
            f"live evaluation needs {minimum_rows} real call records, got {len(rows)}"
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


def run_live(report_path: str | None = None, *, tier: str = "smoke") -> dict[str, Any]:
    """Run the real trunk per selected golden tier and score outputs."""

    from .run_deepeval import _build_judge, _measure_grounded, _measure_no_evidence
    from .contracts import require_model_credential

    api_key = require_model_credential()
    judge = _build_judge(api_key)
    if tier == "fast":
        cases = load_fast_golden_cases()
    elif tier == "deep":
        cases = load_deep_golden_cases()
    elif tier == "all":
        cases = load_golden_cases() + load_fast_golden_cases() + load_deep_golden_cases()
    else:
        cases = load_golden_cases()
    results: list[dict[str, Any]] = []
    all_success = True

    for index, case in enumerate(cases):
        trace_id = f"{index + 1:08x}" * 4
        observed = asyncio.run(_run_case(case, trace_id=trace_id))
        _timeouts, denials = _fault_plan(case)
        _assert_real_calls(observed, minimum_rows=2 if denials else 3)
        if "artifact" in case:
            metric = _assert_v2_contract(case, observed)
            scenario_type = case["category"]
            dataset_version = case["dataset_version"]
            source = case["source"]
        else:
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
            scenario_type = case["scenario_type"]
            dataset_version = "legacy-v1"
            source = "expert"

        metric_success = bool(metric.get("success"))
        all_success = all_success and metric_success
        results.append(
            {
                "case_id": case["id"],
                "scenario_type": scenario_type,
                "candidate_kind": "LIVE_MODEL_OUTPUT",
                "outcome": observed["outcome"],
                "artifact": observed.get("artifact"),
                "dataset_version": dataset_version,
                "source": source,
                "metric": metric["metric"],
                "threshold": metric["threshold"],
                "status": "PASS" if metric_success else "FAIL",
                "failure": None if metric_success else metric.get("reason"),
                "call_records": len(observed["call_rows"]),
                "measured_token_rows": sum(
                    1 for row in observed["call_rows"] if int(row["total_tokens"]) > 0
                ),
                "degradations": observed["degradations"],
                **metric,
            }
        )

    report = {
        "mode": "live",
        "tier": tier,
        "candidate_source": "REAL_INCIDENT_COMMAND",
        "candidate_not_model_output": False,
        "judge_model": __import__("os").environ.get("SCENIC_EVAL_MODEL")
        or __import__("os").environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash",
        "case_count": len(cases),
        "metric_catalog": METRIC_CATALOG,
        "thresholds": THRESHOLDS,
        "results": results,
        "success": all_success,
    }
    if report_path:
        from .run_deepeval import _write_report

        _write_report(report_path, report)
    return report


__all__ = ["run_live"]
