## Context

当前架构：SQLite + asyncio.Queue + 无认证 + 无容器化。目标是分 3 Phase 逐步提升到企业级。

核心设计原则：
- **接口不变，后端可切换**: 新能力通过 Protocol/ABC 抽象，两个实现（生产 + DEMO_MODE 兜底）
- **不改现有调用方**: DB 查询、消息队列、日志记录均不改签名
- **DEMO_MODE 全程兼容**: 所有切换点根据 `DEMO_MODE` 环境变量自动选择后端

## Goals / Non-Goals

**Goals:**
- Phase 1: SQLite→PostgreSQL、asyncio.Queue→Redis、Docker Compose 完善、API 认证
- Phase 2: JSON 结构化日志、LLM 多模型 fallback、健康检查增强、密钥集中管理
- Phase 3: 多租户隔离、API 限流、KB 管理 UI、性能测试与优化

**Non-Goals:**
- 不修改 skill 接口或 orchestrator 路由逻辑
- 不引入 ORM（保持原始 SQL）
- 不重写前端框架（保持静态 HTML）
- 不改变企微 webhook 协议

## Decisions

**D1: Protocol 抽象而非重写。** 所有后端切换通过 Python Protocol 类定义接口，两个实现并存。避免了大规模代码改动和回归风险。

**D2: contextvars 而非 structlog。** trace_id 传递用 stdlib contextvars，不改 200+ 处现有 logger.info() 调用。日志格式化用 loguru 的 JSON 格式化器。

**D3: slowapi 而非手写限流。** 成熟库（2k stars），支持 Redis 后端和多 key 策略，避免重复造轮子。

**D4: FastAPI Depends 认证而非中间件。** 利用 FastAPI 原生依赖注入，每个端点独立声明认证需求，DEMO_MODE 下自动跳过。

**D5: SQL 占位符自动翻译。** PostgresDBClient 内部 `_translate_sql()` 将 `?` 替换为 `$1, $2...`。调用方零改动。

## Risks / Trade-offs

- [Risk] SQL 方言差异导致查询失败 → 全量 154 tests 对两种后端均运行
- [Risk] Redis 不可用导致消息丢失 → DEMO_MODE 自动回退到 asyncio.Queue
- [Risk] LLM fallback 模型返回不同 JSON 格式 → parse_json() schema 校验兜底
- [Risk] 多租户数据泄漏 → 隔离测试套件验证租户 A 数据对租户 B 不可见
