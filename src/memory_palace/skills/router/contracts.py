"""Contracts for the router agent."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...agent_contracts.models import (
    ContractModel,
    FieldEvidence,
    IncidentSnapshot,
    Severity,
)
from ..context_trigger.contracts import ContextTriggerOutput


class RouterInput(ContractModel):
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    field_evidence: list[FieldEvidence] = Field(default_factory=list)


class RouterOutput(ContractModel):
    intent: Literal["incident_report", "emergency_advice", "chitchat", "other"]
    severity: Severity
    summary: str
    is_critical: bool
    confidence: float = Field(ge=0.0, le=1.0)
    risk_reason: str
    risk_codes: list[str] = Field(default_factory=list)


__all__ = ["RouterInput", "RouterOutput"]
