"""Model-service quota and circuit breaker enforcement (ticket m4-05)."""

from __future__ import annotations

import pytest

from src.memory_palace.agent_contracts.models import AgentRole
from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.model_policy import (
    DatabaseModelPreflight,
    LLMCallLogFailureCounter,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from tests.unit.test_incident_command import (
    Registry,
    ScriptedAgent,
    SpyRecorder,
    _advice,
    _context,
    _request,
    _routing,
)

pytestmark = pytest.mark.asyncio
FROZEN_NOW = 1785283200.0


async def _database(tmp_path) -> AsyncDBClient:
    database = AsyncDBClient(tmp_path / "model-policy.db")
    await init_database(database)
    return database


def _agents():
    return {
        AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
        AgentRole.ROUTER: ScriptedAgent([_routing()]),
        AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
        AgentRole.COMMANDER: ScriptedAgent([_advice()]),
    }


async def _spend(database, *, total_tokens: int, created_at: float = FROZEN_NOW):
    await database.execute(
        """
        INSERT INTO llm_call_logs (
            id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
            status, attempt_count, latency_seconds, prompt_tokens,
            completion_tokens, total_tokens, request_id, is_mock, created_at
        ) VALUES (?, ?, ?, 'Router', 'Router', 'deepseek', 'deepseek-flash',
                  'SUCCEEDED', 1, 1.0, ?, ?, ?, 'req', 0, ?)
        """,
        (
            f"call-{total_tokens}-{created_at}",
            "venue-alpha",
            "e" * 32,
            total_tokens,
            0,
            total_tokens,
            created_at,
        ),
    )


async def test_exhausted_daily_quota_degrades_without_calling_the_provider(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "1000")
    database = await _database(tmp_path)
    await _spend(database, total_tokens=1000)
    agents = _agents()
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=LLMCallLogRecorder(database, clock=lambda: FROZEN_NOW),
        config=IncidentCommandConfig(),
        clock=lambda: FROZEN_NOW,
        preflight=DatabaseModelPreflight(database, clock=lambda: FROZEN_NOW),
    )

    result = await command.execute(_request())

    assert result.outcome == "DEGRADED"
    # Every advice-step agent is blocked, and none of them reaches the provider.
    assert [d.code for d in result.degradations] == ["QUOTA_EXCEEDED"] * 3
    assert all(agent.calls == 0 for agent in agents.values())
    assert result.advice is not None
    assert result.advice.advice_text == "\u6ca1\u6709\u4f9d\u636e"
    await database.close()


async def test_quota_under_the_limit_still_calls_the_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "1000")
    database = await _database(tmp_path)
    await _spend(database, total_tokens=10)
    agents = _agents()
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=LLMCallLogRecorder(database, clock=lambda: FROZEN_NOW),
        config=IncidentCommandConfig(),
        clock=lambda: FROZEN_NOW,
        preflight=DatabaseModelPreflight(database, clock=lambda: FROZEN_NOW),
    )

    result = await command.execute(_request())

    assert result.outcome == "READY"
    assert agents[AgentRole.MEMORY_OPS].calls == 1
    await database.close()


async def test_three_real_failures_open_the_breaker_across_processes(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS", "60")
    monkeypatch.setenv("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "1000000")
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: FROZEN_NOW)
    for attempt in range(3):
        await recorder.record_failure(
            role=AgentRole.ROUTER,
            venue_id="venue-alpha",
            trace_id=f"{attempt:032d}",
            incident_id="incident-1",
            step="ADVICE",
            attempt=attempt + 1,
            error=RuntimeError("provider down"),
        )

    agents = _agents()
    # A fresh command instance simulates a process restart: the breaker state must come
    # from llm_call_logs, not from memory.
    restarted = PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=recorder,
        config=IncidentCommandConfig(),
        clock=lambda: FROZEN_NOW,
        preflight=DatabaseModelPreflight(
            database,
            failure_counter=LLMCallLogFailureCounter(
                database, clock=lambda: FROZEN_NOW
            ),
            clock=lambda: FROZEN_NOW,
        ),
    )

    result = await restarted.execute(_request())

    assert "CIRCUIT_OPEN" in [d.code for d in result.degradations]
    assert agents[AgentRole.ROUTER].calls == 0
    await database.close()


async def test_breaker_recloses_after_the_recovery_window(tmp_path, monkeypatch):
    monkeypatch.setenv("SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS", "60")
    monkeypatch.setenv("SCENIC_AGENT_DAILY_TOKEN_LIMIT", "1000000")
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: FROZEN_NOW)
    for attempt in range(3):
        await recorder.record_failure(
            role=AgentRole.ROUTER,
            venue_id="venue-alpha",
            trace_id=f"{attempt:032d}",
            incident_id="incident-1",
            step="ADVICE",
            attempt=attempt + 1,
            error=RuntimeError("provider down"),
        )

    later = FROZEN_NOW + 120
    agents = _agents()
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(agents),
        call_recorder=LLMCallLogRecorder(database, clock=lambda: later),
        config=IncidentCommandConfig(),
        clock=lambda: later,
        preflight=DatabaseModelPreflight(database, clock=lambda: later),
    )

    result = await command.execute(_request())

    assert result.outcome == "READY"
    assert agents[AgentRole.ROUTER].calls == 1
    await database.close()
