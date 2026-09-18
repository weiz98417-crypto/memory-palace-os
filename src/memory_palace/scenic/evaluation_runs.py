"""Persist Agent evaluation runs so the UI reads them from PostgreSQL."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class EvaluationRun:
    run_id: str
    venue_id: str
    tier: str
    case_set: str
    case_count: int
    passed_count: int
    failed_count: int
    pass_rate: float
    judge_model: str | None
    context_source: str | None
    elapsed_seconds: float | None
    summary: dict[str, Any]
    results: list[dict[str, Any]]
    created_at: float


class EvaluationRunRepository:
    """Read/write access to `scenic_evaluation_runs`."""

    def __init__(self, database: Any, *, clock: Callable[[], float] | None = None) -> None:
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._clock = clock or time.time

    async def record(
        self,
        *,
        venue_id: str,
        tier: str,
        case_set: str,
        results: list[dict[str, Any]],
        judge_model: str | None = None,
        context_source: str | None = None,
        elapsed_seconds: float | None = None,
        summary: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> EvaluationRun:
        resolved_id = run_id or uuid.uuid4().hex
        passed = sum(1 for item in results if item.get("passed"))
        failed = len(results) - passed
        pass_rate = round(passed / len(results), 4) if results else 0.0
        created_at = float(self._clock())
        body = dict(summary or {})
        body.setdefault("tier", tier)
        body.setdefault("case_set", case_set)
        await self._database.execute(
            """
            INSERT INTO scenic_evaluation_runs (
                id, venue_id, tier, case_set, case_count, passed_count, failed_count,
                pass_rate, judge_model, context_source, elapsed_seconds,
                summary_json, results_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                case_count = EXCLUDED.case_count,
                passed_count = EXCLUDED.passed_count,
                failed_count = EXCLUDED.failed_count,
                pass_rate = EXCLUDED.pass_rate,
                judge_model = EXCLUDED.judge_model,
                context_source = EXCLUDED.context_source,
                elapsed_seconds = EXCLUDED.elapsed_seconds,
                summary_json = EXCLUDED.summary_json,
                results_json = EXCLUDED.results_json
            """,
            (
                resolved_id,
                venue_id,
                tier,
                case_set,
                len(results),
                passed,
                failed,
                pass_rate,
                judge_model,
                context_source,
                elapsed_seconds,
                json.dumps(body, ensure_ascii=False, sort_keys=True),
                json.dumps(results, ensure_ascii=False),
                created_at,
            ),
        )
        return EvaluationRun(
            run_id=resolved_id,
            venue_id=venue_id,
            tier=tier,
            case_set=case_set,
            case_count=len(results),
            passed_count=passed,
            failed_count=failed,
            pass_rate=pass_rate,
            judge_model=judge_model,
            context_source=context_source,
            elapsed_seconds=elapsed_seconds,
            summary=body,
            results=results,
            created_at=created_at,
        )

    async def latest(
        self, *, venue_id: str, tier: str | None = None
    ) -> EvaluationRun | None:
        rows = await self.list_runs(venue_id=venue_id, tier=tier, limit=1)
        return rows[0] if rows else None

    async def list_runs(
        self, *, venue_id: str, tier: str | None = None, limit: int = 20
    ) -> list[EvaluationRun]:
        sql = (
            "SELECT * FROM scenic_evaluation_runs WHERE venue_id = ?"
        )
        params: list[Any] = [venue_id]
        if tier:
            sql += " AND tier = ?"
            params.append(tier)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        rows = await self._database.fetch_all(sql, tuple(params))
        return [self._to_run(row) for row in rows or []]

    def _to_run(self, row: Any) -> EvaluationRun:
        def _load(key: str, default: Any) -> Any:
            raw = row.get(key) if hasattr(row, "get") else None
            if not raw:
                return default
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return default

        return EvaluationRun(
            run_id=str(row["id"]),
            venue_id=str(row["venue_id"]),
            tier=str(row["tier"]),
            case_set=str(row["case_set"]),
            case_count=int(row["case_count"]),
            passed_count=int(row["passed_count"]),
            failed_count=int(row["failed_count"]),
            pass_rate=float(row["pass_rate"]),
            judge_model=row.get("judge_model"),
            context_source=row.get("context_source"),
            elapsed_seconds=row.get("elapsed_seconds"),
            summary=_load("summary_json", {}),
            results=_load("results_json", []),
            created_at=float(row["created_at"]),
        )


__all__ = ["EvaluationRun", "EvaluationRunRepository"]
