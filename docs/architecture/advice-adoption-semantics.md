# 处置建议采纳语义与卷宗呈现（票 05）

状态：已确认（2026-09-17，grilling 两轮完成）

## 1. 决策权限

- 只有同场地的 `manager` 或 `admin` 可以采纳、忽略或选择“不等待建议”。
- `operator` 可以提交证据、查看建议正文/引用/状态和任务结果，但不能改变建议判断。
- 决定必须绑定 `incident_id + advice_run_id`；跨场地、跨事件或已经 `SUPERSEDED` 的建议拒绝写入。`READY` 和 `FAILED` 在本矩阵允许的范围内仍可作决定。
- 决定活动必须记录 `decided_by`、`decided_at`、`decision`、`reason_code`、可选理由文本和幂等键。
- 决定是追加记录，不覆盖历史判断。纠错只能追加一条 correction 活动，不能改写原决定。

## 2. 状态与允许动作

建议运行状态继续使用 `PENDING / RUNNING / READY / FAILED / SUPERSEDED`。人类决定只允许下列组合：

| 建议状态 | 建议证据状态 | 允许的决定 |
| --- | --- | --- |
| `READY` | `GROUNDED` | `ADOPT`；或 `IGNORE` + reason code |
| `READY` | `NO_EVIDENCE` | `IGNORE` + reason code；或 `PROCEED_WITHOUT_WAITING` + reason code |
| `PENDING` / `RUNNING` | 未产出 | `PROCEED_WITHOUT_WAITING` + reason code；随后 CAS 为 `SUPERSEDED` |
| `FAILED` | 未产出或 `RETRIEVAL_FAILED` | `PROCEED_WITHOUT_WAITING` + reason code |
| `SUPERSEDED` | 任意 | 不允许重新采纳；只能审计查看 |

`RETRIEVAL_FAILED` 或模型不可用不是“没有依据”的知识结论，而是运行失败。界面显示“未获得模型建议”，并记录系统上下文 `MODEL_UNAVAILABLE`；它不能伪装成正常建议或 SOP 命中。

UI 操作确认：

- `ADOPT` 单次提交，可选备注。
- `IGNORE` 单次表单提交，reason code 必填，`OTHER` 必须有文本，不额外弹 modal。
- `PROCEED_WITHOUT_WAITING` 必须先填 reason，再二次确认“后续派单不会引用该建议”；确认后写入决定，并在需要时 CAS 为 `SUPERSEDED`。
- 既有高风险审批不变；建议决定不能替代继续停运、启用备用车等审批。

内部状态 `FAILED` 可在诊断/UI 派生为“未获得模型建议”；如果执行器因开关、配额或熔断没有创建可运行 attempt，则以 `UNAVAILABLE` 语义展示，不能伪造一个 `READY` advice。

## 3. Reason code

忽略或“不等待建议”必须带结构化 reason：

| code | 含义 |
| --- | --- |
| `NO_BASIS` | 没有可用依据 |
| `NOT_APPLICABLE` | 建议不适用于现场 |
| `EVIDENCE_CONFLICT` | 建议与现场证据冲突 |
| `HUMAN_JUDGMENT` | 由人工判断决定 |
| `OTHER` | 其他原因，必须填写文本说明 |

- `ADOPT` 可带可选备注，不要求 reason code。
- `IGNORE` 必须有 reason code；`OTHER` 必须有非空文本。
- `PROCEED_WITHOUT_WAITING` 必须有 reason code；`OTHER` 必须有非空文本。
- 系统另记 `system_context`，例如 `MODEL_UNAVAILABLE`、`EVENT_CLOSED`，不把它冒充为用户理由。`NO_EVIDENCE` 是建议的 `evidence_status`，不作为 system context 重复记录。

决定活动的规范化 payload：

```json
{
  "decision": "ADOPT",
  "incident_id": "incident-id",
  "advice_run_id": "scenic-command-id",
  "expected_advice_state": "READY",
  "reason_code": null,
  "reason_text": null,
  "system_context": null,
  "decided_by": "scenic-wangfang",
  "decided_at": 1780000000.0,
  "idempotency_key": "advice-decision:..."
}
```

## 4. 流程推进门禁

进入派单草案必须已经有一个与当前 advice run 绑定的人类决定：

1. `ADOPT`；或
2. `IGNORE` + reason code；或
3. `PROCEED_WITHOUT_WAITING` + reason code；若建议仍在 `PENDING/RUNNING`，同一业务事务必须已经把它 CAS 为 `SUPERSEDED`。

“存在未决 advice run”本身不满足门禁；没有决定时不能进入派单草案。

决定本身不创建任务、不发送外部渠道、不改变关闭门禁。它只允许后续的派单动作继续。

下游 Commander 的输入规则：

- `ADOPT`：允许建议正文和引用进入 Commander 上下文。
- `IGNORE`：禁止被忽略建议的正文和引用进入 Commander 上下文；队列继续基于事件、现场证据和已核验知识生成草案。
- `PROCEED_WITHOUT_WAITING`：Commander 不接收建议正文/引用；迟到建议不能改变已生成的派单。
- 无建议或失败：允许人工继续处置，但界面和卷宗必须明确写“未获得模型建议”。

## 5. SUPERSEDED

建议在 `PENDING/RUNNING` 时，人选择不等建议并推进到派单，或事件先被关闭：

- 在业务事务中对建议运行执行 CAS：`PENDING/RUNNING -> SUPERSEDED`。
- 同时记录 `superseded_by`（人的命令/活动 id 或 `EVENT_CLOSED`）、`superseded_at`、`system_context`；人的不等待动作还必须有 reason code。
- 迟到的模型结果仍写入建议运行和卷宗，但不参与派单、任务生成、关闭门禁或后续建议引用。
- `READY` 建议不能自动变成 `SUPERSEDED`；必须采纳或忽略，避免把人的决定吞掉。
- `FAILED` 建议不是 `SUPERSEDED`；它保留失败状态，人可以带理由 `PROCEED_WITHOUT_WAITING`。

## 6. 卷宗时间线与字段

时间线顺序固定为：

```text
SOP_RETRIEVED
  -> ADVICE_PENDING
  -> ADVICE_READY / ADVICE_FAILED
  -> ADVICE_DECIDED / ADVICE_SUPERSEDED
  -> DISPATCHED
```

建议卡字段：

- 状态：分析中 / 已就绪 / 未获得模型建议 / 已过期。
- 正文：建议内容；无依据时固定“没有依据”。
- 引用：SOP/案例的标题、版本、source id、vector score、rerank score。
- 模型证据：model name、token、latency、trace、`is_mock`；只以 `llm_call_logs` 为事实源。
- 决定：ADOPT/IGNORE/PROCEED_WITHOUT_WAITING、操作人、时间、reason code、理由文本、superseded_by。
- 迟到建议：折叠在“迟到建议（未用于处置）”区块，正文和引用只读保留。

## 7. 可见性

| 字段 | manager/admin | operator |
| --- | --- | --- |
| 建议正文、引用、vector/rerank score | 完整 | 完整 |
| 当前状态、决定类型 | 完整 | 完整 |
| 忽略/不等待理由全文 | 完整 | 不展示全文，仅展示“已忽略/未等待/已过期” |
| model/token/latency/trace | 完整 | 不展示技术字段 |
| 迟到建议正文 | 完整、折叠、只读 | 摘要与状态，不展示完整正文 |
| correction 活动 | 完整 | 不展示 |

所有可见性仍受 venue 隔离约束；卷宗和审计接口只能读取当前场地数据。

## 8. 与关闭门禁的关系

- 关闭门禁保持不变：现场证据、SOP 命中、任务完成、审批结果、告警恢复；建议不是关闭必需项。
- 关闭时若建议仍为 `PENDING/RUNNING`，由事件关闭动作将其系统标记为 `SUPERSEDED`，`superseded_by=EVENT_CLOSED`，不得留下无限 pending。
- 关闭时若建议已经 `READY` 但尚未判断，不自动改成 `SUPERSEDED`；关闭活动记录 `advice_status=READY`、`advice_decision_status=UNDECIDED_AT_CLOSURE`，卷宗显示“已生成建议，关闭时未作采纳判断”。
- 关闭时若建议为 `FAILED`，保留失败状态和“未获得模型建议”，不得伪装为已判断。
- 卷宗必须显示：
  - 建议已采纳/忽略/不等待；
  - 或“未获得模型建议”；
  - 或“已过期（原因）”。
- 不能因为模型失败阻塞关闭，也不能因为建议存在而放行未满足的关闭证据。

## 9. 可施工的最小落点

- 建议/决定状态复用票 04 的 `IncidentCommand`/异步运行语义；建议正文和引用作为活动正文留存。
- 决定活动使用既有 `event_activities`，不新增调用记录表或活动账本。
- `ScenicAreaOperations` 在两个派单草案命令之前执行流程推进门禁；关闭命令执行关闭门禁并清理 pending advice。
- SSE `ADVICE_PENDING/READY/FAILED` 的 payload 带状态、建议摘要、决定状态；`SUPERSEDED` 通过 `ADVICE_READY.data.state` 表达。
- 本票只定义 next action 的语义状态；具体动作码和渲染契约由票 09 锁定，前端不得自行推导。