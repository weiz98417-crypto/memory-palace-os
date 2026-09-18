"""OpenTelemetry instrumentation for the scenic Agent trunk.

Tracing is a debugging aid, never a source of business truth: spans describe the
orchestration, while `llm_call_logs` and `scenic_commands` stay authoritative.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

_TRACER_NAME = "scenic.agent_trunk"


def _get_tracer():
    """Seam for tests: returns the OpenTelemetry tracer for the trunk."""

    from opentelemetry import trace

    return trace.get_tracer(_TRACER_NAME)


def tracing_enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


@contextlib.contextmanager
def _span(
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    trace_id: str | None = None,
):
    """Start a span, adopting the caller's W3C trace id as the remote parent.

    The business trace id must equal the Jaeger trace id, otherwise the dossier and the
    trace viewer cannot be correlated.
    """

    if not tracing_enabled():
        yield None
        return
    try:
        from opentelemetry import trace
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
    except ImportError:  # pragma: no cover - opentelemetry is a hard dependency
        yield None
        return
    tracer = _get_tracer()
    context = None
    if trace_id:
        try:
            context = trace.set_span_in_context(
                NonRecordingSpan(
                    SpanContext(
                        trace_id=int(trace_id, 16),
                        span_id=int("1" * 16, 16),
                        is_remote=True,
                        trace_flags=TraceFlags(TraceFlags.SAMPLED),
                    )
                )
            )
        except Exception:
            context = None
    with tracer.start_as_current_span(name, context=context) as span:
        for key, value in (attributes or {}).items():
            if value is None:
                continue
            try:
                span.set_attribute(key, value)
            except Exception:
                continue
        yield span


def incident_command_span(*, mode: str, venue_id: str, trace_id: str):
    return _span(
        "scenic.incident_command",
        {
            "scenic.mode": mode,
            "scenic.venue_id": venue_id,
            "scenic.trace_id": trace_id,
        },
        trace_id=trace_id,
    )


def agent_span(*, role: str, agent_name: str, trace_id: str):
    return _span(
        f"scenic.agent.{role}",
        {
            "gen_ai.agent.name": agent_name,
            "scenic.trace_id": trace_id,
        },
    )


def record_agent_outcome(span: Any, *, status: str, model_name: str | None = None) -> None:
    if span is None:
        return
    try:
        span.set_attribute("scenic.agent.status", status)
        if model_name:
            span.set_attribute("gen_ai.request.model", model_name)
    except Exception:
        return


__all__ = [
    "_get_tracer",
    "agent_span",
    "incident_command_span",
    "record_agent_outcome",
    "tracing_enabled",
]
