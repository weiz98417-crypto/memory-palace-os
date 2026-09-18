"""Persist scenic Agent calls into the existing `llm_call_logs` table.

`llm_call_logs` is the single source of truth for model-call evidence (ADR-0018). This
recorder only writes and reads that table: it never creates a parallel activity type
and it never fabricates usage it did not observe.
"""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

from ..agent_contracts.models import AgentRole, ModelCallRef

CALL_NAMESPACE = uuid.UUID("6f5e6c3a-5c2b-4a4d-9a53-1f0f4a7f1c11")

_ROLE_AGENT_ID = {
    AgentRole.CONTEXT_TRIGGER: "ContextTrigger",
    AgentRole.ROUTER: "Router",
    AgentRole.MEMORY_OPS: "MemoryOps",
    AgentRole.COMMANDER: "Commander",
}
_ROLE_AGENT_NAME = {
    AgentRole.CONTEXT_TRIGGER: "ContextTrigger",
    AgentRole.ROUTER: "Router",
    AgentRole.MEMORY_OPS: "MemoryOps",
    AgentRole.COMMANDER: "Commander",
}


def _call_id(
    *, venue_id: str, role: AgentRole, incident_id: str, step: str, attempt: int
) -> str:
    return str(
        uuid.uuid5(
            CALL_NAMESPACE,
            f"scenic-agent-call:{venue_id}:{role.value}:{incident_id}:{step}:{attempt}",
        )
    )


class LLMCallLogRecorder:
    """Writes one row per real provider call and returns a reference to it."""

    provider = "deepseek"

    def __init__(self, database: Any, *, clock: Any = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time

    async def record(
        self,
        *,
        outcome: Any,
        role: AgentRole,
        venue_id: str,
        trace_id: str,
        incident_id: str,
        step: str,
        attempt: int,
    ) -> ModelCallRef:
        prompt_tokens = max(0, int(getattr(outcome, "prompt_tokens", 0) or 0))
        completion_tokens = max(0, int(getattr(outcome, "completion_tokens", 0) or 0))
        is_mock = bool(getattr(outcome, "is_mock", False))
        total_tokens = prompt_tokens + completion_tokens
        status = "MOCKED" if is_mock else (
            "SUCCEEDED" if total_tokens > 0 else "SUCCEEDED_NO_USAGE"
        )
        latency = float(getattr(outcome, "latency_seconds", 0.0) or 0.0)
        call_id = _call_id(
            venue_id=venue_id, role=role, incident_id=incident_id, step=step, attempt=attempt
        )
        await self._insert(
            call_id=call_id,
            venue_id=venue_id,
            trace_id=trace_id,
            role=role,
            model_name=str(getattr(outcome, "model_name", "") or "unknown"),
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            request_id=str(getattr(outcome, "request_id", "") or "") or None,
            latency_seconds=latency if math.isfinite(latency) else None,
            error_type=None,
            error_message=None,
            is_mock=is_mock,
        )
        return ModelCallRef(
            call_id=call_id,
            trace_id=trace_id,
            agent_id=_ROLE_AGENT_ID[role],
            agent_name=_ROLE_AGENT_NAME[role],
            status=status,
            is_mock=is_mock,
        )

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
        model_name: str = "unknown",
        is_mock: bool = False,
    ) -> ModelCallRef:
        call_id = _call_id(
            venue_id=venue_id, role=role, incident_id=incident_id, step=step, attempt=attempt
        )
        await self._insert(
            call_id=call_id,
            venue_id=venue_id,
            trace_id=trace_id,
            role=role,
            model_name=model_name,
            status="FAILED",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            request_id=None,
            latency_seconds=None,
            error_type=type(error).__name__,
            error_message=str(error)[:500],
            is_mock=is_mock,
        )
        return ModelCallRef(
            call_id=call_id,
            trace_id=trace_id,
            agent_id=_ROLE_AGENT_ID[role],
            agent_name=_ROLE_AGENT_NAME[role],
            status="FAILED",
            is_mock=is_mock,
        )

    async def _insert(
        self,
        *,
        call_id: str,
        venue_id: str,
        trace_id: str,
        role: AgentRole,
        model_name: str,
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        request_id: str | None,
        latency_seconds: float | None,
        error_type: str | None,
        error_message: str | None,
        is_mock: bool,
    ) -> None:
        await self._database.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
                status, attempt_count, latency_seconds, prompt_tokens,
                completion_tokens, total_tokens, request_id, error_type,
                error_message, is_mock, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                call_id,
                venue_id,
                trace_id,
                _ROLE_AGENT_ID[role],
                _ROLE_AGENT_NAME[role],
                self.provider,
                model_name,
                status,
                latency_seconds,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                request_id,
                error_type,
                error_message,
                bool(is_mock),
                float(self._clock()),
            ),
        )


__all__ = ["CALL_NAMESPACE", "LLMCallLogRecorder"]
