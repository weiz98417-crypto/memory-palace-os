"""Durable advice workflow contract (ticket m4-04)."""

from __future__ import annotations

import pytest

from src.memory_palace.scenic.advice_dispatch import (
    HatchetAdviceDispatcher,
    InProcessAdviceDispatcher,
)
from src.memory_palace.scenic.advice_runs import (
    AdviceRunRepository,
    AdviceWorker,
    InMemoryAdviceQueue,
    advice_run_id,
)
from src.memory_palace.scenic.hatchet_workflow import (
    ADVICE_DECISION_EVENT_KEY,
    AdviceDecision,
    AdviceRunInput,
)
from tests.integration.test_advice_runs import Sink, StubCommand, _create, _repository, _result
from tests.unit.test_incident_command import _request

pytestmark = pytest.mark.asyncio


class FakeDurableContext:
    """Records the wait and returns a scripted human decision."""

    def __init__(self, decision: AdviceDecision | None = None) -> None:
        self.decision = decision
        self.calls: list[dict] = []

    async def aio_wait_for_event(self, key, *, payload_validator, scope, lookback_window):
        self.calls.append(
            {
                "key": key,
                "validator": payload_validator,
                "scope": scope,
                "lookback": lookback_window,
            }
        )
        if self.decision is None:
            raise TimeoutError("no decision arrived")
        return self.decision


async def test_worker_run_run_id_executes_without_a_queue(tmp_path):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository,
        queue=InMemoryAdviceQueue(),
        incident_command=StubCommand(_result()),
        sink=Sink(),
    )

    finalized = await worker.run_run_id(venue_id="venue-alpha", run_id=run.run_id)

    assert finalized is not None
    assert finalized.state == "READY"
    await repository._database.close()


async def test_durable_task_pauses_on_the_decision_event_after_advice(tmp_path, monkeypatch):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())
    worker = AdviceWorker(
        repository=repository,
        queue=InMemoryAdviceQueue(),
        incident_command=StubCommand(_result()),
        sink=Sink(),
    )

    decision = AdviceDecision(
        decision="ADOPT", decided_by="manager-1", reason_code=None, reason_text=None
    )
    ctx = FakeDurableContext(decision)
    captured: dict = {}

    class FakeWorkflow:
        def durable_task(self, **_kwargs):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

    class FakeHatchet:
        def workflow(self, *, name, input_validator):
            captured["workflow_name"] = name
            return FakeWorkflow()

    from src.memory_palace.scenic import hatchet_workflow

    workflow, _client = hatchet_workflow.build_workflow(
        worker=worker, hatchet=FakeHatchet()
    )
    assert captured["workflow_name"] == "scenic-agent-advice"

    payload = AdviceRunInput(
        advice_run_id=run.run_id,
        venue_id=run.venue_id,
        incident_id=run.incident_id,
    )
    result = await captured["fn"](payload, ctx)

    assert result["state"] == "READY"
    assert result["decision"]["decision"] == "ADOPT"
    assert ctx.calls == [
        {
            "key": ADVICE_DECISION_EVENT_KEY,
            "validator": AdviceDecision,
            "scope": run.incident_id,
            "lookback": hatchet_workflow.DEFAULT_DECISION_LOOKBACK,
        }
    ]
    await repository._database.close()


async def test_durable_task_does_not_wait_when_a_human_already_superseded(tmp_path):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())
    await repository.transition(
        venue_id="venue-alpha",
        run_id=run.run_id,
        expected="PENDING",
        new_state="SUPERSEDED",
        response={"superseded_by": "manager-1"},
    )
    worker = AdviceWorker(
        repository=repository,
        queue=InMemoryAdviceQueue(),
        incident_command=StubCommand(_result()),
        sink=Sink(),
    )
    captured: dict = {}
    ctx = FakeDurableContext(None)

    class FakeWorkflow:
        def durable_task(self, **_kwargs):
            def decorator(fn):
                captured["fn"] = fn
                return fn

            return decorator

    class FakeHatchet:
        def workflow(self, *, name, input_validator):
            return FakeWorkflow()

    from src.memory_palace.scenic import hatchet_workflow

    hatchet_workflow.build_workflow(worker=worker, hatchet=FakeHatchet())
    result = await captured["fn"](
        AdviceRunInput(
            advice_run_id=run.run_id,
            venue_id=run.venue_id,
            incident_id=run.incident_id,
        ),
        ctx,
    )

    assert result["state"] == "SUPERSEDED"
    assert result["decision"] is None
    assert ctx.calls == [], "a superseded run must not block on a human decision"
    await repository._database.close()


async def test_hatchet_dispatcher_triggers_the_durable_workflow(tmp_path):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())

    class FakeWorkflow:
        def __init__(self) -> None:
            self.calls: list[AdviceRunInput] = []

        async def aio_run_no_wait(self, payload: AdviceRunInput) -> None:
            self.calls.append(payload)

    workflow = FakeWorkflow()
    dispatcher = HatchetAdviceDispatcher(workflow)

    await dispatcher.dispatch(run)

    assert dispatcher.backend_name == "hatchet"
    assert workflow.calls == [
        AdviceRunInput(
            advice_run_id=run.run_id,
            venue_id=run.venue_id,
            incident_id=run.incident_id,
        )
    ]
    await repository._database.close()


async def test_in_process_dispatcher_uses_the_local_worker(tmp_path):
    repository = await _repository(tmp_path)
    run, _ = await _create(repository, _request())
    command = StubCommand(_result())
    worker = AdviceWorker(
        repository=repository,
        queue=InMemoryAdviceQueue(),
        incident_command=command,
        sink=Sink(),
    )

    await InProcessAdviceDispatcher(worker).dispatch(run)
    finalized = await worker.run_once()

    assert finalized.state == "READY"
    assert command.calls == 1
    await repository._database.close()
