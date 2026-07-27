from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class ExecutionMode(str, Enum):
    DEMO_ADAPTER = "DEMO_ADAPTER"
    REAL_CONNECTION = "REAL_CONNECTION"


class StepStatus(str, Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class RunAction(str, Enum):
    PLAY = "play"
    PAUSE = "pause"
    STEP = "step"
    STOP = "stop"
    RESET = "reset"


class ClaimLevel(str, Enum):
    VERIFIED = "VERIFIED"
    DEMO_IMPLEMENTATION = "DEMO_IMPLEMENTATION"
    OPTIONAL_CONNECTION = "OPTIONAL_CONNECTION"
    PRODUCTION_EXTENSION = "PRODUCTION_EXTENSION"


class CapabilityState(str, Enum):
    READY = "READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PLANNED = "PLANNED"


class CapabilitySnapshot(BaseModel):
    id: str
    label: str
    claim_level: ClaimLevel
    status: CapabilityState
    detail: str


class EnvironmentSnapshot(BaseModel):
    application: str = "Memory Palace OS"
    mode: str = "ENTERPRISE_DEMO"
    demo_mode: bool = True
    security_mode: str = "LOCAL_DEMO_SIMPLIFIED_AUTH"
    generated_at: datetime
    scenario_data_version: dict[str, int]
    capabilities: list[CapabilitySnapshot]


class ScenarioStep(BaseModel):
    id: str
    title: str
    actor: str
    input_summary: str = ""
    output_summary: str = ""
    route_reason: str | None = None
    timeout_ms: int = Field(default=3000, ge=100, le=120_000)
    presentation_delay_ms: int = Field(default=500, ge=0, le=10_000)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    policy_decision: dict[str, Any] | None = None
    retry_count: int = Field(default=0, ge=0)
    recovery_summary: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.DEMO_ADAPTER


class ScenarioDefinition(BaseModel):
    id: str
    version: int = Field(ge=1)
    title: str
    short_title: str
    description: str
    estimated_seconds: int = Field(gt=0)
    fixed_input: str
    business_outcome: str
    proof_points: list[str]
    steps: list[ScenarioStep] = Field(default_factory=list)


class ScenarioSummary(BaseModel):
    id: str
    version: int
    title: str
    short_title: str
    description: str
    estimated_seconds: int
    proof_points: list[str]
    status: RunStatus = RunStatus.IDLE
    execution_mode: ExecutionMode = ExecutionMode.DEMO_ADAPTER


class StepEvidence(BaseModel):
    step_id: str
    sequence: int
    attempt: int = Field(default=1, ge=1)
    title: str
    actor: str
    status: StepStatus
    started_at: datetime
    duration_ms: int = Field(ge=0)
    input_summary: str
    output_summary: str
    route_reason: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    policy_decision: dict[str, Any] | None = None
    retry_count: int = Field(default=0, ge=0)
    recovery_summary: str | None = None
    execution_mode: ExecutionMode
    error: str | None = None


class RunProgress(BaseModel):
    completed: int = Field(ge=0)
    total: int = Field(ge=0)


class ScenarioRun(BaseModel):
    run_id: str
    trace_id: str
    scenario_id: str
    scenario_version: int
    scenario_title: str
    fixed_input: str
    business_outcome: str
    proof_points: list[str]
    status: RunStatus
    version: int = Field(ge=1)
    current_step_id: str | None = None
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    elapsed_ms: int = Field(default=0, ge=0)
    progress: RunProgress
    steps: list[StepEvidence] = Field(default_factory=list)
    error: str | None = None


class ScenarioReport(BaseModel):
    schema_version: str = "enterprise-demo-report/v1"
    generated_at: datetime
    disclaimer: str
    evidence_count: int = Field(ge=0)
    execution_modes: list[ExecutionMode]
    run: ScenarioRun


class RunActionRequest(BaseModel):
    action: RunAction
    expected_version: int | None = Field(default=None, ge=1)
