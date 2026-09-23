# 审查修复规格索引

状态：规格已拆分，实施未开始；ready-for-agent 表示可交接规格，不表示功能 READY。

GitHub 总览：[审查修复与角色模拟验收 #11](https://github.com/weiz98417-crypto/memory-palace-os/issues/11)；9 份规格对应 Issues #2～#10。

依据：[已确认修复计划](../../../docs/product/review-remediation-and-role-uat-plan.md)、[ADR-0023](../../../docs/adr/0023-role-simulated-internal-acceptance.md)和既有领域词汇表。共 9 份规格，沿用正式 API/UI、证据 CLI 与部署命令测试边界。

| ID | 规格 | 原计划 | 最终验收依赖 |
| --- | --- | --- | --- |
| SPEC-01 | [完整证据与封包门禁](specs/uat-evidence-integrity/spec.md) | R0 | 无；优先实施 |
| SPEC-02 | [安全配置与运行入口边界](specs/secure-runtime-boundaries/spec.md) | R1 | 01 合同、05 环境 |
| SPEC-03 | [建议运行持久投递与恢复](specs/durable-advice-delivery/spec.md) | R2 | 01 合同、05 环境 |
| SPEC-04 | [显式建议执行模式与 Hatchet 就绪](specs/explicit-advice-runtime/spec.md) | R2 | 02、03、05 环境 |
| SPEC-05 | [可重复源码构建与启动](specs/reproducible-source-delivery/spec.md) | R3 | 工具链可独立；完整部署集成 02～04 |
| SPEC-06 | [角色模拟连续主旅程](specs/role-simulated-main-journey/spec.md) | R4 | 01～05 |
| SPEC-07 | [十三条故障旅程与恢复验收](specs/role-simulated-failure-journeys/spec.md) | R5 | 01～06 |
| SPEC-08 | [治理、四入口与恢复的完整验收](specs/complete-internal-acceptance/spec.md) | R5 | 01、02、05～07 |
| SPEC-09 | [证据驱动的注册表就绪发布](specs/evidence-driven-readiness/spec.md) | R6 | 01～08 |

表中的“环境”是测试前提，不是要求先完成该规格的全部工作；避免把共同集成验收误当成实现循环依赖。具体顺序见 [设计](design.md) 和 [任务](tasks.md)。

## 验收覆盖

| 范围 | 负责规格 | 成功条件 |
| --- | --- | --- |
| E2E-00～16 | SPEC-06 | 17 步真实角色连续执行，包含第二员工复用与处理中 App 重启 |
| UAT-F01～13 | SPEC-07 | 13 类故障正确拒绝/恢复/去重并保存证据 |
| 全量封包 | SPEC-01 | 完整集合、实质证据、版本与业务关联通过 |
| 20 业务 + 8 Agent + 5 平台 + DeepSeek | SPEC-08/09 | 每项要求可复核，全部满足后 34 项 READY |
| 企业微信、短信、语音 | SPEC-02/07/09 | 3 项保留禁用，安全禁用证据可满足相关旅程 |
| 四入口 | SPEC-05/08 | 源码构建、功能等价、浏览器证据、回滚及独立视觉门禁 |
| 客户、持续运行、容量签收 | 不由规格自动代签 | 报告独立剩余门禁 |

## 交付约束

每份规格包含问题、方案、用户故事、实施决定、测试决定、范围外事项，以及 SHALL 要求和 WHEN/THEN 场景。Implementation Decisions 使用模块与接口语义，不绑定具体源码位置。

此次只编写和发布规格；不轮换秘密、不清理目录、不执行 UAT、不修改功能注册表、不提交或推送代码。GitHub 发布链接另见 [发布索引](issues.md)。
