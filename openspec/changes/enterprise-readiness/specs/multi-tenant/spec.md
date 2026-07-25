## ADDED Requirements

### Requirement: venue_id extraction
系统 SHALL 从企微消息或 demo payload 中提取 venue_id 并设置租户上下文。

#### Scenario: WeChat message contains agent ID
- **WHEN** 企微消息到达，FromUserName 映射到 venue_a
- **THEN** 租户上下文设置为 venue_a，后续查询自动过滤

### Requirement: Data isolation
系统 SHALL 确保租户 A 的数据对租户 B 不可见。

#### Scenario: Cross-tenant query blocked
- **WHEN** 租户 A 的上下文下查询 messages 表
- **THEN** 查询结果仅包含 venue_id = 'venue_a' 的记录

#### Scenario: Demo mode no isolation
- **WHEN** DEMO_MODE=true 且未指定 venue_id
- **THEN** 所有数据可见（通配模式）
