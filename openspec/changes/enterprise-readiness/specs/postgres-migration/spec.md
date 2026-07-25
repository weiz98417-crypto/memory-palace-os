## ADDED Requirements

### Requirement: AsyncDBClient Protocol
系统 SHALL 定义一个 Protocol 类规定数据库客户端接口（fetch_one, fetch_all, execute, transaction, close）。

#### Scenario: Protocol defines interface
- **WHEN** 任意实现类继承该 Protocol
- **THEN** 必须实现全部 5 个方法，否则类型检查失败

### Requirement: PostgresDBClient
系统 SHALL 提供 PostgreSQL 数据库客户端，使用 asyncpg 连接池。

#### Scenario: Connection pool
- **WHEN** DATABASE_URL 环境变量设置为有效的 PostgreSQL 连接串
- **THEN** PostgresDBClient 创建 min_size=5, max_size=20 的连接池

#### Scenario: SQL placeholder translation
- **WHEN** 执行包含 `?` 占位符的 SQL 查询
- **THEN** PostgresDBClient 自动将 `?` 替换为 `$1, $2, $3...`

#### Scenario: DEMO_MODE fallback
- **WHEN** DEMO_MODE=true
- **THEN** 容器注入 SQLiteDBClient 而非 PostgresDBClient

### Requirement: SQLiteDBClient
系统 SHALL 保留 SQLite 数据库客户端作为 DEMO_MODE 兜底。

#### Scenario: SQLite in demo mode
- **WHEN** DEMO_MODE=true
- **THEN** 使用现有 aiosqlite 连接，所有查询正常工作
