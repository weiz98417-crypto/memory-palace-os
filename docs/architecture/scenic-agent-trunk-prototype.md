# 景区 Agent 主干端到端最小验证（票 08）

状态：真实链路已跑通（2026-09-17）

![Jaeger trace](/D:/Documents/memory-palace-os/artifacts/scenic-agent-prototype/jaeger-ticket-08.png)

## 1. 本次运行

| 项目 | 值 |
| --- | --- |
| incident_id | `16bdf82c-07c9-5a6c-91c3-b375cf8e2279` |
| event_id | `b46f41e0-8579-505f-929d-e42176f00f8b` |
| Hatchet run | `f0ac3ce9-12c6-4c40-aac0-73a06d34073e` |
| W3C trace | `265814e76d40fa94928883e0a5f5555e` |
| 证据 JSON | [ticket-08-evidence.json](/D:/Documents/memory-palace-os/artifacts/scenic-agent-prototype/ticket-08-evidence.json) |
| Jaeger UI | `http://127.0.0.1:16686/trace/265814e76d40fa94928883e0a5f5555e` |

执行命令：

```powershell
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml build app
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml --profile agent-runtime build scenic-agent-prototype

docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile agent-runtime --profile tracing --profile tei-embedding up -d

docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile agent-runtime --profile tracing --profile tei-embedding `
  run --rm scenic-agent-prototype `
  python -m scripts.scenic_agent_prototype.runner `
  --base-url http://nginx --evidence /evidence/ticket-08-evidence.json
```

runner 输出：

```json
{"incident_id":"16bdf82c-07c9-5a6c-91c3-b375cf8e2279","trace_id":"265814e76d40fa94928883e0a5f5555e","evidence":"/evidence/ticket-08-evidence.json"}
```

## 2. 四 agent 真实调用

四个 agent 都使用 `deepseek-flash`，经 LiteLLM 直达 `https://api.deepseek.com/v1`。所有记录写入既有 `llm_call_logs`，`is_mock=false`：

| agent | prompt tokens | completion tokens | total | latency seconds |
| --- | ---: | ---: | ---: | ---: |
| context_trigger | 385 | 889 | 1274 | 4.37 |
| router | 791 | 834 | 1625 | 5.55 |
| memory_ops | 1009 | 355 | 1364 | 2.41 |
| commander | 1054 | 697 | 1751 | 4.40 |

`MemoryOps` 返回 `GROUNDED`，引用 `source_id=1` 的《雨后观光车复运与分流 SOP》v1.0；`Commander` 对停运/备用车/解除风险要求 `requires_human_approval=true`。

TEI 使用 `BAAI/bge-m3` 生成 1024 维查询向量，Top-1 SOP source_id 与正式持久化命中一致，score `0.719889104366302`。

## 3. 卷宗与追踪

- `build_event_dossier` 返回 4 条 `model_calls`，包含模型、agent、token、延迟、provider request id、trace 和 honest `is_mock=false`。
- journey timeline 包含 4 条 `MODEL_CALL_COMPLETED`、`ADVICE_READY`、`ADVICE_DECIDED`。
- references 包含正式检索得到的 5 条已核验 SOP；模型只引用其中 `source_id=1`。
- Jaeger 同一 trace 包含：
  - `scenic.incident_command`
  - `scenic.agent.context_trigger`
  - `scenic.agent.router`
  - `scenic.agent.memory_ops`
  - `scenic.agent.commander`
  - 4 个 `gen_ai.chat`
- Jaeger 不可用只影响开发期下钻；审计事实仍来自 `llm_call_logs`。

## 4. 人工中断与关闭门禁

Hatchet durable event wait 使用：

```python
await ctx.aio_wait_for_event(
    "scenic:advice:decision",
    payload_validator=ApprovalDecision,
    scope=request.incident_id,
    lookback_window=timedelta(minutes=5),
)
```

本次 runner 在建议写入后暂停 3.064 秒，再 push `ADOPT` 事件；worker 随后写入 `ADVICE_DECIDED` 并完成 run。事件早于监听时由 lookback window 处理。

关闭门禁在 agent 运行前后都返回 409，未被绕过：

- before：`incident must be RESOLVED before it can be CLOSED`
- after：同一生命周期门禁仍生效
- 没有任务、审批、告警恢复证据时，Agent 建议不会自动放行关闭

## 5. 复现边界

- 测试事件通过 `scenic_situation_alerts` 写入 `PROTOTYPE_FIXTURE`，因为受保护的运行准备入口故意只允许本机管理入口；这是测试夹具，不会伪装成生产信号来源。
- 事件转换、现场证据、SOP 检索和关闭尝试仍走正式 HTTP 契约。
- 模型调用与 TEI 命中均来自真实服务；没有 mock、没有伪造 token、没有伪造 SOP 引用。
- prototype worker 使用独立镜像 `memory-palace-scenic-agent-prototype:local`，不把 prototype 依赖混入正式 app 镜像。

## 6. 需要回炉的设计点

1. **依赖锁定必须修正**：`pydantic-ai==2.43.0` 全量包依赖 `openai>=3.8`，而 `litellm==1.101.0` 依赖 `openai<3`。两者不能直接同时安装。原型使用 `pydantic-ai-slim==2.43.0` + `FunctionModel` + LiteLLM adapter；票 12 必须把正式依赖方案定为 slim 适配或升级到兼容版本。
2. **结构化输出模式必须写死为 PromptedOutput**：`deepseek-flash` thinking 模式不支持 `tool_choice` 和原生 JSON Schema `response_format`。四 agent 继续使用同一模型，但采用 `PromptedOutput` + Pydantic 校验/重试，不得改回默认 tool output。
3. **卷宗模型证据不能只挂在 message source 上**：原先 `event_dossier.py` 仅在 `source_message` 存在时把 model calls 放进 journey timeline。票 08 已补上顶层 `model_calls` 和无 message 场景的 timeline 证据，并增加回归测试。
4. **正式要求文件仍需票 12 收口**：原型 requirements 与正式 `requirements.txt` 分开；在依赖锁定完成前，不应把 prototype 依赖直接合并到生产依赖。

除以上四点外，`IncidentCommand` 边界、Hatchet 人工中断、TEI 检索、`llm_call_logs` 事实源和关闭门禁的主干设计均通过本次验证。
