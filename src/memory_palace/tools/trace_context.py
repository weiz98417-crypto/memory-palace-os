"""contextvars-based trace_id propagation for structured logging."""
import contextvars
import uuid

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="UNKNOWN")


def set_trace_id(trace_id: str) -> contextvars.Token:
    """Set trace_id for current async context. Returns token for reset."""
    return _trace_id.set(trace_id)


def get_trace_id() -> str:
    """Get current trace_id. Returns 'UNKNOWN' if not set."""
    return _trace_id.get()


def new_trace_id() -> str:
    """Generate and set a new trace_id. Returns the ID."""
    tid = uuid.uuid4().hex[:12]
    _trace_id.set(tid)
    return tid
