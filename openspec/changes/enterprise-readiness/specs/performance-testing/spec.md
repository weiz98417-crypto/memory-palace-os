## ADDED Requirements

### Requirement: Load testing script
系统 SHALL 提供 Locust 压测脚本覆盖核心场景。

#### Scenario: Webhook ingestion load test
- **WHEN** 100 并发用户持续 60 秒向 /webhook 发送消息
- **THEN** p95 网关延迟 < 500ms

### Requirement: Query optimization
系统 SHALL 合并 admin dashboard 的多次独立查询为 CTE。

#### Scenario: Dashboard query consolidation
- **WHEN** GET /api/v1/admin/stats 被调用
- **THEN** 使用单个 CTE 查询替代 6 次独立 SELECT

### Requirement: TTL cache
系统 SHALL 为热点统计查询提供 30 秒 TTL 缓存。

#### Scenario: Cache hit
- **WHEN** 30 秒内重复请求相同统计数据
- **THEN** 返回缓存结果，不执行数据库查询
