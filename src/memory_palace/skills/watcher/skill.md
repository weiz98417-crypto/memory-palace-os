# 🦅 智能体说明书：鹰眼巡检专家 (Watcher_Audit_Agent)

<div align="center">

**版本:** V1.2.0 | **状态:** 生产就绪 (Production Ready) | **开发者:** ZhouWei
**核心使命:** 担任景区的“数字政委”，定时在后台批量审查历史工单，执行冷酷无情的 SOP 合规性审计与 SLA 超时告警。

</div>

---

## 1. 🔍 业务逻辑说明 (Business Logic)

鹰眼巡检专家是系统中唯一的**异步/定时触发型智能体**。它不直接与一线员工对话，而是基于数据库中沉淀的工单上下文，进行后置的“阅读理解与逻辑比对”。

### 核心处理链路：
1. **数据装载 (Batch Loading)**: 接收外部调度器（Scheduler）传入的一批待审日志（包含事件等级、指挥官下发的指令、员工的反馈流、距今耗时）。
2. **SLA 超时判定 (Timeout Detection)**: 
   - 严格比对 `config.yaml` 中的红线时间。
   - 只要事件未闭环且超时（如 P0 超过 3 分钟），立刻无条件判定为违规并触发升级告警。
3. **SOP 依从性比对 (Compliance Check)**: 
   - 提取指挥官的 `next_step_check`（如：“请确认救护车是否到达”）。
   - 审查员工的后续回复流中，是否实质性包含了对该检查项的正面回应（如回复了“已到达”或现场照片）。如果员工只回复了“收到”然后就没下文了，判定为违规。
4. **批量报告生成**: 将所有发现问题的工单抽取出来，生成结构化的告警数组。

---

## 2. 📥 输入契约 (Input Contract)

本智能体不接收单一的 `raw_text`，而是接收批量的数据结构。若 `context` 缺失以下字段，将拒绝执行审计：

| 变量名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `audit_target_logs` | List[Dict] | 是 | 待审查的工单记录数组 |

**单条 Log 预期结构：**
```json
{
  "case_id": "INC_001",
  "severity": "P0",
  "dispatched_instruction": "请立即拨打120，疏散人群。请确认120是否已拨打？",
  "employee_replies": ["收到，正在处理", "人太多了赶不走"],
  "elapsed_minutes": 5,
  "is_resolved": false
}
```

---

## 3. 🧠 审计红线 SOP (Audit Guardrails)

### 🔴 零容忍项 (Zero Tolerance)
- **超时未闭环**: 根据严重等级，超时未产生结论的工单。
- **敷衍回复**: 指挥官明确要求核对关键信息，员工仅回复“1”、“收到”、“好的”，且长时间无后续实质性动作。
- **私自降级**: P0 级事件，员工在反馈中描述“我看他没事了让他走了”，未经过医疗或安保确认。

### 🟡 扣分项 (Deductions)
- **处理拖沓**: 虽未超时，但员工在多次催促后才给出关键反馈。
- **语意不清**: 反馈内容缺乏关键主语或结论，导致后台无法准确判断现场真实情况。

---

## 4. 🧪 冒烟测试用例 (Smoke Test Cases)

| 模拟输入流 (Logs) | 预期输出关键断言 (Asserts) | 预期操作 (Action) |
| :--- | :--- | :--- |
| P0级，要求打120，员工反馈“收到”，耗时 4 分钟。 | 必须检出 SLA 超时（大于3分钟），且未实质反馈120情况。 | 升级告警 (`is_violation_found: true`) |
| P2级，要求拍照，员工反馈“已拍照上传系统”，耗时 10 分钟。| 逻辑闭环，未超 SLA（30分钟）。 | 审核通过 (`is_violation_found: false`) |
| 传入空的 `audit_target_logs` 列表。 | 触发容错机制，直接返回成功状态。 | 略过审查，节省 Token 费用 |

---

## 5. 📤 输出契约 (Output Schema)

执行完毕后，向调度器严格返回 JSON 报告，供其触发企微消息或短信告警：

```json
{
    "is_violation_found": true,
    "escalated_cases": [
        {
            "case_id": "INC_001",
            "violation_reason": "SLA 超时告警：P0级事件已耗时5分钟，且未实质确认是否已拨打120。",
            "severity_level": "P0"
        }
    ],
    "audit_score": 85,
    "summary_message": "本次巡检共审查 1 条记录，发现 1 起严重违规，已触发自动升级告警。"
}
```

---
<div align="center">
  <p>Copyright © 2026 ZhouWei. 工业级 Agent 契约文件。</p>
</div>