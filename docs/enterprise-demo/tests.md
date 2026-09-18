# 企业演示版测试覆盖图

## 已有覆盖

| 规则 | 证据 | 状态 |
|---|---|---|
| 四场景目录、固定输入、步骤和报告契约 | `tests/integration/test_demo_scenarios.py` | 自动化，merge gate 候选 |
| Reset 只影响目标场景，重建 trace | `tests/integration/test_demo_reset.py` | 自动化，merge gate 候选 |
| 失败证据保留、重试恢复、边界动作优先级 | `tests/unit/test_scenario_controller.py` | 自动化，merge gate 候选 |
| 展示延迟不计入业务耗时、步骤超时失败 | `tests/unit/test_scenario_controller.py` | 自动化，merge gate 候选 |
| Demo 模式只暴露企业场景、控制台与健康端点 | `tests/integration/test_demo_scenarios.py` | 自动化，merge gate 候选 |
| 并发 Play 只创建一条执行链 | `test_repeated_play_requests_create_only_one_execution_chain` | 自动化，merge gate 候选 |
| 文件路径和通知客户端回归 | 全量 pytest | 自动化 |
| Play/Pause/Step/Stop/Reset、切场景、下载、全屏、断线重连 | Playwright + Edge 实机浏览器验证 | 手工触发的自动化 QA |
| 服务重启显示 INTERRUPTED、旧快照拒绝、Reset 恢复 | Playwright + Edge 实机浏览器验证 | 手工触发的自动化 QA |
| 1366/1440/1920 与 1179/899 断点 | 验证截图 + overflow/clipping 断言 | 手工触发的自动化 QA |

## 建议新增

| 用例 | 类型 | 预期 |
|---|---|---|
| 将浏览器 QA 驱动固化为仓库测试 | 自动化 E2E | CI 可重复验证所有交互和断点 |
| 真实 PostgreSQL/Redis/pgvector 技术栈 | guarded live | 只在专用测试环境使用临时密钥 |
| 公网反向代理与正式鉴权 | 集成/安全 | 未认证请求拒绝，租户资源隔离 |
| 生产版持久化运行恢复 | 故障注入 | 独立于 V1 的 INTERRUPTED + Reset 契约设计和验收 |

## 缺口

- 当前 CI 配置未显示 `demo.cmd verify` 是主分支强制 gate。
- 默认演示不验证真实渠道发送、密钥轮换、生产 RLS、高可用和灾备。
- 旧模块存在依赖弃用警告，当前不阻断 V1，但升级 FastAPI/Pydantic 前需消除。
