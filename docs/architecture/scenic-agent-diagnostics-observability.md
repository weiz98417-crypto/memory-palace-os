# 景区 Agent 诊断与可观测契约（票 10）

状态：已定稿（2026-09-17）

## 1. 事实源与展示边界

- 业务事实源仍是 PostgreSQL 中的 `llm_call_logs`。
- 诊断接口 `/admin/diagnostics` 只展示按场地过滤、白名单化的字段，不返回 prompt、回答正文、API Key、完整堆栈或数据库连接串。
- Jaeger 只作为开发期链路下钻视图；其不可用不影响业务、卷宗、关闭门禁或诊断状态，`business_impact_on_unavailable` 固定为 `none`。
- `/health` 与 `/ready` 继续承担容器探针；TEI、Hatchet、Jaeger 的配置和可选失败语义见部署 profile 文档。

## 2. 诊断响应扩展

`collect_runtime_diagnostics` 在原有 `deepseek` 字段之外新增：

```json
{
  "model_runtime": {
    "status": "READY",
    "provider": "deepseek",
    "model": "deepseek-flash",
    "configured": true,
    "mock_enabled": false,
    "live_verified": true,
    "latest_real_call": {
      "model_name": "deepseek-flash",
      "status": "SUCCEEDED",
      "prompt_tokens": 100,
      "completion_tokens": 28,
      "total_tokens": 128,
      "latency_seconds": 0.75,
      "request_id": "provider-request-id",
      "trace_id": "w3c-trace-id",
      "agent_id": "Router",
      "is_mock": false,
      "created_at": 1780000000.0
    },
    "degradation_reasons": []
  },
  "token_quota": {
    "status": "NORMAL",
    "limit_tokens": 20000000,
    "used_tokens": 128,
    "remaining_tokens": 19999872,
    "usage_percent": 0.001,
    "window": "UTC_DAY"
  },
  "circuit_breaker": {
    "state": "CLOSED",
    "source": "llm_call_logs",
    "consecutive_failures": 0,
    "failure_threshold": 3,
    "recovery_timeout_seconds": 60,
    "retry_after_seconds": null
  },
  "observability": {
    "business_evidence_source": "llm_call_logs",
    "jaeger": {
      "status": "OPTIONAL_NOT_CONFIGURED",
      "ui_url": null,
      "business_impact_on_unavailable": "none"
    }
  }
}
```

### 模型运行时

- `latest_real_call` 只取 `provider=deepseek`、`status=SUCCEEDED`、`is_mock=false` 的最新记录。
- 模型名、token、延迟、request id 和 trace id 均来自 `llm_call_logs`，不重新估算。
- `mock_enabled=true`、无 Key、模型配置错误、无近期真实调用时，模型运行时为 `DEGRADED`。

### 每日 Token 配额

- 环境变量：`SCENIC_AGENT_DAILY_TOKEN_LIMIT`，本机默认 `20000000`。
- 统计窗口为 UTC 当日，按当前 `venue_id` 汇总 `llm_call_logs.total_tokens`。
- `NORMAL < 80% <= WARNING < 100% <= EXHAUSTED`。
- 配额触顶只降级生成式建议；业务仍可按“未获得模型建议”人工推进，不阻塞关闭门禁。
- `SCENIC_AGENT_DAILY_TOKEN_LIMIT<=0` 表示 `DISABLED`，但不伪造 token 使用量为已测量值。

### 熔断器

- 阈值：`SCENIC_AGENT_CIRCUIT_FAILURE_THRESHOLD`，默认 `3`。
- 冷却：`SCENIC_AGENT_CIRCUIT_RECOVERY_SECONDS`，默认 `60`。
- 为避免内存态和后端进程重启造成不可审计，诊断页按 `llm_call_logs` 最新失败序列推导 `CLOSED / OPEN / HALF_OPEN`。
- 连续失败达到阈值且未过冷却时为 `OPEN`；冷却到期但尚未出现真实探测调用时为 `HALF_OPEN`。
- 熔断状态只影响模型环节，不改变业务事实和关闭门禁。

## 3. Jaeger 可选下钻

- `JAEGER_UI_URL` 配置时，诊断页显示“打开 Jaeger”按钮。
- 未配置时显示 `OPTIONAL_NOT_CONFIGURED`，不显示错误或阻断。
- Jaeger 下钻链接只打开带有具体 Trace ID 的页面；业务审计仍以 PostgreSQL 记录为准。

## 4. 页面呈现

运维诊断页新增指标卡：

- 模型运行时：状态、模型、最近真实调用的 token/耗时；
- 每日 Token 配额：已用、上限、剩余、百分比；
- 模型熔断器：状态、连续失败数、阈值、重试等待；
- 追踪下钻：业务证据源与 Jaeger 可选状态。

现有 DeepSeek 调用证据表继续展示最近 50 次调用，不增加 prompt 正文或回答正文。

## 5. 契约测试

- `tests/integration/test_runtime_diagnostics_api.py::test_runtime_diagnostics_reports_unified_safe_operational_status`
- `tests/integration/test_runtime_diagnostics_api.py::test_runtime_diagnostics_surfaces_exhausted_quota_and_open_circuit`
- `tests/unit/test_runtime_health_checks.py`
## 6. 本机真实冒烟

![模型运行时、配额与熔断诊断](/D:/Documents/memory-palace-os/artifacts/scenic-agent-prototype/diagnostics-runtime.png)

本机容器实测：生成式模型契约、应用配置与真实落库模型名统一为 `deepseek-flash`，模型运行时不再因模型名不一致而 `DEGRADED`；每日配额本机默认 `20000000`，熔断器 `CLOSED`，Jaeger 显示 `OPTIONAL_NOT_CONFIGURED`。诊断只读取 `llm_call_logs` 真实调用，不把 Mock 或估算 token 伪装成真实调用。
