## Why

Memory Palace OS 当前是 Function Demo 阶段：SQLite 单文件数据库、asyncio.Queue 内存队列、无认证、无容器化部署。这 4 个硬门槛阻止了任何生产环境部署。在此基础上，结构化的可观测性、LLM 容灾、多租户隔离是"能运维、能扩展"的必备能力。分 3 个 Phase 逐步推进，每一阶段都有独立的交付价值。

## What Changes

### Phase 1: 能上线
- **PostgreSQL 迁移**: 定义 AsyncDBClient Protocol，新增 PostgresDBClient（asyncpg）和 SQLiteDBClient（DEMO_MODE 兜底），SQL 占位符自动翻译
- **Redis 消息队列**: 定义 MessageQueueProtocol，新增 RedisStreamsQueue（XADD/XREADGROUP/XACK + 死信队列）和 InMemoryQueue（DEMO_MODE）
- **Docker 部署**: 完善 docker-compose.yml（app+PG+Redis+ChromaDB+Nginx）+ docker-compose.demo.yml（DEMO_MODE 精简版）
- **基础认证**: FastAPI Depends 注入 require_auth（API Key / JWT），DEMO_MODE 自动通过

### Phase 2: 能运维
- **结构化日志**: contextvars 传递 trace_id，loguru JSON 格式化器，不改现有 logger 调用
- **LLM Fallback 链**: 多模型链式重试，CircuitBreaker 自动切换，环境变量配置备用模型
- **健康检查增强**: 扩展现有 HealthCheckerRegistry，注册 PG/Redis/ChromaDB 检查器
- **密钥管理**: Secrets dataclass + fail-fast 启动校验，DEMO_MODE 安全默认值

### Phase 3: 能扩展
- **多租户隔离**: contextvars venue_id + WHERE 子句注入，企微 AgentID → venue_id 映射
- **API 限流**: slowapi 库，Redis 后端（生产）/ 内存后端（demo），/webhook/* 白名单豁免
- **知识库管理 UI**: 扩展现有 admin_frontend.html，新增 KB 搜索/删除/导入/重建索引
- **性能测试 + 优化**: Locust 压测脚本，CTE 查询合并，TTL 缓存

## Capabilities

### New Capabilities
- `postgres-migration`: PostgreSQL 数据库后端，SQLite 兜底，接口不变
- `redis-queue`: Redis Streams 消息队列，死信队列，consumer group
- `docker-deploy`: 生产 + Demo 双套 Docker Compose
- `api-auth`: API Key / JWT 认证，FastAPI Depends 注入
- `structured-logging`: contextvars trace_id + loguru JSON 格式化
- `llm-fallback`: 多模型链式重试 + CircuitBreaker 自动切换
- `health-checks-enhanced`: PG/Redis/ChromaDB 连通性检查
- `secret-management`: Secrets 启动校验，fail-fast
- `multi-tenant`: contextvars venue_id 数据隔离
- `rate-limiting`: slowapi 限流中间件
- `kb-admin-ui`: 知识库管理前端标签页
- `performance-testing`: Locust 压测 + 查询优化

### Modified Capabilities
- `<none>`

## Impact

- 新增依赖：asyncpg、redis[hiredis]、slowapi、locust（dev only）
- 修改核心模块：db_client.py、queue_worker.py、container.py、main.py、gateway.py
- 新增模块：db_client_protocol.py、redis_queue.py、auth.py、trace_context.py、llm_fallback.py、secrets.py、tenant.py、rate_limit.py、cache.py
- DEMO_MODE 全程兼容，所有后端切换自动判断
- 不修改任何 skill 接口或 orchestrator 路由逻辑
