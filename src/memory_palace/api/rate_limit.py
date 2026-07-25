"""Rate limiting middleware using slowapi (Redis backend in prod, in-memory for demo)."""
import os

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    SLOWAPI_AVAILABLE = True
except ImportError:
    Limiter = None
    get_remote_address = lambda: "127.0.0.1"
    RateLimitExceeded = Exception
    SLOWAPI_AVAILABLE = False


def create_limiter() -> object:
    """Create a rate limiter instance. Uses Redis in production, memory in demo."""
    if not SLOWAPI_AVAILABLE:
        return None

    if os.environ.get("DEMO_MODE", "").lower() == "true":
        return Limiter(key_func=get_remote_address, storage_uri="memory://")

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return Limiter(key_func=get_remote_address, storage_uri=redis_url)
