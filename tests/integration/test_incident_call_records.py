"""`IncidentCommand` writing real evidence into the existing `llm_call_logs` table."""

from __future__ import annotations

import json

import pytest

from src.memory_palace.agent_contracts.models import AgentRole, CommandMode
from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from tests.unit.test_incident_command import (  # noqa: F401 - shared scripted fixtures
    Registry,
    ScriptedAgent,
    _advice,
    _context,
    _knowledge,
    _request,
    _routing,
)

pytestmark = pytest.mark.asyncio


async def _database(tmp_path) -> AsyncDBClient:
    database = AsyncDBClient(tmp_path / "incident-command.db")
    await init_database(database)
    return database


def _agents():
    return {
        AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
        AgentRole.ROUTER: ScriptedAgent([_routing()]),
        AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
        AgentRole.COMMANDER: ScriptedAgent([_advice()]),
    }


async def test_every_real_call_lands_in_llm_call_logs_with_usage_and_trace(tmp_path):
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: 1785283200.0)
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(_agents()),
        call_recorder=recorder,
        config=IncidentCommandConfig(),
        clock=lambda: 1785283200.0,
    )

    result = await command.execute(_request(incident=_request().incident))

    rows = await database.fetch_all(
        "SELECT * FROM llm_call_logs WHERE venue_id = ? ORDER BY created_at, agent_id",
        ("venue-alpha",),
    )
    assert len(rows) == 3
    by_agent = {row["agent_id"]: row for row in rows}
    assert set(by_agent) == {"ContextTrigger", "Router", "MemoryOps"}
    for row in rows:
        assert row["trace_id"] == "b" * 32
        assert row["model_name"] == "deepseek-flash"
        assert row["status"] == "SUCCEEDED"
        assert row["prompt_tokens"] == 11
        assert row["completion_tokens"] == 7
        assert row["total_tokens"] == 18
        assert row["request_id"] == "req-1"
        assert bool(row["is_mock"]) is False
    assert {ref.call_id for ref in result.call_refs} == {row["id"] for row in rows}
    await database.close()


async def test_replaying_the_same_idempotency_key_does_not_duplicate_call_records(tmp_path):
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: 1785283200.0)
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(_agents()),
        call_recorder=recorder,
        config=IncidentCommandConfig(),
        clock=lambda: 1785283200.0,
    )
    request = _request()

    await command.execute(request)
    await command.execute(request)

    count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM llm_call_logs WHERE venue_id = ?",
        ("venue-alpha",),
    )
    assert int(count["total"]) == 3, "one business attempt must not double-charge the model"

    # A new attempt is a new run and does get its own call records.
    await command.execute(request.model_copy(update={"attempt": 2}))
    count = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM llm_call_logs WHERE venue_id = ?",
        ("venue-alpha",),
    )
    assert int(count["total"]) == 6
    await database.close()


async def test_call_records_are_scoped_to_the_venue(tmp_path):
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: 1785283200.0)
    command = PydanticAIIncidentCommand(
        agent_registry=Registry(_agents()),
        call_recorder=recorder,
        config=IncidentCommandConfig(),
        clock=lambda: 1785283200.0,
    )
    request = _request(incident=_request().incident.model_copy(update={"venue_id": "venue-beta"}))

    await command.execute(request)

    other = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM llm_call_logs WHERE venue_id = ?",
        ("venue-alpha",),
    )
    mine = await database.fetch_one(
        "SELECT COUNT(*) AS total FROM llm_call_logs WHERE venue_id = ?",
        ("venue-beta",),
    )
    assert int(other["total"]) == 0
    assert int(mine["total"]) == 3
    await database.close()


async def test_circuit_breaker_state_is_derivable_from_llm_call_logs(tmp_path):
    database = await _database(tmp_path)
    recorder = LLMCallLogRecorder(database, clock=lambda: 1785283200.0)
    for index in range(3):
        await recorder.record_failure(
            role=AgentRole.ROUTER,
            venue_id="venue-alpha",
            trace_id=f"{index:032d}",
            incident_id="incident-1",
            step="ADVICE",
            attempt=index + 1,
            error=RuntimeError("provider down"),
        )

    row = await database.fetch_one(
        """
        SELECT COUNT(*) AS failures FROM llm_call_logs
        WHERE venue_id = ? AND agent_id = ? AND status = 'FAILED'
        """,
        ("venue-alpha", "Router"),
    )
    assert int(row["failures"]) == 3
    error = await database.fetch_one(
        "SELECT error_type FROM llm_call_logs WHERE agent_id = 'Router' LIMIT 1"
    )
    assert error["error_type"] == "RuntimeError"
    await database.close()
