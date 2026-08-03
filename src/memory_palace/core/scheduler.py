"""PostgreSQL-backed Watcher scheduling for the formal runtime."""

from __future__ import annotations

import time
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .watcher_runtime import recover_interrupted_watcher_runs, run_watcher_policy


_last_watcher_run: float = 0.0


def get_last_watcher_run() -> float:
    return _last_watcher_run


class TaskScheduler:
    """Schedules persisted Watcher policies on the application event loop."""

    def __init__(self, container: Optional[Any] = None):
        self._container = container
        self.scheduler = AsyncIOScheduler(
            timezone="Asia/Shanghai",
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

    @property
    def _db(self):
        return getattr(self._container, "db_client", None)

    async def start(self) -> None:
        if self._db is not None:
            await recover_interrupted_watcher_runs(self._db)
        if not self.scheduler.running:
            self.scheduler.start()
        await self.reload_jobs()
        logger.success("⏱️ PostgreSQL 巡检策略调度器已启动")

    async def reload_jobs(self) -> None:
        """Rebuild runtime jobs from persisted enabled policies."""
        for job in self.scheduler.get_jobs():
            if job.id.startswith("watcher-policy-"):
                self.scheduler.remove_job(job.id)

        if self._db is None:
            logger.warning("巡检调度器缺少数据库连接，暂不注册策略")
            return

        policies = await self._db.fetch_all(
            "SELECT id, venue_id, schedule_cron FROM watcher_policies WHERE enabled = ?",
            (True,),
        )
        registered = 0
        for policy in policies:
            try:
                trigger = CronTrigger.from_crontab(
                    policy["schedule_cron"],
                    timezone="Asia/Shanghai",
                )
            except ValueError as exc:
                logger.error("巡检策略 {} 的 Cron 无效: {}", policy["id"], exc)
                continue
            self.scheduler.add_job(
                self._run_policy,
                trigger=trigger,
                id=f"watcher-policy-{policy['id']}",
                args=[policy["id"], policy["venue_id"]],
                replace_existing=True,
            )
            registered += 1
        logger.info("📅 已从 PostgreSQL 注册 {} 条巡检策略", registered)

    async def _run_policy(self, policy_id: str, venue_id: str) -> None:
        global _last_watcher_run
        try:
            await run_watcher_policy(
                self._db,
                policy_id=policy_id,
                venue_id=venue_id,
                trigger_source="SCHEDULED",
            )
            _last_watcher_run = time.time()
        except Exception as exc:
            logger.error("定时巡检策略 {} 执行失败: {}", policy_id, exc)

    def add_once_job(self, func, run_at, job_id, args=None):
        self.scheduler.add_job(
            func,
            "date",
            run_date=run_at,
            id=job_id,
            args=args or [],
            replace_existing=True,
        )

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        logger.warning("⏱️ 巡检策略调度器已关闭")
