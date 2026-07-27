import asyncio

import pytest

from src.memory_palace.demo.adapters import DeterministicScenarioAdapter
from src.memory_palace.demo.models import RunAction, RunStatus, StepStatus
from src.memory_palace.demo.scenario_controller import ScenarioController


class FailFirstAttemptAdapter:
    def __init__(self) -> None:
        self._delegate = DeterministicScenarioAdapter()

    async def execute(self, step, sequence, attempt):
        if attempt == 1:
            raise RuntimeError("temporary adapter failure")
        return await self._delegate.execute(step, sequence, attempt)


class BlockingAdapter:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._delegate = DeterministicScenarioAdapter()

    async def execute(self, step, sequence, attempt):
        self.started.set()
        await self.release.wait()
        return await self._delegate.execute(step, sequence, attempt)


class CountingAdapter:
    def __init__(self) -> None:
        self.calls = []
        self._delegate = DeterministicScenarioAdapter()

    async def execute(self, step, sequence, attempt):
        self.calls.append((step.id, attempt))
        await asyncio.sleep(0.001)
        return await self._delegate.execute(step, sequence, attempt)


class NeverCompletesAdapter:
    async def execute(self, step, sequence, attempt):
        await asyncio.Event().wait()


class BlockingFailureAdapter:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, step, sequence, attempt):
        self.started.set()
        await self.release.wait()
        raise RuntimeError("adapter failed at boundary")


@pytest.mark.asyncio
async def test_failed_step_can_be_retried_without_losing_evidence():
    controller = ScenarioController(step_delay_scale=0, adapter=FailFirstAttemptAdapter())
    initial = await controller.create_run("emergency-p0")

    failed = await controller.apply_action(
        initial.run_id,
        RunAction.STEP,
        initial.version,
    )

    assert failed.status is RunStatus.FAILED
    assert failed.progress.completed == 0
    assert [evidence.status for evidence in failed.steps] == [StepStatus.FAILED]
    assert failed.steps[0].attempt == 1
    assert failed.steps[0].error == "RuntimeError: temporary adapter failure"

    recovered = await controller.apply_action(
        initial.run_id,
        RunAction.STEP,
        failed.version,
    )

    assert recovered.status is RunStatus.PAUSED
    assert recovered.progress.completed == 1
    assert [evidence.status for evidence in recovered.steps] == [
        StepStatus.FAILED,
        StepStatus.SUCCESS,
    ]
    assert recovered.steps[1].attempt == 2
    assert recovered.steps[1].retry_count == 1
    assert recovered.steps[1].recovery_summary


@pytest.mark.asyncio
async def test_reset_supersedes_a_queued_pause_at_the_step_boundary():
    adapter = BlockingAdapter()
    controller = ScenarioController(step_delay_scale=0, adapter=adapter)
    initial = await controller.create_run("emergency-p0")
    running = await controller.apply_action(
        initial.run_id,
        RunAction.PLAY,
        initial.version,
    )
    await adapter.started.wait()

    pause_task = asyncio.create_task(controller.apply_action(initial.run_id, RunAction.PAUSE, running.version))
    await asyncio.sleep(0)
    reset_task = asyncio.create_task(controller.apply_action(initial.run_id, RunAction.RESET, running.version))
    await asyncio.sleep(0)
    adapter.release.set()

    await pause_task
    reset = await reset_task
    latest = controller.get_run(initial.run_id)

    assert reset.status is RunStatus.IDLE
    assert reset.trace_id != initial.trace_id
    assert reset.progress.completed == 0
    assert reset.steps == []
    assert latest == reset


@pytest.mark.asyncio
async def test_repeated_play_requests_create_only_one_execution_chain():
    adapter = CountingAdapter()
    controller = ScenarioController(step_delay_scale=0, adapter=adapter)
    initial = await controller.create_run("emergency-p0")

    first, second = await asyncio.gather(
        controller.apply_action(initial.run_id, RunAction.PLAY),
        controller.apply_action(initial.run_id, RunAction.PLAY),
    )

    assert first.status is RunStatus.RUNNING
    assert second.status is RunStatus.RUNNING

    for _ in range(100):
        completed = controller.get_run(initial.run_id)
        if completed.status is RunStatus.COMPLETED:
            break
        await asyncio.sleep(0.005)

    assert completed.status is RunStatus.COMPLETED
    assert completed.progress.completed == completed.progress.total == 7
    assert adapter.calls == [
        ("receive-message", 1),
        ("classify-event", 1),
        ("retrieve-sop", 1),
        ("generate-orders", 1),
        ("notify-teams", 1),
        ("audit-sla", 1),
        ("close-case", 1),
    ]


@pytest.mark.asyncio
async def test_presentation_delay_is_excluded_from_business_duration():
    controller = ScenarioController(step_delay_scale=1)
    controller.get_scenario("emergency-p0").steps[0].presentation_delay_ms = 120
    initial = await controller.create_run("emergency-p0")

    started = asyncio.get_running_loop().time()
    advanced = await controller.apply_action(
        initial.run_id,
        RunAction.STEP,
        initial.version,
    )
    wall_duration_ms = round((asyncio.get_running_loop().time() - started) * 1000)

    assert wall_duration_ms >= 100
    assert advanced.steps[0].duration_ms < 80


@pytest.mark.asyncio
async def test_adapter_timeout_creates_failed_evidence():
    controller = ScenarioController(step_delay_scale=0, adapter=NeverCompletesAdapter())
    controller.get_scenario("emergency-p0").steps[0].timeout_ms = 100
    initial = await controller.create_run("emergency-p0")

    failed = await controller.apply_action(
        initial.run_id,
        RunAction.STEP,
        initial.version,
    )

    assert failed.status is RunStatus.FAILED
    assert failed.steps[0].status is StepStatus.FAILED
    assert failed.steps[0].duration_ms >= 90
    assert failed.steps[0].error == "TimeoutError: Step receive-message timed out after 100 ms"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        (RunAction.STOP, RunStatus.STOPPED),
        (RunAction.RESET, RunStatus.IDLE),
    ],
)
async def test_stop_and_reset_survive_a_failure_at_the_step_boundary(action, expected_status):
    adapter = BlockingFailureAdapter()
    controller = ScenarioController(step_delay_scale=0, adapter=adapter)
    initial = await controller.create_run("emergency-p0")
    running = await controller.apply_action(
        initial.run_id,
        RunAction.PLAY,
        initial.version,
    )
    await adapter.started.wait()

    boundary_task = asyncio.create_task(controller.apply_action(initial.run_id, action, running.version))
    await asyncio.sleep(0)
    adapter.release.set()
    result = await boundary_task

    assert result.status is expected_status
    if action is RunAction.STOP:
        assert result.steps[0].status is StepStatus.FAILED
    else:
        assert result.steps == []
