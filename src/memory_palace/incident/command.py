"""`IncidentCommand`: the single deep seam of the scenic Agent trunk.

Callers submit already tenant-verified facts and receive structured advice, a dispatch
draft, or a closure summary, plus references into `llm_call_logs`. Everything else -
agent order, prompt assembly, grounding checks, per-agent degradation, retry and
circuit breaking - stays behind this seam.

Decision sources:
- `docs/architecture/incident-command-contract.md` (ticket 04)
- `docs/architecture/advice-adoption-semantics.md` (ticket 05)
- ADR-0018 (human keeps the gates), ADR-0020 (dependency lock)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from ..agent_contracts.models import (
    AgentDegradation,
    AgentRole,
    CommandMode,
    ModelCallRef,
)
from ..skills.commander.contracts import (
    ClosureSummary,
    CommanderInput,
    DispatchDraft,
    requires_human_approval,
)
from ..skills.context_trigger.contracts import (
    ContextTriggerInput,
    ContextTriggerOutput,
)
from ..skills.memory_ops.contracts import (
    MemoryOpsInput,
    MemoryOpsOutput,
    NO_EVIDENCE_TEXT,
    RETRIEVAL_FAILED_TEXT,
)
from ..skills.router.contracts import RouterInput, RouterOutput
from .contracts import IncidentCommandRequest, IncidentCommandResult
from .model_policy import AllowAllPreflight, CounterModelPreflight
from .telemetry import agent_span, incident_command_span, record_agent_outcome

OutputT = TypeVar("OutputT", bound=BaseModel)

AGENT_ORDER: tuple[AgentRole, ...] = (
    AgentRole.CONTEXT_TRIGGER,
    AgentRole.ROUTER,
    AgentRole.MEMORY_OPS,
    AgentRole.COMMANDER,
)

DEFAULT_AGENT_TIMEOUT_SECONDS = 20.0
DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 3
DEFAULT_CIRCUIT_RECOVERY_SECONDS = 60.0

_ROLE_ENV_PREFIX = {
    AgentRole.CONTEXT_TRIGGER: "CONTEXT_TRIGGER",
    AgentRole.ROUTER: "ROUTER",
    AgentRole.MEMORY_OPS: "MEMORY_OPS",
    AgentRole.COMMANDER: "COMMANDER",
}


@dataclass(frozen=True)
class IncidentCommandConfig:
    """Per-agent switches and timeouts. ADR-0018 requires these to be independent."""

    enabled: dict[AgentRole, bool] = field(default_factory=dict)
    timeout_seconds: dict[AgentRole, float] = field(default_factory=dict)
    circuit_failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD
    circuit_recovery_seconds: float = DEFAULT_CIRCUIT_RECOVERY_SECONDS

    def is_enabled(self, role: AgentRole) -> bool:
        if role in self.enabled:
            return bool(self.enabled[role])
        return True

    def timeout_for(self, role: AgentRole) -> float:
        if role in self.timeout_seconds:
            return float(self.timeout_seconds[role])
        return DEFAULT_AGENT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "IncidentCommandConfig":
        env = environ if environ is not None else os.environ
        enabled: dict[AgentRole, bool] = {}
        timeouts: dict[AgentRole, float] = {}
        for role, suffix in _ROLE_ENV_PREFIX.items():
            raw_enabled = env.get(f"SCENIC_AGENT_{suffix}_ENABLED")
            if raw_enabled is not None and str(raw_enabled).strip():
                enabled[role] = str(raw_enabled).strip().lower() not in {
                    "0",
                    "false",
                    "no",
                }
            raw_timeout = env.get(f"SCENIC_AGENT_{suffix}_TIMEOUT_SECONDS")
            if raw_timeout is not None and str(raw_timeout).strip():
                timeouts[role] = float(raw_timeout)
        return cls(
            enabled=enabled,
            timeout_seconds=timeouts,
            circuit_failure_threshold=int(
                env.get(
                    "SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD",
                    str(DEFAULT_CIRCUIT_FAILURE_THRESHOLD),
                )
            ),
            circuit_recovery_seconds=float(
                env.get(
                    "SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS",
                    str(DEFAULT_CIRCUIT_RECOVERY_SECONDS),
                )
            ),
        )


@runtime_checkable
class IncidentAgentRegistry(Protocol):
    """Returns the pydantic-ai agent for a role. The command never sees prompts."""

    def resolve(self, role: AgentRole) -> Any: ...


@dataclass(frozen=True)
class AgentCallOutcome:
    """What a single provider call produced, as observed by the recorder."""

    output: BaseModel
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    request_id: str = ""
    is_mock: bool = False


class ModelCallRecorder(Protocol):
    """Normalizes one provider call into an `llm_call_logs` row reference."""

    async def record(
        self,
        *,
        outcome: AgentCallOutcome,
        role: AgentRole,
        venue_id: str,
        trace_id: str,
        incident_id: str,
        step: str,
        attempt: int,
    ) -> ModelCallRef: ...

    async def record_failure(
        self,
        *,
        role: AgentRole,
        venue_id: str,
        trace_id: str,
        incident_id: str,
        step: str,
        attempt: int,
        error: Exception,
        is_mock: bool = False,
    ) -> ModelCallRef: ...


class AgentFailureCounter(Protocol):
    """Counts consecutive terminal failures for one venue/agent pair."""

    async def consecutive_failures(self, *, venue_id: str, role: AgentRole) -> int: ...

    async def seconds_since_last_failure(
        self, *, venue_id: str, role: AgentRole
    ) -> float | None: ...


class IncidentCommand(Protocol):
    async def execute(self, request: IncidentCommandRequest) -> IncidentCommandResult: ...


class InMemoryAgentFailureCounter:
    """Fallback counter for tests and single-process runs.

    Production reads the same facts from `llm_call_logs`; the count is reset as soon as
    one call succeeds so a healthy call clears the breaker.
    """

    def __init__(self) -> None:
        self._failures: dict[tuple[str, AgentRole], list[float]] = {}
        self._successes: dict[tuple[str, AgentRole], float] = {}

    def note_success(self, *, venue_id: str, role: AgentRole, at: float) -> None:
        self._failures[(venue_id, role)] = []
        self._successes[(venue_id, role)] = at

    def note_failure(self, *, venue_id: str, role: AgentRole, at: float) -> None:
        self._failures.setdefault((venue_id, role), []).append(at)

    async def consecutive_failures(self, *, venue_id: str, role: AgentRole) -> int:
        return len(self._failures.get((venue_id, role), []))

    async def seconds_since_last_failure(
        self, *, venue_id: str, role: AgentRole
    ) -> float | None:
        failures = self._failures.get((venue_id, role), [])
        if not failures:
            return None
        return max(0.0, self._successes.get((venue_id, role), 0.0))


class PydanticAIIncidentCommand:
    """Production `IncidentCommand`: pydantic-ai agents behind one seam."""

    def __init__(
        self,
        *,
        agent_registry: IncidentAgentRegistry,
        call_recorder: ModelCallRecorder,
        config: IncidentCommandConfig | None = None,
        clock: Any = None,
        failure_counter: AgentFailureCounter | None = None,
        preflight: Any = None,
        database: Any = None,
    ) -> None:
        if agent_registry is None:
            raise ValueError("agent_registry is required")
        if call_recorder is None:
            raise ValueError("call_recorder is required")
        self._registry = agent_registry
        self._recorder = call_recorder
        self._config = config or IncidentCommandConfig.from_env()
        self._clock = clock or (lambda: __import__("time").time())
        self._counter = failure_counter or InMemoryAgentFailureCounter()
        if preflight is not None:
            self._preflight = preflight
        elif database is not None:
            self._preflight = CounterModelPreflight(
                self._counter, database=database, clock=self._clock
            )
        else:
            self._preflight = CounterModelPreflight(self._counter, clock=self._clock)

    async def execute(self, request: IncidentCommandRequest) -> IncidentCommandResult:
        with incident_command_span(
            mode=request.mode.value,
            venue_id=request.incident.venue_id,
            trace_id=request.trace_id,
        ):
            return await self._execute_inner(request)

    async def _execute_inner(
        self, request: IncidentCommandRequest
    ) -> IncidentCommandResult:
        command_id = str(uuid.uuid4())
        call_refs: list[ModelCallRef] = []
        degradations: list[AgentDegradation] = []
        context: ContextTriggerOutput | None = None
        routing: RouterOutput | None = None
        advice: MemoryOpsOutput | None = None
        draft: DispatchDraft | None = None
        summary: ClosureSummary | None = None

        context, routing, advice, step_degradations, step_refs = await self._run_advice_chain(
            request
        )
        degradations.extend(step_degradations)
        call_refs.extend(step_refs)

        if request.mode == CommandMode.ADVICE:
            if advice is None:
                advice = self._unavailable_advice(degradations)
        else:
            commander_input = CommanderInput(
                mode=(
                    "DISPATCH_DRAFT"
                    if request.mode == CommandMode.DISPATCH_DRAFT
                    else "CLOSURE_SUMMARY"
                ),
                incident=request.incident,
                context=context,
                routing=routing,
                knowledge=request.knowledge,
                prior_advice=(
                    request.prior.advice
                    if request.prior and request.mode == CommandMode.DISPATCH_DRAFT
                    else None
                ),
                advice_decision=request.advice_decision,
                closure_facts=request.closure_facts,
            )
            artifact, degradation, call_ref = await self._invoke(
                AgentRole.COMMANDER,
                commander_input,
                request=request,
                output_type=(
                    DispatchDraft
                    if request.mode == CommandMode.DISPATCH_DRAFT
                    else ClosureSummary
                ),
                allow_high_risk=request.mode == CommandMode.DISPATCH_DRAFT,
            )
            if call_ref is not None:
                call_refs.append(call_ref)
            if degradation is not None:
                degradations.append(degradation)
            if isinstance(artifact, DispatchDraft):
                if requires_human_approval(artifact) and not artifact.requires_human_approval:
                    artifact = artifact.model_copy(
                        update={"requires_human_approval": True}
                    )
                draft = artifact
            elif isinstance(artifact, ClosureSummary):
                summary = artifact

        outcome = self._outcome_for(request.mode, degradations, advice, draft, summary)
        return IncidentCommandResult(
            command_id=command_id,
            mode=request.mode,
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
            outcome=outcome,
            context=context,
            routing=routing,
            advice=advice if request.mode == CommandMode.ADVICE else None,
            dispatch_draft=draft,
            closure_summary=summary,
            call_refs=call_refs,
            degradations=degradations,
        )

    # ------------------------------------------------------------------ internals

    async def _run_advice_chain(
        self, request: IncidentCommandRequest
    ) -> tuple[
        ContextTriggerOutput,
        RouterOutput,
        MemoryOpsOutput | None,
        list[AgentDegradation],
        list[ModelCallRef],
    ]:
        degradations: list[AgentDegradation] = []
        call_refs: list[ModelCallRef] = []

        context_input = ContextTriggerInput(
            incident=request.incident,
            field_evidence=request.field_evidence,
            knowledge=request.knowledge,
        )
        context, degradation, call_ref = await self._invoke(
            AgentRole.CONTEXT_TRIGGER,
            context_input,
            request=request,
            output_type=ContextTriggerOutput,
        )
        if call_ref is not None:
            call_refs.append(call_ref)
        if degradation is not None:
            degradations.append(degradation)
        if context is None:
            context = ContextTriggerOutput(
                normalized_summary=request.incident.raw_text[:400],
                triggered=True,
                event_type=request.incident.event_type,
                severity_hint=request.incident.priority,
                confidence=0.0,
                evidence_refs=[
                    evidence.evidence_id for evidence in request.field_evidence
                ],
                deduplicated_count=0,
            )

        router_input = RouterInput(
            incident=request.incident,
            context=context,
            field_evidence=request.field_evidence,
        )
        routing, degradation, call_ref = await self._invoke(
            AgentRole.ROUTER,
            router_input,
            request=request,
            output_type=RouterOutput,
        )
        if call_ref is not None:
            call_refs.append(call_ref)
        if degradation is not None:
            degradations.append(degradation)
        if routing is None:
            routing = RouterOutput(
                intent="incident_report",
                severity=request.incident.priority,
                summary=context.normalized_summary,
                is_critical=request.incident.priority in {"P0", "P1"},
                confidence=0.0,
                risk_reason="\u8def\u7531\u4e0d\u53ef\u7528\uff0c\u4fdd\u7559\u4e8b\u4ef6\u539f\u59cb\u4f18\u5148\u7ea7",
            )

        if request.mode != CommandMode.ADVICE:
            return context, routing, None, degradations, call_refs

        memory_input = MemoryOpsInput(
            incident=request.incident,
            context=context,
            routing=routing,
            knowledge=request.knowledge,
            field_evidence=request.field_evidence,
        )
        advice, degradation, call_ref = await self._invoke(
            AgentRole.MEMORY_OPS,
            memory_input,
            request=request,
            output_type=MemoryOpsOutput,
        )
        if call_ref is not None:
            call_refs.append(call_ref)
        if degradation is not None:
            degradations.append(degradation)
        if advice is not None:
            advice = self._enforce_grounding(advice, request, degradations)
        return context, routing, advice, degradations, call_refs

    def _enforce_grounding(
        self,
        advice: MemoryOpsOutput,
        request: IncidentCommandRequest,
        degradations: list[AgentDegradation],
    ) -> MemoryOpsOutput:
        """A model can never cite knowledge the caller did not verify."""

        if advice.evidence_status != "GROUNDED":
            return advice
        verified_source_ids = {
            hit.source_id
            for hit in (
                list(request.knowledge.sop_hits)
                + list(request.knowledge.experience_hits)
            )
        }
        verified_vector_ids = {
            hit.vector_doc_id
            for hit in (
                list(request.knowledge.sop_hits)
                + list(request.knowledge.experience_hits)
            )
        }
        accepted = [
            citation
            for citation in advice.citations
            if citation.source_id in verified_source_ids
            or citation.source_id in verified_vector_ids
        ]
        if not accepted or len(accepted) != len(advice.citations):
            degradations.append(
                AgentDegradation(
                    agent_role=AgentRole.MEMORY_OPS,
                    code="INVALID_OUTPUT",
                    public_message="\u5efa\u8bae\u5f15\u7528\u4e86\u672a\u7ecf\u6838\u9a8c\u7684\u4f9d\u636e\uff0c\u5df2\u964d\u7ea7",
                )
            )
            return MemoryOpsOutput(
                evidence_status="RETRIEVAL_FAILED",
                advice_text=RETRIEVAL_FAILED_TEXT,
                confidence=0.0,
            )
        return advice

    def _unavailable_advice(
        self, degradations: list[AgentDegradation]
    ) -> MemoryOpsOutput:
        has_retrieval_failure = any(
            degradation.code in {"RETRIEVAL_FAILED"} for degradation in degradations
        )
        if has_retrieval_failure:
            return MemoryOpsOutput(
                evidence_status="RETRIEVAL_FAILED",
                advice_text=RETRIEVAL_FAILED_TEXT,
                confidence=0.0,
            )
        if not degradations:
            return MemoryOpsOutput(
                evidence_status="NO_EVIDENCE",
                advice_text=NO_EVIDENCE_TEXT,
                confidence=0.0,
                absence_reason="\u672a\u547d\u4e2d\u5df2\u53d1\u5e03\u4f9d\u636e",
            )
        return MemoryOpsOutput(
            evidence_status="NO_EVIDENCE",
            advice_text=NO_EVIDENCE_TEXT,
            confidence=0.0,
            absence_reason="\u6a21\u578b\u5efa\u8bae\u4e0d\u53ef\u7528",
        )

    async def _invoke(
        self,
        role: AgentRole,
        agent_input: BaseModel,
        *,
        request: IncidentCommandRequest,
        output_type: type[OutputT],
        allow_high_risk: bool = False,
    ) -> tuple[OutputT | None, AgentDegradation | None, ModelCallRef | None]:
        venue_id = request.incident.venue_id
        incident_id = request.incident.incident_id
        step = request.mode.value
        attempt = request.attempt
        configured_model = _configured_model_name()

        if not self._config.is_enabled(role):
            return (
                None,
                AgentDegradation(
                    agent_role=role,
                    code="DISABLED",
                    public_message="\u8be5\u73af\u8282\u5df2\u88ab\u8fd0\u7ef4\u5173\u95ed",
                ),
                None,
            )

        decision = await self._preflight.check(venue_id=venue_id, role=role)
        if not decision.allowed:
            return (
                None,
                AgentDegradation(
                    agent_role=role,
                    code=decision.code or "FAILED",
                    public_message=decision.public_message,
                ),
                None,
            )

        agent = self._registry.resolve(role)
        timeout = self._config.timeout_for(role)
        last_error: Exception | None = None
        for provider_attempt in range(2):
            started = float(self._clock())
            with agent_span(
                role=role.value, agent_name=role.value, trace_id=request.trace_id
            ) as span:
                try:
                    result = await asyncio.wait_for(
                        agent.run(agent_input.model_dump_json()),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError as exc:
                    last_error = exc
                    await self._note_failure(venue_id, role)
                    call_ref = await self._recorder.record_failure(
                        role=role,
                        venue_id=venue_id,
                        trace_id=request.trace_id,
                        incident_id=incident_id,
                        step=step,
                        attempt=attempt,
                        error=exc,
                        model_name=configured_model,
                    )
                    record_agent_outcome(span, status="TIMEOUT")
                    if provider_attempt == 1:
                        return (
                            None,
                            AgentDegradation(
                                agent_role=role,
                                code="TIMEOUT",
                                public_message="\u6a21\u578b\u8c03\u7528\u8d85\u65f6\uff0c\u5df2\u964d\u7ea7\u672c\u73af\u8282",
                                call_id=call_ref.call_id,
                            ),
                            call_ref,
                        )
                    continue
                except Exception as exc:  # provider or contract failure
                    last_error = exc
                    await self._note_failure(venue_id, role)
                    call_ref = await self._recorder.record_failure(
                        role=role,
                        venue_id=venue_id,
                        trace_id=request.trace_id,
                        incident_id=incident_id,
                        step=step,
                        attempt=attempt,
                        error=exc,
                        model_name=configured_model,
                    )
                    record_agent_outcome(span, status="FAILED")
                    if provider_attempt == 1:
                        return (
                            None,
                            AgentDegradation(
                                agent_role=role,
                                code="FAILED",
                                public_message="\u6a21\u578b\u672c\u73af\u8282\u5931\u8d25\uff0c\u4e1a\u52a1\u4ecd\u53ef\u63a8\u8fdb",
                                call_id=call_ref.call_id,
                            ),
                            call_ref,
                        )
                    continue

                output = result.output
                if not isinstance(output, output_type):
                    record_agent_outcome(span, status="INVALID_OUTPUT")
                    degraded = AgentDegradation(
                        agent_role=role,
                        code="INVALID_OUTPUT",
                        public_message="\u6a21\u578b\u8f93\u51fa\u672a\u901a\u8fc7\u5951\u7ea6\u6821\u9a8c",
                    )
                    await self._note_failure(venue_id, role)
                    return None, degraded, None

                usage = getattr(result, "usage", None)
                prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                outcome = AgentCallOutcome(
                    output=output,
                    model_name=str(
                        getattr(getattr(result, "response", None), "model_name", "")
                        or getattr(result, "model_name", "")
                        or ""
                    ),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_seconds=max(0.0, float(self._clock()) - started),
                    request_id=str(
                        getattr(
                            getattr(result, "response", None),
                            "provider_response_id",
                            None,
                        )
                        or getattr(result, "provider_response_id", "")
                        or ""
                    ),
                    is_mock=bool(getattr(result, "is_mock", False)),
                )
                call_ref = await self._recorder.record(
                    outcome=outcome,
                    role=role,
                    venue_id=venue_id,
                    trace_id=request.trace_id,
                    incident_id=incident_id,
                    step=step,
                    attempt=attempt,
                )
                self._note_success(venue_id, role)
                record_agent_outcome(
                    span, status=call_ref.status, model_name=outcome.model_name
                )
                if call_ref.status == "SUCCEEDED_NO_USAGE":
                    return (
                        output,
                        AgentDegradation(
                            agent_role=role,
                            code="USAGE_NOT_REPORTED",
                            public_message="\u8c03\u7528\u6210\u529f\u4f46\u672a\u62a5\u544a token \u7528\u91cf",
                            call_id=call_ref.call_id,
                        ),
                        call_ref,
                    )
                return output, None, call_ref

        # Unreachable in practice; keeps a defensive terminal degradation.
        return (
            None,
            AgentDegradation(
                agent_role=role,
                code="FAILED",
                public_message=f"\u672c\u73af\u8282\u5931\u8d25\uff1a{type(last_error).__name__}",
            ),
            None,
        )

    async def _circuit_open(self, venue_id: str, role: AgentRole) -> bool:
        failures = await self._counter.consecutive_failures(
            venue_id=venue_id, role=role
        )
        if failures < self._config.circuit_failure_threshold:
            return False
        elapsed = await self._counter.seconds_since_last_failure(
            venue_id=venue_id, role=role
        )
        if elapsed is None:
            return False
        return elapsed < self._config.circuit_recovery_seconds

    async def _note_failure(self, venue_id: str, role: AgentRole) -> None:
        note = getattr(self._counter, "note_failure", None)
        if callable(note):
            note(venue_id=venue_id, role=role, at=float(self._clock()))

    def _note_success(self, venue_id: str, role: AgentRole) -> None:
        note = getattr(self._counter, "note_success", None)
        if callable(note):
            note(venue_id=venue_id, role=role, at=float(self._clock()))

    @staticmethod
    def _outcome_for(
        mode: CommandMode,
        degradations: list[AgentDegradation],
        advice: MemoryOpsOutput | None,
        draft: DispatchDraft | None,
        summary: ClosureSummary | None,
    ) -> Literal["READY", "DEGRADED", "FAILED"]:
        if mode == CommandMode.ADVICE:
            if advice is None:
                return "FAILED"
            return "DEGRADED" if degradations else "READY"
        terminal = draft if mode == CommandMode.DISPATCH_DRAFT else summary
        if terminal is None:
            return "FAILED"
        return "DEGRADED" if degradations else "READY"



def _configured_model_name() -> str:
    """The model the runtime would call; used so a failed call still names its model."""

    return (
        os.environ.get("SCENIC_AGENT_MODEL")
        or os.environ.get("LLM_DEFAULT_MODEL")
        or "deepseek-flash"
    )

__all__ = [
    "AGENT_ORDER",
    "AgentCallOutcome",
    "AgentFailureCounter",
    "DEFAULT_AGENT_TIMEOUT_SECONDS",
    "IncidentAgentRegistry",
    "IncidentCommand",
    "IncidentCommandConfig",
    "InMemoryAgentFailureCounter",
    "ModelCallRecorder",
    "PydanticAIIncidentCommand",
]
