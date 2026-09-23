# 审查修复与角色模拟验收

## Why

现有建议运行缺少可靠恢复，配置和部署边界存在冲突；正式角色模拟执行器仅覆盖最初三步，证据封包还不能保证完整验收。用户已确认通过自动化角色操作完成真实业务旅程，按证据提升就绪状态。代码存在、页面可打开和单次演示成功均不足以证明内部验收就绪。

## What Changes

- 修复证据完整性、秘密管理、代理信任、建议运行恢复和运行时选择。
- 统一构建启动，扩展现有执行器至 17 条主旅程和 13 条故障旅程。
- 补齐主线未覆盖的治理功能、四入口功能等价和隔离备份恢复验收。
- 自动生成并验证注册表候选，目标为 34 项 READY、3 项已验证禁用、30 条旅程 READY。
- 交付 9 份可分别实施与验收的规格；任务完成状态与业务 READY 状态分开。

## Capabilities

### New Capabilities

- `uat-evidence-integrity`：SPEC-01，分阶段证据检查、完整封包与实际测试版本溯源。
- `secure-runtime-boundaries`：SPEC-02，配置严格校验、秘密轮换、代理信任及临时会话隔离。
- `durable-advice-delivery`：SPEC-03，建议运行投递、恢复、终态副作用与 ACK。
- `explicit-advice-runtime`：SPEC-04，Redis 与 Hatchet 的显式选择、就绪和消费者归属。
- `reproducible-source-delivery`：SPEC-05，Python/Node/pnpm、离线契约导出与源码交付。
- `role-simulated-main-journey`：SPEC-06，独立角色执行事件到经验复用与 App 重启的连续旅程。
- `role-simulated-failure-journeys`：SPEC-07，十三条故障旅程及恢复证据。
- `complete-internal-acceptance`：SPEC-08，治理补充、四入口、备份恢复与覆盖矩阵。
- `evidence-driven-readiness`：SPEC-09，注册表候选、动态就绪、禁用例外与内部验收报告。

### Modified Capabilities

无已合并的主规格需要直接替换。本变更补充既有事件处置、Agent 主干与企业就绪契约；既有 change 的历史规格不作为当前通过证据。

## Impact

影响建议队列与状态机、应用生命周期、代理与部署配置、依赖工具链、验收执行器、证据校验和功能注册表。复用现有正式接口、IncidentCommand 和业务事实源；不增加第二套业务后端，不扩展模型或向量技术栈。

## Authority

依据已确认的审查修复计划、企业 MVP PRD、统一员工助手 PRD、领域词汇表，以及 ADR-0018～0023。当前采用 PostgreSQL、Redis Streams、pgvector、1024 维 bge-m3 与 deepseek-flash。ADR-0023 允许角色模拟内部验收；ADR-0022 的视觉签收、切流与退场门禁继续有效。发布规格不表示实施完成或客户签收。
