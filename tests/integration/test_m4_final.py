"""
M4 Phase 3+4 集成测试 — 任务图 + 工作区隔离

验证：TaskGraph 恢复、Workspace 路径防护、Container 完整架构

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest

from src.memory_palace.core.container import AppContainer


class TestTaskGraph:

    def test_reload_from_db_no_tasks(self):
        """空表 reload_from_db 不报错"""
        from src.memory_palace.core.task_graph import TaskGraph
        tg = TaskGraph()
        # Should complete without error when no tasks exist
        import asyncio
        asyncio.run(tg.reload_from_db())

    def test_container_has_task_graph(self):
        """Container 暴露 task_graph"""
        c = AppContainer()
        tg = c.task_graph
        assert tg is not None
        c.reset()


class TestWorkspace:

    def test_path_traversal_detected(self):
        """路径遍历攻击被拦截"""
        from pathlib import Path
        from src.memory_palace.core.workspace import Workspace
        ws = Workspace(workspace_id="test_task", base_path=Path("/tmp/test_ws"))
        # workspace path = /tmp/test_ws/test_task
        ws_path = ws.path
        safe = ws._validate_path(ws_path / "subdir" / "file.txt")
        assert safe is not None
        import pytest as pt
        with pt.raises(ValueError):
            ws._validate_path(ws_path / ".." / ".." / ".." / "etc" / "passwd")

    def test_container_has_workspace(self):
        """Container 暴露 workspace"""
        c = AppContainer()
        ws = c.workspace
        assert ws is not None
        c.reset()


class TestFinalArchitecture:

    def test_container_has_all_8_services(self):
        """Container 提供全部 8 个服务：最终架构 = C"""
        c = AppContainer()
        services = [
            c.db_client,
            c.vector_store,
            c.llm_client,
            c.wechat_client,
            c.context_tier,
            c.agent_memory,
            c.permission_engine,
            c.tool_executor,
            c.task_graph,
            c.workspace,
        ]
        # vector_store and wechat_client may be None without env vars
        core_services = services[:4]  # db, vector, llm, wechat
        phase_services = services[4:]  # context_tier through workspace
        assert c.db_client is not None
        assert c.llm_client is not None
        assert all(s is not None for s in phase_services), "All Phase services should be available"
        c.reset()
