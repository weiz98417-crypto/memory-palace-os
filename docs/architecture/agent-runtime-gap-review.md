# Agent 运行时选型的遗漏检查（2026-09-16）

针对 ADR-0018 / ADR-0019 的栈（Hatchet + pydantic-ai + LiteLLM + OTel GenAI + FlashRank + DeepEval）做的一次对口检查。结论：方案可行，但有 3 项必须先解决、若干项需补文档。

## A. 与既有实现重复（已修正 ADR-0018）

- **`llm_call_logs` 表已存在**且字段齐备：`agent_id / agent_name / provider / model_name / status / attempt_count / latency_seconds / prompt_tokens / completion_tokens / total_tokens / request_id / error_type / is_mock / created_at`，并按 `venue_id+created_at`、`trace_id` 建索引。原计划新建 `AGENT_INVOCATION` 属于重复记账，已改为：**`llm_call_logs` 是唯一调用记录源**，卷宗按 trace 关联读取渲染。
- 诊断接口已有 `components["llm"]` 与模型健康判定（含 `is_mock`），agent/模型状态并入现有诊断，不另造面板。

## B. 必须解决的 3 项（阻塞实现）

1. ~~**FlashRank 与 torch 同进程有崩溃风险**~~ **已解决（v3）**：改用 **TEI（Apache-2.0）独立服务**承载重排（默认 bge-reranker-base），并把嵌入（bge-m3）也一并移入 TEI。应用进程不再内嵌 torch，冲突根源消除；重排能力保留且更强。
2. **Phoenix 是 Elastic License 2.0（ELv2）**：仅可作本地开发观测，不得随产品分发或对外提供服务。
3. **4GB WSL 内存不足**：Hatchet engine（含独立库）+ Phoenix 常驻会挤爆；两者以 compose profile 提供，演示默认只跑业务栈。

## C. 产品与合规

- 生成式调用仍依赖云端 DeepSeek，与"本机可运行"表述冲突：需明确"除生成式调用外全部本地"，并提供本地模型（Ollama/vLLM）备选或标注需外网。
- Prompt 治理：进入 prompt 的现场证据、SOP 正文、历史案例可能含个人信息 → 脱敏策略、**严格租户隔离（绝不跨场地拼 prompt）**、不落 prompt 全文。
- 历史事件无建议记录 → 不回填，UI 标注"该事件早于 Agent 在环"。

## D. 行为遗漏（演示会暴露）

- **幂等**：以 `(incident, step, attempt)` 去重，重试不得产生重复建议或重复调用记录。
- **建议过期**：人类先操作时，后到的建议标记 `SUPERSEDED`，不得静默丢弃。
- **延迟体验**：等待期间界面必须显示"分析中"，并经 SSE 推送 `ADVICE_PENDING / ADVICE_READY`，否则演示像卡死。
- **成本配额**：按场地设日 token 上限，触顶降级为"未获得模型建议"，状态在诊断可见。
- **两套历史**：Hatchet 运行历史仅作运行视图，**业务表是唯一事实源**，不得出现两份真相。

## E. 验收基线缺口

- `openspec/changes/scenic-area-simulation/specs/` 只规定了向量后端，**没有生成式处置建议的验收条款** → 需补 spec delta。
- DeepEval 需要黄金样本（场景夹具 + 期望引用），目前没有 → 先建 fixtures。
- CI 非确定性：判官模型会抖动 → 契约测试用固定夹具，真实模型冒烟单独跑，且无 Key 视为失败（ADR-0018 第 10 条）。

## F. 运维

- 离线准备清单补：FlashRank 模型、Hatchet 库迁移、Phoenix 镜像。
- 健康检查覆盖：Hatchet engine 可达、重排组件就绪、模型可用（已有）、Phoenix 可选。
- 文档同步：README 架构图、产品页"技术架构"、CONTEXT.md 术语（处置建议、人工采纳、调用证据）。

## G. 待你决策

（已于 2026-09-16 拍板，结论见 ADR-0019「决议与修订」小节）

1. 模型：四个 agent **统一同一个模型**。
2. 建议生成：**异步入队 + 队列状态机**，SSE 推送 `ADVICE_PENDING/READY/FAILED`。
3. 重排：**弃用 FlashRank**，默认 Postgres 词法重排；可选 bge-reranker（torch 系）走 profile。
4. 追踪：**弃用 Phoenix**（ELv2），默认自写 exporter 落 `llm_call_logs`；可选 Jaeger（Apache-2.0）。
5. 内存：4GB 上限不足，Hatchet/Jaeger 默认关闭；常驻需把 WSL 提到 6GB。
