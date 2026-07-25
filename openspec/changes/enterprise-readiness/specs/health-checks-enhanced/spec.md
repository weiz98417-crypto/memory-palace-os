## ADDED Requirements

### Requirement: PostgreSQL health check
系统 SHALL 在 /ready 端点包含 PostgreSQL 连通性检查。

#### Scenario: PostgreSQL available
- **WHEN** PostgreSQL 连接池可执行 SELECT 1
- **THEN** health check 返回 available: true

#### Scenario: PostgreSQL unavailable
- **WHEN** PostgreSQL 连接失败
- **THEN** health check 返回 available: false，整体状态为 degraded

### Requirement: Redis health check
系统 SHALL 在 /ready 端点包含 Redis 连通性检查。

#### Scenario: Redis available
- **WHEN** Redis PING 成功
- **THEN** health check 返回 connected: true
