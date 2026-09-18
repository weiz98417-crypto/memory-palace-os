# 景区 Agent 评测基线（票 06）

状态：已建立（2026-09-17）

## 1. 目标与边界

这份基线把“建议必须被命中的 SOP 支撑、无命中必须明确拒答、真实调用必须有凭据”变成可执行的评测门禁。它服务于 ADR-0018/0019，不替代业务事实：

- 黄金样本是测试夹具，`FIXTURE-*` 来源不会写入生产 `knowledge_vectors` 或卷宗。
- DeepEval 判官复用景区 Agent 的同一模型配置；评测调用不是业务事件，不写事件建议正文。
- 当前 `run_deepeval.py --mode deepeval` 使用 `CALIBRATION_FIXTURE` 作为候选输出，只验证评测链路和判官配置，不能当作 Agent 质量或真实调用证据。票 08 会把 `IncidentCommand` 的真实结构化输出接到同一夹具。
- 真实模型冒烟缺 `DEEPSEEK_API_KEY`（或 `DEEPSEEK_API_KEY_FILE`）时返回非零失败，不跳过，也不回退 mock。

## 2. 黄金样本矩阵

夹具文件：[golden_cases.json](/D:/Documents/memory-palace-os/evals/scenic_agent/golden_cases.json)

| 场景 | 检索状态 | 期望建议 | 必须引用 | 拒答/禁用断言 |
| --- | --- | --- | --- | --- |
| 设备异常：雨后 12 号观光车右后轮异响 | `HITS` | `READY/GROUNDED` | `FIXTURE-SOP-VEHICLE-RECOVERY-V1` | 不得说“没有依据”；必须保留“继续停运”和值班经理审批边界 |
| 客流告警：东门超过容量阈值 | `HITS` | `READY/GROUNDED` | `FIXTURE-SOP-EAST-GATE-DIVERSION-V1` | 不得说“没有依据”；必须包含单向分流和镜湖引导 |
| 无知识命中：巡检无人机异常 | `ZERO_HITS` | `READY/NO_EVIDENCE` | 无 | 必须包含“没有依据”，引用必须为空，不得声称命中 SOP/案例 |

每个夹具还保存了事件上下文、现场证据、知识命中的版本与摘录，以及仅供评测校准的固定候选回答。固定候选回答明确标记为 `CALIBRATION_FIXTURE`，不会冒充模型输出。

## 3. CI 分工

### 3.1 契约门禁（每次改动，无网络）

命令：

```powershell
uv run --no-project --with-requirements requirements.txt python -m pytest -q tests/evaluation --no-cov
uv run --no-project --with-requirements requirements.txt python evals/scenic_agent/run_deepeval.py --mode contract --report artifacts/scenic-agent-eval/contract-report.json
```

覆盖的断言：

- 三类场景齐备且 schema 可加载；来源 id 不允许重复，期望引用必须存在于已核验命中中。
- `GROUNDED` 建议必须包含全部期望引用，不能引用上下文之外的来源。
- `NO_EVIDENCE` 必须包含精确短语“没有依据”、引用为空、不能出现伪造命中文本。
- 真实模型凭据检查函数在缺 Key 时抛出失败，不允许跳过或切到 mock。
- 票 08 接入真实 `IncidentCommand` 后，在同一夹具上增加假 registry 断言：四 agent 顺序、结构化输出校验、`llm_call_logs` 字段完整、`is_mock` 诚实、单环节失败只降级、幂等键和关闭门禁不被绕过。该部分当前没有业务 Agent 实现，不伪造通过结论。

### 3.2 DeepEval 校准门禁（显式执行，需要真实凭据）

命令：

```powershell
uv run --no-project --with-requirements requirements-eval.txt python evals/scenic_agent/run_deepeval.py --mode deepeval --report artifacts/scenic-agent-eval/deepeval-report.json
```

覆盖的断言：

- 有依据场景运行 `FaithfulnessMetric`，阈值 `0.8`：建议中的事实性陈述必须由对应命中 SOP 摘录支撑。
- 无命中场景运行 `GEval-NoEvidenceRefusal`，阈值 `0.8`：明确拒答、不声称命中、不编造来源或操作步骤。
- 报告记录判官模型名、每项分数、阈值、原因和候选来源；不记录 API Key、prompt 全文或回答全文之外的业务数据。
- 缺凭据时进程退出码为 `2`，CI 应把非零视为失败。判官或模型返回异常同样失败，不能显示“跳过”。

本次本地执行使用 `deepseek-flash` 判官，三项均为 `1.0`，报告见 `artifacts/scenic-agent-eval/deepeval-report.json`（本地证据，不提交）。

### 3.3 真实模型冒烟（票 08 接线）

真实 `IncidentCommand` 实现后，冒烟必须使用同一真实凭据并额外断言：

- provider 返回真实成功（HTTP/调用记录状态，不把 mock 当真实）；
- `llm_call_logs` 中真实模型名、token、延迟、attempt、trace 与 `is_mock=false` 可核对；
- 事件卷宗能按调用引用显示“模型调用证据”和 SOP 引用；
- Jaeger 中存在同 trace 的 `scenic.incident_command`、`scenic.agent.*`、`gen_ai.chat` span；
- 缺少凭据时该门禁失败而非跳过。

在票 08 接线前，不得把 3.2 的校准报告宣称为真实业务链路通过。

## 4. 判官配置

- 模型：`SCENIC_EVAL_MODEL`，否则 `LLM_DEFAULT_MODEL`，否则 `deepseek-flash`。
- 网关：`DEEPSEEK_BASE_URL`，默认 `https://api.deepseek.com/v1`。
- 温度：`0`；价格参数显式设为 `0` 仅避免 DeepEval 对未知模型价格报错，真实业务成本仍只以 `llm_call_logs` 为准。
- 凭据：`DEEPSEEK_API_KEY` 优先，其次 `DEEPSEEK_API_KEY_FILE`。原生栈使用同一环境变量；容器栈从密钥卷注入。

## 5. 结果解释

确定性契约和 DeepEval 分数回答的是不同问题：前者证明结构化边界和拒答行为没有漂移，后者衡量当前候选回答与已核验上下文的忠实度。任何一项失败都阻断对应门禁，不能用另一层的成功覆盖。无命中时重点不是“回答有多像”，而是系统是否诚实地承认没有依据。
