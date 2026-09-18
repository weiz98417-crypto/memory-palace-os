"""Real-model + Jaeger smoke for the scenic Agent trunk span tree."""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path.cwd()))

from opentelemetry import trace  # noqa: E402
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # noqa: E402
from opentelemetry.sdk.resources import Resource  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402

from src.memory_palace.agent_contracts.models import (  # noqa: E402
    CommandMode,
    FieldEvidence,
    IncidentSnapshot,
    KnowledgeHit,
    VerifiedKnowledge,
)
from src.memory_palace.incident.call_records import LLMCallLogRecorder  # noqa: E402
from src.memory_palace.incident.command import (  # noqa: E402
    IncidentCommandConfig,
    PydanticAIIncidentCommand,
)
from src.memory_palace.incident.contracts import IncidentCommandRequest  # noqa: E402
from src.memory_palace.incident.runtime import build_incident_agent_registry  # noqa: E402
from src.memory_palace.knowledge.db_client import AsyncDBClient  # noqa: E402
from src.memory_palace.knowledge.db_init import init_database  # noqa: E402


def configure_tracing(endpoint: str) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create({"service.name": "scenic-agent-trunk"})
    )
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    return provider


async def main() -> int:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        print("TRACE_SMOKE_FAIL: OTEL_EXPORTER_OTLP_ENDPOINT is required")
        return 1
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("TRACE_SMOKE_FAIL: DEEPSEEK_API_KEY is required")
        return 1
    provider = configure_tracing(endpoint)
    trace_id = "d" * 32

    with tempfile.TemporaryDirectory() as tmp:
        database = AsyncDBClient(pathlib.Path(tmp) / "trace.db")
        await init_database(database)
        request = IncidentCommandRequest(
            mode=CommandMode.ADVICE,
            trace_id=trace_id,
            idempotency_key="advice:trace-smoke:ADVICE:1",
            incident=IncidentSnapshot(
                incident_id="trace-incident",
                event_id="trace-event",
                business_id="SJ-TRACE",
                venue_id="venue-trace",
                run_id="trace-run",
                lifecycle="OPEN",
                priority="P1",
                title="\u89c2\u5149\u8f66\u5f02\u54cd",
                event_type="\u8bbe\u5907\u5b89\u5168",
                raw_text="12 \u53f7\u89c2\u5149\u8f66\u540e\u8f6e\u5f02\u54cd",
                conversion_reason="\u4eba\u5de5\u786e\u8ba4",
                occurred_at=1785283200.0,
            ),
            field_evidence=[
                FieldEvidence(
                    evidence_id="e1",
                    evidence_type="PHOTO",
                    text="\u8f6e\u80ce\u6709\u5212\u75d5",
                    submitted_by="u1",
                    submitted_at=1785283200.0,
                )
            ],
            knowledge=VerifiedKnowledge(
                retrieval_snapshot_id="snap",
                sop_hits=[
                    KnowledgeHit(
                        vector_doc_id="sop:venue-trace:1",
                        source_id="1",
                        source_type="SOP",
                        source_label="SOP",
                        title="\u8f6e\u80ce\u5f02\u5e38\u5904\u7f6e SOP",
                        version="1.0",
                        vector_score=0.7,
                        rerank_score=0.9,
                        excerpt="\u505c\u8fd0\u68c0\u67e5",
                        content_sha256="digest",
                    )
                ],
            ),
        )
        command = PydanticAIIncidentCommand(
            agent_registry=build_incident_agent_registry(),
            call_recorder=LLMCallLogRecorder(database),
            config=IncidentCommandConfig(),
        )
        result = await command.execute(request)
        await database.close()

    provider.force_flush()
    print("TRACE_ID:", trace_id)
    print("OUTCOME:", result.outcome)
    print("CALL_REFS:", len(result.call_refs))
    print("TRACE_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
