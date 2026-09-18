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

from .business_ids import build_business_id


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "PENDING"      # 等待执行
    RUNNING = "RUNNING"      # 执行中
    DONE = "DONE"           # 已完成
    FAILED = "FAILED"        # 失败 (重试次数耗尽)
    BLOCKED = "BLOCKED"      # 等待依赖任务
    STAGED = "STAGED"


@dataclass
class Task:
    """
    任务数据模型

    支持依赖关系: dependencies 列表中的任务全部 DONE 后，当前任务才可执行
    """
    id: str                    # UUID
    session_id: str            # 所属会话
    description: str            # 任务描述
    business_id: str = ""
    venue_id: str = ""
    event_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = field(default_factory=list)  # 前置任务 ID 列表
    due_at: Optional[float] = None
    result_schema_json: Dict[str, Any] = field(default_factory=dict)
    evidence_refs_json: List[Dict[str, Any]] = field(default_factory=list)
    result: Optional[Dict] = None
    error: Optional[str] = None
    block_reason: Optional[str] = None
    assigned_agent: Optional[str] = None
    assigned_user_id: Optional[str] = None
    decomposition_id: Optional[str] = None
    created_at: float = 0
    updated_at: float = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    attempts: int = 0
    max_attempts: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "business_id": self.business_id,
            "session_id": self.session_id,
            "venue_id": self.venue_id,
            "event_id": self.event_id,
            "description": self.description,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "due_at": self.due_at,
            "result_schema_json": self.result_schema_json,
            "evidence_refs_json": self.evidence_refs_json,
            "result": self.result,
            "error": self.error,
            "block_reason": self.block_reason,
            "assigned_agent": self.assigned_agent,
            "assigned_user_id": self.assigned_user_id,
            "decomposition_id": self.decomposition_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        dependencies = data.get("dependencies", [])
        result = data.get("result")
        result_schema = data.get("result_schema_json", {})
        evidence_refs = data.get("evidence_refs_json", [])
        if isinstance(dependencies, str):
            dependencies = json.loads(dependencies or "[]")
        if isinstance(result, str):
            result = json.loads(result) if result else None
        if isinstance(result_schema, str):
            result_schema = json.loads(result_schema or "{}")
        if isinstance(evidence_refs, str):
            evidence_refs = json.loads(evidence_refs or "[]")
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            description=data["description"],
            business_id=data.get("business_id", ""),
            venue_id=data.get("venue_id", ""),
            event_id=data.get("event_id"),
            status=TaskStatus(data.get("status", "PENDING")),
            dependencies=dependencies,
            due_at=data.get("due_at"),
            result_schema_json=result_schema,
            evidence_refs_json=evidence_refs,
            result=result,
            error=data.get("error"),
            block_reason=data.get("block_reason"),
            assigned_agent=data.get("assigned_agent"),
            assigned_user_id=data.get("assigned_user_id"),
            decomposition_id=data.get("decomposition_id"),
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

    def __init__(self, db_client=None):
        # 内存缓存: task_id -> Task
        self._tasks: Dict[str, Task] = {}
        # session_id -> [task_ids]
        self._session_tasks: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()
        self._db = db_client

    def set_database(self, db_client) -> None:
        self._db = db_client

    async def create_task(
        self,
        session_id: str,
        description: str,
        dependencies: Optional[List[str]] = None,
        assigned_agent: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        max_attempts: int = 3,
        venue_id: str = "",
        event_id: Optional[str] = None,
        due_at: Optional[float] = None,
        result_schema_json: Optional[Dict[str, Any]] = None,
        evidence_refs_json: Optional[List[Dict[str, Any]]] = None,
        defer_activation: bool = False,
        decomposition_id: Optional[str] = None,
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
                business_id=build_business_id("RW", task_id, now),
                venue_id=venue_id,
                event_id=event_id,
                dependencies=deps,
                due_at=due_at,
                result_schema_json=result_schema_json or {},
                evidence_refs_json=evidence_refs_json or [],
                assigned_agent=assigned_agent,
                assigned_user_id=assigned_user_id,
                decomposition_id=decomposition_id,
                max_attempts=max_attempts,
                status=TaskStatus.STAGED if defer_activation else (
                    TaskStatus.BLOCKED if blocked else TaskStatus.PENDING
                ),
                created_at=now,
                updated_at=now
            )

            self._tasks[task_id] = task

            if session_id not in self._session_tasks:
                self._session_tasks[session_id] = []
            self._session_tasks[session_id].append(task_id)

            try:
                await self._persist_task(task)
            except Exception:
                self._tasks.pop(task_id, None)
                session_tasks = self._session_tasks.get(session_id, [])
                if task_id in session_tasks:
                    session_tasks.remove(task_id)
                if not session_tasks:
                    self._session_tasks.pop(session_id, None)
                raise

            logger.debug(
                f"[TaskGraph] 创建任务 {task_id}: {description[:50]}... "
                f"(deps: {len(dependencies or [])})"
            )

            return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)

    async def assign_task(
        self,
        task_id: str,
        *,
        assigned_user_id: Optional[str] = None,
        assigned_agent: Optional[str] = None,
    ) -> Optional[Task]:
        """更新任务负责人或执行 Agent。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.assigned_user_id = assigned_user_id
            if assigned_agent is not None:
                task.assigned_agent = assigned_agent
            task.updated_at = time.time()
            await self._persist_task(task)
            return task

    async def delete_tasks(self, task_ids: List[str], *, venue_id: str) -> None:
        """删除一组任务并同步清理内存任务图。"""
        unique_ids = list(dict.fromkeys(task_ids))
        if not unique_ids:
            return
        async with self._lock:
            if self._db:
                placeholders = ",".join("?" for _ in unique_ids)
                await self._db.execute(
                    f"DELETE FROM tasks WHERE venue_id = ? AND id IN ({placeholders})",
                    (venue_id, *unique_ids),
                )
            affected_sessions = {
                self._tasks[task_id].session_id
                for task_id in unique_ids
                if task_id in self._tasks
                and self._tasks[task_id].venue_id == venue_id
            }
            for task_id in unique_ids:
                task = self._tasks.get(task_id)
                if task and task.venue_id == venue_id:
                    self._tasks.pop(task_id, None)
            for session_id in affected_sessions:
                remaining = [
                    task_id
                    for task_id in self._session_tasks.get(session_id, [])
                    if task_id not in unique_ids
                ]
                if remaining:
                    self._session_tasks[session_id] = remaining
                else:
                    self._session_tasks.pop(session_id, None)

    async def activate_tasks(self, task_ids: List[str]) -> List[Task]:
        """一次发布一组暂存任务，并返回发布后的任务。"""
        unique_ids = list(dict.fromkeys(task_ids))
        if not unique_ids:
            return []
        async with self._lock:
            tasks = [self._tasks.get(task_id) for task_id in unique_ids]
            if any(task is None for task in tasks):
                raise ValueError("待发布任务不完整")
            staged_tasks = [task for task in tasks if task.status == TaskStatus.STAGED]
            desired_statuses = []
            for task in staged_tasks:
                dependencies_done = all(
                    self._tasks.get(dep_id)
                    and self._tasks[dep_id].status == TaskStatus.DONE
                    for dep_id in task.dependencies
                )
                desired_statuses.append(
                    TaskStatus.PENDING if dependencies_done else TaskStatus.BLOCKED
                )
            now = time.time()
            if self._db and staged_tasks:
                cases = " ".join("WHEN ? THEN ?" for _ in staged_tasks)
                placeholders = ",".join("?" for _ in staged_tasks)
                parameters = []
                for task, desired_status in zip(staged_tasks, desired_statuses):
                    parameters.extend((task.id, desired_status.value))
                parameters.extend((now, *(task.id for task in staged_tasks)))
                updated = await self._db.execute(
                    f"""
                    UPDATE tasks
                    SET status = CASE id {cases} ELSE status END, updated_at = ?
                    WHERE id IN ({placeholders}) AND status = 'STAGED'
                    """,
                    tuple(parameters),
                )
                if updated != len(staged_tasks):
                    raise RuntimeError("暂存任务未能完整发布")
            for task, desired_status in zip(staged_tasks, desired_statuses):
                task.status = desired_status
                task.updated_at = now
            return tasks

    async def retry_task(self, task_id: str) -> Optional[Task]:
        """将失败任务恢复为可执行状态，保留历史尝试次数。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.status != TaskStatus.FAILED:
                return task
            task.status = TaskStatus.PENDING
            task.error = None
            task.block_reason = None
            task.completed_at = None
            task.max_attempts = max(task.max_attempts, task.attempts + 1)
            task.updated_at = time.time()
            await self._persist_task(task)
            return task

    async def reconcile_dependencies(self, session_id: Optional[str] = None) -> List[Task]:
        """根据当前依赖终态修复 PENDING/BLOCKED，并同步持久化。"""
        async with self._lock:
            changed: List[tuple[Task, TaskStatus]] = []
            for task in self._tasks.values():
                if session_id is not None and task.session_id != session_id:
                    continue
                if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
                    continue
                if task.status == TaskStatus.BLOCKED and task.block_reason:
                    continue
                dependencies_done = all(
                    self._tasks.get(dependency_id)
                    and self._tasks[dependency_id].status == TaskStatus.DONE
                    for dependency_id in task.dependencies
                )
                desired_status = (
                    TaskStatus.PENDING if dependencies_done else TaskStatus.BLOCKED
                )
                if task.status != desired_status:
                    changed.append((task, desired_status))

            if not changed:
                return []

            now = time.time()
            if self._db:
                status_cases = " ".join("WHEN ? THEN ?" for _ in changed)
                placeholders = ",".join("?" for _ in changed)
                parameters = []
                for task, desired_status in changed:
                    parameters.extend((task.id, desired_status.value))
                parameters.extend((now, *(task.id for task, _ in changed)))
                updated = await self._db.execute(
                    f"""
                    UPDATE tasks
                    SET status = CASE id {status_cases} ELSE status END,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    tuple(parameters),
                )
                if updated != len(changed):
                    raise RuntimeError("任务依赖状态未能完整持久化")

            for task, desired_status in changed:
                task.status = desired_status
                task.updated_at = now
            return [task for task, _ in changed]

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
        await self.reconcile_dependencies(session_id)
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
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[TaskGraph] 任务不存在: {task_id}")
                return None

            now = time.time()
            dependents_to_unblock = [
                candidate
                for candidate in self._tasks.values()
                if candidate.status == TaskStatus.BLOCKED
                and not candidate.block_reason
                and task_id in candidate.dependencies
                and all(
                    dependency_id == task_id
                    or (
                        self._tasks.get(dependency_id)
                        and self._tasks[dependency_id].status == TaskStatus.DONE
                    )
                    for dependency_id in candidate.dependencies
                )
            ]
            changed_tasks = [task, *dependents_to_unblock]

            if self._db:
                status_cases = " ".join("WHEN ? THEN ?" for _ in changed_tasks)
                placeholders = ",".join("?" for _ in changed_tasks)
                parameters = []
                for changed_task in changed_tasks:
                    parameters.extend(
                        (
                            changed_task.id,
                            TaskStatus.DONE.value
                            if changed_task.id == task_id
                            else TaskStatus.PENDING.value,
                        )
                    )
                parameters.extend(
                    (
                        task_id,
                        json.dumps(result) if result is not None else None,
                        task_id,
                        now,
                        now,
                        *(changed_task.id for changed_task in changed_tasks),
                    )
                )
                updated = await self._db.execute(
                    f"""
                    UPDATE tasks
                    SET status = CASE id {status_cases} ELSE status END,
                        result = CASE WHEN id = ? THEN ? ELSE result END,
                        completed_at = CASE WHEN id = ? THEN ? ELSE completed_at END,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    tuple(parameters),
                )
                if updated != len(changed_tasks):
                    raise RuntimeError("任务完成状态未能完整持久化")

            task.status = TaskStatus.DONE
            task.result = result
            task.completed_at = now
            task.updated_at = now
            for dependent in dependents_to_unblock:
                dependent.status = TaskStatus.PENDING
                dependent.updated_at = now

            logger.info(f"[TaskGraph] 任务完成 {task_id}: {task.description[:50]}...")

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

    async def block_task(self, task_id: str, reason: str) -> Optional[Task]:
        """Pause a running task until a manager explicitly resumes it."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.status != TaskStatus.RUNNING:
                return task
            task.status = TaskStatus.BLOCKED
            task.block_reason = reason
            task.updated_at = time.time()
            task.completed_at = None
            await self._persist_task(task)
            logger.info(f"[TaskGraph] 任务人工阻塞 {task_id}: {reason[:80]}")
            return task

    async def unblock_task(self, task_id: str) -> Optional[Task]:
        """Clear a manual block while preserving dependency-based blocking."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.status != TaskStatus.BLOCKED or not task.block_reason:
                return task
            dependencies_done = all(
                self._tasks.get(dependency_id)
                and self._tasks[dependency_id].status == TaskStatus.DONE
                for dependency_id in task.dependencies
            )
            task.block_reason = None
            task.status = (
                TaskStatus.PENDING if dependencies_done else TaskStatus.BLOCKED
            )
            task.updated_at = time.time()
            await self._persist_task(task)
            return task

    async def _unblock_single_task(self, task_id: str):
        """解除单个任务的阻塞状态"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            dependencies_done = all(
                self._tasks.get(dep_id)
                and self._tasks[dep_id].status == TaskStatus.DONE
                for dep_id in task.dependencies
            )
            if (
                task.status == TaskStatus.BLOCKED
                and not task.block_reason
                and dependencies_done
            ):
                task.status = TaskStatus.PENDING
                task.updated_at = time.time()
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
            "blocked": 0,
            "staged": 0,
        }

        for task in tasks:
            stats[task.status.value.lower()] += 1

        return stats

    async def reload_from_db(self):
        """从数据库恢复完整任务图，RUNNING 在重启后重置为 PENDING。"""
        if not self._db:
            return
        try:
            self._tasks.clear()
            self._session_tasks.clear()
            rows = await self._db.fetch_all("SELECT * FROM tasks ORDER BY created_at ASC")
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

            await self.reconcile_dependencies()
            await self._recover_decompositions_after_restart()

            if recovered or reset_running:
                logger.info(
                    f"[TaskGraph] 从数据库恢复: {recovered} PENDING, {reset_running} RUNNING→PENDING"
                )
        except Exception as e:
            logger.error(f"[TaskGraph] 数据库恢复失败: {e}")
            raise

    async def _recover_decompositions_after_restart(self) -> None:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM task_decompositions
            WHERE status IN ('PROCESSING', 'STAGED')
            ORDER BY created_at ASC
            """
        )
        for row in rows:
            decomposition_id = row["decomposition_id"]
            if row["status"] == "STAGED":
                task_ids = json.loads(row.get("task_ids") or "[]")
                if not task_ids or not row.get("response_json"):
                    logger.error(
                        f"[TaskGraph] 暂存任务分解记录不完整: {decomposition_id}"
                    )
                    continue
                try:
                    tasks = await self.activate_tasks(task_ids)
                    if len(tasks) != len(task_ids) or any(
                        task.status == TaskStatus.STAGED for task in tasks
                    ):
                        raise RuntimeError("暂存任务尚未完整发布")
                    updated = await self._db.execute(
                        """
                        UPDATE task_decompositions
                        SET status = 'COMPLETED', error = NULL, updated_at = ?
                        WHERE decomposition_id = ? AND status = 'STAGED'
                        """,
                        (time.time(), decomposition_id),
                    )
                    if updated != 1:
                        raise RuntimeError("任务分解完成状态未能持久化")
                except Exception as error:
                    logger.error(
                        f"[TaskGraph] 暂存任务分解恢复失败 {decomposition_id}: {error}"
                    )
                continue

            cleanup_started_at = time.time()
            claimed = await self._db.execute(
                """
                UPDATE task_decompositions
                SET error = 'processing_cleanup_pending', updated_at = ?
                WHERE decomposition_id = ? AND venue_id = ?
                  AND status = 'PROCESSING' AND trace_id = ? AND updated_at = ?
                """,
                (
                    cleanup_started_at,
                    decomposition_id,
                    row["venue_id"],
                    row["trace_id"],
                    row["updated_at"],
                ),
            )
            if claimed != 1:
                continue
            orphan_rows = await self._db.fetch_all(
                """
                SELECT id FROM tasks
                WHERE venue_id = ? AND decomposition_id = ? AND status = 'STAGED'
                """,
                (row["venue_id"], decomposition_id),
            )
            task_ids = json.loads(row.get("task_ids") or "[]")
            cleanup_task_ids = list(
                dict.fromkeys([*task_ids, *(task["id"] for task in orphan_rows)])
            )
            await self.delete_tasks(cleanup_task_ids, venue_id=row["venue_id"])
            audit_conditions = [
                "(action = 'TASK_DECOMPOSED' AND resource_type = 'task_decomposition' AND resource_id = ?)"
            ]
            audit_parameters = [row["venue_id"], decomposition_id]
            if cleanup_task_ids:
                task_placeholders = ",".join("?" for _ in cleanup_task_ids)
                audit_conditions.append(
                    "(action = 'TASK_CREATED' AND resource_type = 'task' "
                    f"AND resource_id IN ({task_placeholders}))"
                )
                audit_parameters.extend(cleanup_task_ids)
            await self._db.execute(
                f"""
                DELETE FROM audit_logs
                WHERE venue_id = ? AND ({' OR '.join(audit_conditions)})
                """,
                tuple(audit_parameters),
            )
            activity_keys = [
                *(f"task-created:{task_id}" for task_id in cleanup_task_ids),
                f"task-decomposed:{decomposition_id}",
            ]
            activity_placeholders = ",".join("?" for _ in activity_keys)
            await self._db.execute(
                f"""
                DELETE FROM event_activities
                WHERE venue_id = ? AND idempotency_key IN ({activity_placeholders})
                """,
                (row["venue_id"], *activity_keys),
            )
            await self._db.execute(
                """
                UPDATE task_decompositions
                SET status = 'FAILED', error = 'processing_interrupted_by_restart',
                    updated_at = ?
                WHERE decomposition_id = ? AND venue_id = ? AND status = 'PROCESSING'
                  AND trace_id = ? AND error = 'processing_cleanup_pending'
                  AND updated_at = ?
                """,
                (
                    time.time(),
                    decomposition_id,
                    row["venue_id"],
                    row["trace_id"],
                    cleanup_started_at,
                ),
            )

    async def _persist_task(self, task: Task):
        """持久化任务到数据库"""
        if not self._db:
            return
        try:
            await self._db.execute(
                """
                INSERT INTO tasks
                (id, business_id, venue_id, session_id, event_id, description, status, dependencies,
                 due_at, result_schema_json, evidence_refs_json, result, error, block_reason,
                 assigned_agent, assigned_user_id, decomposition_id, created_at, updated_at,
                 started_at, completed_at, attempts, max_attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    business_id = excluded.business_id,
                    venue_id = excluded.venue_id,
                    session_id = excluded.session_id,
                    event_id = excluded.event_id,
                    description = excluded.description,
                    status = excluded.status,
                    dependencies = excluded.dependencies,
                    due_at = excluded.due_at,
                    result_schema_json = excluded.result_schema_json,
                    evidence_refs_json = excluded.evidence_refs_json,
                    result = excluded.result,
                    error = excluded.error,
                    block_reason = excluded.block_reason,
                    assigned_agent = excluded.assigned_agent,
                    assigned_user_id = excluded.assigned_user_id,
                    decomposition_id = excluded.decomposition_id,
                    updated_at = excluded.updated_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    attempts = excluded.attempts,
                    max_attempts = excluded.max_attempts
                """,
                (
                    task.id,
                    task.business_id,
                    task.venue_id,
                    task.session_id,
                    task.event_id,
                    task.description,
                    task.status.value,
                    json.dumps(task.dependencies),
                    task.due_at,
                    json.dumps(task.result_schema_json, ensure_ascii=False),
                    json.dumps(task.evidence_refs_json, ensure_ascii=False),
                    json.dumps(task.result) if task.result else None,
                    task.error,
                    task.block_reason,
                    task.assigned_agent,
                    task.assigned_user_id,
                    task.decomposition_id,
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
            raise


# 全局单例
task_graph = TaskGraph()


def get_task_graph() -> TaskGraph:
    """获取任务图管理器单例"""
    return task_graph
