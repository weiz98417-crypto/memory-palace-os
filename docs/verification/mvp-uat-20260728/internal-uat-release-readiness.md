# Memory Palace OS 内部 UAT 发布就绪报告

> **Status: superseded (历史快照)** — 本文件记录的 ChromaDB / 1536 维 embedding 与旧四层架构描述，已被 ADR-0007（PostgreSQL pgvector 为唯一向量后端）、ADR-0018（Agent 链为景区事件主干）与 ADR-0019（Agent 运行时技术栈）取代。内容仅作历史证据保留，不是当前实现或实施依据。


> **发布判定：内部 UAT 发布候选（Internal UAT Release Candidate）。**
>
> 本判定只允许继续内部演示、内部验收和发布候选封版准备，**不代表客户可正式交付、生产可上线或企业 MVP 已完成签收**。运行时功能注册表的 `release_gate_passed=true` 是当前 UAT 环境的机器门禁结果，不替代客户 UAT、干净可追溯构建、24 小时连续运行、性能验收或合同约定的外部渠道验收。

## 1. 审计范围与当前基线

| 项目 | 核验结果 | 说明 / 证据 |
|---|---|---|
| 正式客户端 | 可访问 | `http://localhost:8082/admin/`，客户端包含 13 个正式产品视图；旧 `/demo` 不属于交付入口。 |
| 正式 UAT 栈 | 健康 | Compose project 为 `memory-palace-uat`；App、Nginx、PostgreSQL、Redis、ChromaDB 当前健康。 |
| App 镜像 | 已运行，但不可作为客户正式构建 | 镜像 ID `sha256:a2ff9dc1aba5afa9b353c5cc852ecea8899d3f489edde2ca9d867cff20bb9682`；标签 `memory-palace-uat-app:cb55e244f0f2-dirty`。`dirty` 明确表示来源工作树非干净状态。 |
| 运维入口 | PASS | `scripts\mvp.cmd start` 与 `scripts\mvp.cmd verify` 已在当前 UAT 栈通过；命令与门禁定义见 [Windows Docker 运维手册](../../operations/mvp-windows-docker.md)。 |
| PRD 基线 | 已批准实施基线，内部验收中 | 权威需求源为 [企业 MVP PRD](../../../PRD-memory-palace-enterprise-mvp.md)，本报告按 7.15、7.16 与 8.1 判定。 |
| 本报告可声明范围 | 仅内部 UAT 发布候选 | 客户发布仍为 `NO-GO`，剩余条件见第 8 节。 |

## 2. PRD 7.15 功能完整性门禁

当前正式 API 的运行时功能注册表快照如下：

| 门禁项 | 当前结果 | 判定 |
|---|---:|---|
| 注册项总数 | 37 | 已覆盖当前 MVP 注册范围。 |
| `READY` | 34 | 包含 20/20 客户业务功能、8/8 Agent、平台能力与 DeepSeek。 |
| `DISABLED_REQUIRES_CONFIG` | 3 | 企业微信、短信、语音电话；入口安全禁用且不返回假成功。 |
| 客户业务功能 | 20/20 `READY` | 满足注册表的可见业务功能覆盖门禁。 |
| 注册 Agent | 8/8 `READY` | 所有 Agent 均有运行时证据并通过当前机器门禁。 |
| UAT 旅程 | 10/10 `READY` | MVP-UAT-001 至 MVP-UAT-010 均已进入运行时证据聚合。 |
| DeepSeek | `READY` | 生成式调用固定为 `deepseek-v4-flash`，并保存真实调用及故障恢复证据。 |
| 证据采集错误 | `collection_errors=[]` | 当前注册表聚合未报告证据采集错误。 |
| 机器发布门禁 | `release_gate_passed=true` | 仅表示当前内部 UAT 环境的机器门禁通过。 |

对 PRD 7.15 的结论是：**运行时功能注册表门禁通过，但发布包尚未完成客户级封版**。以下两项在本轮并行执行，不能以旧报告替代：

- **全量自动化回归：待本轮回填。** 需回填 PowerShell 运维套件、`tests/unit/test_mvp_operations_script.py`、完整 `pytest` 及三个 UAT runner 的 `node --check` 最终结果。
- **13 视图最终浏览器 QA：待本轮回填。** 需更新最终分数、控制台健康、交互回归和问题关闭情况；现有 88 分报告仅是修复前基线。

## 3. PRD 7.16 发布阻断条件复核

| 阻断类别 | 当前内部证据 | 状态 |
|---|---|---|
| 正式客户端无法完成端到端业务 | 10 条 UAT 旅程均有正式客户端与运行时证据；会话独立生命周期已实跑。 | 内部门禁通过 |
| 可见按钮无真实后端行为 | 业务、审批、动作、任务、知识、Persona、Watcher、SOP 等均有 API、状态、审计或 trace 证据；最终 13 视图交互复验待本轮回填。 | 条件通过 |
| AI 使用硬编码、假模型或错误模型 | TodoWrite、Agent 链路与故障恢复证据记录 `deepseek-v4-flash`、真实调用状态及非 Mock 标志。 | 通过 |
| 数据服务被静默替换 | 当前正式 Compose 使用 PostgreSQL、Redis 与 ChromaDB；备份、独立恢复、队列死信和知识检索均有证据。 | 通过 |
| 刷新或 App 重启丢失状态 | 会话刷新后保持关闭状态，App 处理中重启可恢复且有重复执行保护。 | 通过 |
| 前端硬编码登录 | 三角色服务端登录、密码重置、旧密码 401、角色菜单与 API 权限均已验收。 | 通过 |
| 租户隔离缺失 | 双向租户边界、越权读取/修改、非法路径与拒绝审计已验收。 | 通过 |
| 审批、通知、删除或配置变更缺少审计 | 审批批准/拒绝、站内投递/采纳、用户与设置生命周期、Persona 删除等均保留审计或 trace。 | 通过 |
| 未配置渠道返回成功 | 企业微信、短信与语音电话均为 `DISABLED_REQUIRES_CONFIG`，正式客户端显示缺项并禁用动作。 | 通过 |
| API Key 进入仓库、镜像层、日志、页面或交付材料 | 当前 EnvFile 位于仓库外且不含 DeepSeek Key；Key 由外部 Docker volume 持久化并只读挂载。本报告不包含任何凭据值。 | 当前 UAT 配置通过 |
| 迁移、备份或恢复未验证 | `mvp.cmd verify` 已通过，备份 v2 与独立恢复旅程已验收。 | 通过 |
| 依赖开发人员手改数据库 | 正式运维 CLI 提供安装、迁移、验证、备份、恢复和升级路径。 | 通过 |
| 存在未关闭 P0 | 修复前浏览器基线记录 `Critical=0`，但有两个 High 与后续回归项；最终缺陷级别与关闭状态待本轮 QA 回填。 | 待最终 QA 确认 |

因此，本轮没有证据支持把版本描述成“客户正式可交付”。当前最准确的表述仍是：**内部 UAT 发布候选；客户发布阻断条件尚未全部解除。**

## 4. PRD 8.1 发布策略符合性

PRD 8.1 要求按“功能冻结 → 恢复正式产品 → 打通主链 → 补齐全部功能 → 完成交付”推进，并且只能按退出条件放行，不能按工期跳过真实链路、恢复、安全或 UAT。

当前已达到的内部阶段条件：

- 正式客户端、正式 API、真实数据服务与 `deepseek-v4-flash` 主链已贯通。
- 20/20 业务功能、8/8 Agent 和 10/10 UAT 在当前运行时注册表中已通过机器门禁。
- 认证、角色、租户隔离、审计、失败恢复、备份恢复与安全禁用已有内部证据。
- 运维 CLI 的启动和部署验证门禁已通过。

尚未达到的客户交付阶段条件：

- 当前镜像来自脏工作树，不具备客户发布所需的源码提交、构建记录与不可变镜像追溯链。
- 客户尚未在目标环境独立完成 UAT 并签收。
- 24 小时连续运行与性能验收尚未完成。
- 合同要求启用的外部渠道尚需对应供应商或客户沙箱验收。

结论：**符合 PRD 8.1 的阶段放行原则，可进入内部 UAT 发布候选收口；不得跨过剩余退出条件直接宣布企业 MVP 已交付。**

## 5. UAT 证据索引

| UAT | 已核验证据 | 内部结果 |
|---|---|---|
| MVP-UAT-001 登录、角色与工作台 | [三角色、管理生命周期与权限证据](./evidence/MVP-UAT-001-role-workspaces.json) | PASS |
| MVP-UAT-002 现场事件智能受理 | [实时事件链](./evidence/MVP-UAT-002-live-event.json)、[MemoryOps Live](./evidence/MVP-UAT-002-memory-ops-live.json)、[会话独立生命周期](./evidence/MVP-UAT-002-session-lifecycle.json) | PASS |
| MVP-UAT-003 历史补录与记忆检索 | [历史事件证据](./evidence/MVP-UAT-003-history-event.json) | PASS |
| MVP-UAT-004 任务、审批与动作执行 | [TodoWrite 拆解](./evidence/MVP-UAT-004-todo-decompose.json)、[任务生命周期](./evidence/MVP-UAT-004-todo-lifecycle.json)、[审批决定](./evidence/MVP-UAT-004-approval-decisions.json)、[推送采纳](./evidence/MVP-UAT-004-push-adoption.json) | PASS |
| MVP-UAT-005 事件闭环、知识与 SOP | [事件关闭](./evidence/MVP-UAT-005-event-close.json)、[知识与 SOP 生命周期](./evidence/MVP-UAT-005-knowledge-sop.json) | PASS |
| MVP-UAT-006 数字分身完整生命周期 | [Persona 生命周期](./evidence/MVP-UAT-006-persona-lifecycle.json) | PASS |
| MVP-UAT-007 Watcher 巡检闭环 | [Watcher 生命周期](./evidence/MVP-UAT-007-watcher-lifecycle.json) | PASS |
| MVP-UAT-008 重启、失败与恢复 | [App 重启恢复](./evidence/MVP-UAT-008-app-restart-recovery.json)、[备份恢复](./evidence/MVP-UAT-008-backup-restore.json)、[死信恢复](./evidence/MVP-UAT-008-dead-letter-recovery.json)、[运行时热重载](./evidence/MVP-UAT-008-runtime-reload.json) | PASS |
| MVP-UAT-009 多租户与安全边界 | [租户与认证授权证据](./evidence/MVP-UAT-009-tenant-authz.json) | PASS |
| MVP-UAT-010 DeepSeek 与外部依赖降级 | [外部集成安全禁用](./evidence/MVP-UAT-010-integrations.json)、[DeepSeek 故障恢复](./evidence/MVP-UAT-010-llm-failure-recovery.json) | PASS |

会话生命周期证据额外包含 6 张正式客户端截图：

- [创建前](./screenshots/session-01-before-create-1440x900.png)
- [列表与详情](./screenshots/session-02-list-and-detail-1440x900.png)
- [租户边界](./screenshots/session-03-tenant-boundary-1440x900.png)
- [关闭确认](./screenshots/session-04-close-confirmation-1440x900.png)
- [关闭完成](./screenshots/session-05-closed-1440x900.png)
- [刷新后仍关闭](./screenshots/session-06-closed-after-refresh-1440x900.png)

## 6. 证据资产与文档完整性

本次静态盘点结果：

- `docs/verification/mvp-uat-20260728/evidence/` 中共有 **36 份 JSON**，使用显式 UTF-8 解析，**0 份解析失败**。
- 本报告写入时，`docs/verification/mvp-uat-20260728/screenshots/` 中共有 **110 张 PNG**，全部可读取且分辨率为 **1440×900**。
- JSON 中共有 33 个去重后的截图引用，**0 个缺失引用**；其余截图是补充 QA、问题复现或回归过程资产，不将其误计为机器注册表证据。
- MVP-UAT-001 至 MVP-UAT-010 均至少有一份以 `uat_id` 归档的 JSON；其中 MVP-UAT-002 的会话旅程包含创建、列表、详情、关闭、刷新持久化、租户拒绝与审计证据。

关键报告、runner 与运维文档均存在：

- [浏览器 QA 索引](./browser-qa-report.md)
- [浏览器 UAT runner](./uat_browser_runner.cjs)
- [RBAC UAT runner](./uat_rbac_runner.cjs)
- [运维 UAT runner](./uat_operations_runner.cjs)
- [Windows Docker 运维手册](../../operations/mvp-windows-docker.md)
- [备份恢复与诊断手册](../../operations/mvp-backup-restore.md)

现有浏览器基线位于 `.gstack/qa-reports/qa-report-localhost-8082-2026-07-28.md`，记录 13 视图、88/100、`Critical=0`，同时记录两个 High、一个 Medium 和一个 Low。该报告是问题修复前的基线，**不是本轮最终发布 QA 结论**；修复证据已存在，但必须由本轮最终 13 视图 QA 重新定级并回填。

## 7. 运维、配置与 Secret 边界

- 持久 EnvFile 位于 `C:\Users\Admin\AppData\Local\MemoryPalaceOS\memory-palace-uat.env`，在仓库目录之外。
- EnvFile ACL 当前只显式允许本机 `Admin` 账户读写，文件不包含 `DEEPSEEK_API_KEY`。
- `docker compose --env-file <外置 EnvFile> -f deploy/docker-compose.yml config --quiet` 已通过。
- DeepSeek Key 持久化在外部 Docker volume `memory-palace-secrets`，当前 App 以只读方式挂载到 `/run/memory-palace-secrets`；重新创建容器不需要把 Key 写回仓库或镜像层。
- 运维命令与安全模型见 [Windows Docker 运维手册](../../operations/mvp-windows-docker.md)；备份 v2、覆盖保护、独立恢复与升级回退见 [备份恢复与诊断手册](../../operations/mvp-backup-restore.md)。
- 本报告不记录 API Key、密码、JWT、Token 或任何其他凭据值。

## 8. 发布决定与剩余门槛

### 允许的声明

> **Memory Palace OS 当前达到“内部 UAT 发布候选”水平：正式客户端、真实 Agent/DeepSeek 链路、认证与租户边界、数据恢复、运维入口和 10 条 UAT 旅程已形成内部验收证据。**

### 不允许的声明

以下表述目前均不成立：

- “客户可正式交付”
- “生产可上线”
- “企业 MVP 已完成客户签收”
- “外部渠道已全部可用”

### 客户发布仍需完成

1. **干净、可追溯构建。** 从干净工作树和明确提交构建不可变镜像，记录源码版本、构建结果、镜像 digest、迁移版本与发布说明；按安全流程完成交付凭据轮换，并重新执行 `start/verify` 与证据聚合。
2. **客户 UAT 签收。** 由客户目标角色在目标环境独立完成 MVP-UAT-001～010，保存实际结果、截图、trace、审计记录与签收结论；开发团队内部 UAT 不能替代客户签收。
3. **24 小时 soak 与性能验收。** 完成至少 24 小时连续运行、资源趋势、队列堆积、错误率、恢复能力及 PRD 性能指标报告。
4. **按合同需要完成渠道沙箱。** 若合同范围包含企业微信、短信或语音，必须使用供应商/客户沙箱完成真实发送验收后才能改为 `READY`；若合同不包含，必须在交付范围和限制清单中明确保持安全禁用。

### 本轮封版前待回填

| 项目 | 状态 | 必须回填内容 |
|---|---|---|
| 全量自动化测试 | **待本轮回填** | PowerShell 运维套件、Python 运维测试、完整 `pytest`、三个 runner `node --check` 的命令、通过/失败数与失败说明。 |
| 13 视图最终浏览器 QA | **待本轮回填** | 最新报告路径、最终分数、13/13 视图结果、控制台/网络错误、旧 High/Medium/Low 问题的关闭或接受结论。 |
| Graphify 与发布文档一致性 | **待本轮回填** | Graphify 更新结果及 README、PRD、OpenSpec、客户端、API、注册表名称一致性复核结论。 |

在上述本轮回填完成且无新增 P0 后，可以冻结为内部 UAT 发布候选；只有第 8 节“客户发布仍需完成”的四项全部满足，才可重新评估客户正式交付。
