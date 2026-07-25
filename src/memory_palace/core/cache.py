"""Simple async TTL cache for hot queries."""
import time
from functools import wraps

_cache: dict = {}


def ttl_cache(ttl_seconds: int = 30):
    """Decorator: caches async function results for ttl_seconds."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            now = time.time()
            if key in _cache:
                entry = _cache[key]
                if now - entry["ts"] < ttl_seconds:
                    return entry["value"]
            result = await func(*args, **kwargs)
            _cache[key] = {"value": result, "ts": now}
            # Limit cache size
            if len(_cache) > 100:
                oldest = min(_cache, key=lambda k: _cache[k]["ts"])
                del _cache[oldest]
            return result

        return wrapper

    return decorator
