# 审查修复与角色模拟验收计划

状态：范围已确认，实施与真实验收待完成。记录日期：2026-09-22。

本文记录本次 plan-ceo-review / plan-eng-review 后，经 grill-with-docs 确认的修复方案；不是通过报告。已有未提交的 PRD、知识导入脚本和样式修改须保留。当前注册表不因本计划获批而改变状态。

## 1. 已确认的范围

- 优先打通一条完整主线：现场事件 → 有依据建议 → 人工角色决策 → 任务执行 → 审批与内部通知 → 关闭 → 经验审核发布 → 第二名员工复用。
- 不扩展数字分身、多渠道、景区模拟控制或教学产品。现有交付功能仍须逐项验收，不能因为主线收敛而省略注册表要求。
- 技术基线：PostgreSQL 为业务事实源，pgvector + BAAI/bge-m3 1024 维承担检索，Redis Streams 承担持久化队列，生成式模型统一 deepseek-flash。复用 IncidentCommand、现有 Hatchet 与 TEI 实现，不另建 Agent 框架。
- 自动化扮演员工、经理、专家、知识负责人及管理员；角色之间使用独立身份和会话，业务推进走正式 API/UI。数据库查询仅用于核验。
- 先安全与恢复，再完整 UAT，再按证据更新注册表。旧模型、旧向量架构和旧运行记录仅作历史参考。
- 内部验收可由 Codex 执行；客户签收、24 小时运行、容量和视觉签收保留各自门禁，不阻止先完成内部验收。

决策依据：[ADR-0023](../adr/0023-role-simulated-internal-acceptance.md)。术语见根目录 CONTEXT.md。

实施规格：[9 份 OpenSpec 与依赖索引](../../openspec/changes/review-remediation-role-uat/README.md)。规格发布不代表工作包或验收已完成。

## 2. 本轮复核发现

| 事实 | 对实施的影响 |
| --- | --- |
| journey.py 的 SUPPORTED_UAT_STEPS 只有 E2E-00～02 | 还需实现后续 14 个主旅程步骤和 13 个失败旅程，不能直接执行一条已有的“全量命令” |
| EvidenceRun.complete() 只要求至少一条 PASSED | 必须先补全量封包门禁，部分通过不能标记全量完成 |
| validator 允许 model_calls 为空；部分汇总只检查文件存在 | 加上逐步骤模型调用要求及非空、关联一致的实质证据校验 |
| 注册表会用运行时事实重新计算状态 | 只改 YAML 不构成验收完成，必须核对运行时快照 |
| main.py 使用 InMemoryAdviceQueue；AdviceWorker.run_once 正常返回前没有 ACK | 持久队列、数据库状态恢复、最终副作用和 ACK 必须一起修复 |
| 默认 Compose 注入 /tokens/worker，Hatchet 服务在 profile 内 | 修复启用条件并验证默认栈和完整栈两个启动路径 |
| Docker Linux engine 不可连接；本地 .venv 缺 httpx | Live UAT 前先恢复运行环境，当前不能声明任何 Live 通过 |
| BGE 模型缓存存在；OpenAPI 已有 export_openapi.py | 复用模型缓存与离线契约导出，无需新建替代方案 |

前轮 lint/typecheck/Vitest 成功属于当时的检查结果。它们不覆盖本计划实施后的版本；后端完整测试和真实 UAT 仍待运行。

## 3. 工作包与关闭标准

### R0：冻结证据基线和修复验收器

影响：scripts/unified_agent_uat/{evidence,validation,journey,cli}.py、tests/unit/test_unified_agent_uat_*.py、src/memory_palace/config/feature_registry.py。

1. 区分“运行中证据检查”与“全量封包”：前者允许部分步骤，后者强制 E2E-00～16 和 UAT-F01～13 全部存在且通过；重复、未知、遗漏、失败步骤均不能封包。
2. 对需要生成式能力的步骤要求数据库中的真实调用记录，检查 provider/model/is_mock、调用状态、Agent 名称、trace 和业务对象关联；不能仅验证已有数组中的元素而允许数组为空。
3. 汇总文件校验语义。模型调用、检索、恢复和数据库断言必须有记录；浏览器控制台无错误可以为空，不要求制造错误记录。
4. 保存代码提交、未提交改动摘要及内容指纹、镜像标识、依赖版本、模型/向量基线和环境标识。已有工作区修改必须纳入来源指纹，不能用 HEAD 冒充实际测试版本。
5. 注册表更新先生成候选文件，结合当前证据做结构校验和运行时快照比对后再应用；保留原始失败包。封包不依赖提前把正式注册表刷绿。

关闭标准：仅一条通过、缺失故障步骤、空模型证据、跨 run 引用、哈希不符、旧模型、伪造 READY 等反例均被拒绝；合法的部分进度仍可保存。

### R1：安全边界和配置

影响：.gitignore、.dockerignore、main.py、config/env_validator.py、config/secrets.py、deploy/nginx.conf、deploy/Dockerfile、deploy/docker-compose.yml。

1. 从教学产物中移除已确认的临时 Chrome profile，并在 Git 与 Docker 构建上下文中排除浏览器会话目录；保留教学源文件。删除前核实绝对路径，禁止清空整个 teaching 目录。
2. 先盘点实际部署与 Secret 来源，再轮换数据库密码、JWT 和管理员密码。数据库已有用户密码和已初始化管理员的密码必须同步更新；仅改 .env 不算完成。轮换后验证登录、数据库连接和旧会话失效，不输出新旧秘密。
3. .env 存在真实格式值本身不等于已经泄漏；检查是否进入 Git 历史、日志或镜像，报告只列键名和暴露位置。
4. 启动使用严格校验，并支持 Secret 文件。缺失文件、文件为空、不可读和非法配置要阻止启动；不得因切换 strict 而误把合法的文件注入判为缺少环境变量。
5. 同时收紧应用中间件和 Gunicorn/Uvicorn 的转发头信任；Nginx 清除客户端提供的转发链并重建可信头。按实际代理网络配置受信来源，运行准备入口仍校验身份、角色及来源。

关闭标准：伪造 X-Forwarded-For 不能通过本机限制；经可信代理访问可用；必需配置错误启动失败且日志无秘密；禁用渠道没有初始化、入队或发送副作用。

### R2：建议运行持久化与 Hatchet 启用

影响：scenic/advice_runs.py、advice_dispatch.py、hatchet_workflow.py、advice_sink.py、main.py、现有 Redis Streams 实现及恢复测试。

1. 复用 Redis Streams 的 consumer group、pending、claim、ACK 能力，为建议创建独立 stream/group，避免与员工消息消费者混读。
2. PostgreSQL 保留建议运行的权威状态；解决数据库创建成功而入队失败的窗口，用可重放的待派发记录或对账恢复补发，沿用 (incident_id, step, attempt) 幂等键。
3. 只有持久终态及必要业务副作用落地后 ACK；数据库失败、进程取消和最终落库前中断不能提前 ACK。
4. 恢复 PENDING 和失去执行者的 RUNNING；通过租约/执行者标识与条件更新防止回收仍在执行的任务。仅把队列换成 Redis 不能解决卡住的 RUNNING。
5. 处理“终态已落库但卷宗/SSE 发布失败”窗口：可重放的副作用不得重复生成任务、审批或通知。SSE 断线后的界面从数据库快照恢复。
6. SUPERSEDED 不得重新参与决策；已经在途的迟到结果可留只读证据。重投递不应凭空触发新的模型生成。
7. 明确 Hatchet 的启用条件：默认栈使用 Redis 建议队列；启用 Hatchet 的部署必须有可读非空 token 和对应服务/worker，错误时显式报错，不静默切换造成验收混淆。两个消费者不能重复执行同一 run。

关闭标准：分别在入队前后、领取后、模型返回后、终态落库后和 ACK 前中断；恢复后业务终态唯一，pending 正确清理，审计完整。模型网络超时无法保证供应商绝不重复计费，必须如实保留重试调用证据；保证业务效果幂等。

### R3：可重复启动和构建

影响：run.sh、pyproject.toml、requirements 系列文件、frontend/package.json、前端构建脚本和部署文档。

1. 修复 run.sh 中失效的 init_db 和模块入口，复用现有正式初始化流程，避免每次启动重复播种业务数据。
2. 统一 Python 最低版本为 3.11，并对齐 lint/typecheck 配置与 Docker；确认实际依赖兼容性。uv.lock 当前只是被忽略的简短元数据，不能当作已完成依赖锁定。
3. 固定并验证 Node 24.15.x、pnpm 11.19.0，确保子进程解析到同一 pnpm；不通过关闭 engine-strict 掩盖版本不一致。
4. 本地与镜像构建复用 scripts/export_openapi.py，经 OPENAPI_FILE 输入契约检查，再构建四入口。已有离线导出能力无需重写。
5. 恢复 Docker engine，检查现有数据卷、模型缓存和 Secret 文件是否可用；不删除数据库卷来绕过启动失败。隔离 UAT 数据与已有业务数据。

关闭标准：新终端按文档可构建、默认/完整 profile 可启动，后端相关测试与前端检查通过，健康/就绪接口诚实报告依赖故障。

### R4：扩展角色模拟执行器

复用 scripts/unified_agent_uat，不另建平行业务后端。复用 scripts/mvp.ps1 的 install/start/verify/bootstrap-uat/restart-app/backup/restore；暂不把尚未实现的全量执行命令写成已可用。

| 步骤 | 执行角色与动作 | 必需证据 |
| --- | --- | --- |
| E2E-00～02 | 管理员确认环境，员工登录/渠道身份绑定、上传附件并上报 | 正式身份、会话、附件、唯一消息、Redis stream ID |
| E2E-03～04 | 四 Agent 受理，员工补充同一事件 | 同一消息链的四 Agent 真实调用、SOP 依据、事件不重复 |
| E2E-05～06 | TodoWrite 分解，员工按依赖完成四任务 | 原子激活、三条依赖、负责人、拒绝提前完成及结构化回执 |
| E2E-07～09 | 经理拒绝，员工补证，经理重提/批准 | 两张关联审批、审批前零执行、内部通知唯一送达 |
| E2E-10～12 | 验证关闭门禁，Watcher 巡检，经理关闭 | 前置条件冲突、真实巡检、关闭审计、可重试经验候选 |
| E2E-13～14 | 专家访谈/确认，知识负责人退回/复审/发布 | 可恢复访谈、不可变版本、授权、pgvector 当前有效版本 |
| E2E-15 | 第二名员工重新提问并采用经验，管理员审计 | 独立身份命中新发布经验与 SOP、引用版本、采用记录、八 Agent 关联证据 |
| E2E-16 | 执行者只重启 App，员工恢复会话 | 前后 runtime identity、其他容器未重启、Redis pending/claim/ACK、业务结果唯一 |

八个 Agent 的证据属于同一验收故事，但访谈、复用与巡检可以有不同 trace；通过事件、任务、经验版本和 run 关联，不能要求跨所有步骤共用一个 trace。

前端至少覆盖四个正式入口的登录、核心写操作、等待、错误、重试、权限拒绝和刷新恢复。API 执行器用于精确断言；浏览器操作与截图补齐 UI 验收，不能以 API 全通过替代页面功能等价。

### R5：故障、恢复和主线未覆盖功能

- UAT-F01～02：重复消息、ACK 前中断与恢复。
- UAT-F03～04：生成式超时/401/熔断与检索不可用；恢复后再验证真实成功。
- UAT-F05～09：任务依赖拒绝、审批并发、动作执行失败、访谈恢复、索引发布失败、Watcher 去重。
- UAT-F10～13：跨场地读取、普通员工越权、外部渠道安全禁用、停用/缺失渠道身份。
- 故障注入仅针对隔离 UAT 服务，结束后恢复；预期的业务拒绝属于测试通过，未达预期的拒绝或恢复属于失败。保留失败包，修复后新建 run。
- 对照 FEATURE_REQUIREMENTS 补齐历史补录、SOP 完整治理、Watcher finding 分派/关闭、用户停启用及密码重置、配置重载、死信恢复、备份恢复等独立操作。不能因为 covers 标签包含某功能就认为行为已经覆盖。
- 验证备份在隔离目标恢复；不能只重启 App 就宣称 PostgreSQL 备份恢复通过。
- 按 ADR-0022 完成四入口桌面/移动行为、视觉证据和按入口回滚演练，产品负责人视觉签收单独记录。

### R6：按证据更新注册表

当前 37 个条目的内部验收目标是：20 个业务 + 8 个 Agent + 5 个平台 + DeepSeek，共 34 项 READY；企业微信 1 项按政策禁用；短信/语音 2 项缺配置禁用且已验证安全行为。30 条旅程全部 READY，其中禁用渠道旅程的通过表示“安全禁用行为正确”。

必要条件：当前 run 完整封包、每项功能证据齐全、真实环境快照满足 FEATURE_REQUIREMENTS、证据路径/校验和可复核、禁用渠道例外满足 safe_disabled_verified。任一条件不满足则保留阻断原因。内部 release_gate_passed 与客户交付签收分别报告。

## 4. 证据合同

沿用 docs/verification/unified-agent-uat/<uat_run_id>/ 目录，复用已有 manifest.json、steps/、api/、traces/、screenshots/、failures/ 及汇总文件；不新造第二套证据格式。

- manifest：版本、架构、运行环境、代码/镜像指纹、开始结束时间、每步路径与 SHA-256、主数据 baseline。
- steps：角色、入口、期望与实际结果、断言、业务编号、关联 trace、模型调用引用、产物引用。
- llm-calls：从 llm_call_logs 采集真实记录，仅保留所需元数据；缺失调用不得由执行器补写。
- pgvector-retrieval：检索输入的安全摘要、场地、知识/经验 ID、发布版本、模型维度与引用校验。
- queue-recovery：中断点、前后 App 实例、stream/group/message ID、claim/ACK 与业务唯一性断言。
- db-assertions：只读核验结果和业务关联；不保存密钥、Cookie、访问令牌、完整 Prompt 或不必要个人信息。
- execution-report：通过/失败/未执行、已知限制及客户验收剩余项。不要用空文件、旧截图或其他 run 的结果填充。

执行顺序：R0 → R1/R2/R3 → R4 → R5 → R6。每个工作包先跑针对性回归；全部实现后运行后端正式路径测试、前端检查、Compose 验证及全新连续 UAT。
