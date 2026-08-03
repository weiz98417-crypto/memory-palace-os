# Memory Palace OS 统一员工助手差距执行计划

> 文档状态：待执行  
> 制定日期：2026-08-03  
> 适用范围：统一员工助手、企微模拟器、管理后台、经验资产闭环及正式 UAT  
> 验收基线：[统一员工助手与经验资产企业 MVP PRD](../../PRD-memory-palace-unified-agent-experience-mvp.md)、[页面地图](./unified-agent-page-map.md)、[完整演示旅程与可执行 UAT](./unified-agent-demo-journey.md)  
> 代码事实基线：[Graphify 报告](../../graphify-out/GRAPH_REPORT.md)、[功能注册表](../../src/memory_palace/config/feature_registry.yaml)

## 1. 结论

三份目标文档目前尚未全部达到要求。

当前代码已经具备统一入口、正式消息处理、任务工作流、审批、Watcher、经验访谈与发布等大量基础能力；但“存在代码和局部自动化测试”不等于“完整旅程已验收”。截至本计划制定时：

- `E2E-00` 至 `E2E-16` 在功能注册表中仍全部为 `BLOCKED`，且 `evidence: []`。
- `UAT-F01` 至 `UAT-F13` 仍全部为 `BLOCKED`，且 `evidence: []`。
- 正式证据目录 `docs/verification/unified-agent-uat/<uat_run_id>/` 尚不存在。
- 当前 PostgreSQL 业务样本没有形成同一个 `uat_run_id` 下从上报到复用、审计和 App 重启恢复的连续链路。
- 页面地图要求的全部角色、稳定 URL、页面状态、跳转、可读性与响应式尺寸尚无统一验收矩阵和证据包。

因此后续目标不是重新实现整套系统，而是按连续业务链补齐真实数据、发现并修复阻断点、完成页面门禁，并生成可复核的正式证据。

## 2. 固定技术基线

本计划固定以下架构口径，执行期间不得自行替换：

| 能力 | 正式组件 | 权威边界 | 验收要求 |
|---|---|---|---|
| 业务数据 | PostgreSQL | 用户、会话、消息、事件、任务、审批、访谈、经验、审计等正式记录 | 所有正式验收断言均基于 PostgreSQL 及正式 HTTP API |
| 消息队列与恢复 | Redis Streams | 入队、Consumer Group、pending、claim、ACK 与死信恢复 | `E2E-16`、`UAT-F02` 必须保留真实 Redis 状态证据 |
| 向量索引 | ChromaDB | 已发布知识与经验的向量检索 | 发布状态、`vector_doc_id`、当前版本和检索命中必须一致 |
| 生成式能力 | DeepSeek `deepseek-v4-flash` | 8 个 Agent 的生成式步骤 | 成功旅程必须为真实调用，`is_mock = false` |
| 页面入口 | `/assistant/`、`/simulator/wecom/`、`/admin/` | 三个入口共享正式 API、业务资源和审计链 | 不得使用动画 Demo、固定 JSON 或前端硬编码结果 |

### 2.1 明确排除项

- 不新增、修复、复核或迁移任何 SQLite 实现与 SQLite 专属测试。
- 不把 SQLite 测试结果作为本计划任务的完成门禁。
- 不执行 pgvector 迁移；向量能力继续使用 ChromaDB。
- 不清空 PostgreSQL、Redis 或 ChromaDB 数据卷，不用删除失败记录制造干净结果。
- 不通过数据库手工更新、Swagger 或临时脚本推进业务状态。
- UAT 脚本只能准备主数据、驱动正式 HTTP/UI、采集只读证据和执行受控故障注入。

## 3. 当前状态快照

### 3.1 Graphify

2026-08-03 已完成 Graphify 更新：

- 构建基线：`3e5b08d3`
- 370 个文件、4,708 个节点、10,959 条边、260 个社区
- `diagnose multigraph` 未发现缺失端点、悬空边或重复边
- 新增经验资产后端和企微模拟器实现已进入图谱

Graphify 证明当前代码图谱已经刷新，不代表目标旅程已经通过业务验收。

### 3.2 已存在的主要实现证据

| 范围 | 当前实现证据 | 当前判断 |
|---|---|---|
| 员工入口 | `static/assistant/`、`api/v1/endpoints/assistant.py` | 正式 API 驱动的员工工作面已存在，需连续 UAT 和页面门禁 |
| 企微模拟器 | `static/simulator/wecom/`、`api/v1/endpoints/channels.py` | 已走 Canonical Ingress 和服务端身份，需完整旅程与权限实测 |
| 任务与闭环 | `api/v1/endpoints/workflows.py`、`core/task_graph.py` | 分解、依赖、完成、关闭门禁和经验候选路径已存在，需真实四任务链验证 |
| 审批与动作 | `core/permissions.py`、受控动作与 outbox 相关实现 | 并发终态、拒绝、批准与模拟器送达已有测试基础，需连续故事证据 |
| Watcher | `core/watcher_runtime.py`、`api/v1/endpoints/watcher.py` | 事件检查、策略、run、finding 和去重路径已存在，当前样本无 run |
| 经验资产 | `api/v1/endpoints/experiences.py`、`knowledge/vector_store.py` | 访谈、确认、审核、退回、版本、发布和 Chroma 索引路径已存在，尚未完成正式发布旅程 |
| 恢复 | `core/runtime_recovery.py`、`core/redis_queue.py` | 启动恢复及 pending/claim/ACK 代码和自动化测试已存在，尚无真实 App 重启 UAT 证据 |

### 3.3 当前 PostgreSQL 业务样本

2026-08-03 的只读快照显示：

| 对象 | 当前状态 | 与目标的差距 |
|---|---|---|
| 事件 `SJ-20260731-46AE854D` | `OPEN / P1` | 未完成闭环、Watcher 和经验候选 |
| 关联任务 | 1 项，`DONE` | 目标要求四项有序依赖任务及结构化结果 |
| 审批 | 一张 `REJECTED / NOT_EXECUTED`，一张 `APPROVED / SUCCEEDED` | 状态存在，但尚未证明属于同一完整 UAT 旅程及模拟器唯一送达 |
| Watcher run | 0 | `E2E-11` 未执行 |
| 经验候选 | 0 | `E2E-12` 未形成 |
| 访谈 `FT-20260803-B81D` | `COMPLETED`，4 轮回答 | `E2E-13` 核心数据基本具备，但缺正式证据和连续来源链 |
| 经验卡 `JY-20260803-EF40` | `EXPERT_CONFIRMED / v2` | 尚未完成退回、复审、发布与 Chroma 一致性 |
| PersonaExtract 调用 | `deepseek-v4-flash / SUCCEEDED / is_mock=false` | 只证明单个 Agent 调用，不等于 8 Agent 全链通过 |

这些记录可用于诊断，不作为最终通过证据。最终验收必须使用一个新建、唯一且连续的 `uat_run_id`。

## 4. 差距清单

| 差距 ID | 优先级 | 差距 | 已有事实 | 关闭条件 |
|---|---:|---|---|---|
| GAP-00 | P0 | 没有正式 UAT 证据框架 | 注册表 30 条旅程均无 evidence | 建立证据目录、manifest、逐步断言和自动校验 |
| GAP-01 | P0 | `E2E-00` 至 `E2E-04` 没有同一连续运行证据 | 入口与 API 已存在 | 从身份到事件补充只产生一个事件，四 Agent 均有真实调用证据 |
| GAP-02 | P0 | 目标四任务图没有在当前故事中形成 | 当前样本只有一项任务 | 四任务、三条依赖、负责人、结构化结果和幂等均通过 |
| GAP-03 | P0 | 审批拒绝、补证、重提、批准、唯一送达未形成连续证据 | 当前有两张终态审批 | 在同一事件中完成两轮审批并证明未重复执行或发送 |
| GAP-04 | P0 | 闭环前门禁和 Watcher 未跑通 | 事件仍 OPEN、Watcher run 为 0 | 先拒绝关闭，再成功 Watcher，最后关闭事件 |
| GAP-05 | P0 | 事件关闭未生成经验候选 | 当前候选为 0 | 事件关闭成功，候选为 DRAFT，失败可重试且不回滚事件 |
| GAP-06 | P0 | 专家访谈未纳入正式连续旅程 | 已有独立完成访谈与确认卡 | 访谈来源于本次事件，刷新/恢复、4 轮回答和确认均有证据 |
| GAP-07 | P0 | 审核退回、修订、复审、发布未完成 | 卡片停在 `EXPERT_CONFIRMED / v2` | 完整状态机、不可变版本、审核意见和 Chroma 当前索引一致 |
| GAP-08 | P0 | 第二名员工没有真实命中新发布经验 | 无 published version 和向量记录 | 周琪的新问题同时命中新经验与 SOP，并保存引用和采用日志 |
| GAP-09 | P0 | 管理员无法用正式证据证明 8 Agent 全链 | 只有局部 Agent 记录 | 单一业务编号可进入完整时间线，8 Agent 和 DeepSeek 证据齐全 |
| GAP-10 | P0 | 没有真实 App 重启恢复证据 | 只有代码和自动化测试基础 | 进程/容器 ID 变化，Redis pending 被 claim 并 ACK，业务结果唯一 |
| GAP-11 | P1 | 页面地图门禁未逐页验证 | 页面已大量实现，无统一矩阵 | EA-01～06、AD-01～16 和模拟器按角色、状态、尺寸全部留证 |
| GAP-12 | P1 | 13 条失败旅程未执行 | 注册表全部 BLOCKED | UAT-F01～13 分别保留失败、恢复和最终成功证据 |
| GAP-13 | P1 | 注册表状态与实现进度脱节 | 全部 BLOCKED/evidence 空 | 只根据本次证据包逐条更新状态与 evidence 路径 |

## 5. 执行原则

1. **先证据合同，后跑旅程。** 每一步开始前确定输入、预期、业务编号、API、数据库断言、截图和失败保留方式。
2. **先复用现有实现，后修阻断点。** 任务默认先执行正式 HTTP/UI；只有出现可复现失败才修改代码，并补 PostgreSQL 路径测试。
3. **连续故事优先。** `E2E-01` 至 `E2E-16` 使用同一个组织、同一个旅程和可追溯的业务关联，不能拼接旧记录。
4. **正式 API 推进状态。** PostgreSQL 查询只用于只读核对，不得直接改状态。
5. **失败记录不清理。** 重跑产生新的 `uat_run_id`，旧失败包保留。
6. **READY 必须有证据。** 单元测试、代码存在、截图或数据库单点记录均不能单独把功能改为 READY。
7. **修复不碰 SQLite。** 若现有 SQLite 测试失败但 PostgreSQL 正式路径不受影响，记录为本计划范围外，不为其修改生产代码。

## 6. 工作包与任务

### W0：验收合同和执行骨架

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应目标 |
|---|---|---|---|---|---|
| UA-000 | 固化本计划的运行基线 | 无 | 三份目标文档、本计划 | 明确 PostgreSQL + Redis + ChromaDB + DeepSeek；明确排除 SQLite 和 pgvector | 全局 |
| UA-001 | 建立 `uat_run_id` 证据生成器 | UA-000 | `scripts/unified_agent_uat/`、`docs/verification/unified-agent-uat/` | 创建规范目录、manifest、步骤结果、脱敏器和失败保留机制；不创建业务过程数据 | GAP-00 |
| UA-002 | 建立证据完整性校验器 | UA-001 | `scripts/unified_agent_uat/validate_evidence.*` | 能检查缺文件、空 ID、空引用、Mock 模型、敏感字段和越级 READY | GAP-00、GAP-13 |
| UA-003 | 准备主数据并保存基线快照 | UA-001 | 正式管理 API、UAT 配置说明 | 仅创建组织、场地、7 名角色、身份映射、SOP 和审批规则；证明业务过程数据不存在 | E2E 起始条件 |

### W1：统一入口、消息和事件

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-100 | 运行配置和渠道真实性门禁 | UA-003 | `management.py`、诊断与渠道页面 | App、PostgreSQL、Redis、ChromaDB、Worker、8 Agent、DeepSeek 状态可读；模拟器与真实企微状态不混淆 | E2E-00 |
| UA-101 | 服务端身份与会话恢复 | UA-100 | `channels.py`、模拟器前端、鉴权实现 | 李明身份由服务端绑定；篡改 user/venue 被拒；刷新恢复同一会话 | E2E-01、UAT-F13 |
| UA-102 | 自由文本、真实附件和消息幂等 | UA-101 | Canonical Ingress、附件 API、Queue、模拟器 | 一次输入只生成一条消息和一个 run；附件元数据可恢复；状态经过 QUEUED/PROCESSING/COMPLETED | E2E-02、UAT-F01 |
| UA-103 | 四 Agent 受理和带依据事件卡 | UA-102 | Orchestrator、ContextTrigger、Router、MemoryOps、Commander、Chroma 检索 | 生成一个 P1 事件，命中 SOP、诚实说明无精确经验；四 Agent 均为真实 DeepSeek | E2E-03 |
| UA-104 | 同会话补充并更新原事件 | UA-103 | 消息入口、事件关联和时间线 | 第二轮消息追加到原事件；事件总数仍为 1；跨租户补充被拒 | E2E-04、UAT-F10 |

### W2：任务图、审批与通知

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-200 | 生成并原子激活四任务图 | UA-104 | `workflows.py`、`task_graph.py`、TodoWrite、事件详情 | 四项任务、三条依赖、负责人和业务编号一致；无 STAGED 残留；重复请求不重复创建 | E2E-05、UAT-F01 |
| UA-201 | 员工任务权限、依赖和结构化结果 | UA-200 | `assistant.py`、任务 API、员工/模拟器任务卡 | 先 409 拒绝，再按依赖解锁；结果含字段、单位、附件、提交人和时间 | E2E-06、UAT-F05 |
| UA-202 | 高风险动作与首次真实拒绝 | UA-201 | Permission Engine、审批 API、审批页 | 审批前无工具执行；第一张审批 REJECTED/NOT_EXECUTED，拒绝意见与补证要求可追溯 | E2E-07、E2E-08 |
| UA-203 | 补证、重提、批准和唯一模拟器送达 | UA-202 | 审批、工具执行、outbox、模拟器 | 第二张审批 APPROVED/SUCCEEDED；supersedes 关系存在；每个收件人只有一条模拟器通知 | E2E-08、E2E-09、UAT-F06 |

### W3：Watcher、闭环与经验候选

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-300 | 验证事件关闭服务端门禁 | UA-203 | `workflows.py`、事件详情 | 任务 4 完成前关闭返回冲突并留审计；完成后才显示具备闭环条件 | E2E-10 |
| UA-301 | 执行事件级 Watcher | UA-300 | `watcher_runtime.py`、`watcher.py`、Watcher 页面 | 产生真实 run、目标快照和 DeepSeek 记录；完整故事 finding 为 0；重复运行仍为 0 | E2E-11、UAT-F09 |
| UA-302 | 关闭事件并创建可重试候选 | UA-301 | `workflows.py`、经验候选实现、事件卷宗 | 事件 CLOSED 且不可继续修改；候选为 DRAFT 且不可检索；候选失败不回滚事件 | E2E-12 |

### W4：访谈、治理与 Chroma 发布

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-400 | 从本次候选发起专家访谈 | UA-302 | `experiences.py`、员工和模拟器经验页面 | 张建国从统一助手接受访谈；来源事件、授权和范围完整 | E2E-13 |
| UA-401 | 完成四轮访谈、恢复和专家确认 | UA-400 | PersonaExtract、访谈持久化、经验卡 UI | 四轮回答可追溯；刷新或 App 重启恢复；重复回答不重复；卡为 EXPERT_CONFIRMED | E2E-13、UAT-F07 |
| UA-402 | 完整执行退回、修订和复审 | UA-401 | 经验审核 API、版本表、管理/员工页面 | 执行 `EXPERT_CONFIRMED -> IN_REVIEW -> DRAFT -> EXPERT_CONFIRMED -> IN_REVIEW`；旧版本不可变 | E2E-14 |
| UA-403 | 发布经验并校验 Chroma 一致性 | UA-402 | `experiences.py`、`vector_store.py`、经验管理页面 | PostgreSQL 为 PUBLISHED，发布版本和 `vector_doc_id` 非空；Chroma 只有一个当前有效版本；索引失败不假成功 | E2E-14、UAT-F08 |

### W5：经验复用和全链审计

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-500 | 第二名员工真实复用新经验 | UA-403 | 消息处理、MemoryOps、Persona、引用卡 | 周琪的新输入同时命中新经验和 SOP；引用含 ID、标题、版本、来源、范围和相关性；有采用日志 | E2E-15 |
| UA-501 | 单一业务编号聚合完整审计 | UA-500 | `trace_timeline.py`、管理 API、审计/Trace 页面 | 管理员无需查库或拼 UUID 即可查看完整链；8 Agent 输入摘要、输出、耗时和真实模型记录齐全 | E2E-15 |

### W6：真实 App 重启恢复

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应旅程 |
|---|---|---|---|---|---|
| UA-600 | 建立固定范围 App 重启操作 | UA-501 | 运维脚本、诊断 API、恢复审计 | 只重启 App，不重启或清空 PostgreSQL、Redis、ChromaDB；记录重启前后进程/容器 ID | E2E-16 |
| UA-601 | 验证 pending → claim → ACK | UA-600 | `redis_queue.py`、`runtime_recovery.py`、Queue Worker | 在 ACK 前重启；原 pending 被回收并完成；一条输入只有一个待办和一个最终结果 | E2E-16、UAT-F02 |
| UA-602 | 验证超时、人工重试与死信边界 | UA-601 | Queue Worker、消息重试 UI、诊断页 | 超时消息明确进入可重试或死信；不会静默丢失、重复生成或伪造成功 | E2E-16、UAT-F02 |

### W7：页面门禁、权限与失败旅程

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应目标 |
|---|---|---|---|---|---|
| UA-700 | 建立 EA/AD 页面验收矩阵 | UA-104、UA-203、UA-302、UA-403、UA-501、UA-602 | 三个前端入口、页面地图 | EA-01～06、模拟器、AD-01～16 均映射路由、角色、API、状态、跳转和证据 | 页面地图 |
| UA-701 | 执行服务端角色与租户矩阵 | UA-700 | 鉴权、各资源 API、审计 | 员工、经理、知识负责人、管理员逐路由核验；隐藏菜单之外服务端同样拒绝越权 | UAT-F10、UAT-F11、UAT-F13 |
| UA-702 | 执行可读性和响应式验收 | UA-700 | 三个前端入口样式和交互 | 覆盖目标桌面/移动尺寸；无技术 ID 主标题、原始 JSON、英文状态、空引用或页面横向溢出 | 页面地图、可读性门禁 |
| UA-710 | 消息幂等与 Redis 恢复失败组 | UA-601 | UAT 驱动和证据采集 | 分别执行重复投递与 ACK 前重启，保留失败和恢复证据 | UAT-F01、F02 |
| UA-711 | DeepSeek 与 Chroma 故障组 | UA-403 | 受控故障注入、模型/向量错误处理 | 超时/401/熔断、检索不可用、发布索引失败均不产生假成功；恢复后真实调用成功 | UAT-F03、UAT-F04、UAT-F08 |
| UA-712 | 工作流状态故障组 | UA-301、UA-401 | 任务、审批、访谈、Watcher | 依赖、并发审批/执行、访谈恢复和 finding 去重分别通过 | UAT-F05、UAT-F06、UAT-F07、UAT-F09 |
| UA-713 | 租户、角色和渠道故障组 | UA-701 | 鉴权、渠道、真实企微入口 | 跨场地、普通员工治理接口、企微未配置和身份无映射均在入队/读取前拒绝并审计 | UAT-F10、UAT-F11、UAT-F12、UAT-F13 |

### W8：单一连续 UAT 和发布判定

| 任务 ID | 任务 | 依赖 | 主要影响文件 | 交付与验收 | 对应目标 |
|---|---|---|---|---|---|
| UA-800 | 执行一次全新连续成功旅程 | UA-702、UA-710、UA-711、UA-712、UA-713 | UAT 驱动、正式 UI/API | 一个新 `uat_run_id` 完整通过 E2E-00～16，不拼接旧数据 | E2E-00～16 |
| UA-801 | 执行独立失败旅程 run | UA-710～UA-713 | UAT 驱动、故障注入 | UAT-F01～13 全部有独立输入、实际结果、恢复和最终状态 | UAT-F01～13 |
| UA-802 | 校验证据包和敏感信息 | UA-800、UA-801 | 证据校验器、execution report | 目录完整、ID 可关联、断言全绿；无 Secret、Token、Cookie、密码、完整 Prompt 或私有附件地址 | 证据规范 |
| UA-803 | 更新功能注册表和 Graphify | UA-802 | `feature_registry.yaml`、`graphify-out/` | 只对有证据的条目改状态和 evidence；重新运行 Graphify 并通过 multigraph 诊断 | 最终门禁 |
| UA-804 | 形成发布/不发布结论 | UA-803 | `execution-report.md` | 明确列出通过、阻断、残余风险和回退方式；任一强制门禁失败则不标 READY | 完成定义 |

## 7. 证据合同

每次运行使用不可复用的 `uat_run_id`，目录至少包含：

```text
docs/verification/unified-agent-uat/<uat_run_id>/
  manifest.json
  execution-report.md
  steps/
    E2E-00.json
    ...
    E2E-16.json
    UAT-F01.json
    ...
    UAT-F13.json
  screenshots/
  api/
  traces/
  db-assertions.json
  llm-calls.json
  chroma-retrieval.json
  queue-recovery.json
  browser-console.json
  evidence-validation.json
```

### 7.1 每步最低字段

每个步骤文件必须记录：

- `uat_run_id`、旅程 ID、开始/结束时间、执行角色和入口。
- 用户输入、预期结果、实际结果和通过状态。
- 人类可读业务编号、关联 `trace_id`、消息 ID 和资源 ID。
- 正式 API 请求摘要与响应摘要，不含鉴权头和 Secret。
- 只读 PostgreSQL 断言、Redis/Chroma 断言和对应截图。
- 若涉及 Agent，记录 provider、model、`is_mock`、状态、耗时和 request ID。
- 若失败，记录失败原因、系统状态、恢复动作和恢复后的结果，不删除原失败证据。

### 7.2 READY 判定规则

某个 E2E 或失败旅程只有同时满足以下条件才可从 `BLOCKED` 更新：

1. 对应步骤文件存在且断言通过。
2. 所引用 API、Trace、数据库、队列、Chroma 和截图证据文件存在。
3. 生成式步骤为 `deepseek-v4-flash` 且 `is_mock = false`。
4. 证据完整性校验通过且无敏感信息。
5. 功能注册表中的 `evidence` 指向本次有效证据，不指向旧 MVP 或其他旅程截图。

## 8. 测试与修复策略

### 8.1 测试层次

| 层次 | 用途 | 是否可宣告 READY |
|---|---|---|
| 单元测试 | 验证状态机、解析、幂等和纯逻辑 | 否 |
| PostgreSQL 集成测试 | 验证正式持久化、事务、租户和并发 | 否，但为代码修复必需门禁 |
| 正式 HTTP 契约测试 | 验证鉴权、API、Redis、Chroma 和数据库的真实组合 | 否，但为 UAT 前置门禁 |
| 浏览器 UAT | 验证角色、业务可读性、操作与页面恢复 | 否，必须与后端证据组合 |
| 连续 E2E + 完整证据包 | 验证最终业务目标 | 是 |

### 8.2 发现阻断问题后的处理顺序

1. 固化最小可复现输入和现有证据。
2. 判断问题属于产品代码、UAT 驱动、主数据还是环境配置。
3. 若为代码问题，先增加 PostgreSQL/正式 HTTP 路径的失败测试，再做最小修复。
4. 运行受影响的局部测试和对应 E2E 步骤。
5. 用新的 `uat_run_id` 重跑受影响的连续旅程；不覆盖旧失败包。
6. 更新差距状态和证据路径，但不提前更新无关 READY 状态。

## 9. 里程碑与停止条件

| 里程碑 | 必须满足 | 不满足时 |
|---|---|---|
| M0 可开始 UAT | UA-001～003 完成，E2E-00 全绿 | 不进入业务旅程 |
| M1 事件可处置 | E2E-01～04 连续通过 | 不创建任务图 |
| M2 动作可执行 | E2E-05～09 连续通过 | 不关闭事件 |
| M3 事件可沉淀 | E2E-10～12 连续通过 | 不开始专家审核 |
| M4 经验可检索 | E2E-13～14 连续通过且 Chroma 一致 | 不执行第二人复用 |
| M5 闭环可解释 | E2E-15 通过、8 Agent 证据齐全 | 不执行最终发布判定 |
| M6 系统可恢复 | E2E-16 与 UAT-F02 通过 | 不标记企业级 READY |
| M7 可发布 | 全部 E2E、失败旅程、页面矩阵和证据校验通过 | 输出不发布结论和阻断清单 |

## 10. 最终完成定义

本计划只有在以下条件全部满足时完成：

- `E2E-00` 至 `E2E-16` 全部通过并有同一连续成功 run 的证据。
- `UAT-F01` 至 `UAT-F13` 全部在独立故障 run 中通过。
- EA-01～06、企微模拟器和 AD-01～16 完成目标角色及响应式验收。
- 8 个 Agent 均有真实 DeepSeek、结构化输出、Trace 和可解释业务作用。
- PostgreSQL 业务状态、Chroma 当前索引和页面引用一致。
- App 重启过程中 PostgreSQL、Redis 和 ChromaDB 未清空，消息只产生一个最终结果。
- 功能注册表所有 READY 状态均有有效 evidence 路径。
- 最终 Graphify 已包含本轮代码和文档变更，并通过图完整性诊断。

在此之前，项目可以描述为“核心实现已具备、正式统一旅程尚未验收”，不能描述为“三份目标文档已经全部达到要求”。
