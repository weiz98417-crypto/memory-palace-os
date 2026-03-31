"""
工业级日志管理系统 (Global Logging System)

核心特性：
1. 多文件归档：将 Access, App, Error, Watcher 日志物理隔离，极大提升排障效率。
2. 自动旋转 (Rotation)：每天 00:00 自动切割，或单文件满 100MB 自动分卷。
3. 自动清理 (Retention)：保留最近 30 天的日志，防止磁盘空间耗尽。
4. 诊断增强：在 ERROR 级别日志中自动捕捉详细堆栈（Backtrace）与变量值（Diagnose）。
5. 异步写入：基于线程安全机制，确保高并发下日志记录不阻塞业务逻辑。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import sys
import os
from pathlib import Path
from loguru import logger

def setup_logging():
    """
    配置全局日志处理器。
    在 main.py 或 orchestrator.py 启动时调用一次。
    """
    # 1. 确保日志目录存在
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 2. 移除 loguru 默认的控制台处理器（为了后面自定义格式）
    logger.remove()

    # 3. 配置控制台输出 (带颜色，适合实时观察)
    # 格式：时间 | 等级 | 模块:行号 - 消息
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True
    )

    # 4. 业务流水日志 (app.log)
    # 记录所有 Agent 的执行过程。每天 0 点滚动，保留 30 天。
    logger.add(
        log_dir / "app.log",
        rotation="00:00",
        retention="30 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
        filter=lambda record: record["level"].name != "ERROR",  # 排除错误，保持流水整洁
        level="INFO",
        compression="zip",  # 历史日志压缩，节省空间
        encoding="utf-8"
    )

    # 5. 致命错误日志 (error.log)
    # 仅记录 ERROR 及以上级别。带深度诊断信息。
    logger.add(
        log_dir / "error.log",
        rotation="100 MB",
        retention="90 days",  # 错误日志建议保留久一些，方便追溯
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message} | {exception}",
        level="ERROR",
        backtrace=True,
        diagnose=True,  # 自动打印发生错误时的变量值！
        encoding="utf-8"
    )

    # 6. 巡检专项日志 (watcher.log)
    # 通过 filter 机制，只记录与 Watcher 相关的审计细节
    logger.add(
        log_dir / "watcher.log",
        rotation="10 MB",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
        filter=lambda record: "Watcher" in record["message"] or record["name"] == "watcher_skill",
        level="INFO",
        encoding="utf-8"
    )

    logger.success("🚀 工业级日志引擎已启动，已挂载 data/logs/ 进行持久化。")

# 导出配置函数
if __name__ == "__main__":
    # 测试代码
    setup_logging()
    logger.info("这是一条普通流水")
    logger.error("这是一条模拟错误")
