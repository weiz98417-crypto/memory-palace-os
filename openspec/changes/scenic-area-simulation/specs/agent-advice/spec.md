## ADDED Requirements

### Requirement: Agent 生成式处置建议
系统 SHALL 通过 `IncidentCommand` 编排 `context_trigger → router → memory_ops → commander` 生成处置建议，并把建议绑定到当前场地、事件、知识检索快照和调用记录；业务状态机不得复制一套并行的建议逻辑。

#### Scenario: 设备异常有知识依据
- **WHEN** 观光车设备异常事件已有现场证据，且检索到该场地已发布的复运 SOP
- **THEN** 建议状态为 `READY/GROUNDED`，正文给出与 SOP 一致的处置要点，并包含所使用 SOP 的稳定引用

#### Scenario: 客流告警有知识依据
- **WHEN** 东门客流超过容量阈值且检索到该场地已发布的客流分流 SOP
- **THEN** 建议状态为 `READY/GROUNDED`，正文包含分流动作和该 SOP 的稳定引用

### Requirement: 无知识命中必须明确拒答
系统 SHALL 仅在已核验、同场地的知识命中上生成事实性建议；没有命中时，建议状态 MUST 为 `READY/NO_EVIDENCE`，正文 MUST 明确包含“没有依据”，引用列表 MUST 为空，且不得声称命中 SOP/案例或编造来源。

#### Scenario: 无知识命中
- **WHEN** 当前事件没有可用的已发布 SOP、历史 CASE 或经验卡
- **THEN** 系统返回“没有依据”，说明需要人工按正式制度或专业手册处置，并且不生成伪装成知识依据的引用或操作结论

### Requirement: 调用证据可核对
系统 SHALL 把每次真实模型调用的 provider、实际模型名、token、延迟、attempt、agent role、trace id、状态和 `is_mock` 写入既有 `llm_call_logs`；事件卷宗 SHALL 能按调用记录引用展示该证据。未调用外部 provider 时 MUST 标记 `is_mock=true`，provider 未返回的字段 MUST 保持缺失或显式降级，不得估造。

#### Scenario: 查看模型调用证据
- **WHEN** 授权用户打开包含 Agent 建议的事件卷宗
- **THEN** 可以看到建议引用的 SOP 来源，以及对应的真实调用记录；模型不可用或未调用时明确显示“未获得模型建议”，不显示伪造的成功调用

### Requirement: 模型失败降级不阻塞处置
系统 SHALL 对单 agent 调用执行 20 秒超时、失败重试 1 次和独立开关；最终失败只降级该环节并记录失败证据，不得阻塞现场处置或关闭门禁，也不得生成 `GROUNDED` 建议。

#### Scenario: 建议模型不可用
- **WHEN** Agent 环节达到超时或重试上限
- **THEN** 业务状态仍可继续推进，界面与卷宗显示“未获得模型建议”，且关闭门禁仍按现场证据、SOP 命中、任务、审批和告警恢复独立校验

### Requirement: 建议决定的流程推进门禁
系统 SHALL 在进入派单草案前要求授权人员对当前建议执行 `ADOPT`、`IGNORE` 或 `PROCEED_WITHOUT_WAITING`；忽略和不等待 MUST 带结构化理由，未决建议本身不满足流程推进门禁。只有 `ADOPT` 允许建议正文和引用进入 Commander 后续上下文。

#### Scenario: 未决定不能派单
- **WHEN** 建议已 `READY`，但经理尚未采纳或忽略
- **THEN** 系统拒绝生成派单草案，并要求先完成建议决定

### Requirement: 评测与真实冒烟门禁
系统 SHALL 用固定黄金样本覆盖设备异常、客流告警和无知识命中三类场景；契约测试 MUST 使用假 registry 和固定夹具且不依赖真实模型，真实模型评测 MUST 使用真实凭据。缺少凭据时真实评测 MUST 失败，不得跳过、改用 mock 或返回成功。

#### Scenario: 缺少真实模型凭据
- **WHEN** 执行真实模型评测但环境没有可用凭据
- **THEN** 评测以非零状态失败并明确报告缺少凭据，不执行 mock 结果替代

#### Scenario: 固定黄金样本回归
- **WHEN** 契约测试运行设备异常、客流告警和无知识命中夹具
- **THEN** 有依据场景必须引用期望来源，无命中场景必须出现“没有依据”且不得产生引用
### Requirement: 后端产出的下一步动作
系统 SHALL 在景区快照中返回后端计算的动作码、文案、前置条件、角色要求和可执行指令；前端 MUST 只渲染这些字段，MUST NOT 根据事件生命周期自行推导下一步动作。

#### Scenario: 设备告警转事件
- **WHEN** 快照中存在未转换的设备异常告警
- **THEN** 后端返回 `CONVERT_ALERT` 动作和对应事件参数，前端只显示该动作并调用正式命令入口

### Requirement: 建议卡与 SSE 状态
系统 SHALL 在指挥中心显示建议正文、引用、向量/重排分数、状态和决定结果；现场端 SHALL 显示同一建议的只读状态和引用。SSE 事件 `ADVICE_PENDING`、`ADVICE_READY`、`ADVICE_FAILED` MUST 分别显示“分析中”“已就绪”和“未获得模型建议”。

#### Scenario: 建议状态推送
- **WHEN** 建议从生成中变为就绪或失败
- **THEN** 当前场地的前端收到对应 SSE 事件，刷新建议卡和下一步动作，不使用客户端猜测替代

### Requirement: 前端忽略理由门禁
系统 SHALL 在忽略建议或不等待建议时要求结构化理由；`OTHER` MUST 提供非空文本，`PROCEED_WITHOUT_WAITING` MUST 二次确认。前端提交校验与后端命令校验 MUST 同时存在。

#### Scenario: 忽略缺少理由
- **WHEN** 用户尝试提交忽略但没有选择 reason code
- **THEN** 前端拒绝提交；绕过前端时后端返回 422，不写入决定活动
