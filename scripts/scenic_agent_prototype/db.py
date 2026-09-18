"""Database and TEI helpers for the scenic Agent prototype."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import asyncpg
import httpx


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"


class PrototypeDB:
    def __init__(self, dsn: str, password: str | None = None) -> None:
        self.dsn = dsn
        self.password = password
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> "PrototypeDB":
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                password=self.password or None,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
        return self

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def fetch_one(self, query: str, *args: Any) -> dict[str, Any] | None:
        pool = await self._pool()
        row = await pool.fetchrow(query, *args)
        return dict(row) if row else None

    async def fetch_all(self, query: str, *args: Any) -> list[dict[str, Any]]:
        pool = await self._pool()
        return [dict(row) for row in await pool.fetch(query, *args)]

    async def execute(self, query: str, *args: Any) -> str:
        pool = await self._pool()
        return await pool.execute(query, *args)

    async def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            await self.connect()
        assert self.pool is not None
        return self.pool

    async def insert_model_call(self, record: dict[str, Any]) -> None:
        await self.execute(
            """
            INSERT INTO llm_call_logs (
                id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
                status, attempt_count, latency_seconds, prompt_tokens,
                completion_tokens, total_tokens, request_id, error_type,
                error_message, is_mock, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18
            )
            ON CONFLICT (id) DO NOTHING
            """,
            record["id"],
            record["venue_id"],
            record["trace_id"],
            record["agent_id"],
            record["agent_name"],
            record["provider"],
            record["model_name"],
            record["status"],
            record["attempt_count"],
            record["latency_seconds"],
            record["prompt_tokens"],
            record["completion_tokens"],
            record["total_tokens"],
            record["request_id"],
            record["error_type"],
            record["error_message"],
            record["is_mock"],
            record["created_at"],
        )

    async def append_activity(
        self,
        *,
        venue_id: str,
        event_id: str,
        activity_type: str,
        payload: dict[str, Any],
        trace_id: str,
        created_by: str,
        idempotency_key: str,
    ) -> str:
        activity_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"memory-palace-event-activity:{venue_id}:{event_id}:{idempotency_key}",
            )
        )
        await self.execute(
            """
            INSERT INTO event_activities (
                id, venue_id, event_id, trace_id, activity_type, payload_json,
                idempotency_key, created_by, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT DO NOTHING
            """,
            activity_id,
            venue_id,
            event_id,
            trace_id,
            activity_type,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            idempotency_key,
            created_by,
            time.time(),
        )
        return activity_id

    async def fetch_sop(self, venue_id: str, source_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            """
            SELECT id, title, content, version, status
            FROM sop_documents
            WHERE venue_id = $1 AND CAST(id AS TEXT) = $2 AND status = 'PUBLISHED'
            """,
            venue_id,
            str(source_id),
        )

    async def query_tei_sop_candidates(
        self,
        *,
        venue_id: str,
        query_vector: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        literal = vector_literal(query_vector)
        return await self.fetch_all(
            """
            SELECT kv.doc_id, kv.source_id, kv.source_version, kv.content,
                   sd.title, 1 - (kv.embedding <=> $1::vector) AS similarity
            FROM knowledge_vectors AS kv
            JOIN sop_documents AS sd
              ON sd.venue_id = kv.venue_id
             AND CAST(sd.id AS TEXT) = kv.source_id
            WHERE kv.venue_id = $2
              AND kv.index_name = 'knowledge_vectors_bge_m3_v1'
              AND kv.source_type = 'SOP'
              AND kv.index_status = 'READY'
              AND kv.dimension = 1024
              AND sd.status = 'PUBLISHED'
            ORDER BY kv.embedding <=> $1::vector
            LIMIT $3
            """,
            literal,
            venue_id,
            int(limit),
        )

    async def seed_vehicle_alert(
        self,
        *,
        venue_id: str,
        run_label: str,
    ) -> str:
        """Seed a test-only monitoring fixture; model/knowledge evidence stays real."""
        run_id = str(uuid.uuid4())
        signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:vehicle-signal"))
        alert_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:vehicle-alert"))
        now = time.time()
        await self.execute(
            """
            INSERT INTO scenic_simulation_runs (
                id, venue_id, scenario_key, scenario_version, status, speed,
                simulated_at, started_simulated_at, last_wall_tick, prepared_by,
                preparation_key, created_at, updated_at
            ) VALUES ($1, $2, 'agent_prototype', '1.0', 'RUNNING', 1.0,
                      $3, $3, $3, 'ticket-08-prototype', $4, $3, $3)
            """,
            run_id,
            venue_id,
            now,
            run_label,
        )
        await self.execute(
            """
            INSERT INTO scenic_monitoring_signals (
                id, run_id, venue_id, source_type, source_adapter, source_key,
                zone_id, signal_type, payload_json, simulated_at, recorded_at,
                source_sequence, idempotency_key
            ) VALUES ($1, $2, $3, 'DEVICE', 'PROTOTYPE_FIXTURE', 'vehicle-12',
                      'vehicle-depot', 'DEVICE_ANOMALY', $4, $5, $5, 1, $6)
            """,
            signal_id,
            run_id,
            venue_id,
            json.dumps({"status": "FAULT", "wheel": "right-rear"}, ensure_ascii=False),
            now,
            f"{run_label}:signal",
        )
        await self.execute(
            """
            INSERT INTO scenic_situation_alerts (
                id, business_id, run_id, venue_id, rule_code, severity, status,
                zone_id, source_key, title, details_json, first_signal_id,
                latest_signal_id, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'VEHICLE_12_RIGHT_REAR_WHEEL', 'P1', 'ACTIVE',
                      'vehicle-depot', 'vehicle-12', '12 号观光车右后轮异常',
                      $5, $6, $6, $7, $7)
            """,
            alert_id,
            f"PROTO-{run_label}",
            run_id,
            venue_id,
            json.dumps({"status": "FAULT", "wheel": "right-rear"}, ensure_ascii=False),
            signal_id,
            now,
        )
        return alert_id

    async def fetch_verified_hit(self, venue_id: str, incident_id: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            """
            SELECT hit.*, sop.title
            FROM scenic_knowledge_hits AS hit
            LEFT JOIN sop_documents AS sop
              ON sop.venue_id = hit.venue_id
             AND CAST(sop.id AS TEXT) = hit.source_id
            WHERE hit.venue_id = $1 AND hit.incident_id = $2
              AND hit.source_type = 'SOP'
            ORDER BY hit.recorded_at DESC, hit.id DESC
            LIMIT 1
            """,
            venue_id,
            incident_id,
        )

    async def fetch_model_calls(self, venue_id: str, trace_id: str) -> list[dict[str, Any]]:
        return await self.fetch_all(
            """
            SELECT id, venue_id, trace_id, agent_id, agent_name, provider, model_name,
                   status, attempt_count, latency_seconds, prompt_tokens,
                   completion_tokens, total_tokens, request_id, is_mock, created_at
            FROM llm_call_logs
            WHERE venue_id = $1 AND trace_id = $2
            ORDER BY created_at ASC, id ASC
            """,
            venue_id,
            trace_id,
        )

    async def fetch_activity(self, venue_id: str, event_id: str, activity_type: str) -> dict[str, Any] | None:
        return await self.fetch_one(
            """
            SELECT *
            FROM event_activities
            WHERE venue_id = $1 AND event_id = $2 AND activity_type = $3
            ORDER BY created_at DESC
            LIMIT 1
            """,
            venue_id,
            event_id,
            activity_type,
        )


async def tei_embed(base_url: str, text: str, *, timeout: float = 20.0) -> list[float]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/embed",
            json={"inputs": [text]},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise RuntimeError("TEI returned an invalid embedding payload")
    vector = [float(value) for value in payload[0]]
    if len(vector) != 1024:
        raise RuntimeError(f"TEI returned {len(vector)} dimensions, expected 1024")
    return vector


def secret_from_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path = os.environ.get(f"{name}_FILE", "").strip()
    if path:
        return open(path, "r", encoding="utf-8-sig").read().strip()
    raise RuntimeError(f"{name} or {name}_FILE is required")
