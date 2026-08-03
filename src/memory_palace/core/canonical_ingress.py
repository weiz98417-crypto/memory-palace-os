"""Canonical channel ingress for authenticated, idempotent message intake."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .attachments import (
    AttachmentError,
    link_message_attachments,
    prepare_message_attachments,
)


SUPPORTED_CHANNELS = {"WEB", "WECOM_SIMULATOR"}
_SESSION_NAMESPACE = uuid.UUID("6a8cae5c-7dd7-4dbc-a244-8a10792dde32")


class CanonicalIngressError(Exception):
    """A caller-visible canonical ingress rejection."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class IngressMessage:
    channel: str
    content: str
    external_message_id: str
    external_conversation_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    selected_user_id: Optional[str] = None
    external_tenant_id: str = ""
    external_user_id: str = ""


@dataclass(frozen=True)
class AcceptedMessage:
    message_id: str
    trace_id: str
    session_id: str
    status: str
    channel: str
    external_message_id: str
    external_conversation_id: str
    duplicate: bool
    reply_text: Optional[str]
    created_at: datetime
    identity: Optional[dict[str, Any]] = None


class CanonicalMessageIngress:
    """Resolve identity, persist one message run, then enqueue one payload."""

    def __init__(self, db: Any, queue: Any) -> None:
        self._db = db
        self._queue = queue

    async def accept(
        self,
        message: IngressMessage,
        *,
        actor: dict[str, str],
    ) -> AcceptedMessage:
        channel = message.channel.strip().upper()
        if channel not in SUPPORTED_CHANNELS:
            raise CanonicalIngressError(
                "CHANNEL_NOT_SUPPORTED",
                "The requested channel is not supported.",
                status_code=422,
            )

        identity = await self._resolve_identity(channel, message, actor)
        venue_id = identity["venue_id"]
        user_id = identity["user_id"]

        existing = await self._find_existing(
            venue_id=venue_id,
            channel=channel,
            external_message_id=message.external_message_id,
        )
        if existing:
            return self._accepted_from_row(existing, identity=identity, duplicate=True)

        try:
            prepared_attachments = await prepare_message_attachments(
                self._db,
                venue_id=venue_id,
                owner_user_id=user_id,
                attachments=message.attachments,
            )
        except AttachmentError as exc:
            raise CanonicalIngressError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
            ) from exc

        external_conversation_id = (
            message.external_conversation_id.strip()
            if message.external_conversation_id
            else uuid.uuid4().hex
        )
        session_id = self._stable_session_id(
            venue_id=venue_id,
            channel=channel,
            user_id=user_id,
            external_conversation_id=external_conversation_id,
        )
        await self._ensure_session(
            session_id=session_id,
            venue_id=venue_id,
            user_id=user_id,
            channel=channel,
            external_conversation_id=external_conversation_id,
        )

        now = time.time()
        message_id = str(uuid.uuid4())
        trace_id = uuid.uuid4().hex
        try:
            await self._db.execute(
                """
                INSERT INTO message_runs (
                    message_id, trace_id, session_id, user_id, venue_id, content,
                    status, channel, external_message_id, external_conversation_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    trace_id,
                    session_id,
                    user_id,
                    venue_id,
                    message.content,
                    channel,
                    message.external_message_id,
                    external_conversation_id,
                    now,
                    now,
                ),
            )
        except Exception:
            existing = await self._find_existing(
                venue_id=venue_id,
                channel=channel,
                external_message_id=message.external_message_id,
            )
            if existing:
                return self._accepted_from_row(existing, identity=identity, duplicate=True)
            raise

        try:
            normalized_attachments = await link_message_attachments(
                self._db,
                venue_id=venue_id,
                message_id=message_id,
                prepared=prepared_attachments,
            )
        except AttachmentError as exc:
            await self._db.execute(
                "DELETE FROM message_runs WHERE message_id = ? AND venue_id = ?",
                (message_id, venue_id),
            )
            raise CanonicalIngressError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            await self._db.execute(
                "DELETE FROM message_runs WHERE message_id = ? AND venue_id = ?",
                (message_id, venue_id),
            )
            raise CanonicalIngressError(
                "ATTACHMENT_BIND_FAILED",
                "The attachment could not be bound to the message.",
                status_code=503,
            ) from exc

        metadata = dict(message.metadata or {})
        metadata.update(
            {
                "venue_id": venue_id,
                "channel": channel,
                "external_message_id": message.external_message_id,
                "external_conversation_id": external_conversation_id,
            }
        )
        if normalized_attachments:
            metadata["attachments"] = normalized_attachments
        if message.external_tenant_id:
            metadata["external_tenant_id"] = message.external_tenant_id
        if message.external_user_id:
            metadata["external_user_id"] = message.external_user_id

        try:
            await self._write_audit(
                venue_id=venue_id,
                user_id=actor["user_id"],
                message_id=message_id,
                trace_id=trace_id,
                session_id=session_id,
                channel=channel,
            )
            await self._queue.put(
                {
                    "msg_id": message_id,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "from_user": user_id,
                    "venue_id": venue_id,
                    "msg_type": "text",
                    "content": message.content,
                    "timestamp": now,
                    "channel": channel,
                    "external_message_id": message.external_message_id,
                    "external_conversation_id": external_conversation_id,
                    "metadata": metadata,
                }
            )
        except Exception as exc:
            await self._db.execute(
                """
                UPDATE message_runs
                SET status = 'FAILED', error = ?, updated_at = ?, processed_at = ?
                WHERE message_id = ?
                """,
                ("Message intake persistence failed", time.time(), time.time(), message_id),
            )
            raise CanonicalIngressError(
                "MESSAGE_INTAKE_UNAVAILABLE",
                "The message could not be accepted.",
                status_code=503,
            ) from exc

        return AcceptedMessage(
            message_id=message_id,
            trace_id=trace_id,
            session_id=session_id,
            status="QUEUED",
            channel=channel,
            external_message_id=message.external_message_id,
            external_conversation_id=external_conversation_id,
            duplicate=False,
            reply_text=None,
            created_at=datetime.fromtimestamp(now, timezone.utc),
            identity=identity,
        )

    async def _resolve_identity(
        self,
        channel: str,
        message: IngressMessage,
        actor: dict[str, str],
    ) -> dict[str, Any]:
        if channel == "WECOM_SIMULATOR":
            if actor.get("role") not in {"manager", "admin"}:
                raise CanonicalIngressError(
                    "SIMULATOR_FORBIDDEN",
                    "Manager access is required for the simulator.",
                    status_code=403,
                )
            if not message.selected_user_id:
                raise CanonicalIngressError(
                    "IDENTITY_REQUIRED",
                    "A simulator employee identity is required.",
                    status_code=422,
                )
            row = await self._db.fetch_one(
                "SELECT id, display_name, role, venue_id, status FROM users WHERE id = ?",
                (message.selected_user_id,),
            )
            if not row or row.get("venue_id") != actor.get("venue_id"):
                raise CanonicalIngressError(
                    "IDENTITY_NOT_AVAILABLE",
                    "The employee identity is not available in this venue.",
                    status_code=404,
                )
            if row.get("status") != "ACTIVE":
                raise CanonicalIngressError(
                    "IDENTITY_INACTIVE",
                    "The employee identity is inactive.",
                    status_code=403,
                )
            binding = await self._db.fetch_one(
                """
                SELECT external_tenant_id, external_user_id
                FROM channel_identities
                WHERE venue_id = ? AND user_id = ? AND channel = 'WECOM_SIMULATOR'
                  AND status = 'ACTIVE'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (row["venue_id"], row["id"]),
            )
            if binding is None:
                raise CanonicalIngressError(
                    "IDENTITY_NOT_BOUND",
                    "The employee does not have an active WeCom identity binding.",
                    status_code=403,
                )
            return {
                "user_id": row["id"],
                "display_name": row["display_name"],
                "role": row["role"],
                "venue_id": row["venue_id"],
                "status": row["status"],
                "external_tenant_id": binding["external_tenant_id"],
                "external_user_id": binding["external_user_id"],
            }

        if channel != "WEB":
            raise CanonicalIngressError(
                "CHANNEL_NOT_IMPLEMENTED",
                "This channel adapter is not available yet.",
                status_code=503,
            )
        if actor.get("role") not in {"operator", "manager", "admin"}:
            raise CanonicalIngressError(
                "WEB_LOGIN_REQUIRED",
                "A signed-in employee is required.",
                status_code=403,
            )
        row = await self._db.fetch_one(
            "SELECT id, display_name, role, venue_id, status FROM users WHERE id = ?",
            (actor["user_id"],),
        )
        if not row or row.get("venue_id") != actor.get("venue_id"):
            raise CanonicalIngressError(
                "IDENTITY_NOT_AVAILABLE",
                "The employee identity is not available in this venue.",
                status_code=404,
            )
        if row.get("status") != "ACTIVE":
            raise CanonicalIngressError(
                "IDENTITY_INACTIVE",
                "The employee identity is inactive.",
                status_code=403,
            )
        return {
            "user_id": row["id"],
            "display_name": row["display_name"],
            "role": row["role"],
            "venue_id": row["venue_id"],
            "status": row["status"],
        }

    async def _find_existing(
        self,
        *,
        venue_id: str,
        channel: str,
        external_message_id: str,
    ) -> Optional[dict[str, Any]]:
        return await self._db.fetch_one(
            """
            SELECT * FROM message_runs
            WHERE venue_id = ? AND channel = ? AND external_message_id = ?
            """,
            (venue_id, channel, external_message_id),
        )

    async def _ensure_session(
        self,
        *,
        session_id: str,
        venue_id: str,
        user_id: str,
        channel: str,
        external_conversation_id: str,
    ) -> None:
        now = time.time()
        await self._db.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, venue_id, agent_name, stage, message_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'router', 'active', 0, ?, ?)
            ON CONFLICT(session_id) DO NOTHING
            """,
            (session_id, user_id, venue_id, now, now),
        )
        await self._db.execute(
            """
            INSERT INTO channel_conversations (
                session_id, venue_id, channel, external_conversation_id,
                user_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
            ON CONFLICT(venue_id, channel, external_conversation_id, user_id)
            DO NOTHING
            """,
            (
                session_id,
                venue_id,
                channel,
                external_conversation_id,
                user_id,
                now,
                now,
            ),
        )
        mapping = await self._db.fetch_one(
            """
            SELECT session_id FROM channel_conversations
            WHERE venue_id = ? AND channel = ?
              AND external_conversation_id = ? AND user_id = ? AND status = 'ACTIVE'
            """,
            (venue_id, channel, external_conversation_id, user_id),
        )
        if not mapping:
            raise CanonicalIngressError(
                "CONVERSATION_NOT_AVAILABLE",
                "The external conversation could not be mapped.",
                status_code=409,
            )

    async def _write_audit(
        self,
        *,
        venue_id: str,
        user_id: str,
        message_id: str,
        trace_id: str,
        session_id: str,
        channel: str,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, 'MESSAGE_RUN_CREATED', 'message_run', ?,
                      'SUCCEEDED', ?, ?, ?)
            """,
            (
                venue_id,
                user_id,
                message_id,
                trace_id,
                json.dumps(
                    {"session_id": session_id, "status": "QUEUED", "channel": channel},
                    ensure_ascii=False,
                ),
                time.time(),
            ),
        )

    @staticmethod
    def _stable_session_id(
        *,
        venue_id: str,
        channel: str,
        user_id: str,
        external_conversation_id: str,
    ) -> str:
        value = "\x1f".join((venue_id, channel, user_id, external_conversation_id))
        return str(uuid.uuid5(_SESSION_NAMESPACE, value))

    @staticmethod
    def _accepted_from_row(
        row: dict[str, Any],
        *,
        identity: dict[str, Any],
        duplicate: bool,
    ) -> AcceptedMessage:
        return AcceptedMessage(
            message_id=row["message_id"],
            trace_id=row["trace_id"],
            session_id=row["session_id"],
            status=row["status"],
            channel=row["channel"],
            external_message_id=row["external_message_id"],
            external_conversation_id=row["external_conversation_id"],
            duplicate=duplicate,
            reply_text=row.get("reply_text"),
            created_at=datetime.fromtimestamp(float(row["created_at"]), timezone.utc),
            identity=identity,
        )
