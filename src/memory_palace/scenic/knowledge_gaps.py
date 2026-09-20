"""Knowledge-gap facts, annotations, and topic governance.

Retrieval facts remain in `scenic_commands`; this module only derives gap views and
stores human governance annotations/topics in separate tables.
"""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from typing import Any

GAP_STATUSES = frozenset({"OPEN", "ACKNOWLEDGED", "RESOLVED", "REOPENED"})
TOPIC_STATUSES = frozenset({"ACTIVE", "MERGED"})
RESOLUTION_TYPES = frozenset(
    {
        "NEW_SOP",
        "EXISTING_SOP_UPDATED",
        "EXPERT_EXPERIENCE",
        "NOT_A_GAP",
        "DUPLICATE_TOPIC",
    }
)
TRIM_CHARS = " \t\r\n,，。.;；:：!！?？、"


class KnowledgeGapError(ValueError):
    pass


class KnowledgeGapNotFound(KnowledgeGapError):
    pass


class KnowledgeGapConflict(KnowledgeGapError):
    pass


class KnowledgeGapInputError(KnowledgeGapError):
    pass


def normalize_query(query: str) -> str:
    """Conservative, deterministic normalization; no semantic clustering."""

    text = unicodedata.normalize("NFKC", str(query or "")).casefold()
    text = " ".join(text.split())
    return text.strip(TRIM_CHARS)


def gap_id_for(venue_id: str, normalized_query: str) -> str:
    return hashlib.sha256(f"{venue_id}:{normalized_query}".encode()).hexdigest()[:32]


class KnowledgeGapRepository:
    def __init__(self, database: Any, *, clock: Callable[[], float] | None = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time

    def _now(self) -> float:
        return float(self._clock())

    async def list_gaps(self, *, venue_id: str) -> list[dict[str, Any]]:
        facts = await self._gap_facts(venue_id=venue_id)
        annotations = await self._annotations(venue_id=venue_id)
        members = await self._members(venue_id=venue_id)
        topics = await self._topics(venue_id=venue_id)
        topic_by_id = {topic["topic_id"]: topic for topic in topics}

        items: list[dict[str, Any]] = []
        for gap_id, fact in facts.items():
            annotation = annotations.get(gap_id)
            stored_status = str((annotation or {}).get("status") or "OPEN")
            resolved_at = (annotation or {}).get("resolved_at")
            derived_status = stored_status
            if (
                stored_status == "RESOLVED"
                and resolved_at is not None
                and fact["last_seen"] > float(resolved_at)
            ):
                derived_status = "REOPENED"
            member = members.get(gap_id)
            topic = topic_by_id.get(str((member or {}).get("topic_id") or ""))
            items.append(
                {
                    **fact,
                    "gap_id": gap_id,
                    "status": derived_status,
                    "annotation": annotation,
                    "topic": topic,
                }
            )
        items.sort(key=lambda item: (-float(item["last_seen"]), item["normalized_query"]))
        return items

    async def get_gap(self, *, venue_id: str, gap_id: str) -> dict[str, Any]:
        for item in await self.list_gaps(venue_id=venue_id):
            if item["gap_id"] == gap_id:
                return item
        raise KnowledgeGapNotFound("knowledge gap was not found")

    async def acknowledge(
        self, *, venue_id: str, gap_id: str, actor_id: str, trace_id: str
    ) -> dict[str, Any]:
        gap = await self._require_gap(venue_id=venue_id, gap_id=gap_id)
        if gap["status"] in {"RESOLVED", "REOPENED"}:
            raise KnowledgeGapConflict("resolved knowledge gap must be reopened first")
        now = self._now()
        await self._upsert_annotation(
            venue_id=venue_id,
            gap_id=gap_id,
            status="ACKNOWLEDGED",
            resolution_type=None,
            resolution_note=None,
            resolved_at=None,
            actor_id=actor_id,
            now=now,
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_GAP_ACKNOWLEDGED",
            resource_type="scenic_knowledge_gap",
            resource_id=gap_id,
            trace_id=trace_id,
            metadata={},
        )
        return await self.get_gap(venue_id=venue_id, gap_id=gap_id)

    async def resolve(
        self,
        *,
        venue_id: str,
        gap_id: str,
        resolution_type: str,
        note: str | None,
        actor_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        gap = await self._require_gap(venue_id=venue_id, gap_id=gap_id)
        resolution_type = str(resolution_type or "").strip().upper()
        if resolution_type not in RESOLUTION_TYPES:
            raise KnowledgeGapInputError("unsupported resolution_type")
        now = self._now()
        await self._upsert_annotation(
            venue_id=venue_id,
            gap_id=gap_id,
            status="RESOLVED",
            resolution_type=resolution_type,
            resolution_note=str(note).strip() if note else None,
            resolved_at=now,
            actor_id=actor_id,
            now=now,
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_GAP_RESOLVED",
            resource_type="scenic_knowledge_gap",
            resource_id=gap_id,
            trace_id=trace_id,
            metadata={
                "resolution_type": resolution_type,
                "resolution_note": str(note).strip() if note else None,
                "previous_status": gap["status"],
            },
        )
        return await self.get_gap(venue_id=venue_id, gap_id=gap_id)

    async def reopen(
        self, *, venue_id: str, gap_id: str, actor_id: str, trace_id: str
    ) -> dict[str, Any]:
        gap = await self._require_gap(venue_id=venue_id, gap_id=gap_id)
        if gap["status"] not in {"RESOLVED", "REOPENED"}:
            raise KnowledgeGapConflict("only a resolved gap can be reopened")
        now = self._now()
        await self._upsert_annotation(
            venue_id=venue_id,
            gap_id=gap_id,
            status="OPEN",
            resolution_type=None,
            resolution_note=None,
            resolved_at=None,
            actor_id=actor_id,
            now=now,
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_GAP_REOPENED",
            resource_type="scenic_knowledge_gap",
            resource_id=gap_id,
            trace_id=trace_id,
            metadata={"previous_status": gap["status"]},
        )
        return await self.get_gap(venue_id=venue_id, gap_id=gap_id)

    async def list_topics(self, *, venue_id: str) -> list[dict[str, Any]]:
        topics = await self._topics(venue_id=venue_id)
        counts = await self._database.fetch_all(
            """
            SELECT topic_id, COUNT(*) AS member_count
            FROM scenic_knowledge_gap_topic_members
            WHERE venue_id = ?
            GROUP BY topic_id
            """,
            (venue_id,),
        )
        count_by_topic = {str(row["topic_id"]): int(row["member_count"]) for row in counts or []}
        return [
            {
                **topic,
                "member_count": count_by_topic.get(topic["topic_id"], 0),
            }
            for topic in topics
        ]

    async def create_topic(
        self, *, venue_id: str, name: str, actor_id: str, trace_id: str
    ) -> dict[str, Any]:
        name = self._topic_name(name)
        existing = await self._database.fetch_one(
            """
            SELECT * FROM scenic_knowledge_gap_topics
            WHERE venue_id = ? AND name = ? AND status = 'ACTIVE'
            """,
            (venue_id, name),
        )
        if existing:
            return self._topic_view(existing)
        now = self._now()
        topic_id = str(uuid.uuid4())
        await self._database.execute(
            """
            INSERT INTO scenic_knowledge_gap_topics (
                id, venue_id, name, status, merged_into_topic_id, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', NULL, ?, ?, ?)
            """,
            (topic_id, venue_id, name, actor_id, now, now),
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_TOPIC_CREATED",
            resource_type="scenic_knowledge_gap_topic",
            resource_id=topic_id,
            trace_id=trace_id,
            metadata={"name": name},
        )
        topic = await self._topic(venue_id=venue_id, topic_id=topic_id)
        return topic

    async def rename_topic(
        self,
        *,
        venue_id: str,
        topic_id: str,
        name: str,
        actor_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        topic = await self._require_active_topic(venue_id=venue_id, topic_id=topic_id)
        name = self._topic_name(name)
        existing = await self._database.fetch_one(
            """
            SELECT id FROM scenic_knowledge_gap_topics
            WHERE venue_id = ? AND name = ? AND status = 'ACTIVE' AND id <> ?
            """,
            (venue_id, name, topic_id),
        )
        if existing:
            raise KnowledgeGapConflict("an active topic already uses this name")
        now = self._now()
        await self._database.execute(
            """
            UPDATE scenic_knowledge_gap_topics
            SET name = ?, updated_at = ?
            WHERE venue_id = ? AND id = ?
            """,
            (name, now, venue_id, topic_id),
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_TOPIC_RENAMED",
            resource_type="scenic_knowledge_gap_topic",
            resource_id=topic_id,
            trace_id=trace_id,
            metadata={"from": topic["name"], "to": name},
        )
        return await self._topic(venue_id=venue_id, topic_id=topic_id)

    async def assign_gap(
        self,
        *,
        venue_id: str,
        topic_id: str,
        gap_id: str,
        actor_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        await self._require_active_topic(venue_id=venue_id, topic_id=topic_id)
        gap = await self._require_gap(venue_id=venue_id, gap_id=gap_id)
        now = self._now()
        await self._database.execute(
            """
            INSERT INTO scenic_knowledge_gap_topic_members (
                venue_id, topic_id, gap_id, normalized_query, assigned_by, assigned_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (venue_id, gap_id) DO UPDATE SET
                topic_id = excluded.topic_id,
                normalized_query = excluded.normalized_query,
                assigned_by = excluded.assigned_by,
                assigned_at = excluded.assigned_at
            """,
            (venue_id, topic_id, gap_id, gap["normalized_query"], actor_id, now),
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_GAP_ASSIGNED",
            resource_type="scenic_knowledge_gap",
            resource_id=gap_id,
            trace_id=trace_id,
            metadata={"topic_id": topic_id},
        )
        return {"gap_id": gap_id, "topic_id": topic_id, "assigned_at": now}

    async def merge_topics(
        self,
        *,
        venue_id: str,
        source_topic_id: str,
        target_topic_id: str,
        actor_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        if source_topic_id == target_topic_id:
            raise KnowledgeGapInputError("a topic cannot merge into itself")
        await self._require_active_topic(venue_id=venue_id, topic_id=source_topic_id)
        await self._require_active_topic(venue_id=venue_id, topic_id=target_topic_id)
        members = await self._database.fetch_all(
            """
            SELECT gap_id, normalized_query
            FROM scenic_knowledge_gap_topic_members
            WHERE venue_id = ? AND topic_id = ?
            """,
            (venue_id, source_topic_id),
        )
        now = self._now()
        for member in members or []:
            await self._database.execute(
                """
                INSERT INTO scenic_knowledge_gap_topic_members (
                    venue_id, topic_id, gap_id, normalized_query, assigned_by, assigned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (venue_id, gap_id) DO UPDATE SET
                    topic_id = excluded.topic_id,
                    normalized_query = excluded.normalized_query,
                    assigned_by = excluded.assigned_by,
                    assigned_at = excluded.assigned_at
                """,
                (
                    venue_id,
                    target_topic_id,
                    member["gap_id"],
                    member["normalized_query"],
                    actor_id,
                    now,
                ),
            )
        await self._database.execute(
            """
            UPDATE scenic_knowledge_gap_topics
            SET status = 'MERGED', merged_into_topic_id = ?, updated_at = ?
            WHERE venue_id = ? AND id = ?
            """,
            (target_topic_id, now, venue_id, source_topic_id),
        )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_TOPICS_MERGED",
            resource_type="scenic_knowledge_gap_topic",
            resource_id=source_topic_id,
            trace_id=trace_id,
            metadata={"target_topic_id": target_topic_id},
        )
        return await self._topic(venue_id=venue_id, topic_id=source_topic_id)

    async def split_topic(
        self,
        *,
        venue_id: str,
        topic_id: str,
        name: str,
        gap_ids: Iterable[str],
        actor_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        await self._require_active_topic(venue_id=venue_id, topic_id=topic_id)
        gap_ids = list(dict.fromkeys(str(gap_id) for gap_id in gap_ids))
        if not gap_ids:
            raise KnowledgeGapInputError("split requires at least one gap_id")
        members = await self._database.fetch_all(
            """
            SELECT gap_id, normalized_query
            FROM scenic_knowledge_gap_topic_members
            WHERE venue_id = ? AND topic_id = ?
            """,
            (venue_id, topic_id),
        )
        member_map = {str(row["gap_id"]): row for row in members or []}
        missing = [gap_id for gap_id in gap_ids if gap_id not in member_map]
        if missing:
            raise KnowledgeGapConflict(
                "split can only move gaps currently assigned to the source topic"
            )
        name = self._topic_name(name)
        existing = await self._database.fetch_one(
            """
            SELECT id FROM scenic_knowledge_gap_topics
            WHERE venue_id = ? AND name = ? AND status = 'ACTIVE'
            """,
            (venue_id, name),
        )
        if existing:
            raise KnowledgeGapConflict("split requires a new topic name")
        now = self._now()
        new_topic_id = str(uuid.uuid4())
        await self._database.execute(
            """
            INSERT INTO scenic_knowledge_gap_topics (
                id, venue_id, name, status, merged_into_topic_id, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'ACTIVE', NULL, ?, ?, ?)
            """,
            (new_topic_id, venue_id, name, actor_id, now, now),
        )
        new_topic = await self._topic(venue_id=venue_id, topic_id=new_topic_id)
        for gap_id in gap_ids:
            await self._database.execute(
                """
                UPDATE scenic_knowledge_gap_topic_members
                SET topic_id = ?, assigned_by = ?, assigned_at = ?
                WHERE venue_id = ? AND gap_id = ?
                """,
                (new_topic["topic_id"], actor_id, now, venue_id, gap_id),
            )
        await self._audit(
            venue_id=venue_id,
            actor_id=actor_id,
            action="SCENIC_KNOWLEDGE_TOPIC_SPLIT",
            resource_type="scenic_knowledge_gap_topic",
            resource_id=topic_id,
            trace_id=trace_id,
            metadata={"new_topic_id": new_topic["topic_id"], "gap_ids": gap_ids},
        )
        return new_topic

    async def _gap_facts(self, *, venue_id: str) -> dict[str, dict[str, Any]]:
        rows = await self._database.fetch_all(
            """
            SELECT id, request_json, response_json, created_at, updated_at
            FROM scenic_commands
            WHERE venue_id = ? AND command_type = 'RETRIEVE_SOP' AND status = 'SUCCEEDED'
            ORDER BY created_at ASC, id ASC
            """,
            (venue_id,),
        )
        groups: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            request = self._json(row.get("request_json"))
            response = self._json(row.get("response_json"))
            if response.get("evidence_status") != "NO_EVIDENCE":
                continue
            if response.get("hits"):
                continue
            payload = request.get("payload") or {}
            normalized = normalize_query(str(payload.get("query") or ""))
            if not normalized:
                continue
            gap_id = gap_id_for(venue_id, normalized)
            group = groups.setdefault(
                gap_id,
                {
                    "gap_id": gap_id,
                    "normalized_query": normalized,
                    "query": str(payload.get("query") or ""),
                    "occurrence_count": 0,
                    "first_seen": float(row.get("created_at") or 0.0),
                    "last_seen": float(row.get("updated_at") or row.get("created_at") or 0.0),
                    "incident_ids": set(),
                    "command_ids": [],
                },
            )
            group["occurrence_count"] += 1
            group["first_seen"] = min(group["first_seen"], float(row.get("created_at") or 0.0))
            group["last_seen"] = max(
                group["last_seen"],
                float(row.get("updated_at") or row.get("created_at") or 0.0),
            )
            incident_id = str(payload.get("incident_id") or "").strip()
            if incident_id:
                group["incident_ids"].add(incident_id)
            group["command_ids"].append(str(row["id"]))
        for group in groups.values():
            group["incident_ids"] = sorted(group["incident_ids"])
        return groups

    async def _annotations(self, *, venue_id: str) -> dict[str, dict[str, Any]]:
        rows = await self._database.fetch_all(
            """
            SELECT * FROM scenic_knowledge_gap_annotations
            WHERE venue_id = ?
            """,
            (venue_id,),
        )
        return {
            str(row["gap_id"]): {
                "status": str(row["status"]),
                "resolution_type": row.get("resolution_type"),
                "resolution_note": row.get("resolution_note"),
                "resolved_at": row.get("resolved_at"),
                "updated_by": row.get("updated_by"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows or []
        }

    async def _members(self, *, venue_id: str) -> dict[str, dict[str, Any]]:
        rows = await self._database.fetch_all(
            """
            SELECT * FROM scenic_knowledge_gap_topic_members
            WHERE venue_id = ?
            """,
            (venue_id,),
        )
        return {str(row["gap_id"]): dict(row) for row in rows or []}

    async def _topics(self, *, venue_id: str) -> list[dict[str, Any]]:
        rows = await self._database.fetch_all(
            """
            SELECT * FROM scenic_knowledge_gap_topics
            WHERE venue_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (venue_id,),
        )
        return [self._topic_view(row) for row in rows or []]

    async def _topic(self, *, venue_id: str, topic_id: str) -> dict[str, Any]:
        row = await self._database.fetch_one(
            """
            SELECT * FROM scenic_knowledge_gap_topics
            WHERE venue_id = ? AND id = ?
            """,
            (venue_id, topic_id),
        )
        if not row:
            raise KnowledgeGapNotFound("knowledge gap topic was not found")
        return self._topic_view(row)

    async def _require_active_topic(self, *, venue_id: str, topic_id: str) -> dict[str, Any]:
        topic = await self._topic(venue_id=venue_id, topic_id=topic_id)
        if topic["status"] != "ACTIVE":
            raise KnowledgeGapConflict("knowledge gap topic is not active")
        return topic

    async def _require_gap(self, *, venue_id: str, gap_id: str) -> dict[str, Any]:
        return await self.get_gap(venue_id=venue_id, gap_id=gap_id)

    async def _upsert_annotation(
        self,
        *,
        venue_id: str,
        gap_id: str,
        status: str,
        resolution_type: str | None,
        resolution_note: str | None,
        resolved_at: float | None,
        actor_id: str,
        now: float,
    ) -> None:
        annotation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{venue_id}:{gap_id}:annotation"))
        gap = await self._gap_by_id(venue_id=venue_id, gap_id=gap_id)
        await self._database.execute(
            """
            INSERT INTO scenic_knowledge_gap_annotations (
                id, venue_id, gap_id, normalized_query, status, resolution_type,
                resolution_note, resolved_at, updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (venue_id, gap_id) DO UPDATE SET
                status = excluded.status,
                resolution_type = excluded.resolution_type,
                resolution_note = excluded.resolution_note,
                resolved_at = excluded.resolved_at,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (
                annotation_id,
                venue_id,
                gap_id,
                gap["normalized_query"],
                status,
                resolution_type,
                resolution_note,
                resolved_at,
                actor_id,
                now,
                now,
            ),
        )

    async def _gap_by_id(self, *, venue_id: str, gap_id: str) -> dict[str, Any]:
        facts = await self._gap_facts(venue_id=venue_id)
        if gap_id not in facts:
            raise KnowledgeGapNotFound("knowledge gap was not found")
        return facts[gap_id]

    async def _audit(
        self,
        *,
        venue_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        trace_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self._database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, 'SUCCEEDED', ?, ?, ?)
            """,
            (
                venue_id,
                actor_id,
                action,
                resource_type,
                resource_id,
                trace_id,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                self._now(),
            ),
        )

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _topic_name(name: str) -> str:
        normalized = " ".join(str(name or "").split())
        if not normalized:
            raise KnowledgeGapInputError("topic name is required")
        return normalized

    @staticmethod
    def _topic_view(row: Any) -> dict[str, Any]:
        return {
            "topic_id": str(row["id"]),
            "name": str(row["name"]),
            "status": str(row["status"]),
            "merged_into_topic_id": row.get("merged_into_topic_id"),
            "created_by": row.get("created_by"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }


__all__ = [
    "GAP_STATUSES",
    "RESOLUTION_TYPES",
    "TOPIC_STATUSES",
    "KnowledgeGapConflict",
    "KnowledgeGapError",
    "KnowledgeGapInputError",
    "KnowledgeGapNotFound",
    "KnowledgeGapRepository",
    "gap_id_for",
    "normalize_query",
]