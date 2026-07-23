## Why

`landing-refactor` 修好了基础设施：启动零 ERROR、懒加载、DB 初始化、核心链路跑通。但技能层仍有空洞——单元测试大量 FAIL、DEMO_MODE 不降级、路由冲突、`.env` 无 gitignore 保护导致 API key 泄露风险、MemoryOps RAG 检索接口不匹配、Watcher 从未真实运行。需要从"能跑"推进到"健全"。

## What Changes

- 创建 `.gitignore`，保护敏感文件（`.env`、`data/`、`__pycache__`）
- `llm_wrapper.py` 加 DEMO_MODE 检查，`true` 时返回 Mock 响应，零 API key 也能跑全链路
- 修复 `/admin` 和 `/api/v1/skills` 的 307 重定向问题
- 修复所有 FAIL 的单元测试（patch 路径、缺失依赖、API 签名变更）
- 修复 MemoryOps 的 RAG 检索调用（`search()` → `query_experience()`）
- 让 Watcher 定时巡检真实运行一次
- 补全 `requirements.txt`（`h2`、`pytest-mock`、`requests-mock`、`python-dotenv`）

## Capabilities

### New Capabilities
- `demo-mode`: `DEMO_MODE=true` 时全链路用 Mock 响应，不依赖外部 API
- `secure-defaults`: `.gitignore` 保护敏感文件，阻止 API key 和数据库被提交
- `route-fix`: `/admin` 和 `/api/v1/skills` 正常响应，无 307 重定向
- `test-health`: 所有已有单元测试 PASS（或明确标记 skip + 原因）

### Modified Capabilities
_无_

## Impact

- `llm_wrapper.py`：加 DEMO_MODE Mock 分支
- `main.py`：调整 StaticFiles mount 顺序
- `requirements.txt`：补 4 个依赖
- `.gitignore`：新建
- `tests/unit/test_vector_search.py`：fix patch 路径
- `tests/unit/test_orchestrator.py`、`test_hot_reload.py`、`test_circuit_breaker.py`：追踪修复
- `src/memory_palace/skills/memory_ops/skill.py`：fix API 调用
- 不影响：Agent 业务逻辑、API 端点签名、外部接口
