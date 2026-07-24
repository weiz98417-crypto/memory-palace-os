## ADDED Requirements

### Requirement: 多标签页演示控制台
系统 SHALL 提供一个可通过 `/admin/demo_console.html` 访问的单页 Web 控制台，包含 5 个功能标签页。

#### Scenario: 访问控制台
- **WHEN** 用户在浏览器中打开 `/admin/demo_console.html`
- **THEN** 系统展示控制台界面，默认选中"消息链路"标签页

### Requirement: 消息链路演示
控制台 SHALL 提供消息发送和 pipeline 可视化功能。

#### Scenario: 发送预设紧急消息
- **WHEN** 用户点击预设按钮"游客受伤"
- **THEN** 系统通过 POST `/demo/send` 发送消息，轮询 GET `/demo/result/{trace_id}` 获取结果，展示完整的 pipeline 路径（ContextTrigger → Commander）和回复内容

#### Scenario: 发送自定义消息
- **WHEN** 用户在文本框中输入消息并点击发送
- **THEN** 系统发送消息并展示完整回复和路由信息

#### Scenario: Pipeline 可视化
- **WHEN** 获取到处理结果后
- **THEN** 系统以横向流程图形式展示 ContextTrigger Stage1 → Stage2 → Router → Agent 的执行链路，每个节点用颜色标记执行状态

### Requirement: 任务系统展示
控制台 SHALL 展示 TaskGraph 中的任务列表和依赖关系。

#### Scenario: 查看任务列表
- **WHEN** 用户切换到"任务系统"标签页
- **THEN** 系统调用 GET `/demo/tasks` 获取任务列表，展示每个任务的状态（PENDING/BLOCKED/RUNNING/DONE）、描述、依赖关系

#### Scenario: 任务依赖可视化
- **WHEN** 存在有依赖关系的任务
- **THEN** 系统以树形缩进或箭头连接的方式展示任务间的依赖关系

### Requirement: 知识库检索
控制台 SHALL 提供知识库向量检索的交互界面。

#### Scenario: 搜索知识库
- **WHEN** 用户在知识库标签页输入查询并提交
- **THEN** 系统调用 GET `/v1/knowledge/query` 并展示检索结果

### Requirement: 系统监控
控制台 SHALL 展示系统运行状态概览。

#### Scenario: 查看系统状态
- **WHEN** 用户切换到"系统监控"标签页
- **THEN** 系统调用 GET `/demo/stats` 展示队列深度、消息数量、任务数量、注册技能数、上次巡检时间

### Requirement: 管理后台入口
控制台 SHALL 在"管理"标签页中提供到已有管理大屏的入口。

#### Scenario: 访问管理大屏
- **WHEN** 用户切换到"管理"标签页
- **THEN** 系统展示管理大屏的关键数据摘要，并提供跳转链接到 `/admin/admin_frontend.html`
