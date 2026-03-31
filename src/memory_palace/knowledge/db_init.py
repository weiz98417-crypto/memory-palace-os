"""
数据库初始化脚本 (Database Initialization) - 异步版本

负责创建 memory.db 的核心表结构和索引。
在项目首次部署或数据重置时运行。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import aiosqlite
from pathlib import Path
from loguru import logger


async def init_database():
    """
    初始化 memory.db 数据库 (异步版本)
    """
    db_path = Path("data/memory.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(db_path)) as db:
        try:
            # 1. 标准作业程序表 (SOP)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sop_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    priority INTEGER DEFAULT 3,
                    version VARCHAR(20) DEFAULT '1.0',
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✅ 创建表: sop_documents")

            # 2. 突发事件流水表 (核心审计表)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS incident_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id VARCHAR(64) UNIQUE NOT NULL,
                    severity VARCHAR(10) NOT NULL,
                    raw_query TEXT NOT NULL,
                    ai_instruction TEXT,
                    employee_feedback TEXT,
                    is_resolved BOOLEAN DEFAULT 0,
                    audit_status VARCHAR(20) DEFAULT 'PENDING',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✅ 创建表: incident_logs")

            # 3. 会话状态表 (新增 - 用于 FastAPI 异步架构)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    current_intent TEXT,
                    current_severity TEXT,
                    active_agent TEXT,
                    context_payload TEXT DEFAULT '{}',
                    history_summary TEXT DEFAULT ''
                )
            """)
            logger.info("✅ 创建表: sessions")

            # 4. 对话轮次表 (新增 - 用于滑动窗口历史)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    input_text TEXT NOT NULL,
                    output_text TEXT,
                    structured_data TEXT DEFAULT '{}',
                    tokens_used INTEGER DEFAULT 0,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            """)
            logger.info("✅ 创建表: conversation_turns")

            # 5. 创建索引优化 Watcher 巡检速度
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_incident_case ON incident_logs(case_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_lookup ON incident_logs(is_resolved, audit_status)
            """)
            
            # 6. 消息表
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    from_user TEXT NOT NULL,
                    msg_type TEXT DEFAULT 'text',
                    content TEXT DEFAULT '',
                    sla_response_at REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    metadata TEXT DEFAULT '{}'
                )
            """)
            logger.info("✅ 创建表: messages")

            # 7. 创建会话相关索引 (新增)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_stage ON sessions(stage, updated_at)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, timestamp)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(from_user, created_at)
            """)
            logger.info("✅ 创建索引完成")

            await db.commit()
            logger.success(f"🎉 数据库初始化成功: {db_path}")

        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 数据库初始化失败: {e}")
            raise


def init_database_sync():
    """同步包装器（用于命令行直接运行）"""
    asyncio.run(init_database())


if __name__ == "__main__":
    init_database_sync()