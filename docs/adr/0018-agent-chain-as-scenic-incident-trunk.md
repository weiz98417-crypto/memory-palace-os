# ADR-0018: Agent 链是景区事件处置的主干，IncidentCommand 是唯一边界

## 状态

已接受（2026-09-16 评审）

## 背景

景区垂直切片最初在 `src/memory_palace/scenic/operations.py`（1581 行）内自行实现了信号判定、事件受理、SOP 建议、派单、审批、关闭与通知，`context_trigger / router / memory_ops / commander` 这条 Agent 链没有任何调用方。结果是：AI native 的核心能力被做成了旁支，模型调用既不在业务链路上，也不在卷宗里，无法证明系统"由模型在调度和回答"。

## 决策

1. 景区事件的受理、研判、建议、派单草案与关闭摘要**必须经由 Agent 链**：`context_trigger`（上下文装配）→ `router`（意图与风险分级）→ `memory_ops`（基于 pgvector 命中的 SOP 出建议，必须引用来源）→ `commander`（任务与决定草案）。
2. 新增深模块 `IncidentCommand` 作为唯一边界：接口只暴露"给事件 + 证据 + 知识命中，返回建议 / 派单草案 / 关闭摘要 + 模型调用记录"。Agent 链、提示词装配、调用记录与失败降级都藏在它后面，由 DI 容器注入；`scenic/operations.py` 只保留状态机与持久化。
3. **人保留高风险决定与关闭门禁**：继续停运/启用备用车、解除风险、关闭事件仍由有权限的人审批执行；关闭门禁（现场证据 + SOP 命中 + 任务完成 + 审批结果 + 告警恢复）不变。
4. **模型不可用时不阻塞业务、也不伪造**：链路照常推进，但界面与卷宗必须明确标注"未获得模型建议"。
5. **调用记录复用既有 `llm_call_logs`（2026-09-16 遗漏检查修正）**：该表已存在且字段齐备（`agent_id / agent_name / provider / model_name / status / attempt_count / latency_seconds / prompt_tokens / completion_tokens / total_tokens / request_id / error_type / is_mock / created_at`，并按 `venue_id+created_at`、`trace_id` 建索引），因此不再新建 `AGENT_INVOCATION` 活动类型。唯一事实源是 `llm_call_logs`，`event_dossier` 按 trace/事件关联读取并渲染"模型调用证据"小节（含引用来源）；只记录元数据与引用，不落 prompt 与回答全文，回答正文作为事件活动正文留存。`is_mock` 必须诚实，禁止把模拟调用标成真实调用。
6. **失败降级策略**：单次调用超时 20 秒、失败重试 1 次；仍失败则记录 `outcome=FAILED` 与错误类型，业务继续推进并在界面与卷宗标注"未获得模型建议"；同一场地连续 3 次失败进入 60 秒熔断。
7. **提示词与输出契约留在各自 skill 目录**：`IncidentCommand` 只负责按顺序装配上下文（事件 + 现场证据 + pgvector 命中 + 历史 CASE）、调用技能、收集调用记录与引用，不复制提示词。职责边界：`context_trigger` 装配与去重上下文；`router` 定意图与风险级别；`memory_ops` 只基于命中来源出建议（无命中必须明确说没有依据）；`commander` 产出任务与决定草案。
8. **一次性接入四个 agent**（`context_trigger → router → memory_ops → commander`），同时删除 `operations.py` 中对应的旧建议与草案逻辑，避免两套实现并存。为保持可调试性，每个 agent 具备独立开关（`SCENIC_AGENT_<ROLE>_ENABLED`）、独立超时与独立失败记录；任一环节失败仅降级该环节，其余环节照常运行，卷宗按 agent 分节显示调用记录，便于逐段定位。
9. **引导流程由后端产出**：态势快照直接返回 `next_actions`（动作码 + 文案 + 前置条件）与 `advice`（建议正文 + SOP 引用 + 调用记录摘要），前端只渲染不再推导。引导流程在"SOP 检索"之后插入「查看处置建议」，人必须**采纳**或**忽略并填写理由**，两种选择都写入活动与卷宗，之后才进入派单草案。
10. **测试面**：契约测试（假 skill registry）覆盖建议必须带 SOP 引用、无命中必须说"没有依据"、调用记录字段齐全、单环节失败只降级不阻塞、关闭门禁不被绕过；真实模型冒烟覆盖真调用 200、模型名与 token 落库、卷宗"模型调用证据"可见。**真实冒烟必须有可用 API Key，无 Key 视为失败而非跳过**：容器栈使用密钥卷 `memory-palace-secrets/deepseek_api_key`（已验证可用，`deepseek-flash` 返回 200），本机原生栈必须配置同一环境的 `DEEPSEEK_API_KEY`（当前为占位值，实施时替换）。

## 原因

Agent 链是产品的 AI native 能力所在；把它排除在业务链之外，等于把"智能"降级为规则引擎。同时，审计要求决定权必须可追溯到人，因此选择"Agent 在环、人做决定"，而不是让 Agent 全权处置。

## 影响

- 每次 Agent 调用都要留下可核对的调用记录（模型名、token、耗时、trace），并进入事件活动与审计卷宗。
- `IncidentCommand` 的接口是测试面：用假 adapter 即可覆盖建议、引用与记录三件套，不必依赖真实模型。
- 既有的规则判定逻辑需要逐步从 `operations.py` 迁出（见后续态势引擎决策），迁移期间不得出现两套建议实现并存。
