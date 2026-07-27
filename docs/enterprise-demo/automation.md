# Agent 与自动化边界

| 自动化 | 触发 | 可读输入 | 允许工具面 | 输出契约 | 硬护栏 |
|---|---|---|---|---|---|
| P0 应急链 | Play/Step | 固定事件输入、SOP 引用 | Mock WeCom/SMS/Voice 记录 | 7 个步骤证据 + 报告 | Demo Adapter、状态机、版本检查 |
| 知识问答链 | Play/Step | 固定问题、演示知识引用 | 本地检索证据 | 5 个步骤证据 | 版本化数据、无真实 LLM |
| 经验萃取链 | Play/Step | 固定人物和访谈素材 | 本地 Persona 证据 | 6 个步骤证据 | 无真实个人数据写入 |
| 任务拆解链 | Play/Step | 固定目标和任务图 | 本地任务/设备检查证据 | 6 个成功步骤 + 1 个失败 attempt | 固定失败注入、确定性恢复 |

## Steering 与强制控制

- YAML 中的标题、摘要、引用和工具声明用于演示内容 steering。
- `ScenarioController` 状态机、锁、版本检查、动作优先级和 Demo Adapter 是非提示词硬护栏。
- Agent 证据描述的是系统生成或记录的动作，不把模型建议直接当作已执行的企业操作。
- 所有默认工具调用的 `execution_mode` 必须为 `DEMO_ADAPTER`。

## Kill switch 与恢复

- 页面 Stop 在步骤边界停止当前 run。
- 页面 Reset 清空当前 run 并生成新 trace。
- `demo.cmd stop` 停止整个演示栈并保留数据卷。
- `demo.cmd reset` 删除演示卷并恢复已知初始状态。
