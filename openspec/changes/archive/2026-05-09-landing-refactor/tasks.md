# Tasks: 落地级重构

## 1. 依赖与基础设施

- [x] 1.1 requirements.txt：添加 `pytz`，删除重复的 `httpx>=0.27.0`（第 41 行）
- [x] 1.2 tools/logger_config.py：Windows 下 sys.stdout.reconfigure(encoding="utf-8")
- [x] 1.3 knowledge/db_client.py 和 knowledge/db_init.py：DB 路径改为基于项目根目录的绝对路径

## 2. 模块级副作用清零（P0 bugs）

- [x] 2.1 knowledge/vector_store.py：删模块级 `PalaceVectorStore()`，新增 `get_vector_client()` 工厂函数
- [x] 2.2 knowledge/__init__.py：不再 import `vector_client`，改为导出 `get_vector_client`
- [x] 2.3 全局搜索所有 `vector_client` 引用，改为调用 `get_vector_client()`
- [x] 2.4 tools/embedding_client.py：模块级 GPU 检测/模型加载移到 `get_embedding_client()` 内
- [x] 2.5 tools/wechat_client.py：模块级初始化移到 `get_wechat_client()` 内
- [x] 2.6 core/scheduler.py：WatcherSkill 导入移到回调函数内；修复 APScheduler 序列化 bug；删除 sys_scheduler

## 3. 运行时逻辑修复（P1 bugs）

- [x] 3.1 main.py lifespan：在 TaskGraph/Permission 恢复前先调用 `init_database()`
- [x] 3.2 core/orchestrator.py:260：`_default_route()` 中 `target_agent` 从 `"deep_interview"` 改为 `"persona_extract"`
- [x] 3.3 core/gateway.py：删除 `create_app()` 和 `lifespan()` 函数（grep 确认无外部引用）
- [x] 3.4 config/init.py → config/config_manager.py：重命名 + 更新 `config/__init__.py` 的 import
- [x] 3.5 skills/context_trigger/skill.py：`example.com` → `os.getenv("CT_PUSH_URL", "http://localhost:8000")`；加 `import os`

## 4. 清理与精简

- [x] 4.1 tools/db_client.py 与 knowledge/db_client.py 确认不是重复（前者是 SQLAlchemy ORM，后者是 aiosqlite 异步），加注释说明各自用途
- [x] 4.2 core/permissions.py：`reload_from_db()` 改为 no-op（加 `# STUB: Phase 2` 注释）
- [x] 4.3 core/task_graph.py：`reload_from_db()` 改为 no-op（加 `# STUB: Phase 3` 注释）
- [x] 4.4 core/workspace.py、agent_memory.py、context_tier.py：文件头部加 STUB 标记
- [x] 4.5 skills/__init__.py：确认 `_auto_register_skills()` 仅在 lifespan 中调用（已是正确的，无需修改）
- [x] 4.6 main.py lifespan：Phase 恢复已使用 warning 级别（已是正确的，无需修改）

## 5. 测试

- [x] 5.1 tests/integration/test_core_pipeline.py：消息入队 → 消费者取出 → Orchestrator 路由
- [x] 5.2 tests/integration/test_context_trigger.py：关键词命中 → 路由到 Commander
- [x] 5.3 tests/integration/test_routing.py：非紧急消息 → 路由到 Persona
- [x] 5.4 tests/integration/test_demo_full_chain.py：DEMO_MODE=true 全链路
- [x] 5.5 tests/integration/test_sla_recording.py：SLA 响应时间写入数据库

## 6. 最终验证

- [x] 6.1 `pip install -r requirements.txt` 无报错
- [x] 6.2 `python -c "from main import app"` 无 error 日志
- [x] 6.3 `DEMO_MODE=true uvicorn main:app` 启动无 error 级别日志，所有表创建成功
- [x] 6.4 `curl http://localhost:8000/health` 返回 `{"status": "ok"}`
- [x] 6.5 模拟企微 POST 到 `/webhook/v1/wechat` 返回 "success"
- [x] 6.6 5 个新集成测试全通过 (10/10)
