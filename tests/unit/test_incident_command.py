"""External behaviour of `IncidentCommand`.

Every assertion goes through `IncidentCommandRequest -> IncidentCommandResult`. The
agents are scripted stand-ins, so the tests describe the trunk's contract rather than
any prompt or provider detail.
"""

from __future__ import annotations

import asyncio

import pytest

from src.memory_palace.agent_contracts.models import (
    AgentRole,
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from src.memory_palace.incident.command import (
    AgentCallOutcome,
    IncidentCommandConfig,
    InMemoryAgentFailureCounter,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.contracts import IncidentCommandRequest
from src.memory_palace.skills.context_trigger.contracts import ContextTriggerOutput
from src.memory_palace.skills.memory_ops.contracts import (
    KnowledgeCitation,
    MemoryOpsOutput,
    NO_EVIDENCE_TEXT,
    RETRIEVAL_FAILED_TEXT,
)
from src.memory_palace.skills.router.contracts import RouterOutput

TRACE_ID = "b" * 32


class ScriptedAgent:
    """Stands in for a pydantic-ai agent. Records the prompt it was handed."""

    def __init__(self, outputs, *, error=None, delay=0.0) -> None:
        self._outputs = list(outputs)
        self._error = error
        self._delay = delay
        self.prompts: list[str] = []
        self.calls = 0

    async def run(self, user_prompt: str):
        self.calls += 1
        self.prompts.append(user_prompt)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        index = min(self.calls - 1, len(self._outputs) - 1)
        output = self._outputs[index]
        if isinstance(output, BaseException):
            raise output
        if callable(output):
            output = output()

        class _Usage:
            input_tokens = 11
            output_tokens = 7

        class _Result:
            pass

        result = _Result()
        result.output = output
        result.usage = _Usage()
        result.model_name = "deepseek-flash"
        result.response = type(
            "R", (), {"model_name": "deepseek-flash", "provider_response_id": "req-1"}
        )()
        return result


class SpyRecorder:
    def __init__(self, *, status="SUCCEEDED", status_by_role=None) -> None:
        self.records: list[dict] = []
        self._status = status
        self._status_by_role = status_by_role or {}

    async def record(self, **kwargs):
        self.records.append(kwargs)
        from src.memory_palace.agent_contracts.models import ModelCallRef

        role = kwargs["role"]
        status = self._status_by_role.get(role, self._status)
        return ModelCallRef(
            call_id=f"call-{len(self.records)}",
            trace_id=kwargs["trace_id"],
            agent_id=role.value,
            agent_name=role.value,
            status=status,
            is_mock=False,
        )

    async def record_failure(self, **kwargs):
        self.records.append({"failed": True, **kwargs})
        from src.memory_palace.agent_contracts.models import ModelCallRef

        return ModelCallRef(
            call_id=f"call-failure-{len(self.records)}",
            trace_id=kwargs["trace_id"],
            agent_id=kwargs["role"].value,
            agent_name=kwargs["role"].value,
            status="FAILED",
            is_mock=False,
        )


class Registry:
    def __init__(self, agents: dict[AgentRole, ScriptedAgent]) -> None:
        self._agents = agents

    def resolve(self, role: AgentRole):
        return self._agents[role]


def _incident(venue_id: str = "venue-alpha") -> IncidentSnapshot:
    return IncidentSnapshot(
        incident_id="incident-1",
        event_id="event-1",
        business_id="SJ-0001",
        venue_id=venue_id,
        run_id="run-1",
        lifecycle="OPEN",
        priority="P1",
        title="\u89c2\u5149\u8f66\u5f02\u54cd",
        event_type="\u8bbe\u5907\u5b89\u5168",
        raw_text="\u4e00\u53f7\u95e8\u6709\u5f02\u54cd",
        conversion_reason="\u4eba\u5de5\u786e\u8ba4",
        occurred_at=1785283200.0,
    )


def _knowledge() -> VerifiedKnowledge:
    return VerifiedKnowledge(
        retrieval_snapshot_id="snapshot-1",
        sop_hits=[
            KnowledgeHit(
                vector_doc_id="sop:venue-alpha:1",
                source_id="1",
                source_type="SOP",
                source_label="\u9632\u95f8\u673a",
                title="\u505c\u8fd0 SOP",
                version="1.0",
                vector_score=0.81,
                rerank_score=0.94,
                excerpt="\u5148\u505c\u8fd0",
                content_sha256="digest-1",
            )
        ],
    )


def _context(**overrides) -> ContextTriggerOutput:
    payload = dict(
        normalized_summary="summary",
        triggered=True,
        event_type="\u8bbe\u5907\u5b89\u5168",
        severity_hint="P1",
        confidence=0.9,
    )
    payload.update(overrides)
    return ContextTriggerOutput(**payload)


def _routing(**overrides) -> RouterOutput:
    payload = dict(
        intent="emergency_advice",
        severity="P1",
        summary="summary",
        is_critical=True,
        confidence=0.9,
        risk_reason="reason",
    )
    payload.update(overrides)
    return RouterOutput(**payload)


def _advice(**overrides) -> MemoryOpsOutput:
    payload = dict(
        evidence_status="GROUNDED",
        advice_text="\u5148\u505c\u8fd0\u518d\u68c0\u4fee",
        citations=[
            KnowledgeCitation(
                source_id="1",
                source_type="SOP",
                title="\u505c\u8fd0 SOP",
                version="1.0",
                vector_score=0.81,
                rerank_score=0.94,
                excerpt="\u5148\u505c\u8fd0",
            )
        ],
        confidence=0.8,
    )
    payload.update(overrides)
    return MemoryOpsOutput(**payload)


def _request(**overrides) -> IncidentCommandRequest:
    payload = dict(
        mode=CommandMode.ADVICE,
        trace_id=TRACE_ID,
        idempotency_key="advice:incident-1:ADVICE:1",
        incident=_incident(),
        field_evidence=[
            FieldEvidence(
                evidence_id="evidence-1",
                evidence_type="PHOTO",
                text="\u8f66\u8f6e\u5f02\u5e38",
                submitted_by="user-1",
                submitted_at=1785283200.0,
            )
        ],
        knowledge=_knowledge(),
    )
    payload.update(overrides)
    return IncidentCommandRequest(**payload)


def _command(agents, *, config=None, counter=None, recorder=None):
    return PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=recorder or SpyRecorder(),
        config=config or IncidentCommandConfig(),
        clock=lambda: 1785283200.0,
        failure_counter=counter or InMemoryAgentFailureCounter(),
    )


@pytest.mark.asyncio
async def test_advice_runs_the_four_agent_chain_in_order_with_grounded_advice():
    context_agent = ScriptedAgent([_context()])
    router_agent = ScriptedAgent([_routing()])
    memory_agent = ScriptedAgent([_advice()])
    recorder = SpyRecorder()
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: context_agent,
            AgentRole.ROUTER: router_agent,
            AgentRole.MEMORY_OPS: memory_agent,
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        recorder=recorder,
    )

    result = await command.execute(_request())

    assert result.outcome == "READY"
    assert result.mode == CommandMode.ADVICE
    assert result.advice is not None
    assert result.advice.evidence_status == "GROUNDED"
    assert result.advice.citations[0].source_id == "1"
    assert result.degradations == []
    assert [ref.agent_id for ref in result.call_refs] == [
        "context_trigger",
        "router",
        "memory_ops",
    ]
    assert [record["role"].value for record in recorder.records] == [
        "context_trigger",
        "router",
        "memory_ops",
    ]
    # Router sees the verified context the previous agent produced.
    import json

    router_prompt = json.loads(router_agent.prompts[0])
    assert router_prompt["context"]["normalized_summary"] == "summary"
    # memory_ops receives only the verified hits plus field evidence.
    memory_prompt = json.loads(memory_agent.prompts[0])
    assert memory_prompt["knowledge"]["retrieval_snapshot_id"] == "snapshot-1"
    assert memory_prompt["field_evidence"][0]["evidence_id"] == "evidence-1"


@pytest.mark.asyncio
async def test_no_verified_knowledge_forces_the_fixed_no_basis_text():
    memory_agent = ScriptedAgent(
        [
            MemoryOpsOutput(
                evidence_status="NO_EVIDENCE",
                advice_text=NO_EVIDENCE_TEXT,
                confidence=0.0,
                absence_reason="\u672a\u547d\u4e2d",
            )
        ]
    )
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: memory_agent,
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        }
    )

    result = await command.execute(
        _request(
            knowledge=VerifiedKnowledge(retrieval_snapshot_id="snapshot-empty")
        )
    )

    assert result.outcome == "READY"
    assert result.advice is not None
    assert result.advice.evidence_status == "NO_EVIDENCE"
    assert result.advice.advice_text == NO_EVIDENCE_TEXT
    assert result.advice.citations == []


@pytest.mark.asyncio
async def test_citation_outside_verified_knowledge_is_downgraded_never_shown():
    memory_agent = ScriptedAgent(
        [
            MemoryOpsOutput(
                evidence_status="GROUNDED",
                advice_text="invented",
                citations=[
                    KnowledgeCitation(
                        source_id="999",
                        source_type="SOP",
                        title="made up",
                        version="9.9",
                        vector_score=0.99,
                    )
                ],
                confidence=0.9,
            )
        ]
    )
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: memory_agent,
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        }
    )

    result = await command.execute(_request())

    assert result.outcome == "DEGRADED"
    assert result.advice is not None
    assert result.advice.evidence_status == "RETRIEVAL_FAILED"
    assert result.advice.advice_text == RETRIEVAL_FAILED_TEXT
    assert result.advice.citations == []
    assert [d.code for d in result.degradations] == ["INVALID_OUTPUT"]


@pytest.mark.asyncio
async def test_single_agent_failure_only_degrades_that_step_and_keeps_business_moving():
    recorder = SpyRecorder()
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: ScriptedAgent(
                [RuntimeError("provider exploded")]
            ),
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        recorder=recorder,
    )

    result = await command.execute(_request())

    assert result.outcome == "DEGRADED"
    assert result.advice is not None
    assert result.advice.evidence_status == "GROUNDED"
    assert [d.code for d in result.degradations] == ["FAILED"]
    assert result.degradations[0].agent_role == AgentRole.CONTEXT_TRIGGER
    # One business attempt means one provider retry, and the failure is recorded.
    assert len([r for r in recorder.records if r.get("failed")]) == 2


@pytest.mark.asyncio
async def test_agent_timeout_retries_once_then_degrades(monkeypatch):
    slow_agent = ScriptedAgent([_context()], delay=0.05)
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: slow_agent,
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        config=IncidentCommandConfig(
            timeout_seconds={AgentRole.CONTEXT_TRIGGER: 0.01}
        ),
    )

    result = await command.execute(_request())

    assert slow_agent.calls == 2
    assert [d.code for d in result.degradations] == ["TIMEOUT"]


@pytest.mark.asyncio
async def test_three_consecutive_failures_open_the_circuit_for_that_agent_only():
    counter = InMemoryAgentFailureCounter()
    context_agent = ScriptedAgent([RuntimeError("boom")])
    router_agent = ScriptedAgent([_routing()])
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: context_agent,
            AgentRole.ROUTER: router_agent,
            AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        counter=counter,
    )

    for _ in range(3):
        await command.execute(_request(idempotency_key=f"k-{counter}"))

    calls_before = context_agent.calls
    result = await command.execute(_request(idempotency_key="k-circuit"))

    assert context_agent.calls == calls_before, "an open circuit must not call the provider"
    assert "CIRCUIT_OPEN" in [d.code for d in result.degradations]
    assert result.outcome == "DEGRADED"


@pytest.mark.asyncio
async def test_disabled_agent_is_reported_without_a_model_call():
    context_agent = ScriptedAgent([_context()])
    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: context_agent,
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        config=IncidentCommandConfig(
            enabled={AgentRole.CONTEXT_TRIGGER: False}
        ),
    )

    result = await command.execute(_request())

    assert context_agent.calls == 0
    assert [d.code for d in result.degradations] == ["DISABLED"]
    assert result.outcome == "DEGRADED"


@pytest.mark.asyncio
async def test_missing_usage_is_reported_honestly_and_marked_degraded():
    class NoUsageAgent(ScriptedAgent):
        async def run(self, user_prompt: str):
            self.calls += 1
            self.prompts.append(user_prompt)

            class _Usage:
                input_tokens = 0
                output_tokens = 0

            class _Result:
                pass

            result = _Result()
            result.output = _context()
            result.usage = _Usage()
            result.response = type("R", (), {})()
            return result

    command = _command(
        {
            AgentRole.CONTEXT_TRIGGER: NoUsageAgent([]),
            AgentRole.ROUTER: ScriptedAgent([_routing()]),
            AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
            AgentRole.COMMANDER: ScriptedAgent([_advice()]),
        },
        recorder=SpyRecorder(
            status_by_role={AgentRole.CONTEXT_TRIGGER: "SUCCEEDED_NO_USAGE"}
        ),
    )

    result = await command.execute(_request())

    assert result.outcome == "DEGRADED"
    assert [d.code for d in result.degradations] == ["USAGE_NOT_REPORTED"]
    assert any(
        ref.status == "SUCCEEDED_NO_USAGE" for ref in result.call_refs
    )
