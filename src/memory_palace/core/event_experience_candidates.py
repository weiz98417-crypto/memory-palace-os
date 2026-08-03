"""Idempotent event-to-experience candidate extraction and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any, Optional

from ..tools.llm_wrapper import REQUIRED_GENERATIVE_MODEL
from .business_ids import build_business_id
from .event_activities import append_event_activity
from .experience_assets import (
    ExperienceDraftExtractionError,
    validate_extracted_experience_draft,
)


EXTRACTION_LEASE_SECONDS = 300
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "cookie",
    "credential",
)


class EventExperienceCandidateError(RuntimeError):
    """Raised when an event cannot participate in candidate extraction."""


class DeepSeekEventExperienceCandidateExtractor:
    """Extract one governed draft from a closed event evidence snapshot."""

    model_name = REQUIRED_GENERATIVE_MODEL
    agent_name = "PersonaExtract"

    def __init__(self, llm_client: Any):
        if llm_client is None:
            raise EventExperienceCandidateError("经验候选 LLM 客户端未初始化")
        self._llm = llm_client

    async def extract(
        self,
        evidence: Mapping[str, Any],
        *,
        trace_id: str,
        venue_id: str,
    ) -> dict[str, Any]:
        source_corpus = str(evidence.get("source_corpus") or "").strip()
        if not source_corpus:
            raise ExperienceDraftExtractionError("闭环事件没有可供萃取的业务证据")

        system_prompt = """你是企业事件经验候选萃取 Agent。只能依据提供的闭环事件、任务结果、审批与 Watcher 证据生成草稿，不能补造事实。
返回一个 JSON 对象，且只能包含 title、applicable_context、signals、decision_rule、recommended_actions、rationale、prohibitions、exceptions、source_excerpts。
signals、recommended_actions、prohibitions、exceptions、source_excerpts 必须是非空字符串数组，其余字段必须是非空字符串。
source_excerpts 必须逐字复制证据中的原文。候选仅供后续专家确认和知识审核，不得描述为已发布经验。不要返回 Markdown 或代码围栏。"""
        user_prompt = f"闭环事件证据：\n{source_corpus}"
        try:
            response = await self._llm.ask(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model_name,
                temperature=0.2,
                max_tokens=1800,
                json_mode=True,
                trace_id=trace_id,
                venue_id=venue_id,
                agent_id=self.agent_name,
                agent_name=self.agent_name,
            )
            if getattr(response, "is_mock", False):
                raise ExperienceDraftExtractionError("正式经验候选萃取不接受 Mock 模型结果")
            response_model = getattr(response, "model_name", self.model_name)
            if response_model != REQUIRED_GENERATIVE_MODEL:
                raise ExperienceDraftExtractionError(
                    f"经验候选萃取仅允许 {REQUIRED_GENERATIVE_MODEL}"
                )
            parsed = await self._llm.parse_json(response.content, trace_id=trace_id)
        except ExperienceDraftExtractionError:
            raise
        except Exception as exc:
            raise ExperienceDraftExtractionError("DeepSeek 经验候选萃取失败") from exc

        return _validate_candidate_draft(parsed, source_corpus)


def _json_value(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _safe_snapshot(value: Any, *, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _safe_snapshot(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_snapshot(item) for item in value]
    if isinstance(value, str):
        return value[:12000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:12000]


def _json_text(value: Any) -> str:
    return json.dumps(
        _safe_snapshot(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(evidence: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_text(evidence).encode("utf-8")).hexdigest()


def _validate_candidate_draft(draft: Any, source_corpus: str) -> dict[str, Any]:
    return validate_extracted_experience_draft(
        draft,
        {"turns": [{"answer_text": source_corpus}]},
    )


def _candidate_id(venue_id: str, event_id: str) -> str:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"memory-palace-experience-candidate:{venue_id}:{event_id}",
    ).hex


def _attempt_id(candidate_id: str, attempt_number: int) -> str:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"memory-palace-experience-candidate-attempt:{candidate_id}:{attempt_number}",
    ).hex


def _decode_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(row)
    for stored_name, public_name, fallback in (
        ("signals_json", "signals", []),
        ("recommended_actions_json", "recommended_actions", []),
        ("prohibitions_json", "prohibitions", []),
        ("exceptions_json", "exceptions", []),
        ("source_excerpts_json", "source_excerpts", []),
        ("event_snapshot_json", "event_snapshot", {}),
        ("task_results_snapshot_json", "task_results_snapshot", []),
        ("approval_evidence_snapshot_json", "approval_evidence_snapshot", []),
        ("watcher_evidence_snapshot_json", "watcher_evidence_snapshot", {}),
    ):
        candidate[public_name] = _json_value(candidate.pop(stored_name, None), fallback)
    candidate["retryable"] = bool(candidate.get("retryable"))
    return candidate


def _watcher_run_matches_event(run: Mapping[str, Any], event_id: str) -> bool:
    if str(run.get("event_id") or "") == event_id:
        return True
    if event_id in str(run.get("trigger_source") or ""):
        return True
    for field in ("target_snapshot_json", "result_json"):
        payload = _json_value(run.get(field), {})
        if not isinstance(payload, Mapping):
            continue
        candidate_ids = (
            payload.get("event_id"),
            payload.get("source_event_id"),
            payload.get("target_id"),
        )
        if event_id in {str(value) for value in candidate_ids if value is not None}:
            return True
    return False


async def _collect_evidence(
    database: Any,
    *,
    venue_id: str,
    event_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event = await database.fetch_one(
        """
        SELECT event_id, business_id, venue_id, from_user, raw_text, event_type,
               severity, context_trigger_data, source_type, status, resolution,
               trace_id, created_at, confirmed_at, closed_at, updated_at
        FROM confirmed_events
        WHERE event_id = ? AND venue_id = ?
        """,
        (event_id, venue_id),
    )
    if event is None:
        raise EventExperienceCandidateError("当前场地不存在该事件")
    if str(event.get("status") or "OPEN").upper() != "CLOSED":
        raise EventExperienceCandidateError("只有已闭环事件可以生成经验候选")

    tasks = await database.fetch_all(
        """
        SELECT id, business_id, description, status, assigned_user_id,
               result, error, evidence_refs_json, completed_at, updated_at
        FROM tasks
        WHERE venue_id = ? AND event_id = ?
        ORDER BY created_at, id
        """,
        (venue_id, event_id),
    )
    task_snapshot = [
        {
            "id": task.get("id"),
            "business_id": task.get("business_id"),
            "description": task.get("description"),
            "status": task.get("status"),
            "assigned_user_id": task.get("assigned_user_id"),
            "result": _json_value(task.get("result"), task.get("result")),
            "error": task.get("error"),
            "evidence_refs": _json_value(task.get("evidence_refs_json"), []),
            "completed_at": task.get("completed_at"),
            "updated_at": task.get("updated_at"),
        }
        for task in tasks
    ]

    approvals = await database.fetch_all(
        """
        SELECT approval_id, business_id, tool_name, args, task_id, status,
               requested_by, reviewed_by, comment, execution_status,
               execution_result, execution_error, evidence_snapshot_json,
               requested_at, reviewed_at
        FROM approval_requests
        WHERE venue_id = ? AND event_id = ?
        ORDER BY requested_at, approval_id
        """,
        (venue_id, event_id),
    )
    approval_snapshot = [
        {
            "approval_id": approval.get("approval_id"),
            "business_id": approval.get("business_id"),
            "tool_name": approval.get("tool_name"),
            "arguments": _json_value(approval.get("args"), {}),
            "task_id": approval.get("task_id"),
            "status": approval.get("status"),
            "requested_by": approval.get("requested_by"),
            "reviewed_by": approval.get("reviewed_by"),
            "comment": approval.get("comment"),
            "execution_status": approval.get("execution_status"),
            "execution_result": _json_value(approval.get("execution_result"), {}),
            "execution_error": approval.get("execution_error"),
            "evidence_snapshot": _json_value(
                approval.get("evidence_snapshot_json"),
                {},
            ),
            "requested_at": approval.get("requested_at"),
            "reviewed_at": approval.get("reviewed_at"),
        }
        for approval in approvals
    ]

    watcher_runs = await database.fetch_all(
        """
        SELECT * FROM watcher_runs
        WHERE venue_id = ?
        ORDER BY completed_at DESC, started_at DESC, id DESC
        """,
        (venue_id,),
    )
    watcher_run = next(
        (
            run
            for run in watcher_runs
            if str(run.get("status") or "").upper() == "SUCCEEDED"
            and _watcher_run_matches_event(run, event_id)
        ),
        None,
    )
    watcher_findings: list[dict[str, Any]] = []
    if watcher_run is not None:
        watcher_findings = await database.fetch_all(
            """
            SELECT id, finding_type, severity, title, description, source_type,
                   source_id, status, resolution, created_at, updated_at, closed_at
            FROM watcher_findings
            WHERE venue_id = ? AND run_id = ?
            ORDER BY created_at, id
            """,
            (venue_id, watcher_run["id"]),
        )
    watcher_snapshot = {
        "run": (
            {
                "id": watcher_run.get("id"),
                "policy_id": watcher_run.get("policy_id"),
                "status": watcher_run.get("status"),
                "trace_id": watcher_run.get("trace_id"),
                "model_name": watcher_run.get("model_name"),
                "summary": watcher_run.get("summary"),
                "target_count": watcher_run.get("target_count"),
                "finding_count": watcher_run.get("finding_count"),
                "target_snapshot": _json_value(
                    watcher_run.get("target_snapshot_json"),
                    {},
                ),
                "result": _json_value(watcher_run.get("result_json"), {}),
                "started_at": watcher_run.get("started_at"),
                "completed_at": watcher_run.get("completed_at"),
            }
            if watcher_run is not None
            else None
        ),
        "findings": [dict(finding) for finding in watcher_findings],
    }
    event_snapshot = {
        **dict(event),
        "context_trigger_data": _json_value(event.get("context_trigger_data"), {}),
    }
    evidence = _safe_snapshot(
        {
            "event": event_snapshot,
            "task_results": task_snapshot,
            "approval_evidence": approval_snapshot,
            "watcher_evidence": watcher_snapshot,
        }
    )
    evidence["source_corpus"] = _json_text(evidence)
    return dict(event), evidence


async def _mark_attempt_failed(
    database: Any,
    *,
    venue_id: str,
    candidate_id: str,
    attempt_number: int,
    error: str,
) -> None:
    completed_at = time.time()
    await database.execute(
        """
        UPDATE experience_candidate_attempts
        SET status = 'FAILED', error = ?, completed_at = ?
        WHERE venue_id = ? AND candidate_id = ? AND attempt_number = ?
        """,
        (error[:2000], completed_at, venue_id, candidate_id, attempt_number),
    )
    await database.execute(
        """
        UPDATE experience_candidates
        SET extraction_status = 'FAILED', extraction_error = ?, retryable = ?,
            updated_at = ?
        WHERE venue_id = ? AND id = ? AND extraction_status = 'EXTRACTING'
        """,
        (error[:2000], True, completed_at, venue_id, candidate_id),
    )


async def _write_created_evidence(
    database: Any,
    *,
    candidate: Mapping[str, Any],
    principal: Mapping[str, Any],
    trace_id: str,
) -> dict[str, Any]:
    payload = {
        "candidate_id": candidate["id"],
        "business_id": candidate["business_id"],
        "source_event_id": candidate["source_event_id"],
        "title": candidate["title"],
        "status": "DRAFT",
        "index_status": "NOT_INDEXED",
        "extraction_status": "SUCCEEDED",
        "model": REQUIRED_GENERATIVE_MODEL,
        "attempt_count": candidate["attempt_count"],
        "summary": f"已生成待审核经验候选：{candidate['title']}",
    }
    activity = await append_event_activity(
        database,
        venue_id=str(candidate["venue_id"]),
        event_id=str(candidate["source_event_id"]),
        activity_type="EXPERIENCE_CANDIDATE_CREATED",
        created_by=str(principal["user_id"]),
        trace_id=trace_id,
        payload=payload,
        idempotency_key=f"experience-candidate-created:{candidate['id']}",
        created_at=candidate.get("generated_at"),
    )
    existing_audit = await database.fetch_one(
        """
        SELECT id FROM audit_logs
        WHERE venue_id = ? AND action = 'EXPERIENCE_CANDIDATE_CREATED'
          AND resource_type = 'experience_candidate' AND resource_id = ?
          AND outcome = 'SUCCEEDED'
        """,
        (candidate["venue_id"], candidate["id"]),
    )
    if existing_audit is None:
        await database.execute(
            """
            INSERT INTO audit_logs (
                venue_id, user_id, action, resource_type, resource_id,
                outcome, trace_id, metadata_json, created_at
            ) VALUES (?, ?, 'EXPERIENCE_CANDIDATE_CREATED',
                      'experience_candidate', ?, 'SUCCEEDED', ?, ?, ?)
            """,
            (
                candidate["venue_id"],
                principal["user_id"],
                candidate["id"],
                trace_id,
                _json_text(payload),
                candidate.get("generated_at") or time.time(),
            ),
        )
    return activity


def _result(
    *,
    outcome: str,
    candidate: Mapping[str, Any],
    trace_id: str,
    idempotent_replay: bool,
    retryable: bool,
    activity: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    decoded = _decode_candidate(candidate)
    return {
        "outcome": outcome,
        "candidate": decoded,
        "idempotent_replay": idempotent_replay,
        "retryable": retryable,
        "extraction": {
            "status": decoded["extraction_status"],
            "model": decoded["extraction_model"],
            "trace_id": decoded.get("extraction_trace_id") or trace_id,
            "attempt_count": decoded["attempt_count"],
            "error": decoded.get("extraction_error"),
        },
        "activity": dict(activity) if activity is not None else None,
    }


async def ensure_event_experience_candidate(
    database: Any,
    *,
    venue_id: str,
    event_id: str,
    trace_id: str,
    principal: Optional[Mapping[str, Any]] = None,
    llm_client: Any = None,
    extractor: Any = None,
) -> dict[str, Any]:
    """Create, replay, or retry one tenant-scoped candidate for a closed event."""
    normalized_venue_id = str(venue_id or "").strip()
    normalized_event_id = str(event_id or "").strip()
    normalized_trace_id = str(trace_id or "").strip()[:128]
    if not normalized_venue_id or not normalized_event_id or not normalized_trace_id:
        raise EventExperienceCandidateError("venue_id、event_id 和 trace_id 均不能为空")
    effective_principal = dict(
        principal or {"venue_id": normalized_venue_id, "user_id": "system"}
    )
    if effective_principal.get("venue_id") != normalized_venue_id:
        raise EventExperienceCandidateError("候选操作人与来源事件不属于同一场地")
    if not effective_principal.get("user_id"):
        raise EventExperienceCandidateError("候选操作人缺少 user_id")

    selected_extractor = extractor or DeepSeekEventExperienceCandidateExtractor(llm_client)
    if getattr(selected_extractor, "model_name", None) != REQUIRED_GENERATIVE_MODEL:
        raise EventExperienceCandidateError(
            f"经验候选萃取仅允许 {REQUIRED_GENERATIVE_MODEL}"
        )

    event, evidence = await _collect_evidence(
        database,
        venue_id=normalized_venue_id,
        event_id=normalized_event_id,
    )
    snapshots = {
        "event_snapshot_json": _json_text(evidence["event"]),
        "task_results_snapshot_json": _json_text(evidence["task_results"]),
        "approval_evidence_snapshot_json": _json_text(evidence["approval_evidence"]),
        "watcher_evidence_snapshot_json": _json_text(evidence["watcher_evidence"]),
    }
    evidence_fingerprint = _fingerprint(
        {
            "event": evidence["event"],
            "task_results": evidence["task_results"],
            "approval_evidence": evidence["approval_evidence"],
            "watcher_evidence": evidence["watcher_evidence"],
        }
    )
    now = time.time()
    candidate_id = _candidate_id(normalized_venue_id, normalized_event_id)
    business_id = build_business_id(
        "JY",
        candidate_id,
        event.get("closed_at") or event.get("updated_at") or now,
    )
    await database.execute(
        """
        INSERT INTO experience_candidates (
            id, business_id, venue_id, source_event_id,
            source_event_business_id, status, index_status,
            extraction_status, extraction_model, retryable, attempt_count,
            event_snapshot_json, task_results_snapshot_json,
            approval_evidence_snapshot_json, watcher_evidence_snapshot_json,
            evidence_fingerprint, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'DRAFT', 'NOT_INDEXED', 'PENDING', ?, ?, 0,
                  ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            candidate_id,
            business_id,
            normalized_venue_id,
            normalized_event_id,
            event.get("business_id"),
            REQUIRED_GENERATIVE_MODEL,
            True,
            snapshots["event_snapshot_json"],
            snapshots["task_results_snapshot_json"],
            snapshots["approval_evidence_snapshot_json"],
            snapshots["watcher_evidence_snapshot_json"],
            evidence_fingerprint,
            effective_principal["user_id"],
            now,
            now,
        ),
    )

    candidate = await database.fetch_one(
        "SELECT * FROM experience_candidates WHERE venue_id = ? AND source_event_id = ?",
        (normalized_venue_id, normalized_event_id),
    )
    if candidate is None:
        raise EventExperienceCandidateError("经验候选初始化失败")
    if candidate["extraction_status"] == "SUCCEEDED":
        await database.execute(
            """
            UPDATE experience_candidate_attempts
            SET status = 'SUCCEEDED', completed_at = COALESCE(completed_at, ?)
            WHERE venue_id = ? AND candidate_id = ? AND status = 'RUNNING'
            """,
            (candidate.get("generated_at") or now, normalized_venue_id, candidate["id"]),
        )
        activity = await _write_created_evidence(
            database,
            candidate=candidate,
            principal=effective_principal,
            trace_id=normalized_trace_id,
        )
        return _result(
            outcome="REPLAYED",
            candidate=candidate,
            trace_id=normalized_trace_id,
            idempotent_replay=True,
            retryable=False,
            activity=activity,
        )

    if candidate["extraction_status"] == "EXTRACTING":
        started_at = float(candidate.get("extraction_started_at") or now)
        if now - started_at < EXTRACTION_LEASE_SECONDS:
            return _result(
                outcome="IN_PROGRESS",
                candidate=candidate,
                trace_id=normalized_trace_id,
                idempotent_replay=True,
                retryable=True,
            )
        await database.execute(
            """
            UPDATE experience_candidates
            SET extraction_status = 'FAILED', extraction_error = ?,
                retryable = ?, updated_at = ?
            WHERE venue_id = ? AND id = ? AND extraction_status = 'EXTRACTING'
            """,
            (
                "上一次经验候选萃取被应用重启中断，可安全重试",
                True,
                now,
                normalized_venue_id,
                candidate["id"],
            ),
        )
        await database.execute(
            """
            UPDATE experience_candidate_attempts
            SET status = 'FAILED', error = ?, completed_at = ?
            WHERE venue_id = ? AND candidate_id = ? AND status = 'RUNNING'
            """,
            (
                "经验候选萃取被应用重启中断",
                now,
                normalized_venue_id,
                candidate["id"],
            ),
        )

    acquired = await database.execute(
        """
        UPDATE experience_candidates
        SET extraction_status = 'EXTRACTING', extraction_trace_id = ?,
            extraction_error = NULL, retryable = ?,
            attempt_count = attempt_count + 1,
            event_snapshot_json = ?, task_results_snapshot_json = ?,
            approval_evidence_snapshot_json = ?, watcher_evidence_snapshot_json = ?,
            evidence_fingerprint = ?, extraction_started_at = ?, updated_at = ?
        WHERE venue_id = ? AND id = ? AND extraction_status IN ('PENDING', 'FAILED')
        """,
        (
            normalized_trace_id,
            True,
            snapshots["event_snapshot_json"],
            snapshots["task_results_snapshot_json"],
            snapshots["approval_evidence_snapshot_json"],
            snapshots["watcher_evidence_snapshot_json"],
            evidence_fingerprint,
            now,
            now,
            normalized_venue_id,
            candidate["id"],
        ),
    )
    candidate = await database.fetch_one(
        "SELECT * FROM experience_candidates WHERE venue_id = ? AND id = ?",
        (normalized_venue_id, candidate["id"]),
    )
    if not acquired:
        outcome = "REPLAYED" if candidate["extraction_status"] == "SUCCEEDED" else "IN_PROGRESS"
        activity = None
        if outcome == "REPLAYED":
            activity = await _write_created_evidence(
                database,
                candidate=candidate,
                principal=effective_principal,
                trace_id=normalized_trace_id,
            )
        return _result(
            outcome=outcome,
            candidate=candidate,
            trace_id=normalized_trace_id,
            idempotent_replay=True,
            retryable=outcome == "IN_PROGRESS",
            activity=activity,
        )

    attempt_number = int(candidate["attempt_count"])
    await database.execute(
        """
        INSERT INTO experience_candidate_attempts (
            id, venue_id, candidate_id, attempt_number, trace_id, model_name,
            status, evidence_fingerprint, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
        """,
        (
            _attempt_id(candidate["id"], attempt_number),
            normalized_venue_id,
            candidate["id"],
            attempt_number,
            normalized_trace_id,
            REQUIRED_GENERATIVE_MODEL,
            evidence_fingerprint,
            now,
        ),
    )

    try:
        draft = await selected_extractor.extract(
            evidence,
            trace_id=normalized_trace_id,
            venue_id=normalized_venue_id,
        )
        draft = _validate_candidate_draft(draft, evidence["source_corpus"])
    except asyncio.CancelledError:
        await asyncio.shield(
            _mark_attempt_failed(
                database,
                venue_id=normalized_venue_id,
                candidate_id=candidate["id"],
                attempt_number=attempt_number,
                error="经验候选萃取被应用关闭中断",
            )
        )
        raise
    except Exception as exc:
        error = str(exc).strip() or type(exc).__name__
        await _mark_attempt_failed(
            database,
            venue_id=normalized_venue_id,
            candidate_id=candidate["id"],
            attempt_number=attempt_number,
            error=error,
        )
        failed = await database.fetch_one(
            "SELECT * FROM experience_candidates WHERE venue_id = ? AND id = ?",
            (normalized_venue_id, candidate["id"]),
        )
        return _result(
            outcome="FAILED",
            candidate=failed,
            trace_id=normalized_trace_id,
            idempotent_replay=False,
            retryable=True,
        )

    generated_at = time.time()
    await database.execute(
        """
        UPDATE experience_candidates
        SET title = ?, applicable_context = ?, signals_json = ?,
            decision_rule = ?, recommended_actions_json = ?, rationale = ?,
            prohibitions_json = ?, exceptions_json = ?, source_excerpts_json = ?,
            status = 'DRAFT', index_status = 'NOT_INDEXED',
            extraction_status = 'SUCCEEDED', extraction_error = NULL,
            retryable = ?, generated_at = ?, updated_at = ?
        WHERE venue_id = ? AND id = ? AND extraction_status = 'EXTRACTING'
        """,
        (
            draft["title"],
            draft["applicable_context"],
            _json_text(draft["signals"]),
            draft["decision_rule"],
            _json_text(draft["recommended_actions"]),
            draft["rationale"],
            _json_text(draft["prohibitions"]),
            _json_text(draft["exceptions"]),
            _json_text(draft["source_excerpts"]),
            False,
            generated_at,
            generated_at,
            normalized_venue_id,
            candidate["id"],
        ),
    )
    await database.execute(
        """
        UPDATE experience_candidate_attempts
        SET status = 'SUCCEEDED', completed_at = ?
        WHERE venue_id = ? AND candidate_id = ? AND attempt_number = ?
        """,
        (
            generated_at,
            normalized_venue_id,
            candidate["id"],
            attempt_number,
        ),
    )
    created = await database.fetch_one(
        "SELECT * FROM experience_candidates WHERE venue_id = ? AND id = ?",
        (normalized_venue_id, candidate["id"]),
    )
    activity = await _write_created_evidence(
        database,
        candidate=created,
        principal=effective_principal,
        trace_id=normalized_trace_id,
    )
    return _result(
        outcome="CREATED",
        candidate=created,
        trace_id=normalized_trace_id,
        idempotent_replay=False,
        retryable=False,
        activity=activity,
    )
