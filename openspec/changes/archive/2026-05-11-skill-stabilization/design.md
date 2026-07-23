## Context

`landing-refactor` 完成后，核心链路（企微消息→Router→Commander→SLA）可运行。但存在以下短板：
- 旧单元测试大量 FAIL（patch 路径过时、缺依赖）
- 无 DEMO_MODE 降级，没 API key 时 LLM 调用直接崩溃
- `.env` 含真实 API key 但无 gitignore 保护
- `/admin`、`/api/v1/skills` 路由 307 重定向
- MemoryOps 调的是不存在的 `vector_client.search()` API
- Watcher 从未运行过

## Goals / Non-Goals

**Goals:**
- DEMO_MODE 降级：没 API key 也能验证全链路
- 安全：`.gitignore` 到位，阻止敏感文件提交
- 路由：`/admin` 和 `/api/v1/skills` 正常响应
- 已有单元测试全部 PASS
- MemoryOps RAG 检索链路可验证
- Watcher 巡检可运行

**Non-Goals:**
- 不新增功能特性
- 不改变 Agent 业务逻辑
- 不改 API 端点签名
- 不涉及 Phase 2-4 激活

## Decisions

### D1: DEMO_MODE 实现方式

选择：在 `llm_wrapper.ask()` 入口处检查 `os.environ.get("DEMO_MODE") == "true"`，如果是则直接返回 Mock 的 `LLMResponse`。

理由：改动最小（一个 if 分支），不需要修改任何 skill 代码。Mock 响应内容固定、可预测。

### D2: 路由修复方案

选择：`app.mount("/admin", StaticFiles(...), name="admin")` 移到所有 `app.include_router()` 之后。

理由：FastAPI 按注册顺序匹配路由。StaticFiles 在前时会截断 `/admin`，但不会截断 `/api/v1/admin/`（前缀不同）。问题在于 `StaticFiles` 对 `/admin` 不带尾部斜杠时返回 307。解决：确保 `/admin` 被挂载为 `directory="static"` + `html=True` 且放在最后。

### D3: 单元测试修复策略

选择：逐个文件跑，看具体错误，针对性修复。不改测试的断言逻辑，只修环境问题（patch 路径、缺失依赖）。

### D4: MemoryOps API 修复

选择：`memory_ops/skill.py` 中 `vector_client.search()` → `get_vector_client().query_experience()`。

理由：`PalaceVectorStore` 暴露的方法就是 `query_experience(text, top_k, threshold)`，没有 `search()` 方法。

### D5: Watcher 激活方式

选择：保留现有 cron job（10:00/20:00），在启动后手动触发一次验证。如果 `WatcherSkill` 不可用，记录 warning 但不崩溃。

## Risks / Trade-offs

- [Risk] DEMO_MODE Mock 响应可能与真实 LLM 行为差距大 → 接受，Mock 只是链路验证工具
- [Risk] `test_circuit_breaker.py` 等测试可能涉及被删除的旧 API → 如果修不了就 skip + 注释原因
- [Risk] Watcher 首次真实运行可能触发意外的 DB 查询 → 先在测试环境验证
