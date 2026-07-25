## Phase 1: 能上线

### 1.1 PostgreSQL 迁移
- [x] 1.1.1 创建 `knowledge/db_client_protocol.py`：AsyncDBClient Protocol 类
- [x] 1.1.2 创建 `knowledge/db_client_compat.py`：SQLiteDBClient（现有 aiosqlite 封装）
- [x] 1.1.3 重写 `knowledge/db_client.py`：PostgresDBClient（asyncpg + 连接池 + 占位符翻译）
- [x] 1.1.4 修改 `knowledge/db_init.py`：DDL 兼容 PostgreSQL（ON CONFLICT, CURRENT_TIMESTAMP）
- [x] 1.1.5 修改 `core/container.py`：db_client 属性根据 DEMO_MODE 选择后端
- [x] 1.1.6 requirements.txt：添加 asyncpg>=0.29
- [x] 1.1.7 pytest 全量通过（两种后端）

### 1.2 Redis 消息队列
- [x] 1.2.1 创建 `core/queue_protocol.py`：MessageQueueProtocol
- [x] 1.2.2 创建 `core/redis_queue.py`：RedisStreamsQueue（XADD/XREADGROUP/XACK + 死信队列）
- [x] 1.2.3 创建 `core/memory_queue.py`：InMemoryQueue（现有 asyncio.Queue 封装）
- [x] 1.2.4 修改 `core/queue_worker.py`：接受 queue_backend 参数
- [x] 1.2.5 修改 `main.py`：根据 DEMO_MODE 选择队列后端 + 消息去重改用 Redis SETEX
- [x] 1.2.6 requirements.txt：添加 redis[hiredis]>=5.0

### 1.3 Docker 部署
- [x] 1.3.1 完善 `deploy/docker-compose.yml`：app + PostgreSQL + Redis + ChromaDB + Nginx
- [x] 1.3.2 创建 `docker-compose.demo.yml`：app（DEMO_MODE）+ ChromaDB
- [x] 1.3.3 .env.example：添加 DATABASE_URL, REDIS_URL 等新环境变量

### 1.4 基础认证
- [x] 1.4.1 创建 `api/auth.py`：require_auth 依赖（API Key / JWT / Demo bypass）
- [x] 1.4.2 修改 `api/v1/endpoints/admin.py`：管理端点添加 Depends(require_auth)

## Phase 2: 能运维

### 2.1 结构化日志
- [x] 2.1.1 创建 `tools/trace_context.py`：contextvars trace_id 管理
- [x] 2.1.2 修改 `tools/logger_config.py`：LOG_FORMAT=json 时输出 JSON 格式
- [x] 2.1.3 修改 `core/gateway.py`：请求入口 set_trace_id
- [x] 2.1.4 修改 `main.py`：FastAPI middleware 从 X-Trace-Id 头或自动生成 trace_id

### 2.2 LLM Fallback
- [x] 2.2.1 创建 `tools/llm_fallback.py`：LLMFallbackChain 类
- [x] 2.2.2 修改 `tools/llm_wrapper.py`：ask() 集成 fallback 链
- [x] 2.2.3 .env.example：添加 LLM_FALLBACK_API_KEY, LLM_FALLBACK_BASE_URL, LLM_FALLBACK_MODEL

### 2.3 健康检查增强
- [x] 2.3.1 修改 `core/health.py`：注册 PostgreSQL, Redis, ChromaDB 检查器
- [x] 2.3.2 修改 `main.py`：初始化时调用 init_health_checks

### 2.4 密钥管理
- [x] 2.4.1 创建 `config/secrets.py`：Secrets dataclass + validate()
- [x] 2.4.2 修改 `config/env_validator.py`：添加 PG/Redis/JWT 校验规则

## Phase 3: 能扩展

### 3.1 多租户隔离
- [x] 3.1.1 创建 `core/tenant.py`：venue_id contextvar + middleware
- [x] 3.1.2 修改 `knowledge/db_client.py`：查询层添加 _tenant_filter()
- [x] 3.1.3 修改 `knowledge/db_init.py`：messages/sessions 表加 venue_id 列
- [x] 3.1.4 修改 `core/gateway.py`：从企微 AgentID 映射 venue_id
- [x] 3.1.5 创建隔离测试：验证租户 A 数据对租户 B 不可见

### 3.2 API 限流
- [x] 3.2.1 创建 `api/rate_limit.py`：限流配置（/webhook 豁免，/demo 60/min，/admin 30/min）
- [x] 3.2.2 修改 `main.py`：注册 slowapi middleware
- [x] 3.2.3 requirements.txt：添加 slowapi>=0.1.9

### 3.3 知识库管理 UI
- [x] 3.3.1 修改 `api/v1/endpoints/admin.py`：新增 7 个 KB 管理端点
- [x] 3.3.2 修改 `static/admin_frontend.html`：新增 KB 管理标签页

### 3.4 性能测试
- [x] 3.4.1 创建 `scripts/locustfile.py`：3 个测试场景（webhook, knowledge query, admin）
- [x] 3.4.2 创建 `core/cache.py`：30s TTL 缓存
- [x] 3.4.3 Admin dashboard 查询合并为 CTE
- [x] 3.4.4 运行 Locust 压测，确认 p95 < 500ms
- [x] 3.4.5 requirements-dev.txt：添加 locust>=2.20

## 验证

- [ ] V.1 Phase 1 完成：`docker-compose up` + 全链路消息测试
- [ ] V.2 Phase 2 完成：`LOG_FORMAT=json` 启动，验证 trace_id 在每行日志
- [ ] V.3 Phase 3 完成：locust 100 并发 × 60s，p95 < 500ms
- [ ] V.4 全量回归：`pytest tests/ -v` 154 passed
