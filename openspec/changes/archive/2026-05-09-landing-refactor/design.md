## Context

Memory Palace OS 当前状态：3000+ 行 Python，7 Agent，4 Phase 架构。能启动（uvicorn main:app 成功），但：

- 启动日志中有 4 处 error（`no such table: tasks`、`no such table: approval_requests`、`Schedulers cannot be serialized`、`UnicodeEncodeError` emoji 编码）
- 模块级副作用：import 时即初始化 ChromaDB、embedding 模型、企微客户端
- `_default_route` 返回不存在的 Agent 名 `deep_interview`
- `requirements.txt` 缺 `pytz`，`httpx` 重复声明
- Phase 2-4 代码在启动恢复阶段报错但不阻塞（被 catch 了）
- Windows 11 开发环境，GBK 控制台

目标：修复所有已知 bug，消除架构异味，Phase 2-4 退回 stub，交付干净可迭代的基底。

## Goals / Non-Goals

**Goals:**
- P0 bug 清零：模块级副作用全部改为懒加载
- P1 bug 清零：DB 初始化顺序、Agent 名称、重复路由、config 命名、硬编码 URL
- Phase 2-4 代码退回 stub，不报错不挡路
- `DEMO_MODE=true` 下全链路可验证
- 5 个核心集成测试通过
- `requirements.txt` 完整，`pip install -r requirements.txt` 无报错

**Non-Goals:**
- 不新增任何功能特性
- 不改变任何 API 端点签名
- 不改变 Agent 业务逻辑
- 不引入新依赖（如 DI 容器）
- 不写 Phase 2-4 的实现代码

## Decisions

### D1: 懒加载模式 — 工厂函数 vs 模块级 `__getattr__`

选择：显式 `get_xxx()` 工厂函数。

理由：Python 3.7+ 支持 `__getattr__` 模块级懒加载，但 `get_xxx()` 更显式、可测试、不依赖 Python 版本特性。每个懒加载对象提供一个 `_instance` 私有变量 + `get_xxx()` 函数。

被影响的模块：
- `knowledge/vector_store.py`：`vector_client` → `get_vector_client()`
- `tools/embedding_client.py`：`embedding_client` → `get_embedding_client()`
- `tools/wechat_client.py`：`wechat_client` → `get_wechat_client()`

### D2: DB 初始化时机

选择：在 lifespan 中，TaskGraph/Permission 恢复之前，显式调用 `init_database()`。

理由：`init_database()` 使用 `CREATE TABLE IF NOT EXISTS`，幂等安全。放在恢复之前确保表存在。当前 `main.py` lifespan 从未调用 `init_db()`，只有命令行手动执行时才建表。

### D3: Phase 2-4 stub 策略

选择：保留类和接口签名，`reload_from_db()` 改为 `async` no-op（直接 return，不打 error 日志）。

理由：不删代码——设计文档已规划这些 Phase 的激活顺序。stub 不报错意味着启动日志干净，后续激活时只需取消注释 + 补充实现。

涉及文件：
- `core/permissions.py`：`PermissionEngine.reload_from_db()` → no-op
- `core/task_graph.py`：`TaskGraph.reload_from_db()` → no-op
- `core/workspace.py`：保留类定义，不改变
- `core/agent_memory.py`：保留类定义，不改变
- `core/context_tier.py`：保留类定义，不改变

### D4: gateway.py 重复路由处理

选择：删除 `create_app()` 函数，保留所有 router 定义。

理由：`main.py` 已经定义并启动 FastAPI app。`gateway.py` 的 `create_app()` 创建了另一个 FastAPI 实例但从未被调用（`main.py` 只用 `gateway.router`）。验证：grep 确认无外部引用后删除。

### D5: config 模块重命名

选择：`config/init.py` → `config/config_manager.py`，`config/__init__.py` 的 import 路径同步更新。

理由：`init` 是 Python 内置模块名（`__init__`）。虽然当前能工作（本地包优先），但在某些 IDE、linter 和测试框架下会触发奇怪的导入问题。

## Risks / Trade-offs

- [Risk] 懒加载后首次调用有延迟（ChromaDB 初始化 ~2s）→ 接受，比 import 时崩溃好
- [Risk] stub 的 Phase 代码可能被误认为已实现 → 在每个 stub 函数上加 `# STUB: Phase N, to be implemented` 注释
- [Risk] `tools/db_client.py` 删除可能破坏未知引用 → 先 grep 全局引用再删
