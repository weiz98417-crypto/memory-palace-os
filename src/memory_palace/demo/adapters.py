from datetime import datetime, timezone
from time import perf_counter
from typing import Protocol

from .models import ScenarioStep, StepEvidence, StepStatus


class DeterministicStepFailure(RuntimeError):
    """Expected demo-only failure used to prove recovery behavior."""


def tool_calls_for_attempt(step: ScenarioStep, attempt: int) -> list[dict]:
    return [tool_call for tool_call in step.tool_calls if tool_call.get("attempt") in {None, attempt}]


class ScenarioAdapter(Protocol):
    async def execute(
        self,
        step: ScenarioStep,
        sequence: int,
        attempt: int,
    ) -> StepEvidence: ...


class DeterministicScenarioAdapter:
    """Turns a versioned scenario step into truthful Demo Adapter evidence."""

    async def execute(
        self,
        step: ScenarioStep,
        sequence: int,
        attempt: int,
    ) -> StepEvidence:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        if attempt <= step.retry_count:
            raise DeterministicStepFailure(
                f"Demo Adapter injected recoverable failure for {step.id} " f"on attempt {attempt}"
            )
        duration_ms = max(1, round((perf_counter() - started) * 1000))
        return StepEvidence(
            step_id=step.id,
            sequence=sequence,
            attempt=attempt,
            title=step.title,
            actor=step.actor,
            status=StepStatus.SUCCESS,
            started_at=started_at,
            duration_ms=duration_ms,
            input_summary=step.input_summary,
            output_summary=step.output_summary,
            route_reason=step.route_reason,
            citations=step.citations,
            tool_calls=tool_calls_for_attempt(step, attempt),
            policy_decision=step.policy_decision,
            retry_count=step.retry_count,
            recovery_summary=step.recovery_summary,
            execution_mode=step.execution_mode,
        )
