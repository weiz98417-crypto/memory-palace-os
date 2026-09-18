import pytest
from pydantic import ValidationError

from scripts.scenic_agent_prototype.contracts import (
    Citation,
    CommanderOutput,
    MemoryOpsOutput,
    build_call_record,
)


def test_memory_ops_no_evidence_contract_requires_refusal_and_no_citations():
    with pytest.raises(ValidationError, match="没有依据"):
        MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice="请按人工经验继续处置。",
            citations=[],
        )

    with pytest.raises(ValidationError, match="citation"):
        MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice="没有依据，需人工判断。",
            citations=[Citation(source_id="sop-1", title="伪造依据", version="1.0")],
        )


def test_memory_ops_grounded_contract_requires_a_citation():
    with pytest.raises(ValidationError, match="citation"):
        MemoryOpsOutput(
            evidence_status="GROUNDED",
            advice="继续停运并检查轮组。",
            citations=[],
        )


def test_commander_high_risk_draft_requires_human_approval():
    with pytest.raises(ValidationError, match="human approval"):
        CommanderOutput(
            next_actions=["继续停运 12 号车", "启用 7 号备用车"],
            requires_human_approval=False,
            closure_summary="风险解除后关闭",
        )


def test_build_call_record_uses_real_usage_and_is_mock_honestly():
    record = build_call_record(
        venue_id="venue-scenic",
        incident_id="incident-1",
        mode="ADVICE",
        attempt=1,
        agent_role="memory_ops",
        agent_name="MemoryOps",
        provider="deepseek",
        model_name="deepseek-flash",
        request_id="request-real-1",
        prompt_tokens=123,
        completion_tokens=45,
        latency_seconds=1.75,
        trace_id="a" * 32,
        is_mock=False,
    )

    assert record["status"] == "SUCCEEDED"
    assert record["total_tokens"] == 168
    assert record["model_name"] == "deepseek-flash"
    assert record["request_id"] == "request-real-1"
    assert record["is_mock"] is False
    assert record["trace_id"] == "a" * 32

    replay = build_call_record(
        venue_id="venue-scenic",
        incident_id="incident-1",
        mode="ADVICE",
        attempt=1,
        agent_role="memory_ops",
        agent_name="MemoryOps",
        provider="deepseek",
        model_name="deepseek-flash",
        request_id="request-real-1",
        prompt_tokens=123,
        completion_tokens=45,
        latency_seconds=1.75,
        trace_id="a" * 32,
        is_mock=False,
    )
    assert replay["id"] == record["id"]
