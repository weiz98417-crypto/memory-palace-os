"""Contract-layer guardrails for the scenic Agent trunk.

These are the invariants that must survive any future prompt or model change: an agent
contract can never widen grounding, cite unverified knowledge, or relax the human
approval gate on a high-risk action.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.memory_palace.agent_contracts.models import (
    AdviceDecisionRef,
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    ModelCallRef,
    VerifiedKnowledge,
)
from src.memory_palace.incident.contracts import (
    IncidentCommandPrior,
    IncidentCommandRequest,
)
from src.memory_palace.skills.commander.contracts import (
    DispatchDraft,
    PlannedAction,
    requires_human_approval,
)
from src.memory_palace.skills.context_trigger.contracts import ContextTriggerOutput
from src.memory_palace.skills.memory_ops.contracts import (
    KnowledgeCitation,
    MemoryOpsOutput,
    NO_EVIDENCE_TEXT,
    RETRIEVAL_FAILED_TEXT,
)
from src.memory_palace.skills.router.contracts import RouterOutput

TRACE_ID = "a" * 32


def _incident() -> IncidentSnapshot:
    return IncidentSnapshot(
        incident_id="incident-1",
        event_id="event-1",
        business_id="SJ-0001",
        venue_id="venue-alpha",
        run_id="run-1",
        lifecycle="OPEN",
        priority="P1",
        title="\u89c2\u5149\u8f66\u5f02\u54cd",
        event_type="\u8bbe\u5907\u5b89\u5168",
        raw_text="\u4e00\u53f7\u95e8\u6709\u5f02\u54cd",
        conversion_reason="\u4eba\u5de5\u786e\u8ba4",
        occurred_at=1785283200.0,
    )


def _verified_knowledge() -> VerifiedKnowledge:
    return VerifiedKnowledge(
        retrieval_snapshot_id="snapshot-1",
        sop_hits=[
            KnowledgeHit(
                vector_doc_id="sop:venue-alpha:1",
                source_id="1",
                source_type="SOP",
                source_label="SOP",
                title="\u505c\u8fd0 SOP",
                version="1.0",
                vector_score=0.8,
                content_sha256="digest",
            )
        ],
    )


def _context() -> ContextTriggerOutput:
    return ContextTriggerOutput(
        normalized_summary="summary",
        triggered=True,
        event_type="\u8bbe\u5907\u5b89\u5168",
        severity_hint="P1",
        confidence=0.9,
    )


def _routing() -> RouterOutput:
    return RouterOutput(
        intent="emergency_advice",
        severity="P1",
        summary="summary",
        is_critical=True,
        confidence=0.9,
        risk_reason="reason",
    )


def test_grounded_advice_requires_a_citation():
    with pytest.raises(ValidationError):
        MemoryOpsOutput(evidence_status="GROUNDED", advice_text="do it", confidence=0.5)


def test_non_grounded_advice_cannot_cite_knowledge():
    citation = KnowledgeCitation(
        source_id="1",
        source_type="SOP",
        title="t",
        version="1.0",
        vector_score=0.8,
    )
    with pytest.raises(ValidationError):
        MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text=NO_EVIDENCE_TEXT,
            citations=[citation],
            confidence=0.1,
        )


def test_no_evidence_text_is_enforced_by_the_contract_not_the_model():
    with pytest.raises(ValidationError):
        MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text="\u6211\u8ba4\u4e3a\u53ef\u4ee5\u8bd5\u8bd5",
            confidence=0.1,
        )
    assert (
        MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text=NO_EVIDENCE_TEXT,
            confidence=0.1,
        ).evidence_status
        == "NO_EVIDENCE"
    )


def test_retrieval_failure_text_is_fixed():
    assert (
        MemoryOpsOutput(
            evidence_status="RETRIEVAL_FAILED",
            advice_text=RETRIEVAL_FAILED_TEXT,
            confidence=0.0,
        ).advice_text
        == RETRIEVAL_FAILED_TEXT
    )


def test_high_risk_action_forces_human_approval_even_when_the_model_says_no():
    draft = DispatchDraft(
        summary="keep suspended",
        priority="P0",
        immediate_actions=[
            PlannedAction(
                action_code="CONTINUE_SUSPENSION",
                description="\u7ee7\u7eed\u505c\u8fd0",
            )
        ],
        required_tools=[],
        next_step_check="check",
        risk_reason="risk",
        requires_human_approval=False,
    )
    assert draft.requires_human_approval is False
    assert requires_human_approval(draft) is True


def test_low_risk_draft_can_skip_approval():
    draft = DispatchDraft(
        summary="log only",
        priority="P3",
        immediate_actions=[
            PlannedAction(action_code="LOG_EVENT", description="record")
        ],
        required_tools=[],
        next_step_check="check",
        risk_reason="risk",
        requires_human_approval=False,
    )
    assert requires_human_approval(draft) is False


def test_ignore_decision_requires_a_structured_reason():
    with pytest.raises(ValidationError):
        AdviceDecisionRef(
            decision_id="d1",
            advice_run_id="advice-1",
            incident_id="incident-1",
            decision="IGNORE",
            decided_by="manager-1",
            decided_at=1785283200.0,
        )


def test_model_call_ref_cannot_claim_a_mock_success():
    with pytest.raises(ValidationError):
        ModelCallRef(
            call_id="c1",
            trace_id=TRACE_ID,
            agent_id="router",
            agent_name="Router",
            status="SUCCEEDED",
            is_mock=True,
        )
    with pytest.raises(ValidationError):
        ModelCallRef(
            call_id="c1",
            trace_id=TRACE_ID,
            agent_id="router",
            agent_name="Router",
            status="MOCKED",
            is_mock=False,
        )


def test_trace_id_must_be_a_non_zero_w3c_trace():
    for bad in ("", "abc", "0" * 32, "z" * 32):
        with pytest.raises(ValidationError):
            IncidentCommandRequest(
                mode=CommandMode.ADVICE,
                trace_id=bad,
                idempotency_key="k",
                incident=_incident(),
                knowledge=_verified_knowledge(),
            )


def test_dispatch_draft_requires_a_flow_gate_decision():
    with pytest.raises(ValidationError):
        IncidentCommandRequest(
            mode=CommandMode.DISPATCH_DRAFT,
            trace_id=TRACE_ID,
            idempotency_key="k",
            incident=_incident(),
            knowledge=_verified_knowledge(),
        )


def test_grounded_advice_cannot_be_proceeded_without_waiting():
    prior = IncidentCommandPrior(
        context=_context(),
        routing=_routing(),
        advice_run_id="advice-1",
        advice=MemoryOpsOutput(
            evidence_status="GROUNDED",
            advice_text="stop",
            citations=[
                KnowledgeCitation(
                    source_id="1",
                    source_type="SOP",
                    title="t",
                    version="1.0",
                    vector_score=0.8,
                )
            ],
            confidence=0.8,
        ),
        advice_state="READY",
    )
    with pytest.raises(ValidationError):
        IncidentCommandRequest(
            mode=CommandMode.DISPATCH_DRAFT,
            trace_id=TRACE_ID,
            idempotency_key="k",
            incident=_incident(),
            knowledge=_verified_knowledge(),
            prior=prior,
            advice_decision=AdviceDecisionRef(
                decision_id="d1",
                advice_run_id="advice-1",
                incident_id="incident-1",
                decision="PROCEED_WITHOUT_WAITING",
                decided_by="manager-1",
                decided_at=1785283200.0,
                reason_ref="reason-1",
            ),
        )


def test_no_evidence_advice_cannot_be_adopted():
    prior = IncidentCommandPrior(
        context=_context(),
        routing=_routing(),
        advice_run_id="advice-1",
        advice=MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text=NO_EVIDENCE_TEXT,
            confidence=0.1,
        ),
        advice_state="READY",
    )
    with pytest.raises(ValidationError):
        IncidentCommandRequest(
            mode=CommandMode.DISPATCH_DRAFT,
            trace_id=TRACE_ID,
            idempotency_key="k",
            incident=_incident(),
            knowledge=_verified_knowledge(),
            prior=prior,
            advice_decision=AdviceDecisionRef(
                decision_id="d1",
                advice_run_id="advice-1",
                incident_id="incident-1",
                decision="ADOPT",
                decided_by="manager-1",
                decided_at=1785283200.0,
            ),
        )
