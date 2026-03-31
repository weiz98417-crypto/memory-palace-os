# 🛠️ 智能体开发指南：如何新增一个 Skill (Agent)

本指南面向开发者，规定了在 **Memory Palace OS** 架构下新增业务智能体（Skill）的标准流程与质量红线。

---

## 1. 目录结构规范

每个 Skill 必须是一个独立的包，存放在 `src/memory_palace/skills/` 目录下。严禁跨目录乱放逻辑。

```text
skills/your_new_skill/
├── __init__.py         # 暴露 Skill 类
├── skill.py            # 【核心】业务逻辑代码，继承自 BaseSkill
├── config.yaml         # 【配置】模型超参数、业务阈值
├── skill.md            # 【契约】业务逻辑说明书（供非技术人员审计）
└── prompts/            # 【指令集】
    └── main.txt        # 核心 System Prompt
```

---

## 2. 核心开发步骤 (The 4-Step Process)

### Step 1: 定义业务配置 (`config.yaml`)
首先确定该 Agent 的“性格参数”和业务边界。
```yaml
agent_settings:
  model: "gpt-4o"
  temperature: 0.3      # 业务型 Agent 建议低于 0.5
  max_tokens: 500
  
business_rules:
  threshold_score: 80   # 业务判定阈值
  retry_limit: 2
```

### Step 2: 编写业务代码 (`skill.py`)
必须继承 `BaseSkill` 抽象基类，并实现 `_execute_impl` 方法。

```python
from memory_palace.core.skill_base import BaseSkill, SkillOutput

class YourNewSkill(BaseSkill):
    def __init__(self):
        # 必须指定 skill_name，系统会自动加载对应的 prompts 和 config
        super().__init__(skill_name="your_new_skill")

    async def _execute_impl(self, context: dict, trace_id: str) -> SkillOutput:
        # 1. 组装输入数据
        user_input = context.get("raw_text", "")
        
        # 2. 调用父类封装好的 llm_ask (自动带入 system prompt)
        response = await self.llm_ask(
            user_content=f"请处理以下任务: {user_input}",
            json_mode=True,
            trace_id=trace_id
        )
        
        # 3. 解析并返回标准化结果
        # 注意：必须返回 SkillOutput 对象，严禁返回 dict 或 str
        return SkillOutput(
            success=True,
            reply_text=response.get("reply_text", "处理完毕"),
            action_taken="logic_completed",
            tokens_used=450  # 假设值
        )
```

### Step 3: 编写指令集 (`prompts/main.txt`)
指令集必须遵循“角色-规则-输出格式”的三段式结构，且必须强制要求 **JSON** 输出。

### Step 4: 动态注册 (`config/registry.yaml`)
在全局注册表中申明你的 Agent，调度器才能找到它。
```yaml
agents:
  ...
  your_intent_name:
    class: "memory_palace.skills.your_new_skill.skill.YourNewSkill"
```

---

## 3. 质量红线 (Quality Guardrails)

| 检查项 | 工业级要求 |
| :--- | :--- |
| **JSON 防爆** | 必须使用 `llm_client.parse_json` 提取结果，严禁直接 `json.loads`。 |
| **异常处理** | `_execute_impl` 内部必须捕获预期的业务异常，禁止让异常抛出到基类之外。 |
| **安全过滤** | 必须在 Prompt 中包含“安全红线”，严禁输出违反景区安全条例的建议。 |
| **SLA 意识** | 核心逻辑执行耗时（含 LLM 推理）不得超过 20 秒。 |

---

## 4. 自动化测试要求

新增 Agent 必须配套以下两类测试，否则不予合并入 `main` 分支：

1.  **单元测试 (`tests/unit/`)**: 模拟不同的 LLM 返回，验证 `skill.py` 里的业务逻辑分支（if/else）是否覆盖。
2.  **集成测试 (`tests/integration/`)**: 验证从 `Orchestrator` 到该 Agent 的调用链路是否畅通。

---

## 5. 常见问题 (FAQ)

**Q: 我的 Agent 需要调用数据库怎么办？**
A: 请在 `skill.py` 中引入 `memory_palace.knowledge.db_client` 中的 DAO 方法，严禁在 Skill 层直接写原生 SQL。

**Q: 多个 Agent 之间如何传递数据？**
A: 通过 `context` 字典。`Orchestrator` 会在 Agent 切换时保留上下文。

---
<div align="center">
  <p>Memory Palace OS - 让 AI 像专家一样思考与执行</p>
</div>