# 景区前端引导与建议契约（票 09）

状态：已定稿（2026-09-17）

## 1. 后端是下一步动作的唯一来源

`/scenic/snapshot` 返回：

```json
{
  "next_actions": [
    {
      "code": "CONVERT_ALERT",
      "label": "确认设备告警并转为 P1 运营事件",
      "description": "……",
      "enabled": true,
      "prerequisites": [],
      "role_required": ["manager", "admin"],
      "incident_id": null,
      "action": {
        "type": "COMMAND",
        "kind": "CONVERT_ALERT",
        "payload": {"alert_ids": ["alert-id"]}
      }
    }
  ],
  "advice": {
    "run_id": "advice-run-id",
    "status": "READY",
    "display_status": "已就绪",
    "evidence_status": "GROUNDED",
    "advice": "……",
    "citations": [],
    "model_evidence": [],
    "decision": null,
    "allowed_actions": ["ADOPT", "IGNORE"]
  }
}
```

动作 `action.type` 只允许：

- `COMMAND`：前端调用 `/scenic/commands`，传递 `kind` 和 `payload`。
- `NAVIGATE`：只导航到已有业务视图，不执行命令。
- `OPEN_DOSSIER`：打开指定事件卷宗。
- `INFO`：只展示说明，不执行任何动作。

动作生成代码在 `src/memory_palace/scenic/guidance.py`。`static/index.html` 的指挥中心只读取 `snapshot.next_actions`；`static/assistant/app.js` 的现场端只显示后端动作文案和建议只读状态。

## 2. 建议状态矩阵

`project_advice` 从 `event_activities` 中按 `advice_run_id` 聚合，并以最新活动的顺序得到状态：

| 状态 | 界面 | 允许动作 |
| --- | --- | --- |
| `PENDING` / `RUNNING` | 分析中 | `PROCEED_WITHOUT_WAITING` |
| `READY` + `GROUNDED` | 已就绪 | `ADOPT` / `IGNORE` |
| `READY` + `NO_EVIDENCE` | 已就绪，明确“没有依据” | `IGNORE` / `PROCEED_WITHOUT_WAITING` |
| `FAILED` | 未获得模型建议 | `PROCEED_WITHOUT_WAITING` |
| `SUPERSEDED` | 已过期，只读 | 无 |

建议卡展示正文、SOP/案例标题、版本、source id、vector score、rerank score；manager/admin 额外看到按 `llm_call_logs.trace_id` 关联的模型名、token、延迟、trace 和 `is_mock`。现场端只读展示正文、引用和状态，不显示技术账本字段。

## 3. 人工决定

指挥中心的 manager/admin 通过正式命令：

```json
{
  "kind": "DECIDE_ADVICE",
  "payload": {
    "incident_id": "incident-id",
    "advice_run_id": "advice-run-id",
    "decision": "IGNORE",
    "expected_state": "READY",
    "reason_code": "HUMAN_JUDGMENT",
    "reason_text": null
  }
}
```

- `ADOPT` 可单次提交。
- `IGNORE` 必须带 reason code；`OTHER` 必须有文本。
- `PROCEED_WITHOUT_WAITING` 必须带 reason code，并二次确认“后续派单不会引用该建议”。
- 后端 `_command_decide_advice` 重复校验同一规则；前端绕过时返回 422/409，不写入决定活动。
- `PENDING/RUNNING` 的不等待决定写成 `ADVICE_SUPERSEDED`；其余写成 `ADVICE_DECIDED`。

## 4. SSE 接线

`/scenic/stream` 对以下情形发送事件名而不是通用的 `situation`：

- `event_type=ADVICE_PENDING` → 界面显示“模型建议分析中”。
- `event_type=ADVICE_READY` → 界面显示“处置建议已就绪”，刷新建议卡。
- `event_type=ADVICE_FAILED` → 界面显示“未获得模型建议”，允许按状态矩阵继续。
- `ADVICE_SUPERSEDED` 仍作为 `ADVICE_READY.data.state` 的派生状态显示“已过期”。

共享客户端 `static/shared/client.js` 通过 `onAdvice` 把事件交给指挥中心和现场端；断线恢复仍以快照为准。

## 5. 卷宗呈现

`event_dossier` 已支持：

- `model_calls`：`llm_call_logs` 的脱敏模型、token、延迟、trace、`is_mock` 证据。
- `journey_timeline`：`MODEL_CALL_COMPLETED`、`ADVICE_READY`、`ADVICE_DECIDED/SUPERSEDED`。
- `references`：正式 `scenic_knowledge_hits` 中已核验的 SOP/案例引用。

关闭门禁不受建议状态影响：没有建议、建议失败或已过期时，业务仍可人工推进；有建议也不会跳过证据、SOP、任务、审批与告警恢复条件。

## 6. 测试

- `tests/unit/test_scenic_guidance.py`：动作码、状态矩阵、允许动作。
- `tests/integration/test_scenic_api.py`：快照 `next_actions/advice`、忽略缺少理由 422、SSE 事件名。
- `tests/unit/test_scenic_frontend_guidance_contract.py`：前端不再从 lifecycle 推导，建议/SSE/理由表单接线存在，现场端只读。
## 7. 本机界面冒烟

![指挥中心建议卡](/D:/Documents/memory-palace-os/artifacts/scenic-agent-prototype/guidance-command-center.png)

![现场端只读建议](/D:/Documents/memory-palace-os/artifacts/scenic-agent-prototype/guidance-field-readonly.png)

本机真实快照冒烟结果：`next_actions=[CREATE_REPAIR_TASK]`，建议 `READY/GROUNDED`，决定 `ADOPT`，1 条 SOP 引用，4 条模型调用证据。指挥中心显示建议正文、引用、模型证据折叠区和人工判断；现场端只显示下一步、建议正文和引用，不出现决定操作。
