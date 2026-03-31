# 🚨 智能体说明书：现场指挥官 (Commander_Agent)

<div align="center">

**版本:** V1.2.5 | **状态:** 生产就绪 (Production Ready) | **开发者:** ZhouWei  
**核心使命:** 针对突发事件（incident_report）执行毫秒级响应，下发标准处置流程（SOP）并协调资源。

</div>

---

## 1. 🔍 业务逻辑说明 (Business Logic)

现场指挥官是系统的"执行中枢"。它不进行发散性创作，而是基于 Router 识别出的风险等级，从企业知识库中检索对应的 **SOP (Standard Operating Procedure)** 并转化为易于执行的指令。

### 核心处理链路：
1. **上下文感知**: 从 `context` 获取 `severity`（风险等级）和 `summary`（事件摘要）。
2. **策略选择**:
   - **P0/P1 (紧急)**: 触发"生命优先"原则。指令强制包含：120/110拨打确认、人群疏散指令、关键岗位禁区封锁。
   - **P2 (一般)**: 触发"合规处置"原则。指令侧重于：证据留存（拍照）、游客情绪安抚、引导至线下调解点。
3. **闭环管理**: 所有输出必须附带一个"待办确认"，用于后续 Watcher Agent 的催办追踪。

---

## 2. 📥 输入契约 (Input Contract)

本智能体严格依赖于上游 **Router** 的输出。若上下文缺少以下字段，将拒绝执行：

| 变量名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `raw_text` | String | 是 | 用户最初发送的求助或报警文本 |
| `intent` | String | 是 | 必须为 `incident_report` 才能激活本智能体 |
| `severity` | String | 是 | 风险等级：P0 (严重) 至 P4 (轻微) |
| `venue_id` | String | 是 | 确定事发具体区域，用于匹配地理坐标和最近安保点 |

---

## 3. 🧠 决策 SOP (Standard Operating Procedures)

### 🔴 P0 级：生命安全 / 紧急火灾
- **强制指令**: "立即拨打120并通知总值班室，请确认是否已拨打？"
- **现场控制**: 要求员工维持现场秩序，严禁非专业人员触碰伤者。
- **语气要求**: 极度冷静、短促、权威命令式。

### 🟡 P2 级：普通客诉 / 财物丢失
- **强制指令**: "请引导游客至最近的服务中心，并进行拍照记录。"
- **现场控制**: 提醒员工佩戴好记录仪，保持文明用语。
- **语气要求**: 专业、有同理心、流程引导式。

---

## 4. 🧪 验收测试用例 (Acceptance Test Cases)

| 测试场景 | 模拟输入 (Context) | 预期输出关键点 (Asserts) |
| :--- | :--- | :--- |
| **严重溺水** | `{severity: "P0", raw_text: "有人落水了"}` | 必须包含 "人工呼吸建议" 和 "拨打120确认" |
| **设备卡顿** | `{severity: "P1", raw_text: "过山车悬停了"}` | 必须包含 "安抚游客" 和 "通知工程部技术员" |
| **轻微擦伤** | `{severity: "P3", raw_text: "小朋友摔了一跤"}` | 引导至最近的"红十字医疗站" |

---

## 5. 📤 输出契约 (Output Schema)

执行完毕后，向 **Orchestrator** 返回的结构化数据如下：

```json
{
    "action_taken": "emergency_dispatch_sop",
    "is_escalated": true,
    "required_tools": ["wechat_msg", "sms_alert"],
    "next_step_check": "请确认医护人员是否在5分钟内抵达",
    "structured_data": {
        "sop_id": "SOP_MEDICAL_001",
        "involved_departments": ["Medical", "Security"]
    }
}
```