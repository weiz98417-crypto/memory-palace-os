# ADR-0019: 景区 Agent 运行时的技术栈选型

## 状态

已接受（2026-09-16 选型评审）。补充 ADR-0018（Agent 链作为主干、`IncidentCommand` 为唯一边界）。

## 背景

ADR-0018 定了"Agent 在环 + 人保留门禁 + 调用记录进卷宗"，但没有定实现组件。第一轮选型只看主流 Agent 框架（LangGraph/CrewAI 等），与实际约束（PostgreSQL 是唯一事实源、必须可调试、本地 CPU、商用许可证）不匹配，已被否决。第二轮按约束重选。

## 决策

采用以下五个组件，构成景区 Agent 运行时；不引入其他框架：

| 角色 | 组件 | 版本（2026-09-16 实测） | 许可证 |
| --- | --- | --- | --- |
| 可持久化编排与人工中断 | **Hatchet**（`hatchet-sdk`） | 1.40.1 | MIT |
| Agent 契约与结构化输出 | **pydantic-ai** | 2.43.0 | MIT |
| 模型调用网关（重试/超时/成本） | **LiteLLM**（以库方式进程内使用） | 1.101.0 | MIT |
| 调用记录语义 | **OpenTelemetry GenAI 语义约定**（`gen_ai.*`）；本地用 **Arize Phoenix** 查看 | — | 规范 / NOASSERTION⚠️ |
| 检索重排 | **FlashRank** | 0.2.10 | Apache-2.0 |
| 评测门禁 | **DeepEval** | 4.2.3 | Apache-2.0 |

## 与缺口的对应

| 缺口 | 由谁承担 |
| --- | --- |
| G1 Agent 链成为主干 | Hatchet 编排 `context_trigger → router → memory_ops → commander`，pydantic-ai 定义每个 agent 的输出契约 |
| G2 调用记录进卷宗 | LiteLLM 产出 token/成本；用 OTel `gen_ai.*` 字段写入 `AGENT_INVOCATION`，Phoenix 本地查看 |
| G3 可调试与降级 | Hatchet 的重试/超时/运行视图 + 每 agent 独立开关；失败降级策略按 ADR-0018 第 6 条 |
| G4 人在环门禁 | Hatchet 的人工中断（等待外部事件）表达审批与关闭门禁 |
| G5 态势判定 | 仍由我们的 `SituationEngine` 承担（本轮不引入工作流引擎做规则） |
| G6 检索质量 | pgvector 保持 + FlashRank 重排 |
| G7 本地模型与向量后端 | 不变（PostgreSQL pgvector + 本地 bge-m3）；LiteLLM 只负责生成式调用 |
| G8 评测回归 | DeepEval（pytest 门禁），真实模型冒烟按 ADR-0018 第 10 条必须有可用 Key |

## 被否决的方案与原因

- **LangGraph / CrewAI / AutoGen**：偏研究型多智能体协作，非确定性高、审计与门禁难保证。
- **Temporal / Restate**：能力更强但需独立服务/集群，本地单机演示过重；DBOS 同样被否，因为 Hatchet 额外提供运行视图，正好补"没有调试"这一条。
- **openai-agents-python**：可用（MIT），但其 tracing 默认上报 OpenAI 云端，且模型中立性与结构化输出严格度不如 pydantic-ai；团队若偏好，可替换并改用本地 trace processor。
- **Langfuse**：功能全但自托管需额外 Postgres/ClickHouse/Redis，成本高于 Phoenix。
- **ParadeDB（AGPL-3.0）/ SpiffWorkflow（LGPL-3.0）/ Windmill（AGPL 核心）/ Dify（多租户与品牌限制）**：许可证不适合商用交付。
- **TruLens**：RAG 诊断更强，但 DeepEval 的 pytest 门禁更贴合现有测试体系；需要看板时再加。

## 影响与部署代价（必须正视）

- Hatchet 需要自己的 PostgreSQL 库与常驻 worker；Phoenix 需要一个容器。当前 WSL 内存上限 4GB，全量常驻会挤爆。因此：**编排与可观测服务通过 compose profile 提供**（演示默认开启 App 栈，Hatchet/Phoenix 按需开启），或在演示机把 WSL 内存上限调高后再常驻。
- LiteLLM 以**库**方式在应用进程内使用，不新增端口与服务。
- FlashRank 首次运行会下载小模型（CPU 可跑），需要纳入离线准备清单。
- DeepEval 需要判官模型：复用同一个可用 API Key（ADR-0018 第 10 条要求必须有 Key）。

## 验证方式

1. Hatchet 运行视图能看到一次事件处置的完整运行与人工中断点。
2. Phoenix 能看到每次模型调用的 span（模型名、token、耗时），字段名与 `AGENT_INVOCATION` 一致。
3. DeepEval 门禁断言"建议必须被命中的 SOP 支撑；无命中必须明确拒答"。
4. 真实模型冒烟：无 Key 视为失败（不跳过），按 ADR-0018 第 10 条执行。

## 决议与修订（2026-09-16 第二轮，已拍板）

1. **模型统一**：四个 agent 使用同一个模型（配置中的 `LLM_DEFAULT_MODEL`），不做 per-agent 模型分工；温度与 max_tokens 由统一配置给出，模型名如实写入 `llm_call_logs`。
2. **建议生成异步化**：队列 + 状态机，不在请求内阻塞。状态 `PENDING → RUNNING → READY / FAILED / SUPERSEDED`；经 SSE 推送 `ADVICE_PENDING / ADVICE_READY / ADVICE_FAILED`；队列复用 Redis Streams；幂等键 `(incident_id, step, attempt)`。
3. **弃用 FlashRank**（onnxruntime 与 torch 同进程冲突，本机已实测同类崩溃）。改为两级重排：默认 Postgres 词法重排（`ts_rank` + `pg_trgm`，零新依赖）；可选 bge-reranker-base（torch 系 cross-encoder），独立进程 + 惰性加载，profile 开关不常驻。进程内只保留 torch 一个原生运行时。
4. **弃用 Phoenix**（Elastic License 2.0，不得随产品分发）。默认不引入追踪 UI：OTel GenAI 语义 + 自写 exporter 直接写 `llm_call_logs`，卷宗与诊断页即查看器；需要深挖调用链时以 profile 启用 Jaeger（Apache-2.0，原生 OTLP）。
5. **内存重新评判**：应用 + bge-m3 峰值 ≈ 2.5–3.2GB，叠加 Hatchet engine/worker ≈ 0.4–0.6GB、可选 Jaeger ≈ 0.2GB，4GB WSL 上限不足 → Hatchet/Jaeger 走 compose profile 默认关闭；需要常驻则把 WSL 上限提到 6GB。

## v3 修订（2026-09-16 第三轮，仍遵循"能选开源就选开源"）

1. **重排采用开源模型服务，不再退回词法重排**：
   - 服务：**Hugging Face TEI**（`ghcr.io/huggingface/text-embeddings-inference`，Apache-2.0），CPU 变体，独立容器，其内部运行时与我们的应用进程隔离（因此不再有 onnxruntime/torch 同进程冲突）。
   - 模型：默认 **BAAI/bge-reranker-base**（278M，约 1.1GB 权重）；若内存宽裕可换 **bge-reranker-v2-m3**（568M，约 2.3GB，多语言更强）。
   - 位置：pgvector 召回 → TEI `/rerank` → 最终排序；重排分数写入检索证据，供"引用来源"展示。
2. **嵌入也移到 TEI**：同一服务同时提供 `BAAI/bge-m3`（1024 维）与重排。应用进程**不再内嵌 torch/sentence-transformers**：
   - `LocalEmbeddingBackend` 保持原接口不变（seam 不破），实现改为 HTTP adapter；
   - 应用镜像从约 10GB 降到约 1GB，启动不再加载本地模型；
   - 本机已验证的"torch 满线程原生崩溃"这类问题从根上消失（模型运行时只在 TEI 内）。
3. **WSL 内存上限 4GB → 6GB**（已改，原配置已备份）。预算：TEI ≈ 3.4GB（bge-m3 2.3 + reranker-base 1.1）、应用 ≈ 0.3GB、PostgreSQL ≈ 0.1GB、Redis/Nginx 忽略不计，合计 ≈ 3.9GB；叠加 Hatchet ≈ 0.5GB 后仍有余量。
4. 若使用 bge-reranker-v2-m3（+1.2GB）或让 Hatchet/Jaeger 常驻，需要把上限再提到 8GB。
5. 实现时必须先锁定 TEI 镜像的具体 CPU 标签（用 `docker manifest inspect` 校验），不写 `latest`。

## v4 修订（2026-09-16 第四轮）：追踪改为"默认开 + 全 OSS"，取消自写 exporter

**原则明确**：凡是开源已有的组件一律直接用开源，不自研。我们只自研业务语义（门禁规则、卷宗结构、多租户），因为那是产品差异，开源里没有对应物。

1. **追踪默认启用 Jaeger（Apache-2.0）**：`opentelemetry-sdk` + `opentelemetry-exporter-otlp`（1.44.x）发送 span，`jaegertracing/all-in-one` 作为查看器；WSL 提到 6GB 后其约 0.2GB 开销可以常驻，不再降级为可选。镜像标签与 Jaeger 版本在实现时用 `docker manifest inspect` 锁定。
2. **取消"自写 exporter"的说法**：业务侧不写任何导出管线。调用记录由 **LiteLLM 官方 callback 扩展点**（`success_callback` / `failure_callback`）落库到既有 `llm_call_logs`；我们只定义该表的行结构（它本来就已存在）。
3. **两条记录的关系**：Jaeger 是**开发期追踪视图**（可随时重装/丢弃）；`llm_call_logs` 是**业务事实**（卷宗、审计、关闭门禁只读它）。二者都必需，互不替代：不能让审计依赖追踪后端，也不该为了审计自研追踪。
4. 内存重算：TEI ≈3.4GB + 应用 ≈0.3GB + PostgreSQL ≈0.1GB + Jaeger ≈0.2GB + Hatchet ≈0.5GB ≈ **4.5GB**，在 6GB 上限内。

### 现在的"OSS 覆盖表"（自研仅剩业务语义）

| 能力 | 采用的开源组件 |
| --- | --- |
| 编排与人工中断 | Hatchet (MIT) |
| Agent 契约 | pydantic-ai (MIT) |
| 模型网关与回调 | LiteLLM (MIT) |
| 嵌入与重排服务 | TEI (Apache-2.0) + bge-m3 / bge-reranker-base |
| 追踪 | OpenTelemetry SDK/OTLP + Jaeger (Apache-2.0) |
| 向量后端 | PostgreSQL pgvector |
| 队列 | Redis Streams |
| 评测门禁 | DeepEval (Apache-2.0) |
| **自研（无开源对应）** | 景区门禁规则、事件卷宗、多租户隔离、处置建议采纳语义 |
