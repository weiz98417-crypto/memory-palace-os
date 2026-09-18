"""IncidentCommand input/output contracts.

`IncidentCommand` is the single deep seam of the scenic Agent trunk: callers submit
already tenant-verified facts and receive structured artifacts plus call-record
references. It never queries pgvector, writes the event state machine, or dispatches.

Decision source: `docs/architecture/incident-command-contract.md` (ticket 04).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..agent_contracts.models import (
    AdviceDecisionRef,
    AgentDegradation,
    ClosureFacts,
    CommandMode,
    ContractModel,
    FieldEvidence,
    IncidentSnapshot,
    ModelCallRef,
    VerifiedKnowledge,
)
from ..skills.commander.contracts import ClosureSummary, DispatchDraft
from ..skills.context_trigger.contracts import ContextTriggerOutput
from ..skills.memory_ops.contracts import MemoryOpsOutput
from ..skills.router.contracts import RouterOutput


class IncidentCommandPrior(ContractModel):
    context: ContextTriggerOutput
    routing: RouterOutput
    advice_run_id: str | None = None
    advice: MemoryOpsOutput | None = None
    advice_state: Literal[
        "PENDING",
        "RUNNING",
        "READY",
        "FAILED",
        "SUPERSEDED",
        "UNAVAILABLE",
    ]


class IncidentCommandRequest(ContractModel):
    mode: CommandMode
    trace_id: str
    idempotency_key: str
    attempt: int = Field(default=1, ge=1)
    incident: IncidentSnapshot
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    knowledge: VerifiedKnowledge
    prior: IncidentCommandPrior | None = None
    advice_decision: AdviceDecisionRef | None = None
    closure_facts: ClosureFacts | None = None

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        lowered = value.lower()
        if (
            len(lowered) != 32
            or lowered == "0" * 32
            or any(ch not in "0123456789abcdef" for ch in lowered)
        ):
            raise ValueError("trace_id must be a non-zero W3C 32-hex trace id")
        return lowered

    @model_validator(mode="after")
    def validate_phase(self) -> "IncidentCommandRequest":
        if not self.incident.venue_id:
            raise ValueError("venue_id is required")
        if self.mode == CommandMode.DISPATCH_DRAFT:
            if self.prior is None or self.advice_decision is None:
                raise ValueError(
                    "dispatch draft requires prior context and a flow-gate decision"
                )
            decision = self.advice_decision
            if decision.incident_id != self.incident.incident_id:
                raise ValueError("flow-gate decision belongs to another incident")
            if not self.prior.advice_run_id:
                raise ValueError("flow gate requires a stable advice run id")
            if (
                decision.advice_run_id
                and decision.advice_run_id != self.prior.advice_run_id
            ):
                raise ValueError("flow-gate decision belongs to another advice run")
            if self.prior.advice_state in {"PENDING", "RUNNING"} and self.prior.advice:
                raise ValueError("pending/running advice cannot already contain a result")
            if (
                self.prior.advice_state in {"FAILED", "UNAVAILABLE"}
                and self.prior.advice
            ):
                raise ValueError(
                    "failed/unavailable advice cannot contain a normal result"
                )
            if self.prior.advice_state == "READY":
                if self.prior.advice is None:
                    raise ValueError("READY advice state requires the advice artifact")
                if self.prior.advice.evidence_status == "GROUNDED":
                    if decision.decision not in {"ADOPT", "IGNORE"}:
                        raise ValueError("grounded ready advice requires adopt or ignore")
                elif self.prior.advice.evidence_status == "NO_EVIDENCE":
                    if decision.decision not in {"IGNORE", "PROCEED_WITHOUT_WAITING"}:
                        raise ValueError("no-evidence advice cannot be adopted")
                elif self.prior.advice.evidence_status == "RETRIEVAL_FAILED":
                    if decision.decision not in {"IGNORE", "PROCEED_WITHOUT_WAITING"}:
                        raise ValueError("retrieval-failed advice cannot be adopted")
                else:
                    raise ValueError("READY advice must contain a terminal evidence status")
            elif decision.decision in {"ADOPT", "IGNORE"}:
                raise ValueError("adopt/ignore requires READY advice")
        if self.mode == CommandMode.CLOSURE_SUMMARY:
            if self.prior is None or self.closure_facts is None:
                raise ValueError("closure summary requires prior context and closure facts")
        return self


class IncidentCommandResult(ContractModel):
    command_id: str
    mode: CommandMode
    trace_id: str
    idempotency_key: str
    outcome: Literal["READY", "DEGRADED", "FAILED"]
    context: ContextTriggerOutput
    routing: RouterOutput
    advice: MemoryOpsOutput | None = None
    dispatch_draft: DispatchDraft | None = None
    closure_summary: ClosureSummary | None = None
    call_refs: list[ModelCallRef] = Field(default_factory=list)
    degradations: list[AgentDegradation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_artifact(self) -> "IncidentCommandResult":
        if self.outcome == "READY" and self.degradations:
            raise ValueError("READY result cannot contain degradations")
        if self.outcome == "DEGRADED" and not self.degradations:
            raise ValueError("DEGRADED result requires at least one degradation")
        if self.dispatch_draft and self.closure_summary:
            raise ValueError("one result cannot contain two commander artifacts")
        if self.mode == CommandMode.ADVICE:
            if self.dispatch_draft or self.closure_summary:
                raise ValueError("ADVICE cannot return commander artifacts")
            if self.outcome == "READY" and self.advice is None:
                raise ValueError("successful ADVICE requires advice")
        if self.mode == CommandMode.DISPATCH_DRAFT:
            if self.advice is not None or self.closure_summary:
                raise ValueError("DISPATCH_DRAFT returns only a dispatch draft")
            if self.outcome == "READY" and self.dispatch_draft is None:
                raise ValueError("successful DISPATCH_DRAFT requires a draft")
        if self.mode == CommandMode.CLOSURE_SUMMARY:
            if self.advice is not None or self.dispatch_draft:
                raise ValueError("CLOSURE_SUMMARY returns only a closure summary")
            if self.outcome == "READY" and self.closure_summary is None:
                raise ValueError("successful CLOSURE_SUMMARY requires a summary")
        return self


__all__ = [
    "IncidentCommandPrior",
    "IncidentCommandRequest",
    "IncidentCommandResult",
]
