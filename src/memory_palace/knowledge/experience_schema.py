"""Portable relational schema for governed expert experience assets."""

from typing import Protocol


class _SchemaDatabase(Protocol):
    async def execute(self, sql: str, parameters: tuple = ()) -> int: ...


_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS expert_profiles (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        venue_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        job_title TEXT,
        department TEXT,
        years_experience INTEGER NOT NULL DEFAULT 0,
        expertise_json TEXT NOT NULL DEFAULT '[]',
        authorization_status TEXT NOT NULL DEFAULT 'PENDING',
        authorization_statement TEXT,
        authorization_signed_at DOUBLE PRECISION,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, business_id),
        UNIQUE (venue_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_interviews (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        venue_id TEXT NOT NULL,
        expert_id TEXT NOT NULL,
        title TEXT NOT NULL,
        source_event_id TEXT,
        status TEXT NOT NULL DEFAULT 'INVITED',
        current_question_index INTEGER NOT NULL DEFAULT 0,
        accepted_at DOUBLE PRECISION,
        paused_at DOUBLE PRECISION,
        completed_at DOUBLE PRECISION,
        cancelled_at DOUBLE PRECISION,
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, business_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_interview_turns (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        interview_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        answer_text TEXT,
        source_excerpt TEXT,
        idempotency_key TEXT,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, interview_id, turn_number),
        UNIQUE (venue_id, interview_id, idempotency_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_interview_authorizations (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        interview_id TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_value TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, interview_id, scope_type, scope_value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_cards (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        venue_id TEXT NOT NULL,
        expert_id TEXT NOT NULL,
        source_interview_id TEXT,
        source_event_id TEXT,
        title TEXT NOT NULL,
        applicable_context TEXT NOT NULL,
        signals_json TEXT NOT NULL DEFAULT '[]',
        decision_rule TEXT NOT NULL,
        recommended_actions_json TEXT NOT NULL DEFAULT '[]',
        rationale TEXT NOT NULL,
        prohibitions_json TEXT NOT NULL DEFAULT '[]',
        exceptions_json TEXT NOT NULL DEFAULT '[]',
        source_excerpts_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        current_version INTEGER NOT NULL DEFAULT 1,
        published_version INTEGER,
        vector_doc_id TEXT,
        extraction_trace_id TEXT,
        index_status TEXT NOT NULL DEFAULT 'NOT_INDEXED',
        created_by TEXT NOT NULL,
        updated_by TEXT,
        confirmed_by TEXT,
        reviewed_by TEXT,
        published_by TEXT,
        confirmed_at DOUBLE PRECISION,
        published_at DOUBLE PRECISION,
        deprecated_at DOUBLE PRECISION,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, business_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_candidates (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        venue_id TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        source_event_business_id TEXT,
        title TEXT NOT NULL DEFAULT '',
        applicable_context TEXT NOT NULL DEFAULT '',
        signals_json TEXT NOT NULL DEFAULT '[]',
        decision_rule TEXT NOT NULL DEFAULT '',
        recommended_actions_json TEXT NOT NULL DEFAULT '[]',
        rationale TEXT NOT NULL DEFAULT '',
        prohibitions_json TEXT NOT NULL DEFAULT '[]',
        exceptions_json TEXT NOT NULL DEFAULT '[]',
        source_excerpts_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        index_status TEXT NOT NULL DEFAULT 'NOT_INDEXED',
        extraction_status TEXT NOT NULL DEFAULT 'PENDING',
        extraction_model TEXT NOT NULL DEFAULT 'deepseek-v4-flash',
        extraction_trace_id TEXT,
        extraction_error TEXT,
        retryable BOOLEAN NOT NULL DEFAULT TRUE,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        event_snapshot_json TEXT NOT NULL DEFAULT '{}',
        task_results_snapshot_json TEXT NOT NULL DEFAULT '[]',
        approval_evidence_snapshot_json TEXT NOT NULL DEFAULT '[]',
        watcher_evidence_snapshot_json TEXT NOT NULL DEFAULT '{}',
        evidence_fingerprint TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        updated_at DOUBLE PRECISION NOT NULL,
        extraction_started_at DOUBLE PRECISION,
        generated_at DOUBLE PRECISION,
        UNIQUE (venue_id, business_id),
        UNIQUE (venue_id, source_event_id),
        CHECK (status = 'DRAFT'),
        CHECK (index_status = 'NOT_INDEXED'),
        CHECK (extraction_model = 'deepseek-v4-flash'),
        CHECK (extraction_status IN ('PENDING', 'EXTRACTING', 'SUCCEEDED', 'FAILED'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_candidate_attempts (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        candidate_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        trace_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence_fingerprint TEXT NOT NULL,
        error TEXT,
        started_at DOUBLE PRECISION NOT NULL,
        completed_at DOUBLE PRECISION,
        UNIQUE (venue_id, candidate_id, attempt_number),
        CHECK (model_name = 'deepseek-v4-flash'),
        CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_card_versions (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        card_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        change_note TEXT,
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, card_id, version_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_authorizations (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        card_id TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_value TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, card_id, scope_type, scope_value)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_reviews (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        card_id TEXT NOT NULL,
        action TEXT NOT NULL,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        comment TEXT,
        actor_id TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experience_usage_logs (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        card_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        session_id TEXT,
        usage_type TEXT NOT NULL,
        query_text TEXT,
        score DOUBLE PRECISION,
        note TEXT,
        message_id TEXT,
        trace_id TEXT,
        retrieval_snapshot_id TEXT,
        experience_version INTEGER,
        agent_id TEXT,
        idempotency_key TEXT,
        created_at DOUBLE PRECISION NOT NULL
    )
    """,
)

_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_experts_venue_status ON expert_profiles(venue_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_experts_venue_user ON expert_profiles(venue_id, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_interviews_venue_status ON experience_interviews(venue_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_interviews_expert ON experience_interviews(venue_id, expert_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_interviews_source_event ON experience_interviews(venue_id, source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_interview_turns_lookup ON experience_interview_turns(venue_id, interview_id, turn_number)",
    "CREATE INDEX IF NOT EXISTS idx_interview_auth_scope ON experience_interview_authorizations(venue_id, interview_id, scope_type, scope_value)",
    "CREATE INDEX IF NOT EXISTS idx_experience_cards_venue_status ON experience_cards(venue_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_cards_expert ON experience_cards(venue_id, expert_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_cards_source_interview ON experience_cards(venue_id, source_interview_id)",
    "CREATE INDEX IF NOT EXISTS idx_experience_cards_source_event ON experience_cards(venue_id, source_event_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_experience_cards_source_interview_unique ON experience_cards(venue_id, source_interview_id) WHERE source_interview_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_experience_candidates_venue_status ON experience_candidates(venue_id, extraction_status, updated_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_experience_candidates_source_event_unique ON experience_candidates(venue_id, source_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_experience_candidate_attempts_lookup ON experience_candidate_attempts(venue_id, candidate_id, attempt_number)",
    "CREATE INDEX IF NOT EXISTS idx_experience_candidate_attempts_trace ON experience_candidate_attempts(venue_id, trace_id)",
    "CREATE INDEX IF NOT EXISTS idx_experience_versions_card ON experience_card_versions(venue_id, card_id, version_number)",
    "CREATE INDEX IF NOT EXISTS idx_experience_auth_scope ON experience_authorizations(venue_id, card_id, scope_type, scope_value)",
    "CREATE INDEX IF NOT EXISTS idx_experience_reviews_card ON experience_reviews(venue_id, card_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_reviews_status ON experience_reviews(venue_id, to_status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_usage_card ON experience_usage_logs(venue_id, card_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_usage_user ON experience_usage_logs(venue_id, user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_usage_trace ON experience_usage_logs(venue_id, trace_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_experience_usage_message ON experience_usage_logs(venue_id, message_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_experience_usage_idempotency ON experience_usage_logs(venue_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
)

_USER_PROFILE_COLUMN_STATEMENTS = (
    "ALTER TABLE users ADD COLUMN department TEXT",
    "ALTER TABLE users ADD COLUMN job_title TEXT",
)

_EXPERIENCE_MIGRATION_STATEMENTS = (
    "ALTER TABLE experience_cards ADD COLUMN extraction_trace_id TEXT",
    "ALTER TABLE expert_profiles ADD COLUMN authorization_status TEXT NOT NULL DEFAULT 'PENDING'",
    "ALTER TABLE expert_profiles ADD COLUMN authorization_statement TEXT",
    "ALTER TABLE expert_profiles ADD COLUMN authorization_signed_at DOUBLE PRECISION",
    "ALTER TABLE experience_usage_logs ADD COLUMN message_id TEXT",
    "ALTER TABLE experience_usage_logs ADD COLUMN trace_id TEXT",
    "ALTER TABLE experience_usage_logs ADD COLUMN retrieval_snapshot_id TEXT",
    "ALTER TABLE experience_usage_logs ADD COLUMN experience_version INTEGER",
    "ALTER TABLE experience_usage_logs ADD COLUMN agent_id TEXT",
    "ALTER TABLE experience_usage_logs ADD COLUMN idempotency_key TEXT",
)


async def init_experience_schema(db: _SchemaDatabase) -> None:
    """Create experience asset tables and lookup indexes idempotently."""
    for statement in _USER_PROFILE_COLUMN_STATEMENTS:
        try:
            await db.execute(statement)
        except Exception:
            # SQLite lacks ADD COLUMN IF NOT EXISTS; duplicate/missing base tables
            # must not prevent this independently initialized domain schema.
            pass

    for statement in _TABLE_STATEMENTS:
        await db.execute(statement)

    for statement in _EXPERIENCE_MIGRATION_STATEMENTS:
        try:
            await db.execute(statement)
        except Exception:
            # Existing installations may already have the additive column.
            pass

    for statement in _INDEX_STATEMENTS:
        await db.execute(statement)
