# 开源选型评估（针对景区应急链路重构）

> **结论已定**：最终选型与理由见 [ADR-0019](../adr/0019-agent-runtime-stack-selection.md)。
> 采用栈：Hatchet（编排）+ pydantic-ai（Agent 契约）+ LiteLLM（模型网关）+ OTel GenAI 约定（记录，本地 Phoenix 查看）+ FlashRank（重排）+ DeepEval（评测门禁）。

> 评估日期：2026-09-16。目的：在动手改 `IncidentCommand` 之前，先看有没有可以直接拿来用的开源实现，避免自造。
> 数据说明：标 ✅ 的 star/license 为本轮实测（GitHub API）；标 ⚠️ 的未实测，需补核（当日未认证配额耗尽，且 AnySearch 匿名配额用尽）。

## 我们要补的缺口（来自 ADR-0018）

| 缺口 | 内容 |
| --- | --- |
| G1 | Agent 链成为主干：`context_trigger → router → memory_ops → commander` 由 `IncidentCommand` 编排 |
| G2 | 模型调用记录进卷宗（model/tokens/latency/trace/citations），只记元数据 |
| G3 | 可调试：每 agent 独立开关/超时/失败记录、重试与熔断 |
| G4 | 人在环：高风险决定与关闭门禁、引导流程 `next_actions` |
| G5 | 态势判定（信号→告警→triage）与持久化分离 |
| G6 | 知识检索质量：来源过滤、必须引用、无命中明确拒答、可选重排 |
| G7 | 本地模型服务（bge-m3 CPU）与向量后端（pgvector） |
| G8 | 评估与回归：引用忠实度、真实模型冒烟 |

## 候选与结论

### 1. Agent 编排与结构化输出

| 项目 | 实测 | 映射 | 建议 |
| --- | --- | --- | --- |
| **pydantic-ai** ✅ 19,980★ MIT | G1/G2/G8 | **直接采用候选**。我们已用 Pydantic，四个 agent 的输出契约可用它做结构化输出；`result.usage()` 直接给 token 数，省掉自算；官方 evals 包可做引用忠实度回归 |
| **openai-agents-python** ✅ 29,489★ MIT | G1/G2/G3 | **直接采用候选**。内建 tracing（span 含 token）、handoff、guardrail；可用 OpenAI 兼容端点接 DeepSeek；代价是 tracing 默认上报 OpenAI，需自建 OTel 导出 |
| **langgraph** ✅ 41,760★ MIT | G1/G4 | **借鉴/可选**。状态图 + checkpoint + `interrupt` 天然表达"人审批后继续"；如果我们想要可恢复的审批中断，它比自己写状态机更稳 |
| crewai ✅ 58,651★ MIT / autogen ✅ 61,004★ CC-BY-4.0 | G1 | **不建议做主干**。面向角色扮演协作，非确定性高、审计难，与"关闭门禁不可绕过"冲突 |

### 2. 可持久化执行 / 人审批中断

| 项目 | 实测 | 映射 | 建议 |
| --- | --- | --- | --- |
| **temporal** ✅ 23,089★ MIT | G1/G3/G4 | **生产可选**。重试、超时、signal 式人工审批是最成熟的；代价是要新增 server+worker（本地演示偏重） |
| **restate** ✅ 4,424★ NOASSERTION⚠️ | G1/G3/G4 | **轻量可选**。Python SDK、promise 表达人工审批，运维成本低于 Temporal |
| spiffworkflow ⚠️ | G4/G5 | **借鉴**。Python 的 BPMN 引擎，可用 BPMN 显式表达"人任务+门禁"；适合把审批流从代码里拿出来 |

### 3. 模型调用可观测（对应 AGENT_INVOCATION）

| 项目 | 实测 | 映射 | 建议 |
| --- | --- | --- | --- |
| **OpenTelemetry GenAI 语义约定** | 标准 | G2 | **直接采用**。用官方属性名（`gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.input_tokens/output_tokens`）定义我们的调用记录，避免自造字段，天然可对接下游 |
| arize-phoenix ✅ 11,487★ NOASSERTION⚠️ | G2/G8 | **本地演示首选**。单容器 OTLP 收集 + UI，能直接看到每次调用与评估结果 |
| langfuse ✅ 34,685★ NOASSERTION⚠️（核心开源） | G2/G8 | **功能更全但更重**（需额外 Postgres/ClickHouse/Redis）；自托管成本高，SaaS 不符合本地要求 |
| openinference ✅ 1,221★ Apache-2.0 / openllmetry ⚠️ | G2 | **直接采用**。给 LangChain/OpenAI 等自动埋点，产出符合上表的 span |
| litellm ✅ 58,877★ NOASSERTION⚠️ | G2/G3 | **建议采用**。统一 DeepSeek/OpenAI 调用，自带 token 与成本统计、重试与 fallback，正好实现我们的降级与配额 |

### 4. 评估与回归（G8）

| 项目 | 实测 | 建议 |
| --- | --- | --- |
| deepeval ✅ 18,292★ Apache-2.0 | **建议采用**：`Faithfulness`/`AnswerRelevancy` 直接对应"建议必须能被命中的 SOP 支撑" |
| ragas ✅ 15,752★ Apache-2.0 | **可选**：RAG 指标齐全，适合批量回归 |
| promptfoo ⚠️ | **可选**：YAML 断言式回归，接 CI 便宜 |

### 5. 检索与本地模型服务（G6/G7）

| 项目 | 建议 |
| --- | --- |
| **text-embeddings-inference (TEI)** ⚠️ | **建议评估**：把 bge-m3 从应用进程拆成独立服务（CPU 支持、容器瘦身）。直接消除我们踩过的 torch 线程崩溃与启动慢 |
| infinity ⚠️ | 同上，部署更简单 |
| paradedb / pg_search ⚠️ | **可选**：Postgres 内 BM25+向量混合检索；我们目前是纯向量，加关键词通道能提升编号类查询（如"12 号车"） |
| pgai / pgvectorscale ⚠️ | **可选**：库内嵌入/重排与更高性能索引；演示规模非必需 |

### 6. 运维自动化 / 告警聚合（G5）

| 项目 | 建议 |
| --- | --- |
| keep (keephq) ⚠️ | **借鉴**：告警聚合与工作流触发模型，可用于"多信号→单事件"的归并策略 |
| stackstorm / rundeck ⚠️ | **不建议**：面向传统运维 runbook，体量大，与现有状态机职责重叠 |

### 7. 已采用 / 无需更换

- **PostgreSQL + pgvector** ✅（已在用，满足 G7 向量后端）。
- **Redis Streams**（在用，队列与实时传输）。

## 对原计划的改进建议（结论）

1. `AGENT_INVOCATION` 字段**改用 OpenTelemetry GenAI 语义约定命名**，而不是自造（G2）。
2. 四个 agent 的**输出契约用 pydantic-ai 实现**，token 统计由框架给出，替换手写 `parse_json`（G1/G2）。
3. **LLM 调用统一走 LiteLLM**，重试/超时/成本统计交给它，我们只记录结果（G3）。
4. **本地可观测用 Phoenix 单容器**（OTLP），演示时能当场看到每次调用（G2/G8）。
5. 把 **bge-m3 拆成 TEI 服务**列入后续优化（G7），可同时解决启动慢与线程崩溃类问题。
6. 回归测试引入 **DeepEval 的忠实度断言**，与 ADR-0018 第 10 条（必须有 Key、必须引用 SOP）配套（G8）。

## 待用 AnySearch 深挖的清单（需要 API Key）

- 上述 ⚠️ 项目的 star/license/最近活跃度实测。
- 中文场景的"应急指挥/景区事件处置"开源实现（是否有可借鉴的状态机与门禁建模）。
- 各候选在 CPU-only、单机 Docker 下的真实部署成本对比。

---

## 第二轮：更贴近我们实现的两类项目（2026-09-16 补）

第一轮只覆盖了"人人都知道"的 Agent 框架，等于没找到。真正贴着我们痛点（**Postgres 是唯一事实源 + 人在环审批 + 要能调试**）的是下面两类。

### A. 以 Postgres 为事实源的可持久化工作流（直接对标 G1/G3/G4）

| 项目 | 实测 | 为什么贴我们的实现 |
| --- | --- | --- |
| **dbos-inc/dbos-transact-py** | ✅ 1,577★ MIT，当日活跃 | 工作流状态直接存在**我们已有的 PostgreSQL**里，不新增中间件；`send/recv` 正好表达"事件推进 + 等人工审批"，进程重启后从数据库恢复。相当于把 `operations.py` 里手写的状态机 + 重试 + 恢复换成框架保证 |
| **hatchet-dev/hatchet** | ✅ 7,952★ MIT，当日活跃 | 同样是 Postgres 后端，带任务依赖图、重试、超时和**带 UI 的运行视图**——正是你说的"连调试都没有"要补的东西；适合把四 agent 编排成可观测的 durable task graph |
| kestra-io/kestra | ✅ 28,138★ Apache-2.0，当日活跃 | YAML 流程 + 人工校验节点；JVM 栈，接我们的 Python 需要额外一跳，适合做"运维 runbook"而非应用内主干 |
| Netflix/conductor | ✅ 12,752★ Apache-2.0，**2023 年后停更** | 不考虑 |

**结论**：编排层建议二选一——**DBOS**（最贴 Postgres 事实源，改动最小）或 **Hatchet**（自带运行视图，调试最省事）。两者都是 MIT。

### B. 直接可用的能力件

| 项目 | 实测 | 用途 |
| --- | --- | --- |
| **infiniflow/ragflow** | ✅ 90,810★ Apache-2.0，当日活跃 | 成熟 RAG 引擎，**答案强制带引用**。可借鉴其"引用即证据"的实现，或作为知识层备选（我们已有 pgvector + bge-m3，替换成本需评估） |
| **PrithivirajDamodaran/FlashRank** | ✅ 1,006★ Apache-2.0 | 极轻量 CPU 交叉编码重排，正好补"12 号车"这类精确召回，无需 GPU |
| truera/trulens | ✅ 3,561★ MIT，活跃 | 评测框架，可与 DeepEval 二选一 |
| langgenius/dify | ✅ 155,939★ NOASSERTION⚠️ | 工作流含人工输入节点；**许可证对多租户 SaaS 与品牌有额外限制**，商用前必须法务确认 |
| windmill-labs/windmill | ✅ 17,949★ NOASSERTION⚠️ | 含审批/挂起；开源核心为 AGPL（另有 EE 部分），**商用需评估** |
| argoproj/argo-workflows | ✅ 16,979★ Apache-2.0 | `suspend` + `approve` 门禁模式值得借鉴；但需 K8s，不符合本机 Docker 演示 |
| flowable/flowable-engine · camunda/camunda | ✅ 9,539★ / 4,279★ Apache-2.0 类 | BPMN 人工任务建模参考；Java 栈，不建议引入 |

### C. 许可证风险清单（商用交付必须确认）

- **AGPL-3.0**：paradedb（污染风险最高）
- **LGPL-3.0**：SpiffWorkflow
- **NOASSERTION / 双许可（需逐个确认）**：langfuse、phoenix、litellm、restate、keep、windmill、dify、camunda
- **安全（MIT/Apache-2.0）**：pydantic-ai、openai-agents-python、langgraph、temporal、deepval/ragas、TEI、FlashRank、dbos、hatchet、kestra、airflow

### D. 修正后的建议（不改原计划结论，只换更贴的实现）

1. 编排：**DBOS 或 Hatchet** 承载 `IncidentCommand` 的持久化与人工中断；Agent 四步仍是 pydantic-ai / openai-agents。
2. 调用记录：**OpenTelemetry GenAI 语义约定** + Phoenix 本地查看。
3. 模型网关：**LiteLLM**（重试/超时/成本）。
4. 检索：pgvector 保持，补 **FlashRank** 重排。
5. 评测：**DeepEval 或 TruLens** 做"必须引用 SOP"的忠实度回归。
6. 没有找到可直接整套复用的"景区应急指挥"开源产品；领域门禁、卷宗与多租户仍由我们实现（这部分是产品差异，不是重复造轮子）。

### E. 本轮未完成的调研（诚实标注）

- **中文生态（Gitee）未查成**：Gitee 搜索 API 需要访问令牌，AnySearch 的 Key 速率极低（连续 2 次查询即被限流），"开源应急指挥/智慧景区"这一轮没有结论。
- 上述 NOASSERTION 项目的许可证原文需逐个核对（本次仅取 GitHub 元数据）。
