"""Build an IncidentCommandRequest from the persisted scenic incident."""

from __future__ import annotations

import uuid
from typing import Any

from ..agent_contracts.models import (
    AdviceDecisionRef,
    ClosureFacts,
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from ..incident.contracts import IncidentCommandPrior, IncidentCommandRequest
from ..skills.context_trigger.contracts import ContextTriggerOutput
from ..skills.memory_ops.contracts import MemoryOpsOutput
from ..skills.router.contracts import RouterOutput


def knowledge_hits(incident_view: dict[str, Any]) -> list[KnowledgeHit]:
    """Map persisted scenic knowledge hits onto the trunk contract."""

    hits: list[KnowledgeHit] = []
    for index, row in enumerate(incident_view.get("knowledge_hits") or []):
        source_type = str(row.get("source_type") or "SOP").upper()
        if source_type not in {"SOP", "CASE", "EXPERIENCE_CARD"}:
            continue
        score = float(row.get("score") or 0.0)
        hits.append(
            KnowledgeHit(
                vector_doc_id=str(row.get("vector_doc_id") or row.get("id") or index),
                source_id=str(row.get("source_id") or ""),
                source_type=source_type,
                source_label=source_type,
                title=str(row.get("title") or row.get("source_id") or ""),
                version=str(row.get("source_version") or ""),
                vector_score=min(1.0, max(0.0, score)),
                rerank_score=row.get("rerank_score"),
                excerpt=str(row.get("excerpt") or row.get("query_text") or ""),
                content_sha256=str(row.get("content_sha256") or row.get("id") or ""),
            )
        )
    return hits


async def build_advice_request(
    *, database: Any, venue_id: str, incident_id: str, attempt: int = 1
) -> tuple[IncidentCommandRequest, str]:
    """Assemble the advice request from PostgreSQL; no caller-specific state leaks in."""

    incident = await database.fetch_one(
        "SELECT * FROM scenic_incidents WHERE venue_id = ? AND incident_id = ?",
        (venue_id, incident_id),
    )
    if incident is None:
        raise ValueError("scenic incident was not found")
    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
        (venue_id, incident["event_id"]),
    )
    evidence = await database.fetch_all(
        """
        SELECT * FROM scenic_event_evidence
        WHERE venue_id = ? AND incident_id = ? ORDER BY recorded_at
        """,
        (venue_id, incident_id),
    )
    hit_rows = await database.fetch_all(
        """
        SELECT * FROM scenic_knowledge_hits
        WHERE venue_id = ? AND incident_id = ? ORDER BY recorded_at
        """,
        (venue_id, incident_id),
    )
    hits = knowledge_hits({"knowledge_hits": [dict(row) for row in hit_rows or []]})

    step = CommandMode.ADVICE.value
    snapshot = IncidentSnapshot(
        incident_id=str(incident["incident_id"]),
        event_id=str(incident["event_id"]),
        business_id=str((event or {}).get("business_id") or incident["incident_id"]),
        venue_id=str(incident["venue_id"]),
        run_id=str(incident["run_id"]),
        lifecycle=str(incident["lifecycle"]),
        priority=str(incident["priority"]),
        title=str(incident["title"]),
        event_type=str((event or {}).get("event_type") or ""),
        raw_text=str((event or {}).get("raw_text") or incident["title"]),
        conversion_reason=str(incident["conversion_reason"]),
        occurred_at=float(incident.get("created_at") or 0.0),
    )
    field_evidence = [
        FieldEvidence(
            evidence_id=str(row["id"]),
            evidence_type=str(row["evidence_type"]),
            text=str(row.get("text_content") or ""),
            attachment_id=row.get("attachment_id"),
            submitted_by=str(row["submitted_by"]),
            submitted_at=float(row.get("recorded_at") or 0.0),
        )
        for row in evidence or []
    ]
    request = IncidentCommandRequest(
        mode=CommandMode.ADVICE,
        trace_id=uuid.uuid4().hex,
        idempotency_key=f"advice:{incident_id}:{step}:{attempt}",
        attempt=attempt,
        incident=snapshot,
        field_evidence=field_evidence,
        knowledge=VerifiedKnowledge(
            retrieval_snapshot_id=f"scenic:{incident_id}",
            sop_hits=[hit for hit in hits if hit.source_type == "SOP"],
            experience_hits=[hit for hit in hits if hit.source_type == "EXPERIENCE_CARD"],
        ),
    )
    return request, step


async def build_dispatch_request(
    *, database: Any, venue_id: str, incident_id: str, attempt: int = 1
) -> IncidentCommandRequest:
    """Build a DISPATCH_DRAFT request from the stored flow-gate decision."""

    base, _step = await build_advice_request(
        database=database, venue_id=venue_id, incident_id=incident_id, attempt=attempt
    )
    advice_row = await database.fetch_one(
        """
        SELECT * FROM scenic_commands
        WHERE venue_id = ? AND command_type = 'GENERATE_ADVICE'
          AND idempotency_key LIKE ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (venue_id, f"advice:{incident_id}:%"),
    )
    if advice_row is None:
        raise ValueError("dispatch draft requires an advice run")

    advice_result = _json_object(advice_row.get("response_json"))
    prior_advice = None
    if advice_result.get("advice"):
        prior_advice = MemoryOpsOutput.model_validate(advice_result["advice"])
    prior_context = _prior_context(
        advice_result.get("context"), base.incident, base.field_evidence
    )
    prior_routing = _prior_routing(advice_result.get("routing"), base.incident)

    event = await database.fetch_one(
        "SELECT * FROM confirmed_events WHERE venue_id = ? AND event_id = ?",
        (venue_id, base.incident.event_id),
    )
    activities = await database.fetch_all(
        """
        SELECT * FROM event_activities
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (venue_id, base.incident.event_id),
    )
    decision = None
    for activity in activities or []:
        if str(activity.get("activity_type") or "") not in {
            "ADVICE_DECIDED",
            "ADVICE_SUPERSEDED",
        }:
            continue
        payload = _json_object(activity.get("payload_json"))
        if str(payload.get("advice_run_id") or "") != str(advice_row["id"]):
            continue
        decision = AdviceDecisionRef(
            decision_id=str(activity["id"]),
            advice_run_id=str(advice_row["id"]),
            incident_id=incident_id,
            decision=str(payload.get("decision") or "PROCEED_WITHOUT_WAITING"),
            decided_by=str(activity.get("created_by") or "unknown"),
            decided_at=float(activity.get("created_at") or 0.0),
            reason_ref=payload.get("reason_code"),
        )
        break
    if decision is None:
        raise ValueError("dispatch draft requires a completed flow-gate decision")

    step = CommandMode.DISPATCH_DRAFT.value
    return IncidentCommandRequest(
        mode=CommandMode.DISPATCH_DRAFT,
        trace_id=uuid.uuid4().hex,
        idempotency_key=f"dispatch:{incident_id}:{step}:{attempt}",
        attempt=attempt,
        incident=base.incident,
        field_evidence=base.field_evidence,
        knowledge=base.knowledge,
        prior=IncidentCommandPrior(
            context=prior_context,
            routing=prior_routing,
            advice_run_id=str(advice_row["id"]),
            advice=prior_advice,
            advice_state=str(advice_row["status"]),
        ),
        advice_decision=decision,
    )


def _prior_context(
    value: Any,
    incident: IncidentSnapshot,
    evidence: list[FieldEvidence],
) -> ContextTriggerOutput:
    if isinstance(value, dict):
        try:
            return ContextTriggerOutput.model_validate(value)
        except Exception:
            pass
    return ContextTriggerOutput(
        normalized_summary=incident.raw_text[:400],
        triggered=True,
        event_type=incident.event_type,
        severity_hint=incident.priority,
        confidence=0.0,
        evidence_refs=[item.evidence_id for item in evidence],
        deduplicated_count=0,
    )


def _prior_routing(value: Any, incident: IncidentSnapshot) -> RouterOutput:
    if isinstance(value, dict):
        try:
            return RouterOutput.model_validate(value)
        except Exception:
            pass
    return RouterOutput(
        intent="incident_report",
        severity=incident.priority,
        summary=incident.title,
        is_critical=incident.priority in {"P0", "P1"},
        confidence=0.0,
        risk_reason="dispatch draft uses the persisted incident priority",
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    import json

    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}

async def build_closure_request(
    *, database: Any, venue_id: str, incident_id: str, attempt: int = 1
) -> IncidentCommandRequest:
    base, _step = await build_advice_request(
        database=database, venue_id=venue_id, incident_id=incident_id, attempt=attempt
    )
    advice_row = await database.fetch_one(
        """
        SELECT * FROM scenic_commands
        WHERE venue_id = ? AND command_type = 'GENERATE_ADVICE'
          AND idempotency_key LIKE ?
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (venue_id, f"advice:{incident_id}:%"),
    )
    advice_result = _json_object(advice_row.get("response_json")) if advice_row else {}
    prior_advice = None
    if advice_result.get("advice"):
        prior_advice = MemoryOpsOutput.model_validate(advice_result["advice"])
    evidence = await database.fetch_all(
        "SELECT id FROM scenic_event_evidence WHERE venue_id = ? AND incident_id = ?",
        (venue_id, incident_id),
    )
    hits = await database.fetch_all(
        "SELECT id FROM scenic_knowledge_hits WHERE venue_id = ? AND incident_id = ?",
        (venue_id, incident_id),
    )
    tasks = await database.fetch_all(
        "SELECT id FROM tasks WHERE venue_id = ? AND event_id = ? AND status = 'DONE'",
        (venue_id, base.incident.event_id),
    )
    approvals = await database.fetch_all(
        "SELECT approval_id FROM approval_requests WHERE venue_id = ? AND event_id = ? AND status = 'APPROVED'",
        (venue_id, base.incident.event_id),
    )
    alerts = await database.fetch_all(
        "SELECT id FROM scenic_situation_alerts WHERE venue_id = ? AND incident_id = ? AND status = 'RECOVERED'",
        (venue_id, incident_id),
    )
    step = CommandMode.CLOSURE_SUMMARY.value
    return IncidentCommandRequest(
        mode=CommandMode.CLOSURE_SUMMARY,
        trace_id=uuid.uuid4().hex,
        idempotency_key=f"closure:{incident_id}:{step}:{attempt}",
        attempt=attempt,
        incident=base.incident,
        field_evidence=base.field_evidence,
        knowledge=base.knowledge,
        prior=IncidentCommandPrior(
            context=_prior_context(advice_result.get("context"), base.incident, base.field_evidence),
            routing=_prior_routing(advice_result.get("routing"), base.incident),
            advice_run_id=str(advice_row["id"]) if advice_row else None,
            advice=prior_advice,
            advice_state=str(advice_row["status"]) if advice_row else "UNAVAILABLE",
        ),
        closure_facts=ClosureFacts(
            evidence_refs=[str(row["id"]) for row in evidence or []],
            sop_hit_refs=[str(row["id"]) for row in hits or []],
            completed_task_refs=[str(row["id"]) for row in tasks or []],
            approval_refs=[str(row["approval_id"]) for row in approvals or []],
            alert_recovery_refs=[str(row["id"]) for row in alerts or []],
        ),
    )

__all__ = ["build_advice_request", "build_closure_request", "build_dispatch_request", "knowledge_hits"]
