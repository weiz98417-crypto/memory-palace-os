"""Stable human-readable identifiers for persisted business resources."""

from datetime import datetime, timedelta, timezone
from typing import Any


def build_business_id(prefix: str, entity_id: str, occurred_at: Any) -> str:
    normalized_prefix = str(prefix).strip().upper()
    normalized_entity_id = "".join(
        character for character in str(entity_id).upper() if character.isalnum()
    )
    if not normalized_prefix or not normalized_entity_id:
        raise ValueError("prefix and entity_id are required")
    try:
        local_time = datetime.fromtimestamp(float(occurred_at), timezone.utc) + timedelta(hours=8)
    except (TypeError, ValueError, OSError):
        local_time = datetime.now(timezone.utc) + timedelta(hours=8)
    return f"{normalized_prefix}-{local_time:%Y%m%d}-{normalized_entity_id[:8]}"
