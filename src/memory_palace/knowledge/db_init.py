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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


async def init_database(db_client=None):
    """
    初始化数据库 (异步版本)。
    db_client=None → 使用默认 SQLite（DEMO_MODE 兼容）。
    传入 PostgresDBClient → 使用 PostgreSQL。
    """
    if db_client is not None and hasattr(db_client, '_pool'):
        # PostgreSQL backend — use the passed client
        await _init_pg(db_client)
        return

    db_path = _PROJECT_ROOT / "data" / "memory.db"
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
                    agent_name TEXT DEFAULT '',
                    message_count INTEGER DEFAULT 0,
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

            # 兼容旧表：添加可能缺失的列
            for col, col_type in [("agent_name", "TEXT DEFAULT ''"), ("message_count", "INTEGER DEFAULT 0")]:
                try:
                    await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # 列已存在则忽略

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

            # [Phase 2] 8. 审批请求表 (Approval Requests)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS approval_requests (
                    approval_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    args TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    requested_at REAL NOT NULL,
                    requested_by TEXT,
                    status TEXT DEFAULT 'PENDING',
                    reviewed_at REAL,
                    reviewed_by TEXT,
                    comment TEXT
                )
            """)
            logger.info("✅ 创建表: approval_requests")

            # [Phase 2] 9. 工具调用日志表 (Tool Invocation Logs)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tool_invocation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    args TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    agent_name TEXT,
                    logged_at REAL NOT NULL
                )
            """)
            logger.info("✅ 创建表: tool_invocation_logs")

            # [Phase 2] 10. 任务表 (Tasks - Phase 3 会用到)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    dependencies TEXT DEFAULT '[]',
                    result TEXT,
                    error TEXT,
                    assigned_agent TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 3
                )
            """)
            logger.info("✅ 创建表: tasks")

            # 创建任务相关索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_approval_session ON approval_requests(session_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_tool_logs_session ON tool_invocation_logs(session_id)
            """)
            logger.info("✅ Phase 2/3 索引创建完成")

            # =================================================================
            # Sprint 1 新增: 推送日志表 + 确认事件表
            # =================================================================

            # 8. 推送日志表 (Push Logs)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS push_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    push_id TEXT UNIQUE NOT NULL,
                    msg_id TEXT,
                    from_user TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    event_type TEXT DEFAULT '其他',
                    severity TEXT DEFAULT 'P3/P4',
                    stage1_triggered BOOLEAN DEFAULT FALSE,
                    hit_keywords TEXT DEFAULT '[]',
                    stage2_triggered BOOLEAN,
                    llm_confidence REAL,
                    pushed_at REAL NOT NULL,
                    confirmed_at REAL,
                    adoption_status TEXT DEFAULT 'pending',
                    confirmed_notes TEXT,
                    confirmed_by TEXT,
                    trace_id TEXT
                )
            """)
            logger.info("✅ 创建表: push_logs")

            # 9. 确认事件记忆表 (Confirmed Event Memories)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS confirmed_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    push_id TEXT,
                    from_user TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    context_trigger_data TEXT DEFAULT '{}',
                    memory_content TEXT NOT NULL,
                    vector_doc_id TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    confirmed_at REAL,
                    venue_id TEXT
                )
            """)
            logger.info("✅ 创建表: confirmed_events")

            # 创建推送日志相关索引
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_push_logs_user ON push_logs(from_user, pushed_at)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_push_logs_status ON push_logs(adoption_status, pushed_at)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_confirmed_events_user ON confirmed_events(from_user, created_at)
            """)
            logger.info("✅ Sprint 1 索引创建完成")

            # =================================================================
            # Sprint 2 新增: 数字分身档案表
            # =================================================================

            # 10. 数字分身档案表 (Personas)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS personas (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT,
                    job_title TEXT NOT NULL,
                    logic_entries TEXT NOT NULL,
                    raw_answers TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            logger.info("✅ 创建表: personas")

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_personas_job ON personas(job_title)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_personas_venue ON personas(venue_id)
            """)
            logger.info("✅ Sprint 2 索引创建完成")

            await db.commit()
            logger.success(f"🎉 数据库初始化成功: {db_path}")

        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 数据库初始化失败: {e}")
            raise


async def _init_pg(db_client):
    """PostgreSQL database initialization using the passed PostgresDBClient."""
    from loguru import logger

    tables = [
        """CREATE TABLE IF NOT EXISTS sop_documents (
            id SERIAL PRIMARY KEY,
            title TEXT DEFAULT '',
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 3,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS incident_logs (
            id SERIAL PRIMARY KEY,
            case_id VARCHAR(50) NOT NULL,
            severity VARCHAR(10) DEFAULT 'P3',
            raw_query TEXT NOT NULL,
            dispatched_instruction TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id VARCHAR(50) PRIMARY KEY,
            user_id TEXT NOT NULL,
            agent_name TEXT DEFAULT 'router',
            stage TEXT NOT NULL DEFAULT 'active',
            message_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            message_id VARCHAR(50) UNIQUE NOT NULL,
            session_id TEXT,
            from_user TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            content TEXT DEFAULT '',
            priority VARCHAR(5) DEFAULT 'P3',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            sla_response_at TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS personas (
            id VARCHAR(50) PRIMARY KEY,
            venue_id TEXT DEFAULT '',
            job_title TEXT,
            logic_entries TEXT,
            raw_answers TEXT DEFAULT '{}',
            description TEXT DEFAULT '',
            created_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS tasks (
            id VARCHAR(50) PRIMARY KEY,
            session_id TEXT,
            description TEXT,
            status VARCHAR(20) DEFAULT 'PENDING',
            dependencies TEXT DEFAULT '[]',
            assigned_agent TEXT,
            created_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION
        )""",
    ]

    for ddl in tables:
        try:
            await db_client.execute(ddl)
        except Exception as e:
            logger.error(f"PG DDL failed: {e}")

    # Create indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_stage ON sessions(stage)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_from_user ON messages(from_user)",
        "CREATE INDEX IF NOT EXISTS idx_incident_case ON incident_logs(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_personas_job ON personas(job_title)",
    ]
    for idx in indexes:
        try:
            await db_client.execute(idx)
        except Exception as e:
            logger.error(f"PG index failed: {e}")

    logger.success("PostgreSQL 数据库初始化完成")


def init_database_sync():
    """同步包装器（用于命令行直接运行）"""
    asyncio.run(init_database())


if __name__ == "__main__":
    init_database_sync()