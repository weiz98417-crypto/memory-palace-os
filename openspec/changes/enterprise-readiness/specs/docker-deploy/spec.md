## ADDED Requirements

### Requirement: Production Docker Compose
系统 SHALL 提供完整的 docker-compose.yml 包含 app, PostgreSQL, Redis, ChromaDB, Nginx。

#### Scenario: All services healthy
- **WHEN** `docker-compose up` 在生产环境执行
- **THEN** 所有 5 个服务通过健康检查，app 可接收请求

### Requirement: Demo Docker Compose
系统 SHALL 提供 docker-compose.demo.yml 仅包含 app + ChromaDB。

#### Scenario: Demo mode deployment
- **WHEN** `docker-compose -f docker-compose.demo.yml up` 执行
- **THEN** app 以 DEMO_MODE=true 启动，使用 SQLite + asyncio.Queue
