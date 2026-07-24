## ADDED Requirements

### Requirement: 任务列表端点
系统 SHALL 在 `GET /demo/tasks` 端点返回 TaskGraph 中的任务列表。

#### Scenario: 获取任务列表
- **WHEN** 客户端请求 GET `/demo/tasks`
- **THEN** 系统返回一个 JSON 数组，每个元素包含 id、description、status、dependencies、assigned_agent、session_id 字段

#### Scenario: TaskGraph 为空时不崩溃
- **WHEN** TaskGraph 中没有任务
- **THEN** 系统返回空数组 `[]`
