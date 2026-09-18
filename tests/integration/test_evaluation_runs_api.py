"""Evaluation run archive: repository and read API."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from src.memory_palace.api.v1.endpoints.scenic import router as scenic_router
from src.memory_palace.knowledge.db_client import AsyncDBClient
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.scenic.evaluation_runs import EvaluationRunRepository

pytestmark = pytest.mark.asyncio


async def _database(tmp_path) -> AsyncDBClient:
    database = AsyncDBClient(tmp_path / "eval-runs.db")
    await init_database(database)
    return database


def _results() -> list[dict]:
    return [
        {
            "case_id": "g-0001",
            "scenario_type": "DEVICE",
            "expected_status": "GROUNDED",
            "evidence_status": "GROUNDED",
            "citations": ["1"],
            "latency": 8.5,
            "passed": True,
        },
        {
            "case_id": "n-0001",
            "scenario_type": "NO_KNOWLEDGE_BASE",
            "expected_status": "NO_EVIDENCE",
            "evidence_status": "NO_EVIDENCE",
            "citations": [],
            "advice_text": "\u6ca1\u6709\u4f9d\u636e",
            "latency": 6.0,
            "passed": True,
        },
        {
            "case_id": "g-0002",
            "scenario_type": "CROWD",
            "expected_status": "GROUNDED",
            "evidence_status": "NO_EVIDENCE",
            "citations": [],
            "latency": 7.0,
            "passed": False,
        },
    ]


async def test_repository_records_counts_and_returns_latest_first(tmp_path):
    database = await _database(tmp_path)
    repo = EvaluationRunRepository(database, clock=lambda: 1785283200.0)
    await repo.record(
        venue_id="venue-hq",
        tier="contract",
        case_set="corpus-100-contract",
        results=_results(),
        elapsed_seconds=12.5,
        summary={"real_calls": 9, "mocked_calls": 0},
    )
    await repo.record(
        venue_id="venue-hq",
        tier="deep",
        case_set="corpus-100-deepeval",
        results=_results()[:2],
        judge_model="deepseek-flash",
    )

    runs = await repo.list_runs(venue_id="venue-hq")
    assert len(runs) == 2
    contract = next(run for run in runs if run.tier == "contract")
    assert contract.case_count == 3
    assert contract.passed_count == 2
    assert contract.failed_count == 1
    assert contract.pass_rate == pytest.approx(0.6667)
    assert contract.summary["real_calls"] == 9
    assert len(contract.results) == 3

    deep_only = await repo.list_runs(venue_id="venue-hq", tier="deep")
    assert [run.tier for run in deep_only] == ["deep"]
    assert deep_only[0].judge_model == "deepseek-flash"

    other_venue = await repo.list_runs(venue_id="venue-other")
    assert other_venue == []
    await database.close()


async def test_recording_the_same_run_id_updates_instead_of_duplicating(tmp_path):
    database = await _database(tmp_path)
    repo = EvaluationRunRepository(database, clock=lambda: 1785283200.0)
    first = await repo.record(
        venue_id="venue-hq", tier="deep", case_set="set",
        results=_results()[:1], run_id="run-1",
    )
    second = await repo.record(
        venue_id="venue-hq", tier="deep", case_set="set",
        results=_results(), run_id="run-1",
    )
    assert first.run_id == second.run_id == "run-1"
    runs = await repo.list_runs(venue_id="venue-hq")
    assert len(runs) == 1
    assert runs[0].case_count == 3
    await database.close()


async def test_read_api_rejects_anonymous_callers(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "MEMORY_PALACE_JWT_SECRET", "eval-test-secret-longer-than-thirty-two-characters"
    )
    from src.memory_palace.api.v1.endpoints.auth import router as auth_router

    database = await _database(tmp_path)
    repo = EvaluationRunRepository(database)
    await repo.record(
        venue_id="venue-hq", tier="contract", case_set="set", results=_results()
    )

    import httpx

    app = FastAPI()
    app.state.db_client = database
    app.include_router(auth_router, prefix="/auth")
    app.include_router(scenic_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/operations/scenic/evaluation-runs")
    assert anonymous.status_code == 401
    await database.close()
