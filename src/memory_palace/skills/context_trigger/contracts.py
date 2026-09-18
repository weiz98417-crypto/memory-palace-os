"""Contracts for the context_trigger agent."""

from __future__ import annotations

from pydantic import Field

from ...agent_contracts.models import (
    ContractModel,
    FieldEvidence,
    IncidentSnapshot,
    Severity,
    VerifiedKnowledge,
)


class ContextTriggerInput(ContractModel):
    incident: IncidentSnapshot
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    knowledge: VerifiedKnowledge


class ContextTriggerOutput(ContractModel):
    normalized_summary: str
    triggered: bool
    event_type: str
    severity_hint: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    deduplicated_count: int = Field(default=0, ge=0)


__all__ = ["ContextTriggerInput", "ContextTriggerOutput"]
