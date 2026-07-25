"""Multi-tenant isolation via contextvars — venue_id propagation."""
import contextvars
from typing import Optional

_venue_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "venue_id", default=None
)


def set_venue_id(venue_id: str) -> contextvars.Token:
    """Set venue_id for current async context."""
    return _venue_id.set(venue_id)


def get_venue_id() -> Optional[str]:
    """Get current venue_id. Returns None if not set (wildcard mode)."""
    return _venue_id.get()


def tenant_filter(venue_id: Optional[str] = None) -> tuple[str, tuple]:
    """Return (WHERE clause fragment, params) for tenant-aware queries.
    Returns empty strings when no tenant context is active.
    """
    vid = venue_id or get_venue_id()
    if vid is None:
        return ("", ())
    return (" AND venue_id = ?", (vid,))
