"""One-off real-model smoke for the scenic Agent trunk (ticket m4-02).

Runs the production `IncidentCommand` with the production LiteLLM adapter against the
real provider, using a throwaway SQLite database so no business state is touched.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path.cwd()))

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
from src.memory_palace.incident.runtime import (  # noqa: E402
    build_incident_agent_registry,
)
from src.memory_palace.knowledge.db_client import AsyncDBClient  # noqa: E402
from src.memory_palace.knowledge.db_init import init_database  # noqa: E402


async def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("SMOKE_FAIL: DEEPSEEK_API_KEY is required for the real-model smoke")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        database = AsyncDBClient(pathlib.Path(tmp) / "smoke.db")
        await init_database(database)
        request = IncidentCommandRequest(
            mode=CommandMode.ADVICE,
            trace_id="c" * 32,
            idempotency_key="advice:smoke:ADVICE:1",
            incident=IncidentSnapshot(
                incident_id="smoke-incident",
                event_id="smoke-event",
                business_id="SJ-SMOKE",
                venue_id="venue-smoke",
                run_id="smoke-run",
                lifecycle="OPEN",
                priority="P1",
                title="\u89c2\u5149\u8f66\u540e\u8f6e\u5f02\u54cd",
                event_type="\u8bbe\u5907\u5b89\u5168",
                raw_text="12 \u53f7\u89c2\u5149\u8f66\u540e\u8f6e\u5f02\u54cd\uff0c\u5df2\u505c\u8f66\u68c0\u67e5",
                conversion_reason="\u4eba\u5de5\u786e\u8ba4",
                occurred_at=1785283200.0,
            ),
            field_evidence=[
                FieldEvidence(
                    evidence_id="smoke-evidence",
                    evidence_type="PHOTO",
                    text="\u8f6e\u80ce\u8868\u9762\u6709\u5212\u75d5",
                    submitted_by="smoke-user",
                    submitted_at=1785283200.0,
                )
            ],
            knowledge=VerifiedKnowledge(
                retrieval_snapshot_id="smoke-snapshot",
                sop_hits=[
                    KnowledgeHit(
                        vector_doc_id="sop:venue-smoke:1",
                        source_id="1",
                        source_type="SOP",
                        source_label="SOP",
                        title="\u89c2\u5149\u8f66\u8f6e\u80ce\u5f02\u5e38\u5904\u7f6e SOP",
                        version="1.0",
                        vector_score=0.72,
                        rerank_score=0.91,
                        excerpt="\u53d1\u73b0\u5f02\u5e38\u7acb\u5373\u505c\u8fd0\uff0c\u9694\u79bb\u8be5\u8f66\u8f86\u5e76\u68c0\u67e5\u8f6e\u80ce\u4e0e\u5239\u8f66\u3002",
                        content_sha256="smoke-digest",
                    )
                ],
            ),
        )
        command = PydanticAIIncidentCommand(
            agent_registry=build_incident_agent_registry(),
            call_recorder=LLMCallLogRecorder(database),
            config=IncidentCommandConfig(),
        )
        try:
            result = await command.execute(request)
        except Exception as exc:  # noqa: BLE001 - smoke reports the raw failure
            print(f"SMOKE_FAIL: {type(exc).__name__}: {exc}")
            await database.close()
            return 1

        rows = await database.fetch_all(
            "SELECT agent_id, model_name, status, prompt_tokens, completion_tokens, "
            "total_tokens, request_id, is_mock, error_type, error_message "
            "FROM llm_call_logs WHERE venue_id = ? ORDER BY created_at",
            ("venue-smoke",),
        )
        await database.close()

    real_calls = [row for row in rows if not bool(row["is_mock"]) and int(row["total_tokens"]) > 0]
    print("OUTCOME:", result.outcome)
    print("ADVICE_STATUS:", result.advice.evidence_status if result.advice else None)
    print("CITATIONS:", [c.source_id for c in (result.advice.citations if result.advice else [])])
    print("DEGRADATIONS:", [(d.agent_role.value, d.code) for d in result.degradations])
    print("CALL_REFS:", [ref.call_id for ref in result.call_refs])
    print("REAL_CALL_ROWS:", len(real_calls))
    for row in rows:
        print(
            "ROW:",
            row["agent_id"],
            row["model_name"],
            row["status"],
            row["prompt_tokens"],
            row["completion_tokens"],
            row["total_tokens"],
            bool(row["is_mock"]),
            row["error_type"],
            str(row["error_message"])[:120],
        )
    if len(real_calls) < 3:
        print("SMOKE_FAIL: fewer than three real token-bearing call records")
        return 1
    if result.advice is None or result.advice.evidence_status != "GROUNDED":
        print("SMOKE_FAIL: real grounded advice was not produced")
        return 1
    if not result.advice.citations or result.advice.citations[0].source_id != "1":
        print("SMOKE_FAIL: advice did not cite the verified SOP")
        return 1
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
