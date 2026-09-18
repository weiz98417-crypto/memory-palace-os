"""Schema for scenic signals, alerts, incidents, commands, and ordered projections."""

from __future__ import annotations


def _statements(*, postgres: bool) -> tuple[str, ...]:
    sequence_column = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return (
        """
        CREATE TABLE IF NOT EXISTS scenic_simulation_runs (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            scenario_key TEXT NOT NULL,
            scenario_version TEXT NOT NULL,
            status TEXT NOT NULL,
            speed DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            simulated_at DOUBLE PRECISION NOT NULL,
            started_simulated_at DOUBLE PRECISION NOT NULL,
            last_wall_tick DOUBLE PRECISION,
            prepared_by TEXT NOT NULL,
            preparation_key TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            UNIQUE (venue_id, preparation_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_monitoring_signals (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_adapter TEXT NOT NULL,
            source_key TEXT NOT NULL,
            zone_id TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            simulated_at DOUBLE PRECISION NOT NULL,
            recorded_at DOUBLE PRECISION NOT NULL,
            source_sequence INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL,
            UNIQUE (venue_id, idempotency_key),
            UNIQUE (run_id, source_sequence)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_situation_alerts (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            rule_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            zone_id TEXT NOT NULL,
            source_key TEXT NOT NULL,
            title TEXT NOT NULL,
            details_json TEXT NOT NULL,
            first_signal_id TEXT NOT NULL,
            latest_signal_id TEXT NOT NULL,
            incident_id TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            recovered_at DOUBLE PRECISION,
            UNIQUE (run_id, rule_code, source_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_incidents (
            incident_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            run_id TEXT NOT NULL,
            venue_id TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            priority TEXT NOT NULL,
            title TEXT NOT NULL,
            conversion_reason TEXT NOT NULL,
            converted_by TEXT NOT NULL,
            repair_task_id TEXT,
            diversion_task_id TEXT,
            decision_approval_id TEXT,
            resolved_at DOUBLE PRECISION,
            closed_at DOUBLE PRECISION,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_event_evidence (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            text_content TEXT,
            attachment_id TEXT,
            submitted_by TEXT NOT NULL,
            simulated_at DOUBLE PRECISION NOT NULL,
            recorded_at DOUBLE PRECISION NOT NULL,
            idempotency_key TEXT NOT NULL,
            UNIQUE (venue_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_knowledge_hits (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            query_text TEXT NOT NULL,
            vector_doc_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_version TEXT NOT NULL,
            score DOUBLE PRECISION NOT NULL,
            backend TEXT NOT NULL,
            model_name TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            recorded_at DOUBLE PRECISION NOT NULL,
            idempotency_key TEXT NOT NULL,
            UNIQUE (venue_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_notification_receipts (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            push_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            status TEXT NOT NULL,
            delivered_at DOUBLE PRECISION NOT NULL,
            acknowledged_at DOUBLE PRECISION,
            receipt_at DOUBLE PRECISION,
            result_json TEXT,
            updated_at DOUBLE PRECISION NOT NULL,
            UNIQUE (venue_id, task_id),
            UNIQUE (venue_id, push_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS scenic_situation_events (
            sequence {sequence_column},
            event_id TEXT NOT NULL UNIQUE,
            venue_id TEXT NOT NULL,
            run_id TEXT,
            event_type TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            payload_json TEXT NOT NULL,
            simulated_at DOUBLE PRECISION,
            recorded_at DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_commands (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            command_type TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            response_json TEXT,
            request_json TEXT,
            error_type TEXT,
            error_message TEXT,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            UNIQUE (venue_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenic_evaluation_runs (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            tier TEXT NOT NULL,
            case_set TEXT NOT NULL,
            case_count INTEGER NOT NULL,
            passed_count INTEGER NOT NULL,
            failed_count INTEGER NOT NULL,
            pass_rate DOUBLE PRECISION NOT NULL,
            judge_model TEXT,
            context_source TEXT,
            elapsed_seconds DOUBLE PRECISION,
            summary_json TEXT NOT NULL DEFAULT '{}',
            results_json TEXT NOT NULL DEFAULT '[]',
            created_at DOUBLE PRECISION NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_scenic_signals_run_time ON scenic_monitoring_signals (venue_id, run_id, simulated_at)",
        "CREATE INDEX IF NOT EXISTS idx_scenic_alerts_status ON scenic_situation_alerts (venue_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_scenic_incidents_state ON scenic_incidents (venue_id, lifecycle, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_scenic_receipts_incident ON scenic_notification_receipts (venue_id, incident_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_scenic_events_sequence ON scenic_situation_events (venue_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_scenic_eval_runs_venue ON scenic_evaluation_runs (venue_id, created_at DESC)",
    )


async def init_scenic_schema(database) -> None:
    postgres = getattr(database, "backend_name", "") == "postgresql"
    for statement in _statements(postgres=postgres):
        await database.execute(statement)
    await _ensure_scenic_commands_request_json(database, postgres=postgres)


async def _ensure_scenic_commands_request_json(database, *, postgres: bool) -> None:
    """Add the Agent-run request payload to pre-existing scenic_commands tables."""

    try:
        rows = await database.fetch_all("SELECT * FROM scenic_commands LIMIT 0")
    except Exception:
        return
    columns: set[str] = set()
    for row in rows or []:
        columns.update(str(key) for key in (row.keys() if hasattr(row, "keys") else row))
    if columns and "request_json" in columns:
        return
    try:
        await database.execute(
            "ALTER TABLE scenic_commands ADD COLUMN request_json TEXT"
        )
    except Exception:
        # A concurrent initialiser may have added it first; that is fine.
        return
