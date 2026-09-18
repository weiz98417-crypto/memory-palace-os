"""Versioned HTTP routers, imported lazily to isolate optional runtimes."""

from importlib import import_module

__all__ = ["v1_router", "v2_router"]


def __getattr__(name):
    if name == "v1_router":
        return import_module(".v1.router", __name__).router
    if name == "v2_router":
        return import_module(".v2.router", __name__).router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
