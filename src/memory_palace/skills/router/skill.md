# 🤖 智能体说明书：路由大管家 (Router_Agent)

<div align="center">

**版本:** V1.2.0 | **状态:** 生产就绪 (Production Ready) | **开发者:** ZhouWei  
**核心使命:** 景区入口流量分诊与风险评级门神，实现双层过滤架构。

</div>

---

## 1. 🔍 业务逻辑说明 (Business Logic)

路由大管家是系统的"意图分发与风险分诊中枢"。采用双层过滤架构，兼顾速度与精准度。

### 核心处理链路：
1. **L1 快速路径 (Regex)**: 极速拦截高频闲聊（如"收到"、"好的"），0 Token 消耗。
2. **L2 深度路径 (LLM)**: 深度解析复杂意图与 P 等级评定。
3. **配置驱动**: 从同级目录下的 config.yaml 加载模型参数。
4. **提示词解耦**: 从 prompts/router.txt 动态读取 System Prompt。

---

## 2. 📥 输入契约 (Input Contract)

| 变量名 | 类型 | 必填 | 描述 |
| :--- | :--- | :--- | :--- |
| `raw_text` | String | 是 | 用户原始输入文本 |

---

## 3. 🧠 意图分类 (Intent Classification)

| 意图 | 描述 | 严重等级范围 |
| :--- | :--- | :--- |
| `incident_report` | 现场突发事件报告 | P0-P2 |
| `emergency_advice` | 历史经验/处置方案查询 | P2-P3 |
| `chitchat` | 日常闲聊 | P4 |
| `other` | 其他 | P3 |

---

## 4. 🧪 验收测试用例 (Acceptance Test Cases)

| 测试场景 | 模拟输入 | 预期输出 |
| :--- | :--- | :--- |
| **闲聊问候** | "你好" | L1 正则拦截，返回问候语 |
| **溺水报警** | "有人落水了" | intent=incident_report, severity=P0 |
| **设备故障** | "过山车停了" | intent=incident_report, severity=P1 |
| **经验查询** | "以前遇到过这种情况吗" | intent=emergency_advice, severity=P3 |

---

## 5. 📤 输出契约 (Output Schema)

```json
{
  "intent": "incident_report|emergency_advice|chitchat|other",
  "severity": "P0|P1|P2|P3|P4",
  "summary": "简要描述",
  "confidence": 0.95
}
```