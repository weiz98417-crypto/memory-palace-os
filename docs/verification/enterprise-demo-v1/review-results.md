# Enterprise Demo V1 审阅结果

## 结论

2026-07-27 完成测试、安全和可维护性三路审阅。所有 P1/P2 阻断项已修复并通过聚焦回归、全量测试、live API 验收与浏览器生命周期验证；未保留已知的企业演示版阻断问题。

## 问题闭环

| 审阅问题 | 处理结果 | 验证证据 |
|---|---|---|
| 展示等待被计入业务耗时 | 展示等待移至 Controller 计时区间之外，证据时间由 Controller 覆盖 | 单元测试；浏览器实测 1 ms |
| 步骤无超时保护 | `ScenarioStep.timeout_ms` 默认 3000 ms，执行使用 `asyncio.wait_for` | 超时形成 FAILED 证据测试 |
| 失败边界丢失 Stop/Reset | FAILED 后继续应用排队的 Stop/Reset，Pause 不覆盖失败 | Stop/Reset 参数化并发测试 |
| `IDLE + Stop` 被错误接受 | 从 Stop 合法状态中移除 IDLE | API 409 契约测试 |
| Demo 暴露旧 Admin/Webhook/真实工具路径 | Demo 模式改为路由和 lifespan 白名单，只加载企业场景、控制台和健康检查 | 6 个旧端点 404 自动化与 live 验证 |
| Controller 懒初始化竞态 | 模块加载时单次构造 Controller | 聚焦并发回归 |
| 重启后静默创建新 run | 浏览器保留 run 标识并显示 INTERRUPTED，只允许 Reset 恢复 | Edge + Playwright 容器重启验证 |
| 旧轮询快照覆盖新状态 | 只接受同 run 且 `version >= current.version` 的快照 | 浏览器旧版本注入验证 |
| `verify` 静态打印四场景 PASS | 改为 Reset → Play → 轮询 → 报告校验 → 最终 Reset 的 live API 流程 | `scripts\demo.cmd verify` |
| 报告测试未请求报告端点 | 测试实际读取 `/report` 并断言失败与恢复 attempt | 聚焦集成测试 |
| “状态持久化”能力声明失真 | 改为“进程内状态保留”，明确重启中断边界 | PRD、场景 YAML 与架构文档 |

## 最终门禁

- 聚焦 Demo 回归：22 passed。
- 全量回归：176 passed。
- Demo 模块 Mypy：6 个 source files，无错误。
- 四个 live API 场景：全部 COMPLETED，最终全部回到 IDLE。
- 安全面：旧 Admin、Webhook、旧 Demo、管理静态页、Swagger/OpenAPI 均为 404。
- 运行态：仅 `memory-palace-demo-app-1`，状态 healthy。
