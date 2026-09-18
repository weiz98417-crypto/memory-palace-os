# IncidentCommand 施工契约（景区 Agent 主干 · 票 04）

状态：已接受为施工基线（2026-09-16）

## 1. 结论

`IncidentCommand` 是景区 Agent 主干唯一新增的最高 seam。调用方只提交已经完成租户校验的现场事实与知识证据，接收结构化建议、派单草案或关闭摘要，以及模型调用记录引用。它不直接查 pgvector、不写事件状态机、不执行派单或关闭。

四个 agent 的数据依赖顺序固定为：

```text
context_trigger -> router -> memory_ops -> commander
```

- `context_trigger`：装配、归一化并去重上下文。
- `router`：判定意图、风险等级与风险码。
- `memory_ops`：只基于已核验知识给出建议与来源引用；无命中必须明确“没有依据”。
- `commander`：消费前面的输出，生成派单草案或关闭摘要；不能执行决定。

派单草案阶段必须已经有人工流程判断：采纳、填理由忽略，或明确选择“不等待建议”并触发 `SUPERSEDED`；关闭摘要是卷宗材料，不能替代既有关闭门禁。两类人工门禁和真实调用真实性继续受 ADR-0018 约束。

## 2. 公开接口

```python
from typing import Protocol

class IncidentCommand(Protocol):
    async def execute(
        self,
        request: IncidentCommandRequest,
    ) -> IncidentCommandResult:
        """执行一个业务阶段；只有这一项公开方法。"""
        ...
```

实现类建议命名为 `PydanticAIIncidentCommand`。依赖通过构造器注入，调用方不得访问内部 agent、prompt、LiteLLM 或回调：

```python
class PydanticAIIncidentCommand:
    def __init__(
        self,
        *,
        agent_registry: IncidentAgentRegistry,
        call_recorder: ModelCallRecorder,
        config: IncidentCommandConfig,
        clock: Callable[[], float],
    ) -> None: ...
```

`agent_registry` 返回带类型参数的 pydantic-ai agent；`call_recorder` 只负责把 LiteLLM 回调归一化并关联到 `llm_call_logs`。`IncidentCommand` 不保存 prompt，不直接写业务表，不读 Jaeger。

## 3. 输入与输出模型

所有契约继承 `ContractModel`，默认 `extra="forbid"`；所有标识符必须是字符串，时间使用 UTC epoch seconds，金额不在本票范围。

```python
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class CommandMode(StrEnum):
    ADVICE = "ADVICE"
    DISPATCH_DRAFT = "DISPATCH_DRAFT"
    CLOSURE_SUMMARY = "CLOSURE_SUMMARY"


class IncidentSnapshot(ContractModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    event_id: str
    business_id: str
    venue_id: str
    run_id: str
    lifecycle: str
    priority: Severity
    title: str
    event_type: str
    raw_text: str
    conversion_reason: str
    occurred_at: float


class FieldEvidence(ContractModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: str
    text: str = ""
    attachment_id: str | None = None
    submitted_by: str
    submitted_at: float


class KnowledgeHit(ContractModel):
    model_config = ConfigDict(extra="forbid")

    vector_doc_id: str
    source_id: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"]
    source_label: str
    title: str
    version: str
    vector_score: float = Field(ge=0.0, le=1.0)
    rerank_score: float | None = None
    excerpt: str = ""
    content_sha256: str


class HistoricalCase(ContractModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    business_id: str
    title: str
    outcome: str
    closed_at: float
    excerpt: str


class VerifiedKnowledge(ContractModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_snapshot_id: str
    sop_hits: list[KnowledgeHit] = Field(default_factory=list)
    historical_cases: list[HistoricalCase] = Field(default_factory=list)
    experience_hits: list[KnowledgeHit] = Field(default_factory=list)


class AdviceDecisionRef(ContractModel):
    decision_id: str
    advice_run_id: str | None = None
    incident_id: str
    decision: Literal["ADOPT", "IGNORE", "PROCEED_WITHOUT_WAITING"]
    decided_by: str
    decided_at: float
    reason_ref: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "AdviceDecisionRef":
        if self.decision in {"ADOPT", "IGNORE"} and not self.advice_run_id:
            raise ValueError("adopt/ignore must reference an advice run")
        if self.decision == "IGNORE" and not self.reason_ref:
            raise ValueError("ignore requires a structured reason reference")
        return self


class ClosureFacts(ContractModel):
    model_config = ConfigDict(extra="forbid")

    evidence_refs: list[str] = Field(default_factory=list)
    sop_hit_refs: list[str] = Field(default_factory=list)
    completed_task_refs: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    alert_recovery_refs: list[str] = Field(default_factory=list)


class IncidentCommandPrior(ContractModel):
    context: "ContextTriggerOutput"
    routing: "RouterOutput"
    advice_run_id: str | None = None
    advice: "MemoryOpsOutput | None"
    advice_state: Literal[
        "PENDING",
        "RUNNING",
        "READY",
        "FAILED",
        "SUPERSEDED",
        "UNAVAILABLE",
    ]


class IncidentCommandRequest(ContractModel):
    model_config = ConfigDict(extra="forbid")

    mode: CommandMode
    trace_id: str
    idempotency_key: str
    attempt: int = Field(default=1, ge=1)
    incident: IncidentSnapshot
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    knowledge: VerifiedKnowledge
    prior: IncidentCommandPrior | None = None
    advice_decision: AdviceDecisionRef | None = None
    closure_facts: ClosureFacts | None = None

    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, value: str) -> str:
        if (
            len(value) != 32
            or value == "0" * 32
            or any(ch not in "0123456789abcdef" for ch in value.lower())
        ):
            raise ValueError("trace_id must be a non-zero W3C 32-hex trace id")
        return value.lower()

    @model_validator(mode="after")
    def validate_phase(self) -> "IncidentCommandRequest":
        if not self.incident.venue_id:
            raise ValueError("venue_id is required")
        if self.mode == CommandMode.DISPATCH_DRAFT:
            if self.prior is None or self.advice_decision is None:
                raise ValueError("dispatch draft requires prior context and a flow-gate decision")
            decision = self.advice_decision
            if decision.incident_id != self.incident.incident_id:
                raise ValueError("flow-gate decision belongs to another incident")
            if not self.prior.advice_run_id:
                raise ValueError("flow gate requires a stable advice run id")
            if decision.advice_run_id and decision.advice_run_id != self.prior.advice_run_id:
                raise ValueError("flow-gate decision belongs to another advice run")
            if self.prior.advice_state in {"PENDING", "RUNNING"} and self.prior.advice is not None:
                raise ValueError("pending/running advice cannot already contain a result")
            if self.prior.advice_state in {"FAILED", "UNAVAILABLE"} and self.prior.advice is not None:
                raise ValueError("failed/unavailable advice cannot contain a normal result")
            if self.prior.advice_state == "READY":
                if self.prior.advice is None:
                    raise ValueError("READY advice state requires the advice artifact")
                if self.prior.advice.evidence_status == "GROUNDED":
                    if decision.decision not in {"ADOPT", "IGNORE"}:
                        raise ValueError("grounded ready advice requires adopt or ignore")
                elif self.prior.advice.evidence_status == "NO_EVIDENCE":
                    if decision.decision not in {"IGNORE", "PROCEED_WITHOUT_WAITING"}:
                        raise ValueError("no-evidence advice cannot be adopted")
                else:
                    raise ValueError("READY advice must contain a terminal evidence status")
            elif decision.decision in {"ADOPT", "IGNORE"}:
                raise ValueError("adopt/ignore requires READY advice")
        if self.mode == CommandMode.CLOSURE_SUMMARY:
            if self.prior is None or self.closure_facts is None:
                raise ValueError("closure summary requires prior context and closure facts")
        return self
```

`FieldEvidence` 当前表没有 `venue_id` 列，租户校验由调用方在进入 seam 前完成；模型中的 `IncidentCommandRequest` 不允许跨场地拼装。

`AdviceDecisionRef` 只证明流程推进门禁已经由人作出判断；忽略理由的具体字段、存储形式和可见性由票 05 的语义决定，本票只要求 `IGNORE` 必须带一个稳定的 `reason_ref`，并绑定到具体 advice run。

票 05 后续细化（2026-09-17）：`READY/GROUNDED` 只能 `ADOPT` 或 `IGNORE`；`READY/NO_EVIDENCE` 不能 `ADOPT`，只能 `IGNORE` 或 `PROCEED_WITHOUT_WAITING`。`PROCEED_WITHOUT_WAITING` 在 pending/running 时触发 `SUPERSEDED`，且必须带结构化 reason。

### 3.1 四个 agent 的契约

契约文件放在各 skill 目录，`IncidentCommand` 只导入这些类型：

- `src/memory_palace/skills/context_trigger/contracts.py`
- `src/memory_palace/skills/router/contracts.py`
- `src/memory_palace/skills/memory_ops/contracts.py`
- `src/memory_palace/skills/commander/contracts.py`

```python
class ContextTriggerInput(ContractModel):
    incident: IncidentSnapshot
    field_evidence: list[FieldEvidence]
    knowledge: VerifiedKnowledge


class ContextTriggerOutput(ContractModel):
    normalized_summary: str
    triggered: bool
    event_type: str
    severity_hint: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    deduplicated_count: int = Field(default=0, ge=0)


class RouterInput(ContractModel):
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    field_evidence: list[FieldEvidence]


class RouterOutput(ContractModel):
    intent: Literal["incident_report", "emergency_advice", "chitchat", "other"]
    severity: Severity
    summary: str
    is_critical: bool
    confidence: float = Field(ge=0.0, le=1.0)
    risk_reason: str
    risk_codes: list[str] = Field(default_factory=list)


class KnowledgeCitation(ContractModel):
    source_id: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"]
    title: str
    version: str
    vector_score: float = Field(ge=0.0, le=1.0)
    rerank_score: float | None = None
    excerpt: str


class MemoryOpsInput(ContractModel):
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    routing: RouterOutput
    knowledge: VerifiedKnowledge


class MemoryOpsOutput(ContractModel):
    evidence_status: Literal["GROUNDED", "NO_EVIDENCE", "RETRIEVAL_FAILED"]
    advice_text: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    absence_reason: str | None = None

    @model_validator(mode="after")
    def enforce_grounding(self) -> "MemoryOpsOutput":
        if self.evidence_status == "GROUNDED" and not self.citations:
            raise ValueError("grounded advice requires at least one citation")
        if self.evidence_status != "GROUNDED" and self.citations:
            raise ValueError("non-grounded output cannot cite knowledge")
        if self.evidence_status == "NO_EVIDENCE" and self.advice_text != "没有依据":
            raise ValueError("no evidence must say 没有依据")
        if self.evidence_status == "RETRIEVAL_FAILED" and self.advice_text != "未获得模型建议":
            raise ValueError("retrieval failure must say 未获得模型建议")
        return self


class PlannedAction(ContractModel):
    action_code: str
    description: str
    preconditions: list[str] = Field(default_factory=list)


class DispatchDraft(ContractModel):
    artifact: Literal["DISPATCH_DRAFT"] = "DISPATCH_DRAFT"
    summary: str
    priority: Severity
    immediate_actions: list[PlannedAction]
    required_tools: list[str]
    next_step_check: str
    risk_reason: str
    requires_human_approval: bool


class ClosureSummary(ContractModel):
    artifact: Literal["CLOSURE_SUMMARY"] = "CLOSURE_SUMMARY"
    outcome_summary: str
    evidence_refs: list[str]
    sop_refs: list[str]
    completed_task_refs: list[str]
    approval_refs: list[str]
    alert_recovery_refs: list[str]
    unresolved_risks: list[str]
    recommended_for_closure: bool


class CommanderInput(ContractModel):
    mode: Literal["DISPATCH_DRAFT", "CLOSURE_SUMMARY"]
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    routing: RouterOutput
    knowledge: VerifiedKnowledge
    prior_advice: MemoryOpsOutput | None = None
    advice_decision: AdviceDecisionRef | None = None
    closure_facts: ClosureFacts | None = None


CommanderDispatchOutput = DispatchDraft
CommanderClosureOutput = ClosureSummary
CommanderOutput = Annotated[
    DispatchDraft | ClosureSummary,
    Field(discriminator="artifact"),
]

HIGH_RISK_ACTION_CODES = frozenset({
    "CONTINUE_SUSPENSION",
    "ACTIVATE_BACKUP_VEHICLE",
    "RELEASE_RISK",
    "RESUME_OPERATION",
    "CLOSE_INCIDENT",
})
```

约束：

- `KnowledgeHit` 是进入 agent 的完整候选证据，`KnowledgeCitation` 是模型最终选择、可展示给用户的子集；两者不是重复 DTO，不能用一个无类型的字典替代。
- `MemoryOpsOutput.citations` 必须是输入 `VerifiedKnowledge` 中已核验来源的子集；不允许模型自行创造 source id。
- `NO_EVIDENCE` 由后端固定为“没有依据”，不依赖模型是否愿意写这句。
- `CommanderInput.mode` 必须选择 mode-specific output：`DISPATCH_DRAFT -> CommanderDispatchOutput`，`CLOSURE_SUMMARY -> CommanderClosureOutput`；registry 不允许一个 mode 返回另一个 artifact。
- `requires_human_approval` 是模型建议；业务策略必须把来自 `HIGH_RISK_ACTION_CODES`（首版含继续停运、启用备用车、解除风险、恢复运营和关闭事件）的动作与模型字段做逻辑 OR，模型返回 false 不能取消审批。
- `ClosureSummary` 只是摘要；能否关闭仍由既有 `event_closure` 门禁计算。

## 4. `IncidentCommandResult` 与调用记录引用

```python
class AgentRole(StrEnum):
    CONTEXT_TRIGGER = "context_trigger"
    ROUTER = "router"
    MEMORY_OPS = "memory_ops"
    COMMANDER = "commander"


class ModelCallRef(ContractModel):
    call_id: str
    trace_id: str
    agent_id: str
    agent_name: str
    status: Literal["SUCCEEDED", "SUCCEEDED_NO_USAGE", "FAILED", "MOCKED"]
    is_mock: bool

    @model_validator(mode="after")
    def validate_mock_status(self) -> "ModelCallRef":
        if self.status == "MOCKED" and not self.is_mock:
            raise ValueError("MOCKED status requires is_mock=true")
        if self.status in {"SUCCEEDED", "SUCCEEDED_NO_USAGE"} and self.is_mock:
            raise ValueError("successful real status cannot be marked mock")
        return self


class AgentDegradation(ContractModel):
    agent_role: AgentRole
    code: Literal[
        "DISABLED",
        "TIMEOUT",
        "FAILED",
        "INVALID_OUTPUT",
        "CIRCUIT_OPEN",
        "QUOTA_EXCEEDED",
        "RETRIEVAL_FAILED",
        "USAGE_NOT_REPORTED",
    ]
    public_message: str
    call_id: str | None = None


class IncidentCommandResult(ContractModel):
    command_id: str
    mode: CommandMode
    trace_id: str
    idempotency_key: str
    outcome: Literal["READY", "DEGRADED", "FAILED"]
    context: ContextTriggerOutput
    routing: RouterOutput
    advice: MemoryOpsOutput | None = None
    dispatch_draft: DispatchDraft | None = None
    closure_summary: ClosureSummary | None = None
    call_refs: list[ModelCallRef] = Field(default_factory=list)
    degradations: list[AgentDegradation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_artifact(self) -> "IncidentCommandResult":
        if self.outcome == "READY" and self.degradations:
            raise ValueError("READY result cannot contain degradations")
        if self.outcome == "DEGRADED" and not self.degradations:
            raise ValueError("DEGRADED result requires at least one degradation")
        if self.dispatch_draft and self.closure_summary:
            raise ValueError("one result cannot contain two commander artifacts")
        if self.mode == CommandMode.ADVICE:
            if self.dispatch_draft or self.closure_summary:
                raise ValueError("ADVICE cannot return commander artifacts")
            if self.outcome == "READY" and self.advice is None:
                raise ValueError("successful ADVICE requires advice")
        if self.mode == CommandMode.DISPATCH_DRAFT:
            if self.advice is not None or self.closure_summary:
                raise ValueError("DISPATCH_DRAFT returns only a dispatch draft")
            if self.outcome == "READY" and self.dispatch_draft is None:
                raise ValueError("successful DISPATCH_DRAFT requires a draft")
        if self.mode == CommandMode.CLOSURE_SUMMARY:
            if self.advice is not None or self.dispatch_draft:
                raise ValueError("CLOSURE_SUMMARY returns only a closure summary")
            if self.outcome == "READY" and self.closure_summary is None:
                raise ValueError("successful CLOSURE_SUMMARY requires a summary")
        return self
```

`call_refs` 只引用 `llm_call_logs`，不复制 token、模型名、耗时等事实字段。卷宗和诊断页按 `trace_id` 或 `call_id` 查询该表。这样同一事实不会在响应或活动表里形成第二份真相。

## 5. 编排与降级

| 模式 | 实际模型依赖链 | 终端产物 | 人工门禁 |
| --- | --- | --- | --- |
| `ADVICE` | `context_trigger -> router -> memory_ops` | `advice` | 建议进入过程不越过派单边界 |
| `DISPATCH_DRAFT` | `context_trigger -> router -> commander`，`memory_ops` 复用 `prior.advice` 已固化输出 | `dispatch_draft` | 必须携带流程门禁判断；无建议先处置可为 `PROCEED_WITHOUT_WAITING` |
| `CLOSURE_SUMMARY` | `context_trigger -> router -> commander`，`memory_ops` 复用 `prior.advice` 已固化输出 | `closure_summary` | 关闭门禁仍由既有业务层校验 |

代码执行时每一步按如下顺序：检查开关和熔断状态 -> 建立 OTel span -> 用带类型的 pydantic-ai agent 调用 -> 校验 Pydantic 输出 -> 收集 `ModelCallRef` -> 将输出传给下一步。任一环节失败时只替换该环节；后续可以拿到明确的降级信号，但不得伪造成功输出。

| agent | 独立开关 | 默认超时 | 失败时的外部行为 |
| --- | --- | --- | --- |
| `context_trigger` | `SCENIC_AGENT_CONTEXT_TRIGGER_ENABLED` | 20s | 使用确定性事件/证据摘要继续，标记 `DEGRADED` |
| `router` | `SCENIC_AGENT_ROUTER_ENABLED` | 20s | 沿用事件表已有严重度和事件类型，标记 `DEGRADED` |
| `memory_ops` | `SCENIC_AGENT_MEMORY_OPS_ENABLED` | 20s | `advice=None`，界面映射为“未获得模型建议”，不生成假引用，标记 `DEGRADED` |
| `commander` | `SCENIC_AGENT_COMMANDER_ENABLED` | 20s | 无草案/摘要；由人继续操作，不自动推进 |

每个 agent 的超时可单独覆盖：`SCENIC_AGENT_<ROLE>_TIMEOUT_SECONDS`。即使 `DISABLED/CIRCUIT_OPEN/QUOTA_EXCEEDED` 没有 provider call，也必须把完整 `degradations` 写入当前 `IncidentCommandResult.command_id` 对应的 `scenic_commands.response_json`；实际 `FAILED` 调用另由 `llm_call_logs` 保存，二者不能互相冒充，且不得回写或覆盖已 READY 的建议运行。

单次外部调用失败重试 1 次；同一场地的熔断键为 `scenic:agent:circuit:{venue_id}:{agent_role}`，连续 3 次终失败后打开 60 秒。熔断只影响该场地、该 agent；打开期间不产生伪造调用记录，只产生 `AgentDegradation(code="CIRCUIT_OPEN")`。每日 token 配额触顶时走同样降级路径，诊断为 `QUOTA_EXCEEDED`。

## 6. 异步建议状态机

状态机持久化复用既有 `scenic_commands`，不新增建议表，也不把 Redis 或 Hatchet 历史当业务事实源。`scenic_situation_events` 只作为 SSE 的派生投影/outbox；若投影丢失，可从 `scenic_commands` 重建。

`scenic_commands` 行映射：

| 逻辑字段 | 列值 |
| --- | --- |
| `advice_run_id` | `id` |
| `venue_id` | `venue_id` |
| `command_type` | `GENERATE_ADVICE` |
| `idempotency_key` | `advice:{incident_id}:{step}:{attempt}` |
| `request_hash` | tenant + canonical incident/evidence snapshot digest + retrieval snapshot id + prior artifact/run fingerprint + advice decision（含 decision/reason_ref）或 closure facts digest + step + attempt 的 SHA-256；同一 key 的不同输入返回冲突 |
| `state` | `status`，取 `PENDING/RUNNING/READY/FAILED/SUPERSEDED` |
| result | `response_json`，只放建议正文、引用摘要、call refs、`degradations`、`superseded_by`/`late_result` 和状态元数据 |
| failure | `error_type` / `error_message` |
| timestamps | `created_at` / `updated_at` |

`GENERATE_ADVICE` 行只由异步建议 repository/worker 更新，不经过 `ScenicAreaOperations._execute_locked`；既有业务命令继续使用 `PROCESSING/SUCCEEDED/FAILED`。建议运行使用独立的 `PENDING/RUNNING/READY/FAILED/SUPERSEDED`，通过 `command_type` 和 `advice:` 前缀隔离，避免同一张表出现两种状态语义冲突。

`scenic_commands` 也承接另外两种 Agent 运行记录，但各自使用独立 key 和状态行：`DISPATCH_DRAFT -> DRAFT_DISPATCH`，`CLOSURE_SUMMARY -> SUMMARIZE_CLOSURE`。它们只记录自己的 `degradations` 和产物，不回写 `GENERATE_ADVICE` 行。

`step` 对所有 mode 都等于 `request.mode.value`：`ADVICE`、`DISPATCH_DRAFT` 或 `CLOSURE_SUMMARY`。`attempt` 从 1 开始；业务级 attempt 内允许一次 provider 重试，provider 重试不会改变状态机 key。三个 mode 的幂等键分别为：

- `GENERATE_ADVICE`: `advice:{incident_id}:ADVICE:{attempt}`
- `DRAFT_DISPATCH`: `dispatch:{incident_id}:DISPATCH_DRAFT:{attempt}`
- `SUMMARIZE_CLOSURE`: `closure:{incident_id}:CLOSURE_SUMMARY:{attempt}`

`DRAFT_DISPATCH` 与 `SUMMARIZE_CLOSURE` 的状态迁移固定为 `PENDING -> RUNNING -> READY/FAILED`，没有 `SUPERSEDED`；它们只在对应门禁已经满足后创建。

`step` 同时进入 `llm_call_logs.id` 的 UUIDv5 输入，因此同一事件在 advice 与 dispatch 两次运行中的 `context_trigger`/`router` 调用不会碰撞。相同 `(incident_id, step, attempt)` 再次入队时，`ON CONFLICT (venue_id, idempotency_key)` 只返回已有行，不重复调用模型，也不重复写 `llm_call_logs`。

状态迁移只有下列合法边：

```text
PENDING -> RUNNING -> READY
PENDING -> FAILED
PENDING -> SUPERSEDED
RUNNING -> FAILED
RUNNING -> SUPERSEDED
```

不设 `READY -> SUPERSEDED`。`SUPERSEDED` 的判定不是时间猜测：当人选择不等建议、直接进入派单前的流程推进动作时，业务命令在同一事务内对仍在 `PENDING/RUNNING` 的建议执行 CAS，记录 `superseded_by` 为人的动作/事件 id，并把该 id 写入 SSE data。若模型随后才返回，结果可保存在 `response_json` 的 `late_result`，但终态只能是 `SUPERSEDED`，不得静默丢弃。`FAILED` 后由人重新生成时创建 `attempt + 1` 的新 key。

SSE 从 `scenic_situation_events` 读取，每条状态迁移写一条带 `sequence` 的派生事件；投影事件 id 由 `(idempotency_key, state)` 做 UUIDv5，重复投递不产生重复事件。SSE 事件名保持规格中的三种，`SUPERSEDED` 通过 payload 的 `state` 区分：

| 持久状态 | SSE 事件 | `data.state` |
| --- | --- | --- |
| `PENDING` / `RUNNING` | `ADVICE_PENDING` | 原状态 |
| `READY` | `ADVICE_READY` | `READY` |
| `SUPERSEDED` | `ADVICE_READY` | `SUPERSEDED` |
| `FAILED` | `ADVICE_FAILED` | `FAILED` |

SSE `data` 最小结构：

```json
{
  "event_version": 1,
  "advice_run_id": "scenic-command-id",
  "incident_id": "incident-id",
  "step": "ADVICE",
  "attempt": 1,
  "idempotency_key": "advice:incident-id:ADVICE:1",
  "state": "PENDING",
  "superseded_by": null,
  "trace_id": "0123456789abcdef0123456789abcdef",
  "occurred_at": 1780000000.0,
  "result": null,
  "error": null
}
```

HTTP 快照返回当前状态和最后一次结果；客户端断线后使用 `Last-Event-ID` 或 `after_sequence` 重放，不能以 SSE 丢失推断建议失败。

## 7. `llm_call_logs` 字段映射

`llm_call_logs` 是调用记录唯一事实源。LiteLLM 的 `success_callback` / `failure_callback` 只负责把外部调用终态归一化后写这里，不写新表、不写新的活动类型。

| OTel / 回调来源 | 列 | 规则 |
| --- | --- | --- |
| `gen_ai.system`（兼容 `gen_ai.provider.name`） | `provider` | 例如 `deepseek` |
| `gen_ai.request.model` | `model_name` 的请求值 | 只能记录实际请求模型 |
| `gen_ai.response.model` | `model_name` | 返回模型存在时以它为准，禁止估造 |
| `gen_ai.response.id` | `request_id` | 没有 provider id 时为 `NULL`，不伪造 |
| `gen_ai.usage.input_tokens` | `prompt_tokens` | provider 明确返回 0 才写 0；缺失由下行显式标记 |
| `gen_ai.usage.output_tokens` | `completion_tokens` | provider 明确返回 0 才写 0；缺失由下行显式标记 |
| 两个 usage 字段之和；有 provider total 时优先使用 | `total_tokens` | 只记录 provider 给出的数字 |
| usage 缺失 | `status` + 三个 token 列 | 因现有 NOT NULL 约束 token 写 0，`status=SUCCEEDED_NO_USAGE`，并给当前 agent 加 `AgentDegradation(code="USAGE_NOT_REPORTED")`；卷宗不得把该 0 展示为已测量 token，也不改写 `error_type` |
| callback 的 provider attempt（从 1 开始） | `attempt_count` | 业务 attempt 仍保留在建议 key 中 |
| callback 的 start/end | `latency_seconds` | 毫秒转换为秒 |
| `traceparent` 的 trace-id | `trace_id` | 新 Agent 链使用 W3C 32 位十六进制 trace id |
| baggage `memory_palace.venue_id` | `venue_id` | 租户边界，不接受请求参数覆盖 |
| metadata `memory_palace.agent.id` | `agent_id` | 固定为四个 role 之一 |
| metadata `memory_palace.agent.name` | `agent_name` | skill 的展示名 |
| callback 终态 | `status` | `SUCCEEDED`、`SUCCEEDED_NO_USAGE`、`FAILED` 或 `MOCKED` |
| 异常类型 / sanitized 公开错误 | `error_type` / `error_message` | 不写 secret、prompt、完整堆栈 |
| callback 的 mock 标志 | `is_mock` | 只有未调用真实外部 provider 时为 true |

`id` 由 `(venue_id, incident_id, mode/step, attempt, agent_role, provider_attempt)` 做 UUIDv5；回调重复投递时 `ON CONFLICT(id) DO NOTHING`。`request_id` 只保留 provider 返回值。失败的真实请求仍写 `is_mock=false`；测试/固定假 adapter 写 `is_mock=true` 与 `status=MOCKED`。禁止把 mock 结果伪装成真实 provider 响应。

## 8. Trace 传播

- `IncidentCommand.execute` 继承调用方 W3C context；有父 context 时创建子 span，无父 context 时才创建 root span，并建立 `scenic.incident_command`；每个 agent 使用 `scenic.agent.<role>` 子 span；LiteLLM 调用使用 `gen_ai.chat` 子 span。
- `request.trace_id` 是本次运行的权威 W3C trace id。若存在 active OTel context，其 trace id 必须与它一致；若不存在，实现用该 trace id 建立显式 remote parent/SpanContext 后再创建 root span，禁止另生成一个 trace。当前 span 的 trace id 注入 `llm_call_logs.trace_id` 和 SSE/卷宗关联字段。
- `incident_id`、`event_id`、`venue_id`、`step`、`attempt`、`agent_role` 作为 span attributes；不把 prompt、回答正文、SOP 全文作为 span attributes。
- 出站调用传播 `traceparent`，Jaeger 只作开发期下钻视图；审计与卷宗只依赖 `llm_call_logs`，Jaeger 不可用不阻断业务。
- `IncidentCommandResult.call_refs` 生成后，业务层按 `call_id`/`trace_id` 读取 `llm_call_logs`。不将 token、模型名和耗时复制到建议活动正文作为第二份账。

## 9. 施工与测试顺序

1. 先在各 skill 的 `contracts.py` 建立上述 Pydantic 模型；先写契约测试，覆盖 grounding、无命中、引用来历、高风险管理字段不可被模型放宽。
2. 以 `IncidentCommand` 为唯一外部 seam，fake `IncidentAgentRegistry` 返回固定模型输出；测试只断言 `IncidentCommandRequest -> IncidentCommandResult` 的外部行为。
3. 覆盖顺序与传参、单 agent 开关/超时/失败降级、熔断、配额、租户隔离、`is_mock` 诚实性、调用引用和 trace。
4. 异步部分单独测 `PENDING/RUNNING/READY/FAILED/SUPERSEDED` CAS、重复入队幂等、迟到结果不丢失、SSE 三种事件及重放。
5. 关闭门禁直接复用既有 `event_closure` 测试；不要用一个“建议已存在”的条件替换证据、SOP、任务、审批或告警恢复检查。
6. 真实模型冒烟必须放到独立门禁：无 Key 直接失败，验证真实 200、真实 token/模型名落库、卷宗可见、Jaeger 有对应 span。
## 10. 票 08 真实模型兼容性补记（2026-09-17）

真实原型验证确认 `deepseek-flash` 是 thinking 模型，不能接受 pydantic-ai 默认结构化输出使用的 `tool_choice`，也不能使用原生 JSON Schema `response_format`。因此施工时不得使用会触发这两种请求的实现，否则 API 返回 400。

已验证的替代路径是：

- 使用 `pydantic-ai-slim==2.43.0` 的 `FunctionModel` 作为 pydantic-ai 模型适配器；
- 由该适配器调用 `litellm.acompletion(..., model="openai/deepseek-flash", api_base="https://api.deepseek.com/v1")`；
- 对四个 agent 使用 `PromptedOutput` + Pydantic 模型做 JSON 指令、解析和重试校验，计划书仍要求 `extra="forbid"`；
- 不切换模型、不绕过 PydanticAI 的 agent/retry 机制，也不把 LiteLLM 结果伪装成 provider 原生结构化输出。

依赖上还有一个必须在票 12 锁定的冲突：`pydantic-ai==2.43.0` 的 OpenAIModel 额外依赖 `openai>=3.8`，而 `litellm==1.101.0` 依赖 `openai<3`。原型使用 `pydantic-ai-slim` 避免该额外依赖；正式 requirements 不能直接同时写两个全量包而期望安装成功。

本次真实四 agent 输出、token/latency、`llm_call_logs`、卷宗 `model_calls`、Jaeger span 和 Hatchet durable event wait 均通过；兼容性补记不改变 `IncidentCommand` 的输入输出语义，只约束模型 adapter 的内部实现。
