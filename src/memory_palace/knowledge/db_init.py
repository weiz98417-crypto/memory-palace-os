"""
数据库初始化脚本 (Database Initialization) - 异步版本

负责创建 memory.db 的核心表结构和索引。
在项目首次部署或数据重置时运行。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import aiosqlite
import sqlite3
from pathlib import Path
from loguru import logger

from ..core.business_ids import build_business_id

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


async def _add_sqlite_column(db, table_name, column_name, column_type):
    try:
        await db.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


async def _isolate_legacy_wecom_identities(db) -> None:
    """Move legacy PostgreSQL identity bindings into the policy-enabled channel."""
    await db.execute(
        """
        UPDATE channel_identities
        SET channel = 'WECOM_SIMULATOR'
        WHERE channel = 'WECOM'
          AND NOT EXISTS (
              SELECT 1
              FROM channel_identities AS isolated
              WHERE isolated.venue_id = channel_identities.venue_id
                AND isolated.channel = 'WECOM_SIMULATOR'
                AND isolated.external_tenant_id = channel_identities.external_tenant_id
                AND isolated.external_user_id = channel_identities.external_user_id
          )
        """
    )
    await db.execute(
        """
        UPDATE channel_identities
        SET status = 'DISABLED'
        WHERE channel = 'WECOM' AND status <> 'DISABLED'
        """
    )


async def init_database(db_client=None):
    """
    初始化数据库 (异步版本)。
    db_client=None → 使用默认 SQLite（DEMO_MODE 兼容）。
    传入 PostgresDBClient → 使用 PostgreSQL。
    """
    if db_client is not None and hasattr(db_client, '_pool'):
        # PostgreSQL backend — use the passed client
        await _init_pg(db_client)
        from .attachment_schema import init_attachment_schema
        from .experience_schema import init_experience_schema
        from .vector_schema import init_vector_schema, verify_vector_schema
        from ..scenic.schema import init_scenic_schema

        await init_experience_schema(db_client)
        await init_attachment_schema(db_client)
        await init_vector_schema(db_client)
        await verify_vector_schema(db_client)
        await init_scenic_schema(db_client)
        return

    db_path = getattr(db_client, "db_path", None) or (_PROJECT_ROOT / "data" / "memory.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(db_path)) as db:
        try:
            # 1. 标准作业程序表 (SOP)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sop_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id TEXT NOT NULL DEFAULT '',
                    category VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    priority INTEGER DEFAULT 3,
                    version VARCHAR(20) DEFAULT '1.0',
                    status VARCHAR(20) DEFAULT 'DRAFT',
                    source_event_id TEXT,
                    created_by TEXT,
                    reviewed_by TEXT,
                    published_at REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
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
            for col, col_type in [
                ("agent_name", "TEXT DEFAULT ''"),
                ("message_count", "INTEGER DEFAULT 0"),
                ("venue_id", "TEXT DEFAULT ''"),
            ]:
                await _add_sqlite_column(db, "sessions", col, col_type)

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

            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_runs (
                    message_id TEXT PRIMARY KEY,
                    trace_id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    venue_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'LEGACY',
                    external_message_id TEXT,
                    external_conversation_id TEXT,
                    target_agent TEXT,
                    reply_text TEXT,
                    result_json TEXT DEFAULT '{}',
                    error TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 4,
                    manual_retry_count INTEGER NOT NULL DEFAULT 0,
                    dead_letter_id TEXT,
                    delivery_status TEXT NOT NULL DEFAULT 'PENDING',
                    delivery_error TEXT,
                    delivered_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    processed_at REAL
                )
            """)
            logger.info("✅ 创建表: message_runs")

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
                    business_id TEXT,
                    venue_id TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL,
                    args TEXT NOT NULL,
                    session_id TEXT,
                    event_id TEXT,
                    task_id TEXT,
                    user_id TEXT,
                    requested_at REAL NOT NULL,
                    requested_by TEXT,
                    supersedes_approval_id TEXT,
                    idempotency_key TEXT,
                    evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT DEFAULT 'PENDING',
                    reviewed_at REAL,
                    reviewed_by TEXT,
                    comment TEXT,
                    correlation_trace_id TEXT,
                    execution_trace_id TEXT,
                    execution_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
                    execution_result TEXT,
                    execution_error TEXT
                )
            """)
            logger.info("✅ 创建表: approval_requests")

            # [Phase 2] 9. 工具调用日志表 (Tool Invocation Logs)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tool_invocation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL,
                    args TEXT NOT NULL,
                    session_id TEXT,
                    user_id TEXT,
                    agent_name TEXT,
                    logged_at REAL NOT NULL,
                    trace_id TEXT NOT NULL DEFAULT '',
                    approval_id TEXT
                )
            """)
            logger.info("✅ 创建表: tool_invocation_logs")

            # [Phase 2] 10. 任务表 (Tasks - Phase 3 会用到)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    business_id TEXT,
                    venue_id TEXT DEFAULT '',
                    session_id TEXT NOT NULL,
                    event_id TEXT,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING',
                    dependencies TEXT DEFAULT '[]',
                    due_at REAL,
                    result_schema_json TEXT NOT NULL DEFAULT '{}',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    result TEXT,
                    error TEXT,
                    block_reason TEXT,
                    assigned_agent TEXT,
                    assigned_user_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 3
                )
            """)
            logger.info("✅ 创建表: tasks")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_decompositions (
                    decomposition_id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    event_id TEXT,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_ids TEXT NOT NULL DEFAULT '[]',
                    response_json TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            logger.info("✅ 创建表: task_decompositions")

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
                    venue_id TEXT NOT NULL DEFAULT '',
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
                    trace_id TEXT,
                    channel TEXT NOT NULL DEFAULT 'legacy',
                    recipient TEXT,
                    delivery_status TEXT NOT NULL DEFAULT 'RECORDED',
                    delivery_error TEXT,
                    delivery_claim_token TEXT,
                    delivery_claimed_at REAL,
                    idempotency_key TEXT
                )
            """)
            logger.info("✅ 创建表: push_logs")

            # 9. 确认事件记忆表 (Confirmed Event Memories)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS confirmed_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    business_id TEXT,
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
                    venue_id TEXT,
                    source_type TEXT DEFAULT 'LIVE',
                    status TEXT DEFAULT 'OPEN',
                    assigned_to TEXT,
                    resolution TEXT,
                    trace_id TEXT,
                    closed_at REAL,
                    updated_at REAL
                )
            """)
            logger.info("✅ 创建表: confirmed_events")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS event_activities (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    session_id TEXT,
                    message_id TEXT,
                    trace_id TEXT,
                    activity_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    idempotency_key TEXT,
                    created_by TEXT,
                    created_at REAL NOT NULL
                )
            """)
            logger.info("✅ 创建表: event_activities")

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
                    description TEXT DEFAULT '',
                    created_at REAL,
                    updated_at REAL
                )
            """)
            logger.info("✅ 创建表: personas")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS persona_interviews (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    source_persona_id TEXT,
                    job_title TEXT NOT NULL,
                    current_question INTEGER NOT NULL,
                    all_entries_json TEXT NOT NULL DEFAULT '[]',
                    raw_answers_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_by TEXT,
                    trace_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_personas_job ON personas(job_title)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_personas_venue ON personas(venue_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_persona_interviews_venue_status
                ON persona_interviews(venue_id, status, updated_at)
            """)
            logger.info("✅ Sprint 2 索引创建完成")

            # =================================================================
            # Enterprise MVP: identity, refresh sessions, and immutable audit
            # =================================================================

            await db.execute("""
                CREATE TABLE IF NOT EXISTS venues (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    venue_id TEXT NOT NULL,
                    department TEXT,
                    job_title TEXT,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_login_at REAL,
                    FOREIGN KEY (venue_id) REFERENCES venues(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    venue_id TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    revoked_at REAL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    outcome TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_venue ON users(venue_id, status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id, revoked_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_venue_time ON audit_logs(venue_id, created_at)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_logs(trace_id)")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channel_conversations (
                    session_id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    external_conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE (venue_id, channel, external_conversation_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channel_identities (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    external_tenant_id TEXT NOT NULL DEFAULT '',
                    external_user_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE (venue_id, channel, external_tenant_id, external_user_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '通用',
                    source_type TEXT NOT NULL DEFAULT 'MANUAL',
                    source_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    vector_doc_id TEXT,
                    import_batch_id TEXT,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_retrieval_snapshots (
                    id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    venue_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    message_id TEXT,
                    session_id TEXT,
                    agent_id TEXT NOT NULL,
                    query_summary TEXT NOT NULL,
                    query_sha256 TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    index_name TEXT,
                    status TEXT NOT NULL,
                    top_k INTEGER NOT NULL,
                    similarity_threshold REAL NOT NULL,
                    filter_json TEXT NOT NULL DEFAULT '{}',
                    attempts_json TEXT NOT NULL DEFAULT '[]',
                    references_json TEXT NOT NULL DEFAULT '[]',
                    raw_hit_count INTEGER NOT NULL DEFAULT 0,
                    selected_count INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    error_message TEXT,
                    started_at REAL NOT NULL,
                    completed_at REAL NOT NULL,
                    latency_ms INTEGER NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sop_versions (
                    id TEXT PRIMARY KEY,
                    sop_id INTEGER NOT NULL,
                    venue_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    change_note TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (sop_id) REFERENCES sop_documents(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watcher_policies (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    schedule_cron TEXT NOT NULL DEFAULT '0 10 * * *',
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    check_types_json TEXT NOT NULL DEFAULT '[]',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT NOT NULL,
                    last_run_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watcher_runs (
                    id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL,
                    venue_id TEXT NOT NULL,
                    event_id TEXT,
                    trigger_source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    model_name TEXT,
                    target_count INTEGER NOT NULL DEFAULT 0,
                    finding_count INTEGER NOT NULL DEFAULT 0,
                    summary TEXT,
                    target_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    FOREIGN KEY (policy_id) REFERENCES watcher_policies(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watcher_findings (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    venue_id TEXT NOT NULL,
                    event_id TEXT,
                    finding_type TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'P2',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_type TEXT,
                    source_id TEXT,
                    issue_fingerprint TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    assigned_to TEXT,
                    resolution TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    closed_at REAL,
                    FOREIGN KEY (run_id) REFERENCES watcher_runs(id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    venue_id TEXT NOT NULL,
                    setting_key TEXT NOT NULL,
                    setting_value TEXT NOT NULL,
                    value_type TEXT NOT NULL DEFAULT 'string',
                    updated_by TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (venue_id, setting_key)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS backup_records (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    storage_path TEXT,
                    checksum TEXT,
                    size_bytes INTEGER,
                    error TEXT,
                    requested_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_call_logs (
                    id TEXT PRIMARY KEY,
                    venue_id TEXT NOT NULL DEFAULT '',
                    trace_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    agent_name TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT 'deepseek',
                    model_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    latency_seconds REAL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    request_id TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    is_mock BOOLEAN NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS runtime_recovery_runs (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL DEFAULT 'GLOBAL',
                    venue_id TEXT NOT NULL DEFAULT '',
                    instance_id TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    task_graph_recovered_count INTEGER NOT NULL DEFAULT 0,
                    task_graph_reset_count INTEGER NOT NULL DEFAULT 0,
                    approval_interrupted_count INTEGER NOT NULL DEFAULT 0,
                    approval_pending_loaded_count INTEGER NOT NULL DEFAULT 0,
                    watcher_interrupted_count INTEGER NOT NULL DEFAULT 0,
                    redis_status TEXT NOT NULL DEFAULT 'NOT_CHECKED',
                    redis_pending_count INTEGER NOT NULL DEFAULT 0,
                    redis_claimed_count INTEGER NOT NULL DEFAULT 0,
                    redis_acked_count INTEGER NOT NULL DEFAULT 0,
                    error_summary TEXT,
                    trace_json TEXT NOT NULL DEFAULT '[]',
                    started_at REAL NOT NULL,
                    completed_at REAL
                )
            """)

            sqlite_column_migrations = {
                "sop_documents": [
                    ("venue_id", "TEXT NOT NULL DEFAULT ''"),
                    ("status", "TEXT DEFAULT 'DRAFT'"),
                    ("source_event_id", "TEXT"),
                    ("created_by", "TEXT"),
                    ("reviewed_by", "TEXT"),
                    ("published_at", "REAL"),
                    ("created_at", "REAL"),
                ],
                "tasks": [
                    ("assigned_user_id", "TEXT"),
                    ("decomposition_id", "TEXT"),
                    ("block_reason", "TEXT"),
                    ("business_id", "TEXT"),
                    ("event_id", "TEXT"),
                    ("due_at", "REAL"),
                    ("result_schema_json", "TEXT NOT NULL DEFAULT '{}'"),
                    ("evidence_refs_json", "TEXT NOT NULL DEFAULT '[]'"),
                ],
                "task_decompositions": [
                    ("event_id", "TEXT"),
                ],
                "confirmed_events": [
                    ("business_id", "TEXT"),
                    ("source_type", "TEXT DEFAULT 'LIVE'"),
                    ("status", "TEXT DEFAULT 'OPEN'"),
                    ("assigned_to", "TEXT"),
                    ("resolution", "TEXT"),
                    ("trace_id", "TEXT"),
                    ("closed_at", "REAL"),
                    ("updated_at", "REAL"),
                ],
                "approval_requests": [
                    ("correlation_trace_id", "TEXT"),
                    ("execution_trace_id", "TEXT"),
                    ("execution_status", "TEXT NOT NULL DEFAULT 'NOT_STARTED'"),
                    ("execution_result", "TEXT"),
                    ("execution_error", "TEXT"),
                    ("business_id", "TEXT"),
                    ("event_id", "TEXT"),
                    ("task_id", "TEXT"),
                    ("supersedes_approval_id", "TEXT"),
                    ("idempotency_key", "TEXT"),
                    ("evidence_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
                ],
                "tool_invocation_logs": [
                    ("trace_id", "TEXT NOT NULL DEFAULT ''"),
                    ("approval_id", "TEXT"),
                ],
                "push_logs": [
                    ("channel", "TEXT NOT NULL DEFAULT 'legacy'"),
                    ("recipient", "TEXT"),
                    ("delivery_status", "TEXT NOT NULL DEFAULT 'RECORDED'"),
                    ("delivery_error", "TEXT"),
                    ("delivery_claim_token", "TEXT"),
                    ("delivery_claimed_at", "REAL"),
                    ("idempotency_key", "TEXT"),
                ],
                "personas": [("description", "TEXT DEFAULT ''")],
                "llm_call_logs": [
                    ("agent_id", "TEXT NOT NULL DEFAULT ''"),
                    ("agent_name", "TEXT NOT NULL DEFAULT ''"),
                ],
                "message_runs": [
                    ("channel", "TEXT NOT NULL DEFAULT 'LEGACY'"),
                    ("external_message_id", "TEXT"),
                    ("external_conversation_id", "TEXT"),
                    ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
                    ("max_attempts", "INTEGER NOT NULL DEFAULT 4"),
                    ("manual_retry_count", "INTEGER NOT NULL DEFAULT 0"),
                    ("dead_letter_id", "TEXT"),
                    ("delivery_status", "TEXT NOT NULL DEFAULT 'PENDING'"),
                    ("delivery_error", "TEXT"),
                    ("delivered_at", "REAL"),
                ],
                "watcher_runs": [
                    ("event_id", "TEXT"),
                    ("model_name", "TEXT"),
                    ("target_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
                ],
                "watcher_findings": [
                    ("event_id", "TEXT"),
                    ("issue_fingerprint", "TEXT"),
                ],
                "users": [
                    ("department", "TEXT"),
                    ("job_title", "TEXT"),
                ],
            }
            for table_name, columns in sqlite_column_migrations.items():
                for column_name, column_type in columns:
                    await _add_sqlite_column(
                        db,
                        table_name,
                        column_name,
                        column_type,
                    )

            await db.execute(
                """
                UPDATE message_runs
                SET delivery_status = 'PERSISTED', delivery_error = NULL,
                    delivered_at = COALESCE(delivered_at, processed_at, updated_at)
                WHERE status = 'COMPLETED'
                  AND UPPER(COALESCE(channel, 'LEGACY'))
                      IN ('WEB', 'WECOM_SIMULATOR', 'LEGACY', '')
                  AND COALESCE(delivery_status, 'PENDING') = 'PENDING'
                """
            )

            event_cursor = await db.execute(
                """
                SELECT event_id, created_at FROM confirmed_events
                WHERE business_id IS NULL OR business_id = ''
                """
            )
            for event_id, created_at in await event_cursor.fetchall():
                await db.execute(
                    "UPDATE confirmed_events SET business_id = ? WHERE event_id = ?",
                    (build_business_id("SJ", event_id, created_at), event_id),
                )

            task_cursor = await db.execute(
                """
                SELECT id, created_at FROM tasks
                WHERE business_id IS NULL OR business_id = ''
                """
            )
            for task_id, created_at in await task_cursor.fetchall():
                await db.execute(
                    "UPDATE tasks SET business_id = ? WHERE id = ?",
                    (build_business_id("RW", task_id, created_at), task_id),
                )

            approval_cursor = await db.execute(
                """
                SELECT approval_id, requested_at FROM approval_requests
                WHERE business_id IS NULL OR business_id = ''
                """
            )
            for approval_id, requested_at in await approval_cursor.fetchall():
                await db.execute(
                    "UPDATE approval_requests SET business_id = ? WHERE approval_id = ?",
                    (build_business_id("SP", approval_id, requested_at), approval_id),
                )

            await db.execute(
                """
                INSERT OR IGNORE INTO event_activities (
                    id,
                    venue_id,
                    event_id,
                    session_id,
                    message_id,
                    trace_id,
                    activity_type,
                    payload_json,
                    idempotency_key,
                    created_by,
                    created_at
                )
                SELECT
                    'legacy-event-created-' || confirmed_events.event_id,
                    COALESCE(confirmed_events.venue_id, ''),
                    confirmed_events.event_id,
                    message_runs.session_id,
                    confirmed_events.push_id,
                    COALESCE(
                        NULLIF(confirmed_events.trace_id, ''),
                        message_runs.trace_id,
                        ''
                    ),
                    'EVENT_CREATED',
                    '{"backfilled":true}',
                    'legacy:event-created:' || confirmed_events.event_id,
                    confirmed_events.from_user,
                    COALESCE(
                        confirmed_events.created_at,
                        confirmed_events.confirmed_at,
                        confirmed_events.updated_at,
                        strftime('%s', 'now')
                    )
                FROM confirmed_events
                LEFT JOIN message_runs
                  ON message_runs.message_id = confirmed_events.push_id
                 AND message_runs.venue_id = COALESCE(confirmed_events.venue_id, '')
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM event_activities AS existing_activity
                    WHERE existing_activity.venue_id = COALESCE(confirmed_events.venue_id, '')
                      AND existing_activity.event_id = confirmed_events.event_id
                      AND existing_activity.activity_type = 'EVENT_CREATED'
                )
                """
            )

            for relationship_backfill_sql in (
                """
                UPDATE task_decompositions
                SET event_id = (
                    SELECT MIN(event_activities.event_id)
                    FROM event_activities
                    WHERE event_activities.venue_id = task_decompositions.venue_id
                      AND event_activities.session_id = task_decompositions.session_id
                )
                WHERE (event_id IS NULL OR event_id = '')
                  AND (
                      SELECT COUNT(DISTINCT event_activities.event_id)
                      FROM event_activities
                      WHERE event_activities.venue_id = task_decompositions.venue_id
                        AND event_activities.session_id = task_decompositions.session_id
                  ) = 1
                """,
                """
                UPDATE tasks
                SET event_id = (
                    SELECT task_decompositions.event_id
                    FROM task_decompositions
                    WHERE task_decompositions.decomposition_id = tasks.decomposition_id
                      AND task_decompositions.venue_id = tasks.venue_id
                )
                WHERE (event_id IS NULL OR event_id = '')
                  AND decomposition_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM task_decompositions
                      WHERE task_decompositions.decomposition_id = tasks.decomposition_id
                        AND task_decompositions.venue_id = tasks.venue_id
                        AND task_decompositions.event_id IS NOT NULL
                        AND task_decompositions.event_id <> ''
                  )
                """,
                """
                UPDATE tasks
                SET event_id = (
                    SELECT MIN(event_activities.event_id)
                    FROM event_activities
                    WHERE event_activities.venue_id = tasks.venue_id
                      AND event_activities.session_id = tasks.session_id
                )
                WHERE (event_id IS NULL OR event_id = '')
                  AND (
                      SELECT COUNT(DISTINCT event_activities.event_id)
                      FROM event_activities
                      WHERE event_activities.venue_id = tasks.venue_id
                        AND event_activities.session_id = tasks.session_id
                  ) = 1
                """,
                """
                UPDATE approval_requests
                SET event_id = (
                    SELECT MIN(event_activities.event_id)
                    FROM event_activities
                    WHERE event_activities.venue_id = approval_requests.venue_id
                      AND event_activities.session_id = approval_requests.session_id
                )
                WHERE (event_id IS NULL OR event_id = '')
                  AND session_id IS NOT NULL
                  AND (
                      SELECT COUNT(DISTINCT event_activities.event_id)
                      FROM event_activities
                      WHERE event_activities.venue_id = approval_requests.venue_id
                        AND event_activities.session_id = approval_requests.session_id
                  ) = 1
                """,
            ):
                await db.execute(relationship_backfill_sql)

            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_knowledge_venue_status ON knowledge_documents(venue_id, status, updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_trace ON knowledge_retrieval_snapshots(venue_id, trace_id, started_at)",
                "CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_message ON knowledge_retrieval_snapshots(venue_id, message_id, started_at)",
                "CREATE INDEX IF NOT EXISTS idx_sop_venue_status ON sop_documents(venue_id, status, updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_sop_versions_sop ON sop_versions(sop_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_watcher_policy_venue ON watcher_policies(venue_id, enabled)",
                "CREATE INDEX IF NOT EXISTS idx_watcher_runs_venue ON watcher_runs(venue_id, started_at)",
                "CREATE INDEX IF NOT EXISTS idx_watcher_runs_event ON watcher_runs(venue_id, event_id, started_at)",
                "CREATE INDEX IF NOT EXISTS idx_watcher_findings_venue ON watcher_findings(venue_id, status, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_watcher_findings_event ON watcher_findings(venue_id, event_id, status, created_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_watcher_open_finding_fingerprint ON watcher_findings(venue_id, policy_id, source_type, source_id, issue_fingerprint) WHERE status != 'CLOSED' AND issue_fingerprint IS NOT NULL AND issue_fingerprint != ''",
                "CREATE INDEX IF NOT EXISTS idx_backup_venue ON backup_records(venue_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_llm_calls_venue_time ON llm_call_logs(venue_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_llm_calls_trace ON llm_call_logs(trace_id)",
                "CREATE INDEX IF NOT EXISTS idx_runtime_recovery_scope_time ON runtime_recovery_runs(scope_type, venue_id, started_at)",
                "CREATE INDEX IF NOT EXISTS idx_runtime_recovery_trace ON runtime_recovery_runs(trace_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_push_logs_idempotency ON push_logs(venue_id, channel, idempotency_key)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_decomposition_idempotency ON task_decompositions(venue_id, requested_by, idempotency_key)",
                "CREATE INDEX IF NOT EXISTS idx_task_decomposition_status ON task_decompositions(status, updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_decomposition ON tasks(decomposition_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_business_id ON tasks(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
                "CREATE INDEX IF NOT EXISTS idx_tasks_event ON tasks(venue_id, event_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_task_decomposition_event ON task_decompositions(venue_id, event_id, updated_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_business_id ON approval_requests(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
                "CREATE INDEX IF NOT EXISTS idx_approval_event ON approval_requests(venue_id, event_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_approval_task ON approval_requests(venue_id, task_id, status)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_idempotency ON approval_requests(venue_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''",
                "CREATE INDEX IF NOT EXISTS idx_event_activities_event ON event_activities(venue_id, event_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_event_activities_trace ON event_activities(venue_id, trace_id, created_at)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_activities_idempotency ON event_activities(venue_id, event_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_runs_channel_external ON message_runs(venue_id, channel, external_message_id)",
                "CREATE INDEX IF NOT EXISTS idx_channel_conversations_user ON channel_conversations(venue_id, user_id, updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_channel_identities_user ON channel_identities(venue_id, user_id, status)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_confirmed_events_business_id ON confirmed_events(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
            ):
                await db.execute(index_sql)

            for table_name in (
                "incident_logs",
                "approval_requests",
                "tool_invocation_logs",
                "tasks",
                "push_logs",
            ):
                await _add_sqlite_column(
                    db,
                    table_name,
                    "venue_id",
                    "TEXT DEFAULT ''",
                )

            await db.commit()
            logger.success(f"🎉 数据库初始化成功: {db_path}")

        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 数据库初始化失败: {e}")
            raise

    from .attachment_schema import init_attachment_schema
    from .experience_schema import init_experience_schema
    from ..scenic.schema import init_scenic_schema

    if db_client is not None:
        await init_experience_schema(db_client)
        await init_attachment_schema(db_client)
        await init_scenic_schema(db_client)
    else:
        from .db_client import AsyncDBClient

        experience_db = AsyncDBClient(db_path)
        try:
            await init_experience_schema(experience_db)
            await init_attachment_schema(experience_db)
            await init_scenic_schema(experience_db)
        finally:
            await experience_db.close()


async def _init_pg(db_client):
    """PostgreSQL database initialization using the passed PostgresDBClient."""
    tables = [
        """CREATE TABLE IF NOT EXISTS sop_documents (
            id SERIAL PRIMARY KEY,
            venue_id TEXT NOT NULL DEFAULT '',
            category VARCHAR(50) NOT NULL DEFAULT '通用',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 3,
            version VARCHAR(20) DEFAULT '1.0',
            status VARCHAR(20) DEFAULT 'DRAFT',
            source_event_id TEXT,
            created_by TEXT,
            reviewed_by TEXT,
            published_at DOUBLE PRECISION,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS incident_logs (
            id SERIAL PRIMARY KEY,
            case_id VARCHAR(64) UNIQUE NOT NULL,
            venue_id TEXT NOT NULL DEFAULT '',
            severity VARCHAR(10) NOT NULL,
            raw_query TEXT NOT NULL,
            ai_instruction TEXT,
            employee_feedback TEXT,
            is_resolved BOOLEAN DEFAULT FALSE,
            audit_status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id VARCHAR(64) PRIMARY KEY,
            user_id TEXT NOT NULL,
            venue_id TEXT NOT NULL DEFAULT '',
            agent_name TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            stage TEXT NOT NULL DEFAULT 'active',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            current_intent TEXT,
            current_severity TEXT,
            active_agent TEXT,
            context_payload TEXT DEFAULT '{}',
            history_summary TEXT DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS conversation_turns (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            timestamp DOUBLE PRECISION NOT NULL,
            input_text TEXT NOT NULL,
            output_text TEXT,
            structured_data TEXT DEFAULT '{}',
            tokens_used INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            message_id VARCHAR(64) UNIQUE NOT NULL,
            session_id TEXT,
            from_user TEXT NOT NULL,
            msg_type TEXT DEFAULT 'text',
            content TEXT DEFAULT '',
            sla_response_at DOUBLE PRECISION,
            created_at DOUBLE PRECISION,
            metadata TEXT DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS message_runs (
            message_id VARCHAR(64) PRIMARY KEY,
            trace_id VARCHAR(64) UNIQUE NOT NULL,
            session_id VARCHAR(64) NOT NULL,
            user_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            content TEXT NOT NULL,
            status VARCHAR(20) NOT NULL,
            channel TEXT NOT NULL DEFAULT 'LEGACY',
            external_message_id TEXT,
            external_conversation_id TEXT,
            target_agent TEXT,
            reply_text TEXT,
            result_json TEXT DEFAULT '{}',
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 4,
            manual_retry_count INTEGER NOT NULL DEFAULT 0,
            dead_letter_id TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'PENDING',
            delivery_error TEXT,
            delivered_at DOUBLE PRECISION,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            processed_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS approval_requests (
            approval_id TEXT PRIMARY KEY,
            business_id TEXT,
            venue_id TEXT NOT NULL DEFAULT '',
            tool_name TEXT NOT NULL,
            args TEXT NOT NULL,
            session_id TEXT,
            event_id TEXT,
            task_id TEXT,
            user_id TEXT,
            requested_at DOUBLE PRECISION NOT NULL,
            requested_by TEXT,
            supersedes_approval_id TEXT,
            idempotency_key TEXT,
            evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
            status TEXT DEFAULT 'PENDING',
            reviewed_at DOUBLE PRECISION,
            reviewed_by TEXT,
            comment TEXT,
            correlation_trace_id TEXT,
            execution_trace_id TEXT,
            execution_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
            execution_result TEXT,
            execution_error TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS tool_invocation_logs (
            id BIGSERIAL PRIMARY KEY,
            venue_id TEXT NOT NULL DEFAULT '',
            tool_name TEXT NOT NULL,
            args TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            agent_name TEXT,
            logged_at DOUBLE PRECISION NOT NULL,
            trace_id TEXT NOT NULL DEFAULT '',
            approval_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS personas (
            id VARCHAR(64) PRIMARY KEY,
            venue_id TEXT NOT NULL,
            job_title TEXT NOT NULL,
            logic_entries TEXT NOT NULL DEFAULT '[]',
            raw_answers TEXT DEFAULT '{}',
            description TEXT DEFAULT '',
            created_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS tasks (
            id VARCHAR(64) PRIMARY KEY,
            business_id TEXT,
            venue_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL,
            event_id TEXT,
            description TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'PENDING',
            dependencies TEXT DEFAULT '[]',
            due_at DOUBLE PRECISION,
            result_schema_json TEXT NOT NULL DEFAULT '{}',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            result TEXT,
            error TEXT,
            block_reason TEXT,
            assigned_agent TEXT,
            assigned_user_id TEXT,
            decomposition_id TEXT,
            created_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION,
            started_at DOUBLE PRECISION,
            completed_at DOUBLE PRECISION,
            attempts INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3
        )""",
        """CREATE TABLE IF NOT EXISTS task_decompositions (
            decomposition_id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_fingerprint TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_id TEXT,
            trace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            task_ids TEXT NOT NULL DEFAULT '[]',
            response_json TEXT,
            error TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS push_logs (
            id BIGSERIAL PRIMARY KEY,
            push_id TEXT UNIQUE NOT NULL,
            venue_id TEXT NOT NULL DEFAULT '',
            msg_id TEXT,
            from_user TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            event_type TEXT DEFAULT '其他',
            severity TEXT DEFAULT 'P3/P4',
            stage1_triggered BOOLEAN DEFAULT FALSE,
            hit_keywords TEXT DEFAULT '[]',
            stage2_triggered BOOLEAN,
            llm_confidence DOUBLE PRECISION,
            pushed_at DOUBLE PRECISION NOT NULL,
            confirmed_at DOUBLE PRECISION,
            adoption_status TEXT DEFAULT 'pending',
            confirmed_notes TEXT,
            confirmed_by TEXT,
            trace_id TEXT,
            channel TEXT NOT NULL DEFAULT 'legacy',
            recipient TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'RECORDED',
            delivery_error TEXT,
            delivery_claim_token TEXT,
            delivery_claimed_at DOUBLE PRECISION,
            idempotency_key TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS confirmed_events (
            id BIGSERIAL PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            business_id TEXT,
            push_id TEXT,
            from_user TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            context_trigger_data TEXT DEFAULT '{}',
            memory_content TEXT NOT NULL,
            vector_doc_id TEXT,
            created_at DOUBLE PRECISION,
            confirmed_at DOUBLE PRECISION,
            venue_id TEXT NOT NULL,
            source_type TEXT DEFAULT 'LIVE',
            status TEXT DEFAULT 'OPEN',
            assigned_to TEXT,
            resolution TEXT,
            trace_id TEXT,
            closed_at DOUBLE PRECISION,
            updated_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS event_activities (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            session_id TEXT,
            message_id TEXT,
            trace_id TEXT,
            activity_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_by TEXT,
            created_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS persona_interviews (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            source_persona_id TEXT,
            job_title TEXT NOT NULL,
            current_question INTEGER NOT NULL,
            all_entries_json TEXT NOT NULL DEFAULT '[]',
            raw_answers_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_by TEXT,
            trace_id TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            completed_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS venues (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'manager', 'operator')),
            venue_id TEXT NOT NULL REFERENCES venues(id),
            department TEXT,
            job_title TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            last_login_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS refresh_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            venue_id TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            revoked_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGSERIAL PRIMARY KEY,
            venue_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            outcome TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}',
            created_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS channel_conversations (
            session_id VARCHAR(64) PRIMARY KEY,
            venue_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            external_conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            UNIQUE (venue_id, channel, external_conversation_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS channel_identities (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            external_tenant_id TEXT NOT NULL DEFAULT '',
            external_user_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            UNIQUE (venue_id, channel, external_tenant_id, external_user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS knowledge_documents (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '通用',
            source_type TEXT NOT NULL DEFAULT 'MANUAL',
            source_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            tags_json TEXT NOT NULL DEFAULT '[]',
            vector_doc_id TEXT,
            import_batch_id TEXT,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS knowledge_retrieval_snapshots (
            id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL DEFAULT 1,
            venue_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            message_id TEXT,
            session_id TEXT,
            agent_id TEXT NOT NULL,
            query_summary TEXT NOT NULL,
            query_sha256 TEXT NOT NULL,
            backend TEXT NOT NULL,
            index_name TEXT,
            status TEXT NOT NULL,
            top_k INTEGER NOT NULL,
            similarity_threshold DOUBLE PRECISION NOT NULL,
            filter_json TEXT NOT NULL DEFAULT '{}',
            attempts_json TEXT NOT NULL DEFAULT '[]',
            references_json TEXT NOT NULL DEFAULT '[]',
            raw_hit_count INTEGER NOT NULL DEFAULT 0,
            selected_count INTEGER NOT NULL DEFAULT 0,
            error_type TEXT,
            error_message TEXT,
            started_at DOUBLE PRECISION NOT NULL,
            completed_at DOUBLE PRECISION NOT NULL,
            latency_ms INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS sop_versions (
            id TEXT PRIMARY KEY,
            sop_id INTEGER NOT NULL REFERENCES sop_documents(id),
            venue_id TEXT NOT NULL,
            version TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            change_note TEXT,
            created_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS watcher_policies (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            schedule_cron TEXT NOT NULL DEFAULT '0 10 * * *',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            check_types_json TEXT NOT NULL DEFAULT '[]',
            config_json TEXT NOT NULL DEFAULT '{}',
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            last_run_at DOUBLE PRECISION,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS watcher_runs (
            id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL REFERENCES watcher_policies(id),
            venue_id TEXT NOT NULL,
            event_id TEXT,
            trigger_source TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            model_name TEXT,
            target_count INTEGER NOT NULL DEFAULT 0,
            finding_count INTEGER NOT NULL DEFAULT 0,
            summary TEXT,
            target_snapshot_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            started_at DOUBLE PRECISION NOT NULL,
            completed_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS watcher_findings (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES watcher_runs(id),
            policy_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            event_id TEXT,
            finding_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'P2',
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            source_type TEXT,
            source_id TEXT,
            issue_fingerprint TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            assigned_to TEXT,
            resolution TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            closed_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS system_settings (
            venue_id TEXT NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            updated_by TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (venue_id, setting_key)
        )""",
        """CREATE TABLE IF NOT EXISTS backup_records (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            status TEXT NOT NULL,
            storage_path TEXT,
            checksum TEXT,
            size_bytes BIGINT,
            error TEXT,
            requested_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            completed_at DOUBLE PRECISION
        )""",
        """CREATE TABLE IF NOT EXISTS llm_call_logs (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL DEFAULT '',
            trace_id TEXT NOT NULL,
            agent_id TEXT NOT NULL DEFAULT '',
            agent_name TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT 'deepseek',
            model_name TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            latency_seconds DOUBLE PRECISION,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            request_id TEXT,
            error_type TEXT,
            error_message TEXT,
            is_mock BOOLEAN NOT NULL DEFAULT FALSE,
            created_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS runtime_recovery_runs (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL DEFAULT 'GLOBAL',
            venue_id TEXT NOT NULL DEFAULT '',
            instance_id TEXT NOT NULL,
            app_version TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            task_graph_recovered_count INTEGER NOT NULL DEFAULT 0,
            task_graph_reset_count INTEGER NOT NULL DEFAULT 0,
            approval_interrupted_count INTEGER NOT NULL DEFAULT 0,
            approval_pending_loaded_count INTEGER NOT NULL DEFAULT 0,
            watcher_interrupted_count INTEGER NOT NULL DEFAULT 0,
            redis_status TEXT NOT NULL DEFAULT 'NOT_CHECKED',
            redis_pending_count INTEGER NOT NULL DEFAULT 0,
            redis_claimed_count INTEGER NOT NULL DEFAULT 0,
            redis_acked_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            trace_json TEXT NOT NULL DEFAULT '[]',
            started_at DOUBLE PRECISION NOT NULL,
            completed_at DOUBLE PRECISION
        )""",
    ]

    for ddl in tables:
        await db_client.execute(ddl)

    migrations = [
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS current_intent TEXT",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS current_severity TEXT",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS active_agent TEXT",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS context_payload TEXT DEFAULT '{}'",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS history_summary TEXT DEFAULT ''",
        "ALTER TABLE incident_logs ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS business_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS event_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS task_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS supersedes_approval_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS evidence_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE tool_invocation_logs ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_user_id TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS decomposition_id TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS block_reason TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS business_id TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS event_id TEXT",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_at DOUBLE PRECISION",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS result_schema_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS evidence_refs_json TEXT NOT NULL DEFAULT '[]'",
        "ALTER TABLE task_decompositions ADD COLUMN IF NOT EXISTS event_id TEXT",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS venue_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'DRAFT'",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS source_event_id TEXT",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS reviewed_by TEXT",
        "ALTER TABLE sop_documents ADD COLUMN IF NOT EXISTS published_at DOUBLE PRECISION",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'LIVE'",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS business_id TEXT",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'OPEN'",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS assigned_to TEXT",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS resolution TEXT",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS trace_id TEXT",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS closed_at DOUBLE PRECISION",
        "ALTER TABLE confirmed_events ADD COLUMN IF NOT EXISTS updated_at DOUBLE PRECISION",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS execution_result TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS execution_error TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS correlation_trace_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS execution_trace_id TEXT",
        "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS execution_status TEXT NOT NULL DEFAULT 'NOT_STARTED'",
        "ALTER TABLE tool_invocation_logs ADD COLUMN IF NOT EXISTS trace_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tool_invocation_logs ADD COLUMN IF NOT EXISTS approval_id TEXT",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'legacy'",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS recipient TEXT",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'RECORDED'",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS delivery_error TEXT",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS delivery_claim_token TEXT",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS delivery_claimed_at DOUBLE PRECISION",
        "ALTER TABLE push_logs ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
        "ALTER TABLE llm_call_logs ADD COLUMN IF NOT EXISTS agent_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE llm_call_logs ADD COLUMN IF NOT EXISTS agent_name TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'LEGACY'",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS external_message_id TEXT",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS external_conversation_id TEXT",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 4",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS manual_retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS dead_letter_id TEXT",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS delivery_status TEXT NOT NULL DEFAULT 'PENDING'",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS delivery_error TEXT",
        "ALTER TABLE message_runs ADD COLUMN IF NOT EXISTS delivered_at DOUBLE PRECISION",
        "ALTER TABLE watcher_runs ADD COLUMN IF NOT EXISTS event_id TEXT",
        "ALTER TABLE watcher_runs ADD COLUMN IF NOT EXISTS model_name TEXT",
        "ALTER TABLE watcher_runs ADD COLUMN IF NOT EXISTS target_snapshot_json TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE watcher_findings ADD COLUMN IF NOT EXISTS event_id TEXT",
        "ALTER TABLE watcher_findings ADD COLUMN IF NOT EXISTS issue_fingerprint TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title TEXT",
    ]
    for ddl in migrations:
        await db_client.execute(ddl)

    await _isolate_legacy_wecom_identities(db_client)

    await db_client.execute(
        """
        UPDATE message_runs
        SET delivery_status = 'PERSISTED', delivery_error = NULL,
            delivered_at = COALESCE(delivered_at, processed_at, updated_at)
        WHERE status = 'COMPLETED'
          AND UPPER(COALESCE(channel, 'LEGACY'))
              IN ('WEB', 'WECOM_SIMULATOR', 'LEGACY', '')
          AND COALESCE(delivery_status, 'PENDING') = 'PENDING'
        """
    )

    if hasattr(db_client, "fetch_all"):
        for table_name, id_column, timestamp_column, prefix in (
            ("confirmed_events", "event_id", "created_at", "SJ"),
            ("tasks", "id", "created_at", "RW"),
            ("approval_requests", "approval_id", "requested_at", "SP"),
        ):
            existing_rows = await db_client.fetch_all(
                f"""
                SELECT {id_column} AS entity_id, {timestamp_column} AS occurred_at
                FROM {table_name}
                WHERE business_id IS NULL OR business_id = ''
                """
            )
            for row in existing_rows:
                await db_client.execute(
                    f"UPDATE {table_name} SET business_id = ? WHERE {id_column} = ?",
                    (
                        build_business_id(
                            prefix,
                            row["entity_id"],
                            row.get("occurred_at"),
                        ),
                        row["entity_id"],
                    ),
                )

    await db_client.execute(
        """
        INSERT INTO event_activities (
            id,
            venue_id,
            event_id,
            session_id,
            message_id,
            trace_id,
            activity_type,
            payload_json,
            idempotency_key,
            created_by,
            created_at
        )
        SELECT
            'legacy-event-created-' || confirmed_events.event_id,
            COALESCE(confirmed_events.venue_id, ''),
            confirmed_events.event_id,
            message_runs.session_id,
            confirmed_events.push_id,
            COALESCE(
                NULLIF(confirmed_events.trace_id, ''),
                message_runs.trace_id,
                ''
            ),
            'EVENT_CREATED',
            '{"backfilled":true}',
            'legacy:event-created:' || confirmed_events.event_id,
            confirmed_events.from_user,
            COALESCE(
                confirmed_events.created_at,
                confirmed_events.confirmed_at,
                confirmed_events.updated_at,
                EXTRACT(EPOCH FROM NOW())
            )
        FROM confirmed_events
        LEFT JOIN message_runs
          ON message_runs.message_id = confirmed_events.push_id
         AND message_runs.venue_id = COALESCE(confirmed_events.venue_id, '')
        WHERE NOT EXISTS (
            SELECT 1
            FROM event_activities AS existing_activity
            WHERE existing_activity.venue_id = COALESCE(confirmed_events.venue_id, '')
              AND existing_activity.event_id = confirmed_events.event_id
              AND existing_activity.activity_type = 'EVENT_CREATED'
        )
        ON CONFLICT (id) DO NOTHING
        """
    )

    for relationship_backfill_sql in (
        """
        UPDATE task_decompositions
        SET event_id = (
            SELECT MIN(event_activities.event_id)
            FROM event_activities
            WHERE event_activities.venue_id = task_decompositions.venue_id
              AND event_activities.session_id = task_decompositions.session_id
        )
        WHERE (event_id IS NULL OR event_id = '')
          AND (
              SELECT COUNT(DISTINCT event_activities.event_id)
              FROM event_activities
              WHERE event_activities.venue_id = task_decompositions.venue_id
                AND event_activities.session_id = task_decompositions.session_id
          ) = 1
        """,
        """
        UPDATE tasks
        SET event_id = (
            SELECT task_decompositions.event_id
            FROM task_decompositions
            WHERE task_decompositions.decomposition_id = tasks.decomposition_id
              AND task_decompositions.venue_id = tasks.venue_id
        )
        WHERE (event_id IS NULL OR event_id = '')
          AND decomposition_id IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM task_decompositions
              WHERE task_decompositions.decomposition_id = tasks.decomposition_id
                AND task_decompositions.venue_id = tasks.venue_id
                AND task_decompositions.event_id IS NOT NULL
                AND task_decompositions.event_id <> ''
          )
        """,
        """
        UPDATE tasks
        SET event_id = (
            SELECT MIN(event_activities.event_id)
            FROM event_activities
            WHERE event_activities.venue_id = tasks.venue_id
              AND event_activities.session_id = tasks.session_id
        )
        WHERE (event_id IS NULL OR event_id = '')
          AND (
              SELECT COUNT(DISTINCT event_activities.event_id)
              FROM event_activities
              WHERE event_activities.venue_id = tasks.venue_id
                AND event_activities.session_id = tasks.session_id
          ) = 1
        """,
        """
        UPDATE approval_requests
        SET event_id = (
            SELECT MIN(event_activities.event_id)
            FROM event_activities
            WHERE event_activities.venue_id = approval_requests.venue_id
              AND event_activities.session_id = approval_requests.session_id
        )
        WHERE (event_id IS NULL OR event_id = '')
          AND session_id IS NOT NULL
          AND (
              SELECT COUNT(DISTINCT event_activities.event_id)
              FROM event_activities
              WHERE event_activities.venue_id = approval_requests.venue_id
                AND event_activities.session_id = approval_requests.session_id
          ) = 1
        """,
    ):
        await db_client.execute(relationship_backfill_sql)

    # Create indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_stage ON sessions(stage)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_from_user ON messages(from_user)",
        "CREATE INDEX IF NOT EXISTS idx_incident_case ON incident_logs(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_personas_job ON personas(job_title)",
        "CREATE INDEX IF NOT EXISTS idx_persona_interviews_venue_status ON persona_interviews(venue_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_venue ON sessions(venue_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_message_runs_venue ON message_runs(venue_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_approval_venue ON approval_requests(venue_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_venue ON tasks(venue_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_push_logs_venue ON push_logs(venue_id, pushed_at)",
        "CREATE INDEX IF NOT EXISTS idx_confirmed_events_venue ON confirmed_events(venue_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_venue ON users(venue_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id, revoked_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_venue_time ON audit_logs(venue_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_logs(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_venue_status ON knowledge_documents(venue_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_trace ON knowledge_retrieval_snapshots(venue_id, trace_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_message ON knowledge_retrieval_snapshots(venue_id, message_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_sop_venue_status ON sop_documents(venue_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_sop_versions_sop ON sop_versions(sop_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_watcher_policy_venue ON watcher_policies(venue_id, enabled)",
        "CREATE INDEX IF NOT EXISTS idx_watcher_runs_venue ON watcher_runs(venue_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_watcher_runs_event ON watcher_runs(venue_id, event_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_watcher_findings_venue ON watcher_findings(venue_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_watcher_findings_event ON watcher_findings(venue_id, event_id, status, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_watcher_open_finding_fingerprint ON watcher_findings(venue_id, policy_id, source_type, source_id, issue_fingerprint) WHERE status != 'CLOSED' AND issue_fingerprint IS NOT NULL AND issue_fingerprint != ''",
        "CREATE INDEX IF NOT EXISTS idx_backup_venue ON backup_records(venue_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_venue_time ON llm_call_logs(venue_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_trace ON llm_call_logs(trace_id)",
        "CREATE INDEX IF NOT EXISTS idx_runtime_recovery_scope_time ON runtime_recovery_runs(scope_type, venue_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_runtime_recovery_trace ON runtime_recovery_runs(trace_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_push_logs_idempotency ON push_logs(venue_id, channel, idempotency_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_decomposition_idempotency ON task_decompositions(venue_id, requested_by, idempotency_key)",
        "CREATE INDEX IF NOT EXISTS idx_task_decomposition_status ON task_decompositions(status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_decomposition ON tasks(decomposition_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_business_id ON tasks(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
        "CREATE INDEX IF NOT EXISTS idx_tasks_event ON tasks(venue_id, event_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_task_decomposition_event ON task_decompositions(venue_id, event_id, updated_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_business_id ON approval_requests(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
        "CREATE INDEX IF NOT EXISTS idx_approval_event ON approval_requests(venue_id, event_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_approval_task ON approval_requests(venue_id, task_id, status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_idempotency ON approval_requests(venue_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''",
        "CREATE INDEX IF NOT EXISTS idx_event_activities_event ON event_activities(venue_id, event_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_event_activities_trace ON event_activities(venue_id, trace_id, created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_activities_idempotency ON event_activities(venue_id, event_id, idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_runs_channel_external ON message_runs(venue_id, channel, external_message_id)",
        "CREATE INDEX IF NOT EXISTS idx_channel_conversations_user ON channel_conversations(venue_id, user_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_channel_identities_user ON channel_identities(venue_id, user_id, status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_confirmed_events_business_id ON confirmed_events(venue_id, business_id) WHERE business_id IS NOT NULL AND business_id <> ''",
    ]
    for idx in indexes:
        await db_client.execute(idx)

    logger.success("PostgreSQL 数据库初始化完成")


def init_database_sync():
    """同步包装器（用于命令行直接运行）"""
    asyncio.run(init_database())


if __name__ == "__main__":
    init_database_sync()
