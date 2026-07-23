"""
任务依赖图 (Task Graph)

核心职责:
1. 管理任务的生命周期 (PENDING -> RUNNING -> DONE/FAILED)
2. 支持任务依赖关系 (Task A 完成后 Task B 才能执行)
3. 持久化任务状态，Docker 重启后可恢复
4. 提供 TodoWrite 工具供 Agent 拆分大目标

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "PENDING"      # 等待执行
    RUNNING = "RUNNING"      # 执行中
    DONE = "DONE"           # 已完成
    FAILED = "FAILED"        # 失败 (重试次数耗尽)
    BLOCKED = "BLOCKED"      # 等待依赖任务


@dataclass
class Task:
    """
    任务数据模型

    支持依赖关系: dependencies 列表中的任务全部 DONE 后，当前任务才可执行
    """
    id: str                    # UUID
    session_id: str            # 所属会话
    description: str            # 任务描述
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = field(default_factory=list)  # 前置任务 ID 列表
    result: Optional[Dict] = None
    error: Optional[str] = None
    assigned_agent: Optional[str] = None
    created_at: float = 0
    updated_at: float = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    attempts: int = 0
    max_attempts: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "description": self.description,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "result": self.result,
            "error": self.error,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            description=data["description"],
            status=TaskStatus(data.get("status", "PENDING")),
            dependencies=data.get("dependencies", []),
            result=data.get("result"),
            error=data.get("error"),
            assigned_agent=data.get("assigned_agent"),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3)
        )


class TaskGraph:
    """
    任务依赖图管理器

    使用示例:
        graph = TaskGraph()

        # 创建任务
        task1 = await graph.create_task(session_id, "搜索信息")
        task2 = await graph.create_task(session_id, "整理报告", dependencies=[task1.id])

        # 获取可执行任务
        runnable = await graph.get_runnable_tasks(session_id)

        # 完成任务
        await graph.complete_task(task1.id, result={"found": True})

        # Docker 重启后恢复
        await graph.reload_from_db()
    """

    def __init__(self):
        # 内存缓存: task_id -> Task
        self._tasks: Dict[str, Task] = {}
        # session_id -> [task_ids]
        self._session_tasks: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        session_id: str,
        description: str,
        dependencies: Optional[List[str]] = None,
        assigned_agent: Optional[str] = None
    ) -> Task:
        """
        创建新任务

        Args:
            session_id: 会话 ID
            description: 任务描述
            dependencies: 前置任务 ID 列表
            assigned_agent: 分配的 Agent 名称

        Returns:
            创建的 Task 对象
        """
        async with self._lock:
            task_id = str(uuid.uuid4())
            now = time.time()

            # 检查依赖是否全部完成，否则标记 BLOCKED
            deps = dependencies or []
            blocked = False
            for dep_id in deps:
                dep_task = self._tasks.get(dep_id)
                if dep_task is None or dep_task.status != TaskStatus.DONE:
                    blocked = True
                    break

            task = Task(
                id=task_id,
                session_id=session_id,
                description=description,
                dependencies=deps,
                assigned_agent=assigned_agent,
                status=TaskStatus.BLOCKED if blocked else TaskStatus.PENDING,
                created_at=now,
                updated_at=now
            )

            self._tasks[task_id] = task

            if session_id not in self._session_tasks:
                self._session_tasks[session_id] = []
            self._session_tasks[session_id].append(task_id)

            # 持久化到数据库
            await self._persist_task(task)

            logger.debug(
                f"[TaskGraph] 创建任务 {task_id}: {description[:50]}... "
                f"(deps: {len(dependencies or [])})"
            )

            return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)

    async def get_runnable_tasks(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Task]:
        """
        获取可执行的任务 (依赖已满足)

        Args:
            session_id: 会话 ID
            limit: 返回数量限制

        Returns:
            可执行任务列表
        """
        if session_id not in self._session_tasks:
            return []

        runnable = []

        for task_id in self._session_tasks[session_id]:
            task = self._tasks.get(task_id)
            if not task:
                continue

            if task.status != TaskStatus.PENDING:
                continue

            # 检查依赖是否全部完成
            deps_met = all(
                self._tasks.get(dep_id) and
                self._tasks[dep_id].status == TaskStatus.DONE
                for dep_id in task.dependencies
            )

            if deps_met:
                runnable.append(task)

            if len(runnable) >= limit:
                break

        return runnable

    async def start_task(
        self,
        task_id: str,
        agent_name: Optional[str] = None
    ) -> Optional[Task]:
        """
        标记任务开始执行

        Args:
            task_id: 任务 ID
            agent_name: 执行 Agent 名称

        Returns:
            更新后的 Task
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[TaskGraph] 任务不存在: {task_id}")
                return None

            if task.status != TaskStatus.PENDING:
                logger.warning(
                    f"[TaskGraph] 任务 {task_id} 状态不是 PENDING: {task.status}"
                )
                return task

            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            task.updated_at = time.time()
            if agent_name:
                task.assigned_agent = agent_name
            task.attempts += 1

            await self._persist_task(task)

            logger.info(
                f"[TaskGraph] 任务开始执行 {task_id}: "
                f"{task.description[:50]}... (attempt {task.attempts})"
            )

            return task

    async def complete_task(
        self,
        task_id: str,
        result: Optional[Dict] = None
    ) -> Optional[Task]:
        """
        标记任务完成

        Args:
            task_id: 任务 ID
            result: 任务结果

        Returns:
            更新后的 Task
        """
        # 先收集需要的数据（持有锁的时间尽量短）
        dependent_ids_to_unblock = []

        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[TaskGraph] 任务不存在: {task_id}")
                return None

            task.status = TaskStatus.DONE
            task.result = result
            task.completed_at = time.time()
            task.updated_at = time.time()

            # 收集需要解除阻塞的任务 ID（不直接在锁内做 IO）
            for t in self._tasks.values():
                if task_id in t.dependencies and t.status == TaskStatus.BLOCKED:
                    dependent_ids_to_unblock.append(t.id)

            # 先持久化主任务状态
            await self._persist_task(task)

            logger.info(f"[TaskGraph] 任务完成 {task_id}: {task.description[:50]}...")

        # 在锁外解除依赖任务的阻塞（避免长时间持锁）
        for dep_id in dependent_ids_to_unblock:
            await self._unblock_single_task(dep_id)

        return task

    async def fail_task(
        self,
        task_id: str,
        error: str
    ) -> Optional[Task]:
        """
        标记任务失败

        Args:
            task_id: 任务 ID
            error: 错误信息

        Returns:
            更新后的 Task
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[TaskGraph] 任务不存在: {task_id}")
                return None

            task.error = error
            task.updated_at = time.time()

            # 检查是否超过最大重试次数
            if task.attempts >= task.max_attempts:
                task.status = TaskStatus.FAILED
                task.completed_at = time.time()
                logger.error(
                    f"[TaskGraph] 任务失败 (重试耗尽) {task_id}: {error}"
                )
            else:
                # 重置为 PENDING 等待重试
                task.status = TaskStatus.PENDING
                task.error = None
                logger.warning(
                    f"[TaskGraph] 任务失败 (将重试) {task_id}: {error}"
                )

            await self._persist_task(task)
            return task

    async def _unblock_single_task(self, task_id: str):
        """解除单个任务的阻塞状态"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if task.status == TaskStatus.BLOCKED:
                task.status = TaskStatus.PENDING
                await self._persist_task(task)
                logger.debug(f"[TaskGraph] 任务 {task.id} 解除阻塞")

    async def get_session_tasks(
        self,
        session_id: str,
        include_subgraph: bool = True
    ) -> List[Task]:
        """
        获取会话的所有任务

        Args:
            session_id: 会话 ID
            include_subgraph: 是否包含依赖的子任务

        Returns:
            任务列表

        Raises:
            ValueError: 如果检测到循环依赖
        """
        if session_id not in self._session_tasks:
            return []

        tasks = []
        visited = set()
        in_progress = set()  # 检测循环依赖

        def collect_task(task_id: str):
            if task_id in visited:
                return
            if task_id in in_progress:
                # 循环依赖检测
                raise ValueError(
                    f"循环依赖检测: task {task_id} 依赖链中存在循环"
                )
            in_progress.add(task_id)

            task = self._tasks.get(task_id)
            if task:
                tasks.append(task)
                for dep_id in task.dependencies:
                    collect_task(dep_id)

            in_progress.remove(task_id)
            visited.add(task_id)

        try:
            for task_id in self._session_tasks[session_id]:
                collect_task(task_id)
        except ValueError as e:
            logger.error(f"[TaskGraph] {e}")
            raise

        return sorted(tasks, key=lambda t: t.created_at)

    async def get_session_stats(self, session_id: str) -> Dict[str, int]:
        """获取会话任务统计"""
        tasks = await self.get_session_tasks(session_id)

        stats = {
            "total": len(tasks),
            "pending": 0,
            "running": 0,
            "done": 0,
            "failed": 0,
            "blocked": 0
        }

        for task in tasks:
            stats[task.status.value.lower()] += 1

        return stats

    async def reload_from_db(self):
        """从数据库恢复任务（启动时调用）。PENDING 恢复，RUNNING 重置为 PENDING。"""
        try:
            from ..knowledge.db_client import db_client
            if not db_client:
                return

            rows = await db_client.fetch_all(
                "SELECT * FROM tasks WHERE status IN (?, ?) ORDER BY created_at ASC",
                (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
            )
            recovered = 0
            reset_running = 0
            for row in rows:
                task = Task.from_dict(dict(row))
                self._tasks[task.id] = task
                if task.session_id not in self._session_tasks:
                    self._session_tasks[task.session_id] = []
                if task.id not in self._session_tasks[task.session_id]:
                    self._session_tasks[task.session_id].append(task.id)
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.PENDING
                    task.error = "任务在重启后自动重置"
                    task.updated_at = time.time()
                    await self._persist_task(task)
                    reset_running += 1
                else:
                    recovered += 1

            if recovered or reset_running:
                logger.info(
                    f"[TaskGraph] 从数据库恢复: {recovered} PENDING, {reset_running} RUNNING→PENDING"
                )
        except Exception as e:
            logger.warning(f"[TaskGraph] 数据库恢复失败（不影响启动）: {e}")

    async def _persist_task(self, task: Task):
        """持久化任务到数据库"""
        try:
            from ..knowledge.db_client import db_client

            if not db_client:
                return

            await db_client.execute(
                """
                INSERT OR REPLACE INTO tasks
                (id, session_id, description, status, dependencies,
                 result, error, assigned_agent, created_at, updated_at,
                 started_at, completed_at, attempts, max_attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.session_id,
                    task.description,
                    task.status.value,
                    json.dumps(task.dependencies),
                    json.dumps(task.result) if task.result else None,
                    task.error,
                    task.assigned_agent,
                    task.created_at,
                    task.updated_at,
                    task.started_at,
                    task.completed_at,
                    task.attempts,
                    task.max_attempts
                )
            )

        except Exception as e:
            logger.error(f"[TaskGraph] 任务持久化失败: {e}")


# 全局单例
task_graph = TaskGraph()


def get_task_graph() -> TaskGraph:
    """获取任务图管理器单例"""
    return task_graph
