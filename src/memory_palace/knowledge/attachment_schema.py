from __future__ import annotations


ATTACHMENT_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS message_attachments (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        venue_id TEXT NOT NULL,
        owner_user_id TEXT NOT NULL,
        original_name TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        scan_status TEXT NOT NULL,
        scan_engine TEXT NOT NULL,
        storage_key TEXT NOT NULL,
        external_ref TEXT NOT NULL,
        created_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, business_id),
        UNIQUE (venue_id, storage_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS message_attachment_links (
        id TEXT PRIMARY KEY,
        venue_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        attachment_id TEXT NOT NULL,
        description TEXT,
        linked_at DOUBLE PRECISION NOT NULL,
        UNIQUE (venue_id, message_id, attachment_id),
        UNIQUE (venue_id, attachment_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_message_attachments_owner
    ON message_attachments (venue_id, owner_user_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_message_attachment_links_message
    ON message_attachment_links (venue_id, message_id, linked_at)
    """,
)


async def init_attachment_schema(database) -> None:
    for statement in ATTACHMENT_SCHEMA_STATEMENTS:
        await database.execute(statement)
