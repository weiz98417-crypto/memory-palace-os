"""Contracts for the commander agent."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ...agent_contracts.models import (
    AdviceDecisionRef,
    ClosureFacts,
    ContractModel,
    HIGH_RISK_ACTION_CODES,
    IncidentSnapshot,
    Severity,
    VerifiedKnowledge,
)
from ..context_trigger.contracts import ContextTriggerOutput
from ..memory_ops.contracts import MemoryOpsOutput
from ..router.contracts import RouterOutput


class PlannedAction(ContractModel):
    action_code: str
    description: str
    preconditions: list[str] = Field(default_factory=list)


class DispatchDraft(ContractModel):
    artifact: Literal["DISPATCH_DRAFT"] = "DISPATCH_DRAFT"
    summary: str
    priority: Severity
    immediate_actions: list[PlannedAction]
    required_tools: list[str]
    next_step_check: str
    risk_reason: str
    requires_human_approval: bool


class ClosureSummary(ContractModel):
    artifact: Literal["CLOSURE_SUMMARY"] = "CLOSURE_SUMMARY"
    outcome_summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    sop_refs: list[str] = Field(default_factory=list)
    completed_task_refs: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    alert_recovery_refs: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
    recommended_for_closure: bool


class CommanderInput(ContractModel):
    mode: Literal["DISPATCH_DRAFT", "CLOSURE_SUMMARY"]
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    routing: RouterOutput
    knowledge: VerifiedKnowledge
    prior_advice: MemoryOpsOutput | None = None
    advice_decision: AdviceDecisionRef | None = None
    closure_facts: ClosureFacts | None = None


CommanderDispatchOutput = DispatchDraft
CommanderClosureOutput = ClosureSummary
CommanderOutput = Annotated[
    DispatchDraft | ClosureSummary,
    Field(discriminator="artifact"),
]


def requires_human_approval(draft: DispatchDraft) -> bool:
    """Business policy: a high-risk action always needs approval.

    The model may return ``false``; it can never relax this rule.
    """

    if draft.requires_human_approval:
        return True
    return any(
        action.action_code in HIGH_RISK_ACTION_CODES
        for action in draft.immediate_actions
    )


__all__ = [
    "ClosureSummary",
    "CommanderClosureOutput",
    "CommanderDispatchOutput",
    "CommanderInput",
    "CommanderOutput",
    "DispatchDraft",
    "PlannedAction",
    "requires_human_approval",
]
