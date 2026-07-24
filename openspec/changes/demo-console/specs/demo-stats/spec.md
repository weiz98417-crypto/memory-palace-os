## ADDED Requirements

### Requirement: 系统统计端点
系统 SHALL 在 `GET /demo/stats` 端点返回聚合的运行统计数据。

#### Scenario: 获取正常运行的统计
- **WHEN** 客户端请求 GET `/demo/stats`
- **THEN** 系统返回包含 queue_depth、message_count、task_count、skills_registered、last_watcher_run 字段的 JSON

#### Scenario: 数据库不可用时不崩溃
- **WHEN** 数据库查询失败
- **THEN** 系统返回可用字段的默认值（如 message_count=0），不抛出 500 错误
