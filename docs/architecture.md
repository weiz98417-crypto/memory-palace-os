# 🏗️ Memory Palace OS 系统架构与流转设计白皮书 (V1.3.0)

本文件详述 **Memory Palace OS** 的核心架构设计。景区场景的正式主干是 **Agent 主干化**：一条由
`IncidentCommand` 作为唯一深 seam 的 Agent 链，承载事件从接报到建议、采纳、派单、闭环的完整
处置路径。系统的严肃性来自可审计的事实源与门禁，而不是来自某个 Agent 的自主权。

---

## 0. 企业演示版运行分支

企业演示版在现有应用上增加独立的 `ScenarioController` 边界。浏览器只调用 `/demo` 和 `/demo/*`
路由，场景定义来自 `scripts/seed_data/demo/*.yaml`，默认工具行为由 Demo Adapter 记录，不触发真实
LLM、企微、短信或语音外呼。`/demo/` 只是兼容入口，不是新的业务状态源。

```text
/demo UI
   -> FastAPI demo router
   -> ScenarioController
      -> ScenarioCatalog (versioned YAML)
      -> deterministic Demo Adapter
      -> run snapshot / step evidence / report
```

Controller 使用单 run 锁、`expected_version` 和明确状态机保护 Play/Pause/Step/Stop/Reset。模拟控制
（播放 / 暂停 / 倍速 / 单步）只允许出现在受保护的 `/operations/scenic/` 入口，业务界面不出现任何
模拟控制。运行中边界动作优先级为 `reset > stop > pause`。

默认 Demo Compose 固定单 worker、非 root 用户、SQLite 和进程内队列，并只把端口绑定到
`127.0.0.1`。完整信任边界见 [企业演示版架构](enterprise-demo/architecture.md)。

---

## 1. Agent 主干 (Agent Trunk)

系统由一条主干链路和两侧平面组成。主干对上层暴露唯一的深 seam `IncidentCommand`；上层只描述
"要什么"，主干内部才决定"怎么编排"。

```text
正式客户端 / 现场端 / 受保护的景区运行入口
                  ↓  HTTPS + JWT + venue_id
                Nginx
                  ↓
        FastAPI（Auth / Canonical Ingress / API v1）
                  ↓  先写 PostgreSQL，再入队
     Redis Streams（队列、重试与死信）
                  ↓
         消息 Worker 与 Hatchet 工作流
                  ↓
        ┌─────────────────────────────┐
        │  IncidentCommand（唯一深 seam）│
        │  编排、门禁、超时、失败降级     │
        └─────────────────────────────┘
             ↓      ↓      ↓      ↓
        ContextTrigger  Router  MemoryOps  Commander
        （情境触发）    （分诊） （依据检索）（处置建议）
                  ↓
        LiteLLM（进程内模型网关）
                  ↓
        DeepSeek · deepseek-flash

数据与基础设施平面
  PostgreSQL（唯一业务事实源：事件、卷宗、任务、审批、经验、审计、llm_call_logs）
  PostgreSQL pgvector（1024 维向量索引，由 TEI 承载 bge-m3 嵌入与 bge-reranker-base 重排）
  Redis Streams（消息与建议运行队列）
  external secret volume（DeepSeek Key）

可观测与质量平面
  OpenTelemetry SDK / OTLP → Jaeger（链路下钻，可选，不影响业务）
  DeepEval 4.2.x（评测门禁）
```

### 1.1 四个 agent 契约

景区主干的四个 agent 使用**同一个模型**（`deepseek-flash`），提示词与输出契约留在各自的 skill
目录（`src/memory_palace/skills/*/`）。四者都以 Pydantic 契约输出，主干只接受通过契约校验的结构：

| Agent | 职责 | 契约要点 |
|-------|------|----------|
| `ContextTrigger` | 情境触发与优先级判断 | 是否升级为事件、优先级、触发依据 |
| `Router` | 意图分诊 | 意图分类、严重等级、目标处置模式 |
| `MemoryOps` | 依据检索 | 命中清单与来源，无命中必须显式声明"没有依据" |
| `Commander` | 处置建议 | 受依据约束的建议步骤、风险与待人工确认项 |

`Persona`、`PersonaExtract`、`TodoWrite`、`Watcher` 仍是产品能力，但不属于 `IncidentCommand` 的景区
处置主干；它们各自通过既有 seam 与领域服务交互。

### 1.2 IncidentCommand 边界

`IncidentCommand` 是事件处置的最高 seam，也是唯一允许编排四个 agent 的地方。它：

- 只读取 `IncidentCommand` 输入契约，返回建议、派单草案与 `llm_call_logs` 引用；
- 不替人做业务决定，不自动采纳建议，不跳过流程推进门禁与关闭门禁；
- 让上游可以用一个接口替换整条链路的实现，而不必知道内部编排细节。

### 1.3 状态机与建议运行

建议生成是异步的，由 Redis Streams 承载，幂等键为 `(incident_id, step, attempt)`：

```text
PENDING ──▶ RUNNING ──▶ READY
                  └───▶ FAILED
                  └───▶ SUPERSEDED（人已推进，迟到的建议只读留存）
```

SSE 向客户端推送 `ADVICE_PENDING / ADVICE_READY / ADVICE_FAILED`。迟到建议保留为只读证据，
不参与后续派单、任务或关闭。

### 1.4 两道门禁（不可混淆）

- **流程推进门禁**：进入派单草案前，人必须采纳或忽略建议并填写理由；显式选择"不等建议"会
  把在途建议置为 `SUPERSEDED`。
- **关闭门禁**：证据 + SOP + 任务 + 审批 + 告警恢复齐备，且高风险决定（继续停运 / 启用备用车）
  必须有人审批。`IncidentCommand` 无权代替人接受关闭门禁。

### 1.5 调用记录

生成式调用的唯一事实源是既有 `llm_call_logs` 表：不新建表、不新建活动类型。字段对齐 OTel GenAI
语义（model / prompt tokens / completion tokens / total tokens / latency / trace），`is_mock`
必须诚实反映真实调用状态。`IncidentCommand` 只返回调用记录引用，不复制调用正文。

---

## 2. 失败策略

- 每 agent 独立开关与超时，默认单次 20s；超时后重试 1 次，仍失败只降级该环节。
- 同场地连续 3 次失败熔断 60s，熔断状态由 `llm_call_logs` 推导，不依赖内存态。
- 任何降级都不得伪造模型调用、知识命中或外部渠道送达；无命中必须明确说明"没有依据"。
- 熔断或超时只降级生成式建议，业务仍可按"未获得模型建议"人工推进，不阻塞关闭门禁。

---

## 3. RAG 知识检索增强流

当 **MemoryOps** 介入时，系统执行以下语义检索路径：

1. **Query 转向量**：经 TEI 承载的 bge-m3 将求助文本转换为 1024 维向量（`LocalEmbeddingBackend`
   接口与维度契约不变，仅把实现换成 TEI HTTP adapter）。
2. **向量检索**：在 PostgreSQL pgvector 中做余弦相似度计算。
3. **阈值过滤**：仅保留高于阈值的已发布 SOP 与已审经验。
4. **重排**：需要时由 TEI 承载的 bge-reranker-base 重排候选。
5. **Prompt 注入**：把命中的案例注入 `advice.txt` 的 `{{history_cases}}` 占位符。
6. **依据约束输出**：没有命中时输出"没有依据"，不得伪造引用。

pgvector 里应当有哪些数据、来自哪张事实表、如何核验，见
[向量数据契约](vector-data-contract.md)。

---

## 4. 防御性设计

- **JSON 防抖机制**：全局采用正则剥离技术，应对 LLM 输出的脏数据。
- **契约校验**：四 agent 输出必须先通过 Pydantic 契约校验，失败按失败策略处理，不进入业务状态。
- **并发锁**：`wechat_client` 采用 DCL (Double-Checked Locking) 确保高并发下 Token 刷新不踩踏。
- **降级保护**：当模型挂起或超时，链路只降级该环节；不得用固定兜底文本生成成功业务状态。

---

## 5. 相关文档

- [Agent 处置建议采纳语义](architecture/advice-adoption-semantics.md)
- [景区 Agent 诊断与可观测契约](architecture/scenic-agent-diagnostics-observability.md)
- [景区 Agent 部署 profile 与健康检查](architecture/scenic-agent-deployment-profiles.md)
- [Agent 运行时差距复核](architecture/agent-runtime-gap-review.md)
- [企业演示版交付指南](enterprise-demo/README.md)
- [关键运行流程](enterprise-demo/flows.md)
- [权限与访问边界](enterprise-demo/permissions.md)
- [环境变量与密钥](enterprise-demo/variables.md)
- [Agent 与自动化边界](enterprise-demo/automation.md)
- [测试覆盖图](enterprise-demo/tests.md)
- [故障处理手册](enterprise-demo/failure-playbook.md)

---

<div align="center">
  <p>Memory Palace OS - 让每个指令都具备工业级的严肃性</p>
  <p>Copyright © 2026 ZhouWei</p>
</div>
