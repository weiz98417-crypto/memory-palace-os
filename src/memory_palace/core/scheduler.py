"""
定时任务引擎 (System Scheduler)

职责：
1. 管控主动型智能体（如：鹰眼巡检专家 Watcher）的触发时机。
2. 维护系统级定时巡检（每日 10:00 & 20:00）及临时催办任务。
3. 提供任务持久化存储，确保服务重启后逻辑不中断。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# [防御性导入业务 Agent]
# ---------------------------------------------------------------------------
try:
    from ...skills.watcher import WatcherSkill
except ImportError:
    logger.warning("WatcherSkill 尚未实现，定时任务将以空跑模式注册。")
    WatcherSkill = None

class TaskScheduler:
    """
    工业级异步定时任务管理器 (基于 APScheduler)
    """

    def __init__(self):
        # 1. 配置 JobStore (任务持久化)
        # 将定时任务存储在 SQLite 中，防止程序崩溃后任务丢失
        job_stores = {
            'default': SQLAlchemyJobStore(url="sqlite:///./data/jobs.sqlite")
        }

        # 2. 配置执行池
        executors = {
            'default': ThreadPoolExecutor(20)  # 最大 20 个并发任务
        }

        job_defaults = {
            'coalesce': False,          # 即使积压了多次，也只执行一次
            'max_instances': 1,         # 同一个任务同一时间只允许运行一个实例（防并发冲突）
            'misfire_grace_time': 3600  # 如果错过执行时间，1小时内允许补偿执行
        }

        self.scheduler = BackgroundScheduler(
            jobstores=job_stores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="Asia/Shanghai"
        )

    def start(self):
        """启动调度引擎"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.success("⏱️ 系统调度引擎已启动 (SQLAlchemy Persistence Enabled)")
            self._register_default_jobs()

    def _register_default_jobs(self):
        """注册系统级预设任务（如每日鹰眼巡检）"""
        
        # 任务 A：每日上午 10:00 鹰眼全量巡检
        self.add_cron_job(
            func=self._run_watcher_flow,
            hour=10, minute=0,
            job_id="daily_watcher_morning",
            replace_existing=True
        )

        # 任务 B：每日晚上 20:00 鹰眼全量巡检
        self.add_cron_job(
            func=self._run_watcher_flow,
            hour=20, minute=0,
            job_id="daily_watcher_evening",
            replace_existing=True
        )

        logger.info("📅 默认周期性巡检任务已挂载：10:00 / 20:00")

    def add_cron_job(self, func, hour, minute, job_id, **kwargs):
        """添加 Cron 类型的周期任务"""
        self.scheduler.add_job(
            func,
            'cron',
            hour=hour,
            minute=minute,
            id=job_id,
            **kwargs
        )

    def add_once_job(self, func, run_at, job_id, args=None):
        """添加一次性延迟任务（如：30分钟后如果没有闭环，则触发某逻辑）"""
        self.scheduler.add_job(
            func,
            'date',
            run_date=run_at,
            id=job_id,
            args=args or [],
            replace_existing=True
        )
        logger.info(f"📍 已排期一次性任务: {job_id} | 执行时间: {run_at}")

    def _run_watcher_flow(self):
        """
        内部逻辑包装：实例化 Watcher 并执行
        APScheduler runs in threads, so we use asyncio.run() here.
        """
        import asyncio
        logger.info("🦅 鹰眼定时巡检波次开始...")
        if not WatcherSkill:
            logger.error("WatcherSkill 未定义，取消本次巡检。")
            return

        try:
            watcher = WatcherSkill()

            async def _run():
                result = await watcher.run(context={"trigger_source": "scheduler"})
                return result

            result = asyncio.run(_run())
            logger.success(f"🦅 鹰眼巡检波次结束 | processed: {result.get('processed_count', 0) if isinstance(result, dict) else 'N/A'}")
        except Exception as e:
            logger.error(f"🦅 鹰眼执行中发生未捕获异常: {e}")

    def shutdown(self):
        """优雅关闭"""
        self.scheduler.shutdown()
        logger.warning("⏱️ 系统调度引擎已关闭")

# 全局单例
sys_scheduler = TaskScheduler()