"""Build an IncidentCommandRequest from the persisted scenic incident."""

from __future__ import annotations

import uuid
from typing import Any

from ..agent_contracts.models import (
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from ..incident.contracts import IncidentCommandRequest


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


__all__ = ["build_advice_request", "knowledge_hits"]
