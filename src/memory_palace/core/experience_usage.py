"""Durable, idempotent accounting for experience references."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from uuid import uuid4


class ExperienceUsagePersistenceError(RuntimeError):
    """Raised when an experience reference cannot be durably accounted for."""


@dataclass(frozen=True)
class ExperienceUsageContext:
    venue_id: str
    user_id: str
    message_id: str
    trace_id: str
    session_id: str
    retrieval_snapshot_id: str
    query_text: str
    agent_id: str = "Persona"

    def __post_init__(self) -> None:
        required = {
            "venue_id": self.venue_id,
            "user_id": self.user_id,
            "message_id": self.message_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "retrieval_snapshot_id": self.retrieval_snapshot_id,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"experience usage context is missing: {', '.join(missing)}")


class ExperienceUsageLedger:
    """Verify and persist every experience reference before it is returned."""

    def __init__(self, database: Any):
        if database is None:
            raise ValueError("database is required")
        self._database = database

    async def record_references(
        self,
        context: ExperienceUsageContext,
        references: Iterable[Mapping[str, Any]],
    ) -> list[str]:
        usage_ids: list[str] = []
        for reference in references:
            if str(reference.get("source_type") or "").upper() not in {
                "EXPERIENCE",
                "EXPERIENCE_CARD",
            }:
                continue
            usage_ids.append(await self._record_reference(context, reference))
        return usage_ids

    async def _record_reference(
        self,
        context: ExperienceUsageContext,
        reference: Mapping[str, Any],
    ) -> str:
        card_id = str(reference.get("source_id") or "").strip()
        status = str(reference.get("status") or "").upper()
        try:
            version = int(str(reference.get("version") or "").strip())
        except (TypeError, ValueError):
            version = 0
        if not card_id or status != "PUBLISHED" or version < 1:
            raise ExperienceUsagePersistenceError(
                "experience reference is not a published version"
            )

        try:
            card = await self._database.fetch_one(
                """
                SELECT id, published_version
                FROM experience_cards
                WHERE id = ? AND venue_id = ? AND status = 'PUBLISHED'
                """,
                (card_id, context.venue_id),
            )
            if card is None or int(card.get("published_version") or 0) != version:
                raise ExperienceUsagePersistenceError(
                    "experience reference changed before usage was recorded"
                )

            idempotency_key = hashlib.sha256(
                (
                    f"{context.venue_id}:{context.message_id}:{card_id}:"
                    f"{version}:REFERENCED"
                ).encode("utf-8")
            ).hexdigest()
            usage_id = uuid4().hex
            await self._database.execute(
                """
                INSERT INTO experience_usage_logs (
                    id, venue_id, card_id, user_id, session_id, usage_type,
                    query_text, score, created_at, message_id, trace_id,
                    retrieval_snapshot_id, experience_version, agent_id,
                    idempotency_key
                ) VALUES (?, ?, ?, ?, ?, 'REFERENCED', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    usage_id,
                    context.venue_id,
                    card_id,
                    context.user_id,
                    context.session_id,
                    context.query_text,
                    reference.get("score"),
                    time.time(),
                    context.message_id,
                    context.trace_id,
                    context.retrieval_snapshot_id,
                    version,
                    context.agent_id,
                    idempotency_key,
                ),
            )
            persisted = await self._database.fetch_one(
                """
                SELECT id
                FROM experience_usage_logs
                WHERE venue_id = ? AND idempotency_key = ?
                """,
                (context.venue_id, idempotency_key),
            )
            if persisted is None:
                raise ExperienceUsagePersistenceError(
                    "experience usage record was not persisted"
                )
            return str(persisted["id"])
        except ExperienceUsagePersistenceError:
            raise
        except Exception:
            raise ExperienceUsagePersistenceError(
                "experience usage persistence is unavailable"
            ) from None
