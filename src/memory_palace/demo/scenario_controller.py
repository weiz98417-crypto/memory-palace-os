import asyncio
import uuid
from datetime import datetime, timezone
from time import perf_counter

from .adapters import (
    DeterministicScenarioAdapter,
    DeterministicStepFailure,
    ScenarioAdapter,
    tool_calls_for_attempt,
)
from .catalog import ScenarioCatalog
from .models import (
    CapabilitySnapshot,
    CapabilityState,
    ClaimLevel,
    EnvironmentSnapshot,
    ExecutionMode,
    RunAction,
    RunProgress,
    RunStatus,
    ScenarioDefinition,
    ScenarioReport,
    ScenarioRun,
    ScenarioSummary,
    StepEvidence,
    StepStatus,
)


class ScenarioConflictError(RuntimeError):
    pass


class ScenarioVersionConflictError(ScenarioConflictError):
    pass


class ScenarioController:
    """Single public boundary for deterministic demo scenario execution."""

    _BOUNDARY_ACTION_PRIORITY = {
        RunAction.PAUSE: 1,
        RunAction.STOP: 2,
        RunAction.RESET: 3,
    }

    def __init__(
        self,
        catalog: ScenarioCatalog | None = None,
        step_delay_scale: float = 1.0,
        adapter: ScenarioAdapter | None = None,
    ) -> None:
        self._catalog = catalog or ScenarioCatalog()
        self._step_delay_scale = max(0.0, step_delay_scale)
        self._adapter = adapter or DeterministicScenarioAdapter()
        self._runs: dict[str, ScenarioRun] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_runs: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._boundary_actions: dict[str, RunAction] = {}

    def list_scenarios(self) -> list[ScenarioSummary]:
        summaries = []
        for scenario in self._catalog.list():
            active_run = self._runs.get(self._active_runs.get(scenario.id, ""))
            summaries.append(
                ScenarioSummary(
                    id=scenario.id,
                    version=scenario.version,
                    title=scenario.title,
                    short_title=scenario.short_title,
                    description=scenario.description,
                    estimated_seconds=scenario.estimated_seconds,
                    proof_points=scenario.proof_points,
                    status=active_run.status if active_run else RunStatus.IDLE,
                    execution_mode=ExecutionMode.DEMO_ADAPTER,
                )
            )
        return summaries

    def get_scenario(self, scenario_id: str) -> ScenarioDefinition:
        return self._catalog.get(scenario_id)

    def get_environment(self) -> EnvironmentSnapshot:
        return EnvironmentSnapshot(
            generated_at=datetime.now(timezone.utc),
            scenario_data_version={scenario.id: scenario.version for scenario in self._catalog.list()},
            capabilities=[
                CapabilitySnapshot(
                    id="demo-runtime",
                    label="确定性演示运行时",
                    claim_level=ClaimLevel.DEMO_IMPLEMENTATION,
                    status=CapabilityState.READY,
                    detail="版本化场景、进程内运行状态和 Demo Adapter 已启用；真实连接器不加载。",
                ),
                CapabilitySnapshot(
                    id="audit-evidence",
                    label="场景证据与审计",
                    claim_level=ClaimLevel.VERIFIED,
                    status=CapabilityState.READY,
                    detail="每个步骤记录 trace、执行主体、耗时、引用和策略结果。",
                ),
                CapabilitySnapshot(
                    id="real-llm",
                    label="真实 LLM 连接",
                    claim_level=ClaimLevel.OPTIONAL_CONNECTION,
                    status=CapabilityState.NOT_CONFIGURED,
                    detail="默认演示不使用外部模型或密钥。",
                ),
                CapabilitySnapshot(
                    id="enterprise-data",
                    label="PostgreSQL / Redis / pgvector",
                    claim_level=ClaimLevel.OPTIONAL_CONNECTION,
                    status=CapabilityState.NOT_CONFIGURED,
                    detail="已有连接代码，但不进入默认演示关键路径。",
                ),
                CapabilitySnapshot(
                    id="enterprise-ha",
                    label="高可用与灾备",
                    claim_level=ClaimLevel.PRODUCTION_EXTENSION,
                    status=CapabilityState.PLANNED,
                    detail="属于企业试点和生产化阶段，不在 V1 承诺范围内。",
                ),
            ],
        )

    async def create_run(self, scenario_id: str) -> ScenarioRun:
        self._prune_finished_runs()
        scenario = self._catalog.get(scenario_id)
        active_run = self._runs.get(self._active_runs.get(scenario_id, ""))
        if active_run and active_run.status in {
            RunStatus.IDLE,
            RunStatus.RUNNING,
            RunStatus.PAUSED,
            RunStatus.FAILED,
        }:
            return active_run.model_copy(deep=True)

        now = datetime.now(timezone.utc)
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        run = ScenarioRun(
            run_id=run_id,
            trace_id=f"trace_{uuid.uuid4().hex[:16]}",
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            scenario_title=scenario.title,
            fixed_input=scenario.fixed_input,
            business_outcome=scenario.business_outcome,
            proof_points=scenario.proof_points,
            status=RunStatus.IDLE,
            version=1,
            current_step_id=scenario.steps[0].id if scenario.steps else None,
            updated_at=now,
            progress=RunProgress(completed=0, total=len(scenario.steps)),
        )
        self._runs[run_id] = run
        self._locks[run_id] = asyncio.Lock()
        self._active_runs[scenario_id] = run_id
        return run.model_copy(deep=True)

    def get_run(self, run_id: str) -> ScenarioRun:
        return self._require_run(run_id).model_copy(deep=True)

    def get_report(self, run_id: str) -> ScenarioReport:
        run = self.get_run(run_id)
        execution_modes = sorted(
            {step.execution_mode for step in run.steps},
            key=lambda mode: mode.value,
        )
        return ScenarioReport(
            generated_at=datetime.now(timezone.utc),
            disclaimer="本报告中的外部模型、企微、短信和语音动作均为模拟执行。",
            evidence_count=len(run.steps),
            execution_modes=execution_modes,
            run=run,
        )

    async def apply_action(
        self,
        run_id: str,
        action: RunAction,
        expected_version: int | None = None,
    ) -> ScenarioRun:
        run = self._require_run(run_id)

        if action in {RunAction.PAUSE, RunAction.STOP, RunAction.RESET} and run.status is RunStatus.RUNNING:
            self._check_version(run, expected_version)
            queued_action = self._boundary_actions.get(run_id)
            if (
                queued_action is None
                or self._BOUNDARY_ACTION_PRIORITY[action] > self._BOUNDARY_ACTION_PRIORITY[queued_action]
            ):
                self._boundary_actions[run_id] = action
            async with self._locks[run_id]:
                run = self._require_run(run_id)
                if run.status is RunStatus.RUNNING:
                    boundary_action = self._boundary_actions.pop(run_id, action)
                    self._apply_boundary_action(run, boundary_action)
                elif action is RunAction.RESET and run.status is not RunStatus.IDLE:
                    self._reset(run)
                return run.model_copy(deep=True)

        async with self._locks[run_id]:
            self._check_version(run, expected_version)
            if action is RunAction.STEP:
                await self._step(run)
            elif action is RunAction.PLAY:
                self._play(run)
            elif action is RunAction.PAUSE:
                self._pause(run)
            elif action is RunAction.STOP:
                self._stop(run)
            elif action is RunAction.RESET:
                self._reset(run)
            else:
                raise ScenarioConflictError(f"Unsupported action: {action.value}")
            return run.model_copy(deep=True)

    async def _step(self, run: ScenarioRun) -> None:
        if run.status not in {RunStatus.IDLE, RunStatus.PAUSED, RunStatus.FAILED}:
            raise ScenarioConflictError(f"Cannot step a run in {run.status.value}")
        await self._advance_step(run, pause_after=True)

    def _play(self, run: ScenarioRun) -> None:
        if run.status is RunStatus.RUNNING:
            return
        if run.status not in {RunStatus.IDLE, RunStatus.PAUSED, RunStatus.FAILED}:
            raise ScenarioConflictError(f"Cannot play a run in {run.status.value}")
        if run.progress.completed >= run.progress.total:
            raise ScenarioConflictError("Scenario has no remaining steps")
        if run.started_at is None:
            run.started_at = datetime.now(timezone.utc)
        run.status = RunStatus.RUNNING
        run.version += 1
        run.updated_at = datetime.now(timezone.utc)
        task = asyncio.create_task(self._run_to_completion(run.run_id))
        self._tasks[run.run_id] = task
        task.add_done_callback(lambda completed: self._discard_task(run.run_id, completed))

    def _pause(self, run: ScenarioRun) -> None:
        if run.status is not RunStatus.RUNNING:
            raise ScenarioConflictError(f"Cannot pause a run in {run.status.value}")
        run.status = RunStatus.PAUSED
        run.version += 1
        run.updated_at = datetime.now(timezone.utc)

    def _stop(self, run: ScenarioRun) -> None:
        if run.status not in {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.FAILED}:
            raise ScenarioConflictError(f"Cannot stop a run in {run.status.value}")
        run.status = RunStatus.STOPPED
        run.version += 1
        run.updated_at = datetime.now(timezone.utc)

    def _reset(self, run: ScenarioRun) -> None:
        scenario = self._catalog.get(run.scenario_id)
        self._boundary_actions.pop(run.run_id, None)
        run.trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        run.status = RunStatus.IDLE
        run.version += 1
        run.current_step_id = scenario.steps[0].id if scenario.steps else None
        run.started_at = None
        run.updated_at = datetime.now(timezone.utc)
        run.completed_at = None
        run.elapsed_ms = 0
        run.progress.completed = 0
        run.steps.clear()
        run.error = None

    async def _run_to_completion(self, run_id: str) -> None:
        while True:
            async with self._locks[run_id]:
                run = self._require_run(run_id)
                if run.status is not RunStatus.RUNNING:
                    return
                await self._advance_step(run, pause_after=False)
                boundary_action = self._boundary_actions.pop(run_id, None)
                if boundary_action is not None:
                    if run.status is RunStatus.RUNNING:
                        self._apply_boundary_action(run, boundary_action)
                    elif run.status is RunStatus.FAILED and boundary_action in {
                        RunAction.STOP,
                        RunAction.RESET,
                    }:
                        self._apply_boundary_action(run, boundary_action)
                if run.status is not RunStatus.RUNNING:
                    return
            # Let pending pause/stop actions acquire the run lock at a step boundary.
            await asyncio.sleep(0)

    def _apply_boundary_action(self, run: ScenarioRun, action: RunAction) -> None:
        if action is RunAction.PAUSE:
            self._pause(run)
        elif action is RunAction.STOP:
            self._stop(run)
        elif action is RunAction.RESET:
            self._reset(run)

    async def _advance_step(self, run: ScenarioRun, pause_after: bool) -> None:
        scenario = self._catalog.get(run.scenario_id)
        index = run.progress.completed
        if index >= len(scenario.steps):
            raise ScenarioConflictError("Scenario has no remaining steps")

        if run.started_at is None:
            run.started_at = datetime.now(timezone.utc)
        step = scenario.steps[index]
        attempt = sum(evidence.step_id == step.id for evidence in run.steps) + 1
        while True:
            delay_seconds = step.presentation_delay_ms * self._step_delay_scale / 1000
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            started_at = datetime.now(timezone.utc)
            started = perf_counter()
            try:
                try:
                    evidence = await asyncio.wait_for(
                        self._adapter.execute(step, index + 1, attempt),
                        timeout=step.timeout_ms / 1000,
                    )
                except TimeoutError as exc:
                    raise TimeoutError(f"Step {step.id} timed out after {step.timeout_ms} ms") from exc
                evidence.started_at = started_at
                evidence.duration_ms = max(1, round((perf_counter() - started) * 1000))
                if attempt > 1:
                    evidence.retry_count = max(evidence.retry_count, attempt - 1)
                    evidence.recovery_summary = evidence.recovery_summary or (
                        f"第 {attempt} 次尝试成功，已从上一次步骤失败中恢复。"
                    )
                break
            except Exception as exc:
                duration_ms = max(1, round((perf_counter() - started) * 1000))
                failed_evidence = StepEvidence(
                    step_id=step.id,
                    sequence=index + 1,
                    attempt=attempt,
                    title=step.title,
                    actor=step.actor,
                    status=StepStatus.FAILED,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    input_summary=step.input_summary,
                    output_summary="步骤未完成，可重试当前步骤或重置场景。",
                    route_reason=step.route_reason,
                    citations=step.citations,
                    tool_calls=tool_calls_for_attempt(step, attempt),
                    policy_decision=step.policy_decision,
                    retry_count=max(0, attempt - 1),
                    execution_mode=step.execution_mode,
                    error=f"{type(exc).__name__}: {exc}",
                )
                run.steps.append(failed_evidence)
                run.current_step_id = step.id
                run.error = failed_evidence.error
                run.elapsed_ms = sum(item.duration_ms for item in run.steps)
                run.version += 1
                run.updated_at = datetime.now(timezone.utc)

                if isinstance(exc, DeterministicStepFailure) and attempt <= step.retry_count:
                    attempt += 1
                    continue

                run.status = RunStatus.FAILED
                return

        run.steps.append(evidence)
        run.progress.completed += 1
        run.elapsed_ms = sum(step.duration_ms for step in run.steps)
        run.error = None
        run.version += 1
        run.updated_at = datetime.now(timezone.utc)

        if run.progress.completed == run.progress.total:
            run.status = RunStatus.COMPLETED
            run.current_step_id = None
            run.completed_at = run.updated_at
        else:
            run.status = RunStatus.PAUSED if pause_after else RunStatus.RUNNING
            run.current_step_id = scenario.steps[run.progress.completed].id

    def _discard_task(self, run_id: str, completed: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is completed:
            self._tasks.pop(run_id, None)
        if completed.cancelled():
            return
        error = completed.exception()
        if error is None:
            return
        run = self._runs.get(run_id)
        if run and run.status is RunStatus.RUNNING:
            run.status = RunStatus.FAILED
            run.error = f"{type(error).__name__}: {error}"
            run.version += 1
            run.updated_at = datetime.now(timezone.utc)

    def _prune_finished_runs(self) -> None:
        finished = sorted(
            (run for run in self._runs.values() if run.status in {RunStatus.COMPLETED, RunStatus.STOPPED}),
            key=lambda run: run.completed_at or run.updated_at,
        )
        for run in finished[:-100]:
            self._runs.pop(run.run_id, None)
            self._locks.pop(run.run_id, None)
            self._boundary_actions.pop(run.run_id, None)
            task = self._tasks.get(run.run_id)
            if task is None or task.done():
                self._tasks.pop(run.run_id, None)
            if self._active_runs.get(run.scenario_id) == run.run_id:
                self._active_runs.pop(run.scenario_id, None)

    def _require_run(self, run_id: str) -> ScenarioRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"Unknown demo run: {run_id}") from exc

    @staticmethod
    def _check_version(run: ScenarioRun, expected_version: int | None) -> None:
        if expected_version is not None and run.version != expected_version:
            raise ScenarioVersionConflictError(
                f"Run version changed: expected {expected_version}, current {run.version}"
            )


_controller = ScenarioController()


def get_scenario_controller() -> ScenarioController:
    return _controller
