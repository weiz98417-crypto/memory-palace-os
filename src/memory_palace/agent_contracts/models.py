"""Shared contract primitives for the scenic Agent trunk.

These types are the vocabulary every agent contract builds on. They live outside the
skill packages so the four skill `contracts.py` modules can import them without
creating an import cycle back into `IncidentCommand`.

Decision source: `docs/architecture/incident-command-contract.md` (ticket 04).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Every agent-facing contract forbids unknown keys."""

    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class CommandMode(StrEnum):
    ADVICE = "ADVICE"
    DISPATCH_DRAFT = "DISPATCH_DRAFT"
    CLOSURE_SUMMARY = "CLOSURE_SUMMARY"


class AgentRole(StrEnum):
    CONTEXT_TRIGGER = "context_trigger"
    ROUTER = "router"
    MEMORY_OPS = "memory_ops"
    COMMANDER = "commander"


class IncidentSnapshot(ContractModel):
    incident_id: str
    event_id: str
    business_id: str
    venue_id: str
    run_id: str
    lifecycle: str
    priority: Severity
    title: str
    event_type: str
    raw_text: str
    conversion_reason: str
    occurred_at: float


class FieldEvidence(ContractModel):
    evidence_id: str
    evidence_type: str
    text: str = ""
    attachment_id: str | None = None
    submitted_by: str
    submitted_at: float


class KnowledgeHit(ContractModel):
    vector_doc_id: str
    source_id: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"]
    source_label: str
    title: str
    version: str
    vector_score: float = Field(ge=0.0, le=1.0)
    rerank_score: float | None = None
    excerpt: str = ""
    content_sha256: str


class HistoricalCase(ContractModel):
    case_id: str
    business_id: str
    title: str
    outcome: str
    closed_at: float
    excerpt: str


class VerifiedKnowledge(ContractModel):
    retrieval_snapshot_id: str
    sop_hits: list[KnowledgeHit] = Field(default_factory=list)
    historical_cases: list[HistoricalCase] = Field(default_factory=list)
    experience_hits: list[KnowledgeHit] = Field(default_factory=list)


class AdviceDecisionRef(ContractModel):
    decision_id: str
    advice_run_id: str | None = None
    incident_id: str
    decision: Literal["ADOPT", "IGNORE", "PROCEED_WITHOUT_WAITING"]
    decided_by: str
    decided_at: float
    reason_ref: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "AdviceDecisionRef":
        if self.decision in {"ADOPT", "IGNORE"} and not self.advice_run_id:
            raise ValueError("adopt/ignore must reference an advice run")
        if self.decision == "IGNORE" and not self.reason_ref:
            raise ValueError("ignore requires a structured reason reference")
        return self


class ClosureFacts(ContractModel):
    evidence_refs: list[str] = Field(default_factory=list)
    sop_hit_refs: list[str] = Field(default_factory=list)
    completed_task_refs: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    alert_recovery_refs: list[str] = Field(default_factory=list)


class ModelCallRef(ContractModel):
    call_id: str
    trace_id: str
    agent_id: str
    agent_name: str
    status: Literal["SUCCEEDED", "SUCCEEDED_NO_USAGE", "FAILED", "MOCKED"]
    is_mock: bool

    @model_validator(mode="after")
    def validate_mock_status(self) -> "ModelCallRef":
        if self.status == "MOCKED" and not self.is_mock:
            raise ValueError("MOCKED status requires is_mock=true")
        if self.status in {"SUCCEEDED", "SUCCEEDED_NO_USAGE"} and self.is_mock:
            raise ValueError("successful real status cannot be marked mock")
        return self


class AgentDegradation(ContractModel):
    agent_role: AgentRole
    code: Literal[
        "DISABLED",
        "TIMEOUT",
        "FAILED",
        "INVALID_OUTPUT",
        "CIRCUIT_OPEN",
        "QUOTA_EXCEEDED",
        "RETRIEVAL_FAILED",
        "USAGE_NOT_REPORTED",
    ]
    public_message: str
    call_id: str | None = None


HIGH_RISK_ACTION_CODES = frozenset(
    {
        "CONTINUE_SUSPENSION",
        "ACTIVATE_BACKUP_VEHICLE",
        "RELEASE_RISK",
        "RESUME_OPERATION",
        "CLOSE_INCIDENT",
    }
)
