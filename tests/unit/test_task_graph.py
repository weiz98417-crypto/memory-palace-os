"""
任务依赖图 (TaskGraph) 单元测试

覆盖: 任务创建、依赖解析、状态转换、DB 持久化

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import time
from src.memory_palace.core.task_graph import (
    Task, TaskStatus, TaskGraph,
)


class TestTaskModel:

    def test_task_creation_defaults(self):
        """新任务默认状态为 PENDING"""
        task = Task(
            id="task-1",
            session_id="session-1",
            description="测试任务",
        )
        assert task.status == TaskStatus.PENDING
        assert task.dependencies == []
        assert task.attempts == 0
        assert task.max_attempts == 3
        assert task.result is None
        assert task.error is None

    def test_task_with_dependencies(self):
        """任务可以指定依赖列表（状态由 create_task 管理，__init__ 默认为 PENDING）"""
        task = Task(
            id="task-2",
            session_id="session-1",
            description="依赖任务 B",
            dependencies=["task-1"],
        )
        assert "task-1" in task.dependencies
        # __init__ 不做依赖检查，create_task() 负责设 BLOCKED

    def test_task_to_dict(self):
        """to_dict 返回完整字典"""
        now = time.time()
        task = Task(
            id="task-3",
            session_id="session-1",
            description="序列化测试",
            status=TaskStatus.RUNNING,
            dependencies=["task-1", "task-2"],
            created_at=now,
            updated_at=now,
        )
        d = task.to_dict()
        assert d["id"] == "task-3"
        assert d["session_id"] == "session-1"
        assert d["status"] == "RUNNING"
        assert d["dependencies"] == ["task-1", "task-2"]


class TestTaskStatus:

    def test_all_statuses_defined(self):
        """所有状态枚举值存在"""
        assert TaskStatus.PENDING == "PENDING"
        assert TaskStatus.RUNNING == "RUNNING"
        assert TaskStatus.DONE == "DONE"
        assert TaskStatus.FAILED == "FAILED"
        assert TaskStatus.BLOCKED == "BLOCKED"

    def test_status_value_comparison(self):
        """状态可以直接与字符串比较"""
        assert TaskStatus.DONE != "RUNNING"


class TestTaskGraph:

    @pytest.fixture
    def graph(self):
        return TaskGraph()

    def test_graph_initialization(self, graph):
        """TaskGraph 初始状态为空"""
        assert isinstance(graph._tasks, dict)

    @pytest.mark.asyncio
    async def test_create_task(self, graph):
        """创建任务并加入图"""
        task = await graph.create_task(
            session_id="session-1",
            description="完成 LLM 消毒",
        )
        assert task.id is not None
        assert task.description == "完成 LLM 消毒"
        assert task.status == TaskStatus.PENDING

    @pytest.mark.asyncio
    async def test_create_task_with_unresolved_dependency(self, graph):
        """创建带未完成依赖的任务 → BLOCKED"""
        task_a = await graph.create_task(session_id="s1", description="Task A")
        # task_a 是 PENDING (not DONE) → task_b 应该 BLOCKED
        task_b = await graph.create_task(
            session_id="s1",
            description="Task B (depends on A)",
            dependencies=[task_a.id],
        )
        assert task_b.status == TaskStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_get_task_nonexistent(self, graph):
        """不存在的任务返回 None"""
        result = await graph.get_task("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_reload_from_db_empty(self, graph):
        """空数据库 reload 不崩溃"""
        await graph.reload_from_db()

    @pytest.mark.asyncio
    async def test_complete_nonexistent_task(self, graph):
        """完成不存在的任务返回 None"""
        result = await graph.complete_task("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_task_stores_result(self, graph):
        """完成任务时传入的 result 被存储"""
        task = await graph.create_task(session_id="s1", description="Done task")
        result_data = {"summary": "completed"}
        await graph.complete_task(task.id, result=result_data)
        updated = await graph.get_task(task.id)
        assert updated.status == TaskStatus.DONE
        assert updated.result == result_data
