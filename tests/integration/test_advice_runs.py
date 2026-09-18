"""Advice run state machine, worker, and late-result behaviour."""

from __future__ import annotations

import json

import pytest

from src.memory_palace.agent_contracts.models import CommandMode
from src.memory_palace.incident.call_records import LLMCallLogRecorder
from src.memory_palace.incident.contracts import IncidentCommandResult
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.scenic.advice_runs import (
    AdviceRunConflict,
    AdviceRunRepository,
    AdviceWorker,
    InMemoryAdviceQueue,
    advice_run_id,
)
from tests.unit.test_incident_command import _advice, _context, _request, _routing

pytestmark = pytest.mark.asyncio


class Sink:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.events: list[dict] = []
        self.fail_times = fail_times

    async def finalize(self, *, run, state, activity_type, payload, system_context=None):
        self.events.append(
            {
                "run_id": run.run_id,
                "state": state,
                "activity_type": activity_type,
                "payload": payload,
                "system_context": system_context,
            }
        )


class StubCommand:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def execute(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _result() -> IncidentCommandResult:
    return IncidentCommandResult(
        command_id="command-1",
        mode=CommandMode.ADVICE,
        trace_id="b" * 32,
        idempotency_key="advice:incident-1:ADVICE:1",
        outcome="READY",
        context=_context(),
        routing=_routing(),
        advice=_advice(),
    )


async def _repository(tmp_path) -> AdviceRunRepository:
    database = AsyncDBClient(tmp_path / "advice-runs.db")
    await init_database(database)
    return AdviceRunRepository(database)


async def _create(repository, request):
    run, created = await repository.create_or_get(
        venue_id="venue-alpha",
        incident_id="incident-1",
        step="ADVICE",
        attempt=1,
        request=request,
    )
    return run, created


async def test_run_is_created_once_and_replays_resolve_to_the_same_run(tmp_path):
    repository = await _repository(tmp_path)
    request = _request()
    first, created = await _create(repository, request)
    second, created_again = await repo_create(repository, request)

    assert created is True
    assert created_again is False
    assert first.run_id == second.run_id == advice_run_id("incident-1", step="ADVICE", attempt=1)
    assert first.state == "PENDING"
    assert first.request is not None
    assert first.request.trace_id == request.trace_id
    await repository._database.close()


async def repo_create(repository, request):
    return await repository.create_or_get(
        venue_id="venue-alpha",
        incident_id="incident-1",
        step="ADVICE",
        attempt=1,
        request=request,
    )


async def test_same_idempotency_key_with_different_inputs_is_a_conflict(tmp_path):
    repository = await _repository(tmp_path)
    await _create(repository, _request())
    other = _request(
        incident=_request().incident.model_copy(update={"title": "different"})
    )
    with pytest.raises(AdviceRunConflict):
        await _create(repository, other)
    await repository._database.close()


async def test_transitions_are_compare_and_swap(tmp_path):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())

    assert await repository.transition(
        venue_id="venue-alpha",
        run_id=run.run_id,
        expected="PENDING",
        new_state="RUNNING",
    )
    assert not await repository.transition(
        venue_id="venue-alpha",
        run_id=run.run_id,
        expected="PENDING",
        new_state="RUNNING",
    )
    assert await repository.transition(
        venue_id="venue-alpha",
        run_id=run.run_id,
        expected="RUNNING",
        new_state="READY",
        response={"outcome": "READY"},
    )
    with pytest.raises(AdviceRunConflict):
        await repository.transition(
            venue_id="venue-alpha",
            run_id=run.run_id,
            expected="READY",
            new_state="SUPERSEDED",
        )
    await repository._database.close()


async def test_worker_executes_the_trunk_and_finalizes_ready(tmp_path):
    repository = await _repository(tmp_path)
    queue = InMemoryAdviceQueue()
    sink = Sink()
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository,
        queue=queue,
        incident_command=StubCommand(_result()),
        sink=sink,
    )
    await worker.enqueue(run)

    finalized = await worker.run_once()

    assert finalized is not None
    assert finalized.state == "READY"
    persisted = await repository.get(venue_id="venue-alpha", run_id=run.run_id)
    assert persisted.state == "READY"
    assert persisted.result["advice"]["evidence_status"] == "GROUNDED"
    assert [event["activity_type"] for event in sink.events] == ["ADVICE_READY"]
    await repository._database.close()


async def test_worker_failure_marks_run_failed_and_signals_it(tmp_path):
    repository = await _repository(tmp_path)
    queue = InMemoryAdviceQueue()
    sink = Sink()
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository,
        queue=queue,
        incident_command=StubCommand(error=RuntimeError("provider exploded")),
        sink=sink,
    )
    await worker.enqueue(run)

    finalized = await worker.run_once()

    assert finalized.state == "FAILED"
    persisted = await repository.get(venue_id="venue-alpha", run_id=run.run_id)
    assert persisted.error_type == "RuntimeError"
    assert [event["activity_type"] for event in sink.events] == ["ADVICE_FAILED"]
    await repository._database.close()


async def test_late_result_is_kept_without_resurrecting_a_superseded_run(tmp_path):
    repository = await _repository(tmp_path)
    queue = InMemoryAdviceQueue()
    sink = Sink()
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository,
        queue=queue,
        incident_command=StubCommand(_result()),
        sink=sink,
    )
    await worker.enqueue(run)
    # A human advanced first: the run is superseded while the model is still working.
    await repository.transition(
        venue_id="venue-alpha",
        run_id=run.run_id,
        expected="PENDING",
        new_state="SUPERSEDED",
        response={"superseded_by": "manager-decision"},
    )

    finalized = await worker.run_once()

    assert finalized.state == "SUPERSEDED"
    persisted = await repository.get(venue_id="venue-alpha", run_id=run.run_id)
    assert persisted.state == "SUPERSEDED"
    assert persisted.result["late_result"]["advice"]["evidence_status"] == "GROUNDED"
    assert sink.events == [], "a superseded run must not publish a second ready signal"
    await repository._database.close()


async def test_duplicate_enqueue_does_not_re_run_a_finished_advice(tmp_path):
    repository = await _repository(tmp_path)
    queue = InMemoryAdviceQueue()
    command = StubCommand(_result())
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository, queue=queue, incident_command=command, sink=Sink()
    )
    await worker.enqueue(run)
    await worker.run_once()
    await worker.enqueue(run)

    finalized = await worker.run_once()

    assert finalized.state == "READY"
    assert command.calls == 1, "a replayed queue item must not charge the model twice"
    await repository._database.close()
