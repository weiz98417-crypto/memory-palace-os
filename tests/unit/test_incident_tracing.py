"""Tracing contract for the scenic Agent trunk.

Tracing is a debugging aid: it must adopt the business trace id so the dossier and
Jaeger can be correlated, and it must be inert when no OTLP endpoint is configured.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.memory_palace.agent_contracts.models import AgentRole
from src.memory_palace.incident.command import (
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from tests.unit.test_incident_command import (
    Registry,
    ScriptedAgent,
    SpyRecorder,
    _advice,
    _context,
    _request,
    _routing,
)

pytestmark = pytest.mark.asyncio

EXPECTED_TRACE_ID = int("b" * 32, 16)
EXPECTED_SPAN_NAMES = [
    "scenic.agent.context_trigger",
    "scenic.agent.memory_ops",
    "scenic.agent.router",
    "scenic.incident_command",
]


def _install_capture_provider() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return exporter
    captured = TracerProvider(resource=Resource.create({"service.name": "test-trunk"}))
    captured.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(captured)
    return exporter


def _command() -> PydanticAIIncidentCommand:
    return PydanticAIIncidentCommand(
        agent_registry=Registry(
            {
                AgentRole.CONTEXT_TRIGGER: ScriptedAgent([_context()]),
                AgentRole.ROUTER: ScriptedAgent([_routing()]),
                AgentRole.MEMORY_OPS: ScriptedAgent([_advice()]),
                AgentRole.COMMANDER: ScriptedAgent([_advice()]),
            }
        ),
        call_recorder=SpyRecorder(),
        config=IncidentCommandConfig(),
    )


async def test_the_trunk_emits_spans_under_the_business_trace_id(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    exporter = _install_capture_provider()
    exporter.clear()

    await _command().execute(_request())

    spans = exporter.get_finished_spans()
    assert sorted(span.name for span in spans) == EXPECTED_SPAN_NAMES
    assert {span.context.trace_id for span in spans} == {EXPECTED_TRACE_ID}

    root = next(span for span in spans if span.name == "scenic.incident_command")
    assert root.attributes["scenic.mode"] == "ADVICE"
    assert root.attributes["scenic.trace_id"] == "b" * 32
    assert root.parent is not None
    assert root.parent.is_remote is True
    for span in spans:
        if span.name == "scenic.incident_command":
            continue
        assert span.parent is not None
        assert span.parent.trace_id == EXPECTED_TRACE_ID
        assert span.attributes["gen_ai.agent.name"]


async def test_tracing_is_inert_without_an_otlp_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    exporter = _install_capture_provider()
    exporter.clear()

    result = await _command().execute(_request())

    assert result.outcome == "READY"
    assert exporter.get_finished_spans() == ()
