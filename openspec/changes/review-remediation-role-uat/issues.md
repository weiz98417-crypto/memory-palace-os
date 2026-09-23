# 审查修复与角色模拟验收：规格发布索引

状态：9 份规格已发布，均标记 `ready-for-agent`。实施尚未完成，功能注册表未修改。

总览：[GitHub Issue #11](https://github.com/weiz98417-crypto/memory-palace-os/issues/11)。

## 规格与依赖

| 规格 | GitHub Issue | 实施/验收依赖 |
| --- | --- | --- |
| SPEC-01 完整证据与封包门禁 | [#2](https://github.com/weiz98417-crypto/memory-palace-os/issues/2) | 无；优先修复证据门禁 |
| SPEC-02 安全配置与运行入口边界 | [#3](https://github.com/weiz98417-crypto/memory-palace-os/issues/3) | 独立实施；正式验收使用 SPEC-01 合同和 SPEC-05 环境 |
| SPEC-03 建议运行持久投递与恢复 | [#4](https://github.com/weiz98417-crypto/memory-palace-os/issues/4) | 独立实施；正式验收使用 SPEC-01 合同和 SPEC-05 环境 |
| SPEC-04 显式建议执行模式与 Hatchet 就绪 | [#5](https://github.com/weiz98417-crypto/memory-palace-os/issues/5) | 集成依赖 SPEC-03；部署验收依赖 SPEC-02/05 |
| SPEC-05 可重复源码构建与启动 | [#6](https://github.com/weiz98417-crypto/memory-palace-os/issues/6) | 工具链可独立；完整部署集成 SPEC-02～04 |
| SPEC-06 角色模拟连续主旅程 | [#7](https://github.com/weiz98417-crypto/memory-palace-os/issues/7) | SPEC-01～05 |
| SPEC-07 十三条故障旅程与恢复验收 | [#8](https://github.com/weiz98417-crypto/memory-palace-os/issues/8) | SPEC-01～06 |
| SPEC-08 治理、四入口与恢复的完整验收 | [#9](https://github.com/weiz98417-crypto/memory-palace-os/issues/9) | SPEC-01/02/05～07 |
| SPEC-09 证据驱动的注册表就绪发布 | [#10](https://github.com/weiz98417-crypto/memory-palace-os/issues/10) | SPEC-01～08 |

## 执行顺序

1. SPEC-01 优先补齐证据门禁。
2. SPEC-02/03 与 SPEC-05 的工具链部分可分别推进，SPEC-04 集成建议持久化与显式运行模式。
3. 运行环境和安全/恢复修复就绪后，SPEC-06 执行 17 条连续主旅程。
4. SPEC-07 执行 13 条故障旅程，SPEC-08 补齐治理、四入口和隔离备份恢复。
5. SPEC-09 以完整证据、覆盖矩阵和当前运行事实生成并应用注册表候选。

环境前提不等于实施前置：SPEC-02/03 的代码与合同可在完整部署验收前完成，避免把共同集成验收解释为循环依赖。

## 交接检查表

- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/2
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/3
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/4
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/5
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/6
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/7
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/8
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/9
- [ ] https://github.com/weiz98417-crypto/memory-palace-os/issues/10

规格使用已确认的正式 API/UI、证据 CLI 和部署命令作为测试边界；用户故事、实施决定、测试策略及 SHALL/WHEN/THEN 条款包含在各 Issue 正文。

## 完成口径

- 20 个业务、8 个 Agent、5 个平台与 DeepSeek 共 34 项，在各自证据充分后 READY。
- 企业微信保持 DISABLED_BY_POLICY；短信/语音保持 DISABLED_REQUIRES_CONFIG，并验证安全禁用。
- E2E-00～16 和 UAT-F01～13 共 30 条旅程全部通过；预期拒绝或禁用是故障旅程的正确结果。
- 客户签收、24 小时运行、容量、视觉签收与旧入口退场分别记录，不由自动验收代签。
- `ready-for-agent` 表示规格可实施，不代表依赖已满足、业务已验收或客户交付完成。
