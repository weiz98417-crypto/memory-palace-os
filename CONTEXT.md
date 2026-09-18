# Memory Palace OS

This context defines the user-facing product language for Memory Palace OS, a platform that turns on-site operations into reusable organizational memory.

## Client Scope

**正式客户端**:
The authenticated product experience used by operational staff and administrators to handle work and review organizational memory.
_Avoid_: Demo 控制台, 营销官网

**正式客户端品牌升级**:
The first delivery scope that refreshes the formal client's login experience and operations workspace while leaving the demo, marketing site, and large-screen views unchanged.
_Avoid_: 全站改版, Demo 改版

**冷静指挥台**:
The formal client's visual posture: a dark, low-contrast operational surface where status and risk remain more prominent than brand decoration.
_Avoid_: 炫酷大屏, 通用 SaaS 渐变面板

**值班/运营负责人**:
The formal client's primary user, accountable for seeing active operational risk, coordinating response, and confirming closure.
_Avoid_: 系统管理员, 大屏观众

**真实认证**:
The server-verified identity check required before a user can access the formal client.
_Avoid_: 演示账号, 本地假登录

**现行品牌资产**:
The approved Memory Palace OS logo, motion, and character materials used at standard formal-client interface sizes in this upgrade.
_Avoid_: 大屏品牌资产

**记忆宫殿 · Memory Palace OS**:
The sole formal product name displayed throughout the formal client, including its login experience, navigation, and browser identity.
_Avoid_: Memory Palace, 景区运营数字资产管理 OS

**记忆核心守护者**:
The brand character used only in low-pressure guidance and knowledge moments, never as a signal for risk, approval, failure, or authentication.
_Avoid_: 告警角色, 审批角色

**品牌开场**:
A one-time, muted, skippable logo motion shown only on a user's first visit to the login experience.
_Avoid_: 循环等待动画, 工作台背景动效

**移动现场端**:
The responsive formal-client experience for reviewing incidents and confirming urgent work away from a desktop workstation.
_Avoid_: 被压缩的桌面控制台

## Workspace

**指挥中心**:
The formal client's default workspace for a duty or operations lead to identify the next operational risk and coordinate a response.
_Avoid_: 数据监控大屏, 通用仪表盘

**下一步处置**:
The most urgent operational action a duty or operations lead should take next, surfaced before aggregate statistics in the command center.
_Avoid_: 指标展示

**事件处置**:
The workspace where an operational incident is assessed, assigned, acted on, and closed with evidence.
_Avoid_: 事件列表

**任务与审批**:
The workspace for work that needs human ownership, confirmation, or an explicit business decision.
_Avoid_: 待办清单

**组织记忆**:
The curated operational knowledge created from cases, SOPs, and expert experience.
_Avoid_: 全量记忆卷宗, 数字分身大脑

**系统治理**:
The administrative workspace for operational reliability, integrations, permissions, and audit evidence.
_Avoid_: 设置

**知识负责人**:
The manager-level role accountable for curating knowledge gaps, confirming gap topics, and publishing SOPs or expert experience.
_Avoid_: 普通值班经理, 系统管理员

**知识缺口**:
A deterministic operational fact that a tenant-scoped retrieval completed without a verified knowledge hit.
_Avoid_: 模型失败, 无效提问

**缺口主题**:
A human-confirmed grouping of related knowledge gaps used for knowledge governance; it is not a model-generated fact.
_Avoid_: 语义聚类, 模型主题

**景区模拟环境**:
A local operating environment that simulates external scenic-area devices and channels while running the real business workflow for incidents, tasks, approvals, knowledge, and audit evidence.
_Avoid_: 播放器, 假数据后台

**景区态势**:
The shared operational picture of scenic-area zones, people flow, weather, equipment, active alerts, and incident status at a point in simulated time.
_Avoid_: 监控大屏, 统计仪表盘

**模拟时钟**:
The controllable clock used by the scenic-area simulation to play, pause, step, or accelerate operational time while retaining wall-clock timestamps for audit evidence.
_Avoid_: 假时间, 播放进度

**监测信号**:
A device, observation, or external-condition reading that describes a change in the scenic-area situation but does not yet represent a human-owned operational incident.
_Avoid_: 事件, 工单

**态势告警**:
A rule-evaluated notification that a monitoring signal crosses an operational threshold and may require attention or conversion into an operational incident.
_Avoid_: 红点, 普通消息

**运营事件**:
A human-owned operational matter created from a report or one or more situation alerts, with triage, dispatch, mitigation, evidence, and authorized closure.
_Avoid_: 告警, 工单

**向量知识索引**:
The tenant-scoped semantic index of published SOPs and approved experience assets, backed by PostgreSQL pgvector and linked to their immutable business versions.
_Avoid_: 独立向量库, 黑盒召回

**景区作业地图**:
The local spatial view of scenic-area zones, routes, equipment points, staff positions, capacity thresholds, alerts, and operational events used by the command center.
_Avoid_: 装饰地图, 大屏背景

**态势订阅**:
A client subscription to ordered scenic-area snapshots and operational state changes, with reconnect and snapshot recovery semantics.
_Avoid_: 页面轮询, 动画刷新

**景区指挥中心**:
The command-center projection of the formal client's default workspace, combining the scenic-area map, situation alerts, next operational action, active incidents, and response timeline.
_Avoid_: Demo 控制台, 监控大屏

**模拟控制器**:
The authorized presenter control for simulation time, replay scenarios, manual signal injection, and reset; it changes simulated inputs but cannot directly edit operational outcomes.
_Avoid_: 后台假按钮, 业务操作按钮

**运行准备入口**:
The protected local operations entry used to prepare simulation inputs and environment state before a demonstration, separate from the formal operational workspaces.
_Avoid_: 演示控制台, 播放器

**内部通知渠道**:
The local, auditable channel projection used to deliver simulated operational notifications to the internal system access environment without claiming delivery to a production external provider.
_Avoid_: 假短信, 假企微

**垂直切片**:
A thin but complete path through situation input, alerting, incident response, human action, and audit that can be demonstrated and verified independently.
_Avoid_: 页面优先, 功能堆叠

## Agent 主干

**事件指挥边界 (IncidentCommand)**:
The single deep seam through which scenic incidents receive grounded advice, dispatch drafts, and closure summaries; it orchestrates typed agents and returns call-record references without performing business decisions.
_Avoid_: Agent 调度器, 全权处置器

**处置建议**:
A recommendation grounded only in tenant-scoped, verified SOPs, cases, or expert experience, with explicit citations or an explicit statement that no basis was found.
_Avoid_: 模型猜测, 无来源答案

**后端引导动作**:
A backend-owned next-action descriptor containing an action code, copy, prerequisites, role requirements, and an optional formal command; the frontend renders it and does not infer workflow state itself.
_Avoid_: 前端 lifecycle 推导, 客户端动作码猜测

**建议卡**:
The command-center projection of one advice run, including status, evidence status, grounded citations, optional model-call evidence, and the human decision controls allowed by the current state.
_Avoid_: 自由 HTML 拼接建议, 无状态建议弹窗
**建议运行**:
One idempotent asynchronous advice-generation attempt keyed by incident, step, and attempt, with a durable state of PENDING, RUNNING, READY, FAILED, or SUPERSEDED.
_Avoid_: 后台任务, 临时提示

**流程推进门禁**:
The human decision to adopt an advice, ignore it with a structured reason, or explicitly proceed without waiting (which supersedes pending advice) before the workflow may create a dispatch draft.
_Avoid_: 建议展示, 自动采纳, 无痕跳过

**模型调用证据**:
The auditable record of an actual model call, stored only in llm_call_logs and rendered by reference with model, token, latency, trace, and honest mock status.
_Avoid_: 模拟调用凭证, 估算 token 记录

**模型服务**:
The runtime contract and health surface for the single generative model shared by the scenic agents: one model, a process-internal gateway, real llm_call_logs evidence, a daily token quota, and a circuit breaker.
_Avoid_: 多模型路由, 传统微服务模型网关

**建议采纳判断**:
The venue-scoped manager/admin decision to adopt advice, ignore it, or explicitly proceed without waiting before a dispatch draft may be created.
_Avoid_: 普通确认, Operator 自动采纳

**结构化忽略理由**:
A required reason code and optional explanation recorded when advice is ignored or the workflow proceeds without waiting; OTHER requires free text.
_Avoid_: 自由文本备注, 无理由忽略

**迟到建议**:
A model advice that arrived after a human already advanced the incident; it is retained as read-only SUPERSEDED evidence and cannot participate in later dispatch, tasks, or closure.
_Avoid_: 已忽略建议, 静默丢弃
