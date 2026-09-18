"""Model-service pre-flight: daily token quota and circuit breaker.

Both read the same `llm_call_logs` source of truth as the diagnostics page, so the
enforcement decision and the reported state can never disagree. A denial never creates a
provider call and never claims a degradation succeeded.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..agent_contracts.models import AgentRole

DenialCode = Literal["QUOTA_EXCEEDED", "CIRCUIT_OPEN"]


@dataclass(frozen=True)
class PreflightDecision:
    allowed: bool
    code: DenialCode | None = None
    public_message: str = ""


class ModelPreflight(Protocol):
    async def check(self, *, venue_id: str, role: AgentRole) -> PreflightDecision: ...


class AllowAllPreflight:
    """Used by contract tests and offline paths."""

    async def check(self, *, venue_id: str, role: AgentRole) -> PreflightDecision:
        return PreflightDecision(allowed=True)


def _daily_token_limit() -> int:
    try:
        return int(os.environ.get("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "20000000"))
    except ValueError:
        return 20000000


def _failure_threshold() -> int:
    try:
        return max(1, int(os.environ.get("SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD", "3")))
    except ValueError:
        return 3


def _recovery_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS", "60")))
    except ValueError:
        return 60.0


def _day_start(now: float) -> float:
    return now - (now % 86400)


class LLMCallLogFailureCounter:
    """Derives per-venue/per-agent breaker state from `llm_call_logs`."""

    def __init__(self, database: Any, *, clock: Any = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time

    async def _recent(self, *, venue_id: str, role: AgentRole) -> list[Any]:
        agent_id = {
            AgentRole.CONTEXT_TRIGGER: "ContextTrigger",
            AgentRole.ROUTER: "Router",
            AgentRole.MEMORY_OPS: "MemoryOps",
            AgentRole.COMMANDER: "Commander",
        }[role]
        return await self._database.fetch_all(
            """
            SELECT status, created_at
            FROM llm_call_logs
            WHERE venue_id = ? AND agent_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (venue_id, agent_id),
        )

    async def consecutive_failures(self, *, venue_id: str, role: AgentRole) -> int:
        rows = await self._recent(venue_id=venue_id, role=role)
        count = 0
        for row in rows or []:
            if str(row["status"]).upper() == "FAILED":
                count += 1
                continue
            break
        return count

    async def seconds_since_last_failure(
        self, *, venue_id: str, role: AgentRole
    ) -> float | None:
        rows = await self._recent(venue_id=venue_id, role=role)
        for row in rows or []:
            if str(row["status"]).upper() == "FAILED":
                try:
                    return max(0.0, float(self._clock()) - float(row["created_at"]))
                except (TypeError, ValueError):
                    return None
        return None


class CounterModelPreflight:
    """Breaker + quota check over an injected failure counter.

    Used by contract tests and by callers that already own a counter; the quota part is
    still read from `llm_call_logs` when a database is supplied.
    """

    def __init__(self, counter: Any, *, database: Any = None, clock: Any = None) -> None:
        self._counter = counter
        self._database = database
        self._clock = clock or time.time

    async def used_tokens_today(self, *, venue_id: str) -> int:
        if self._database is None:
            return 0
        row = await self._database.fetch_one(
            """
            SELECT COALESCE(SUM(total_tokens), 0) AS used_tokens
            FROM llm_call_logs
            WHERE venue_id = ? AND created_at >= ?
            """,
            (venue_id, _day_start(float(self._clock()))),
        )
        return max(0, int((row or {}).get("used_tokens") or 0))

    async def circuit_status(self, *, venue_id: str, role: AgentRole) -> dict[str, Any]:
        failures = await self._counter.consecutive_failures(
            venue_id=venue_id, role=role
        )
        elapsed = await self._counter.seconds_since_last_failure(
            venue_id=venue_id, role=role
        )
        open_circuit = failures >= _failure_threshold() and (
            elapsed is not None and elapsed < _recovery_seconds()
        )
        return {
            "state": "OPEN" if open_circuit else "CLOSED",
            "consecutive_failures": failures,
            "failure_threshold": _failure_threshold(),
            "recovery_timeout_seconds": _recovery_seconds(),
        }

    async def check(self, *, venue_id: str, role: AgentRole) -> PreflightDecision:
        limit_tokens = _daily_token_limit()
        if limit_tokens > 0:
            used = await self.used_tokens_today(venue_id=venue_id)
            if used >= limit_tokens:
                return PreflightDecision(
                    allowed=False,
                    code="QUOTA_EXCEEDED",
                    public_message="\u4eca\u65e5\u6a21\u578b token \u914d\u989d\u5df2\u7528\u5c3d\uff0c\u672a\u83b7\u5f97\u6a21\u578b\u5efa\u8bae",
                )
        circuit = await self.circuit_status(venue_id=venue_id, role=role)
        if circuit["state"] == "OPEN":
            return PreflightDecision(
                allowed=False,
                code="CIRCUIT_OPEN",
                public_message="\u8be5\u73af\u8282\u77ed\u6682\u7194\u65ad\uff0c\u7a0d\u540e\u91cd\u8bd5",
            )
        return PreflightDecision(allowed=True)


class DatabaseModelPreflight:
    """Blocks calls when the venue is out of quota or the breaker is open."""

    def __init__(
        self,
        database: Any,
        *,
        failure_counter: Any = None,
        clock: Any = None,
    ) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time
        self._counter = failure_counter or LLMCallLogFailureCounter(
            database, clock=self._clock
        )

    async def used_tokens_today(self, *, venue_id: str) -> int:
        row = await self._database.fetch_one(
            """
            SELECT COALESCE(SUM(total_tokens), 0) AS used_tokens
            FROM llm_call_logs
            WHERE venue_id = ? AND created_at >= ?
            """,
            (venue_id, _day_start(float(self._clock()))),
        )
        return max(0, int((row or {}).get("used_tokens") or 0))

    async def quota_status(self, *, venue_id: str) -> dict[str, Any]:
        limit_tokens = _daily_token_limit()
        used_tokens = await self.used_tokens_today(venue_id=venue_id)
        if limit_tokens <= 0:
            return {"status": "DISABLED", "limit_tokens": limit_tokens, "used_tokens": used_tokens}
        return {
            "status": "EXHAUSTED" if used_tokens >= limit_tokens else "NORMAL",
            "limit_tokens": limit_tokens,
            "used_tokens": used_tokens,
        }

    async def circuit_status(self, *, venue_id: str, role: AgentRole) -> dict[str, Any]:
        failures = await self._counter.consecutive_failures(
            venue_id=venue_id, role=role
        )
        elapsed = await self._counter.seconds_since_last_failure(
            venue_id=venue_id, role=role
        )
        open_circuit = failures >= _failure_threshold() and (
            elapsed is not None and elapsed < _recovery_seconds()
        )
        return {
            "state": "OPEN" if open_circuit else "CLOSED",
            "consecutive_failures": failures,
            "failure_threshold": _failure_threshold(),
            "recovery_timeout_seconds": _recovery_seconds(),
        }

    async def check(self, *, venue_id: str, role: AgentRole) -> PreflightDecision:
        quota = await self.quota_status(venue_id=venue_id)
        if quota["status"] == "EXHAUSTED":
            return PreflightDecision(
                allowed=False,
                code="QUOTA_EXCEEDED",
                public_message="\u4eca\u65e5\u6a21\u578b token 配\u989d\u5df2\u7528\u5c3d\uff0c\u672a\u83b7\u5f97\u6a21\u578b\u5efa\u8bae",
            )
        circuit = await self.circuit_status(venue_id=venue_id, role=role)
        if circuit["state"] == "OPEN":
            return PreflightDecision(
                allowed=False,
                code="CIRCUIT_OPEN",
                public_message="\u8be5\u73af\u8282\u77ed\u6682\u7194\u65ad\uff0c\u7a0d\u540e\u91cd\u8bd5",
            )
        return PreflightDecision(allowed=True)


__all__ = [
    "AllowAllPreflight",
    "CounterModelPreflight",
    "DatabaseModelPreflight",
    "LLMCallLogFailureCounter",
    "ModelPreflight",
    "PreflightDecision",
]
