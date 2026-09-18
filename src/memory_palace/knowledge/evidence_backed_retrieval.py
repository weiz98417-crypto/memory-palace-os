"""Evidence-backed, tenant-scoped knowledge retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from ..core.experience_assets import authorization_allows


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
)


class KnowledgeRetrievalError(RuntimeError):
    """Raised after a failed retrieval attempt has been durably recorded."""

    def __init__(self, message: str, *, snapshot_id: Optional[str] = None):
        super().__init__(message)
        self.snapshot_id = snapshot_id


class KnowledgeSnapshotPersistenceError(KnowledgeRetrievalError):
    """Raised when retrieval evidence cannot be durably persisted."""


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    venue_id: str
    trace_id: str
    user_id: str
    message_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: str = "MemoryOps"
    top_k: int = 3
    similarity_threshold: float = 0.75

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("retrieval query is required")
        if not self.venue_id.strip():
            raise ValueError("venue_id is required")
        if not self.trace_id.strip():
            raise ValueError("trace_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
        if len(self.query) > 4000:
            raise ValueError("retrieval query is too long")
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        if not 0.0 <= float(self.similarity_threshold) <= 1.0:
            raise ValueError("similarity_threshold must be between 0 and 1")


@dataclass(frozen=True)
class RetrievalResult:
    snapshot_id: str
    status: str
    documents: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    raw_hit_count: int


@dataclass(frozen=True)
class _CandidateDecision:
    selected: bool
    rejection_reason: Optional[str]
    document: Optional[dict[str, Any]] = None
    reference: Optional[dict[str, Any]] = None


class EvidenceBackedKnowledgeRetriever:
    """Retrieve candidates, verify relational truth, and persist evidence first."""

    schema_version = 2

    def __init__(
        self,
        *,
        database: Any,
        vector_store: Any = None,
        reranker: Any = None,
    ):
        if database is None:
            raise ValueError("database is required")
        self._database = database
        self._vector_store = vector_store
        if reranker is None:
            from .reranking import build_reranker_backend

            reranker = build_reranker_backend()
        self._reranker = reranker

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        started_at = time.time()
        attempts: list[dict[str, Any]] = []
        selected_documents: list[dict[str, Any]] = []
        selected_references: list[dict[str, Any]] = []
        raw_hit_count = 0

        try:
            if self._vector_store is None:
                error = RuntimeError("knowledge vector service is unavailable")
                attempts.append(
                    {
                        "order": 1,
                        "strategy": "semantic",
                        "top_k": request.top_k,
                        "similarity_threshold": float(request.similarity_threshold),
                        "filter": {"venue_id": request.venue_id},
                        "status": "FAILED",
                        "hits": [],
                        "error_type": type(error).__name__,
                        "error_message": _safe_text(str(error), limit=500),
                    }
                )
                raise error

            strategies = (
                (
                    "semantic",
                    max(8, request.top_k),
                    float(request.similarity_threshold),
                ),
                ("broad", max(8, request.top_k), 0.0),
            )
            for order, (strategy, top_k, threshold) in enumerate(strategies, start=1):
                attempt = {
                    "order": order,
                    "strategy": strategy,
                    "top_k": top_k,
                    "similarity_threshold": threshold,
                    "filter": {"venue_id": request.venue_id},
                    "status": "RUNNING",
                    "hits": [],
                }
                attempts.append(attempt)
                try:
                    hits = self._vector_store.query_experience(
                        text=request.query,
                        top_k=top_k,
                        threshold=threshold,
                        venue_id=request.venue_id,
                        strict=True,
                    )
                except Exception as exc:
                    attempt["status"] = "FAILED"
                    attempt["error_type"] = type(exc).__name__
                    attempt["error_message"] = _safe_text(str(exc), limit=500)
                    raise

                normalized_hits = list(hits or [])
                raw_hit_count += len(normalized_hits)
                try:
                    documents, references = await self._evaluate_hits(
                        normalized_hits,
                        request=request,
                        strategy=strategy,
                        attempt=attempt,
                    )
                except Exception as exc:
                    attempt["status"] = "FAILED"
                    attempt["error_type"] = type(exc).__name__
                    attempt["error_message"] = _safe_text(str(exc), limit=500)
                    raise
                attempt["status"] = "SUCCEEDED"
                attempt["raw_hit_count"] = len(normalized_hits)
                selected_documents.extend(documents)
                selected_references.extend(references)
                if selected_references:
                    break

            status = "SUCCEEDED" if selected_references else "ZERO_HITS"
            snapshot_id = await self._persist_snapshot(
                request=request,
                status=status,
                attempts=attempts,
                references=selected_references,
                raw_hit_count=raw_hit_count,
                started_at=started_at,
            )
            return RetrievalResult(
                snapshot_id=snapshot_id,
                status=status,
                documents=tuple(selected_documents),
                references=tuple(selected_references),
                raw_hit_count=raw_hit_count,
            )
        except KnowledgeSnapshotPersistenceError:
            raise
        except Exception as exc:
            try:
                snapshot_id = await self._persist_snapshot(
                    request=request,
                    status="FAILED",
                    attempts=attempts,
                    references=[],
                    raw_hit_count=raw_hit_count,
                    started_at=started_at,
                    error_type=type(exc).__name__,
                    error_message=_safe_text(str(exc), limit=500),
                )
            except KnowledgeSnapshotPersistenceError:
                raise
            raise KnowledgeRetrievalError(
                "知识检索失败，未返回任何未经确权的引用",
                snapshot_id=snapshot_id,
            ) from None

    async def list_for_trace(
        self,
        *,
        venue_id: str,
        trace_id: str,
        technical: bool,
    ) -> list[dict[str, Any]]:
        rows = await self._database.fetch_all(
            """
            SELECT * FROM knowledge_retrieval_snapshots
            WHERE venue_id = ? AND trace_id = ?
            ORDER BY started_at
            """,
            (venue_id, trace_id),
        )
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            references = _decode_json_list(row.get("references_json"))
            snapshot = {
                "id": row.get("id"),
                "schema_version": row.get("schema_version"),
                "status": row.get("status"),
                "agent_id": row.get("agent_id"),
                "message_id": row.get("message_id"),
                "session_id": row.get("session_id"),
                "references": (
                    references
                    if technical
                    else [_business_reference(reference) for reference in references]
                ),
                "raw_hit_count": row.get("raw_hit_count", 0),
                "selected_count": row.get("selected_count", 0),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "latency_ms": row.get("latency_ms", 0),
            }
            if technical:
                snapshot.update(
                    {
                        "query_summary": row.get("query_summary"),
                        "query_sha256": row.get("query_sha256"),
                        "backend": row.get("backend"),
                        "index_name": row.get("index_name"),
                        "top_k": row.get("top_k"),
                        "similarity_threshold": row.get("similarity_threshold"),
                        "filter": _decode_json_object(row.get("filter_json")),
                        "attempts": _decode_json_list(row.get("attempts_json")),
                        "error_type": row.get("error_type"),
                        "error_message": row.get("error_message"),
                    }
                )
            snapshots.append(snapshot)
        return snapshots

    async def _evaluate_hits(
        self,
        hits: list[Any],
        *,
        request: RetrievalRequest,
        strategy: str,
        attempt: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        evaluations: list[tuple[_CandidateDecision, dict[str, Any], float]] = []
        for hit in hits:
            hit_record = _hit_record(hit)
            if not isinstance(hit, dict):
                decision = _CandidateDecision(False, "MALFORMED_HIT")
            else:
                decision = await self._verify_candidate(
                    hit,
                    venue_id=request.venue_id,
                    user_id=request.user_id,
                )
                if decision.selected and strategy == "broad" and decision.document:
                    lexical_score = _lexical_relevance(request.query, decision.document)
                    hit_record["lexical_score"] = lexical_score
                    if lexical_score < 0.08:
                        decision = _CandidateDecision(False, "LEXICALLY_IRRELEVANT")
            score = _safe_score(hit.get("score") if isinstance(hit, dict) else 0.0)
            evaluations.append((decision, hit_record, score))

        eligible = [
            index
            for index, (decision, _, _) in enumerate(evaluations)
            if decision.selected and decision.document and decision.reference
        ]
        if eligible:
            reranked, rerank_meta = self._rerank(
                request,
                [
                    {
                        "index": index,
                        "text": _rerank_text(evaluations[index][1]),
                    }
                    for index in eligible
                ],
            )
            attempt.update(rerank_meta)
            rerank_order = [
                int(item["index"]) for item in reranked if item.get("index") is not None
            ]
            scores = {
                int(item["index"]): item.get("rerank_score")
                for item in reranked
                if item.get("index") is not None
            }
            ordered_eligible = [index for index in rerank_order if index in eligible]
            remaining = [index for index in eligible if index not in ordered_eligible]
            for index in ordered_eligible:
                if scores.get(index) is not None:
                    evaluations[index][1]["rerank_score"] = scores[index]
            eligible = ordered_eligible + remaining
        def _final_score(index: int) -> float:
            hit_record = evaluations[index][1]
            rerank_score = hit_record.get("rerank_score")
            if rerank_score is not None:
                return float(rerank_score)
            return max(
                evaluations[index][2],
                float(hit_record.get("lexical_score") or 0.0),
            )

        eligible.sort(
            key=lambda index: (
                _source_priority(evaluations[index][0].reference or {}),
                -_final_score(index),
            )
        )
        selected_indexes = set(eligible[: request.top_k])
        selected_vector_ids: set[str] = set()
        documents: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []

        # Hits, documents and references must come out in the final ranked order so the
        # evidence trail shows what the reranker actually decided. Rejected candidates
        # still appear, after the selected ones.
        rejected_indexes = [index for index in range(len(evaluations)) if index not in eligible]
        for index in eligible + rejected_indexes:
            decision, hit_record, _ = evaluations[index]
            vector_doc_id = str(hit_record.get("vector_doc_id") or "")
            selected = index in selected_indexes and vector_doc_id not in selected_vector_ids
            rejection_reason = decision.rejection_reason
            if index in eligible and not selected:
                rejection_reason = (
                    "DUPLICATE_VECTOR_DOCUMENT"
                    if vector_doc_id in selected_vector_ids
                    else "TOP_K_LIMIT"
                )
            hit_record["selected"] = selected
            hit_record["rejection_reason"] = None if selected else rejection_reason
            attempt["hits"].append(hit_record)
            if selected and decision.document and decision.reference:
                selected_vector_ids.add(vector_doc_id)
                documents.append(decision.document)
                references.append(decision.reference)
        return documents, references

    async def _verify_candidate(
        self,
        hit: dict[str, Any],
        *,
        venue_id: str,
        user_id: str,
    ) -> _CandidateDecision:
        metadata = hit.get("metadata") or {}
        if not isinstance(metadata, dict):
            return _CandidateDecision(False, "MALFORMED_METADATA")
        metadata_venue = str(metadata.get("venue_id") or "")
        if metadata_venue and metadata_venue != venue_id:
            return _CandidateDecision(False, "TENANT_MISMATCH")

        source_type = str(
            metadata.get("source_type") or metadata.get("asset_type") or ""
        ).upper()
        if source_type == "SOP":
            return await self._verify_sop(hit, metadata=metadata, venue_id=venue_id)
        if source_type in {"EXPERIENCE", "EXPERIENCE_CARD"}:
            return await self._verify_experience(
                hit,
                metadata=metadata,
                venue_id=venue_id,
                user_id=user_id,
            )
        if source_type in {"HISTORY", "CASE", "LIVE", "EVENT"}:
            return await self._verify_closed_case(hit, metadata=metadata, venue_id=venue_id)
        return _CandidateDecision(False, "UNSUPPORTED_SOURCE_TYPE")

    async def _verify_sop(
        self,
        hit: dict[str, Any],
        *,
        metadata: dict[str, Any],
        venue_id: str,
    ) -> _CandidateDecision:
        if str(metadata.get("status") or "").upper() != "PUBLISHED":
            return _CandidateDecision(False, "NOT_PUBLISHED")
        source_id = str(metadata.get("source_id") or "").strip()
        vector_doc_id = str(hit.get("id") or "").strip()
        if not source_id or not vector_doc_id:
            return _CandidateDecision(False, "SOURCE_ID_MISSING")

        row = await self._database.fetch_one(
            """
            SELECT
                CAST(s.id AS TEXT) AS source_id,
                s.title,
                s.content,
                s.category,
                s.version,
                s.status,
                s.published_at,
                s.reviewed_by,
                k.id AS knowledge_id,
                k.title AS knowledge_title,
                k.content AS knowledge_content,
                k.vector_doc_id,
                COALESCE(u.display_name, u.username) AS publisher_name
            FROM sop_documents s
            JOIN knowledge_documents k
              ON k.venue_id = s.venue_id
             AND k.source_type = 'SOP'
             AND k.source_id = CAST(s.id AS TEXT)
             AND k.status = 'ACTIVE'
            LEFT JOIN users u
              ON u.id = s.reviewed_by
             AND u.venue_id = s.venue_id
            WHERE CAST(s.id AS TEXT) = ?
              AND s.venue_id = ?
              AND s.status = 'PUBLISHED'
            ORDER BY k.updated_at DESC
            LIMIT 1
            """,
            (source_id, venue_id),
        )
        if row is None:
            return _CandidateDecision(False, "SOURCE_NOT_FOUND_OR_INACTIVE")
        if str(row.get("vector_doc_id") or "") != vector_doc_id:
            return _CandidateDecision(False, "VECTOR_DOCUMENT_MISMATCH")
        if str(metadata.get("version") or "") != str(row.get("version") or ""):
            return _CandidateDecision(False, "VERSION_MISMATCH")
        if (
            str(row.get("knowledge_title") or "") != str(row.get("title") or "")
            or str(row.get("knowledge_content") or "") != str(row.get("content") or "")
        ):
            return _CandidateDecision(False, "RELATIONAL_PROJECTION_MISMATCH")
        if row.get("published_at") in (None, ""):
            return _CandidateDecision(False, "PUBLISHED_AT_MISSING")
        publisher_name = str(row.get("publisher_name") or "").strip()
        if not publisher_name:
            return _CandidateDecision(False, "PUBLISHER_NOT_FOUND")

        content = str(row.get("content") or "")
        score = _safe_score(hit.get("score"))
        reference = {
            "source_id": str(row["source_id"]),
            "resource_id": str(row["source_id"]),
            "source_type": "SOP",
            "source_label": "已发布 SOP",
            "title": str(row.get("title") or ""),
            "version": str(row.get("version") or ""),
            "status": "PUBLISHED",
            "category": str(row.get("category") or ""),
            "expert_name": "",
            "publisher_name": publisher_name,
            "published_at": row.get("published_at"),
            "score": score,
            "relevance": score,
            "content": content,
            "vector_doc_id": vector_doc_id,
            "knowledge_id": row.get("knowledge_id"),
            "selection_reason": "RELATIONAL_SOURCE_VERIFIED",
            "source_content_sha256": _sha256(content),
        }
        document = {
            "id": vector_doc_id,
            "content": content,
            "score": score,
            "metadata": dict(reference),
        }
        return _CandidateDecision(True, None, document=document, reference=reference)

    async def _verify_experience(
        self,
        hit: dict[str, Any],
        *,
        metadata: dict[str, Any],
        venue_id: str,
        user_id: str,
    ) -> _CandidateDecision:
        if str(metadata.get("status") or "").upper() != "PUBLISHED":
            return _CandidateDecision(False, "NOT_PUBLISHED")
        card_id = str(metadata.get("card_id") or "").strip()
        vector_doc_id = str(hit.get("id") or "").strip()
        if not card_id or not vector_doc_id:
            return _CandidateDecision(False, "SOURCE_ID_MISSING")
        row = await self._database.fetch_one(
            """
            SELECT
                c.*,
                e.display_name AS expert_name,
                COALESCE(u.display_name, u.username) AS publisher_name,
                source_event.business_id AS source_event_business_id
            FROM experience_cards c
            JOIN expert_profiles e
              ON e.id = c.expert_id
             AND e.venue_id = c.venue_id
             AND e.status = 'ACTIVE'
            LEFT JOIN users u
              ON u.id = c.published_by
             AND u.venue_id = c.venue_id
            LEFT JOIN confirmed_events source_event
              ON source_event.event_id = c.source_event_id
             AND source_event.venue_id = c.venue_id
            WHERE c.id = ?
              AND c.venue_id = ?
              AND c.status = 'PUBLISHED'
            """,
            (card_id, venue_id),
        )
        if row is None:
            return _CandidateDecision(False, "SOURCE_NOT_FOUND_OR_INACTIVE")
        if str(row.get("vector_doc_id") or "") != vector_doc_id:
            return _CandidateDecision(False, "VECTOR_DOCUMENT_MISMATCH")
        if str(metadata.get("version") or "") != str(row.get("published_version") or ""):
            return _CandidateDecision(False, "VERSION_MISMATCH")
        if row.get("published_at") in (None, ""):
            return _CandidateDecision(False, "PUBLISHED_AT_MISSING")
        publisher_name = str(row.get("publisher_name") or "").strip()
        if not publisher_name:
            return _CandidateDecision(False, "PUBLISHER_NOT_FOUND")
        principal = await self._database.fetch_one(
            """
            SELECT id AS user_id, venue_id, role, department, job_title
            FROM users
            WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'
            """,
            (user_id, venue_id),
        )
        scopes = await self._database.fetch_all(
            """
            SELECT scope_type, scope_value
            FROM experience_authorizations
            WHERE venue_id = ? AND card_id = ?
            """,
            (venue_id, card_id),
        )
        if not authorization_allows(venue_id, scopes, principal):
            return _CandidateDecision(False, "NOT_AUTHORIZED")

        content = _experience_content(row)
        score = _safe_score(hit.get("score"))
        reference = {
            "source_id": card_id,
            "resource_id": card_id,
            "business_id": str(row.get("business_id") or ""),
            "source_type": "EXPERIENCE_CARD",
            "source_label": "已发布专家经验",
            "title": str(row.get("title") or ""),
            "version": str(row.get("published_version") or ""),
            "status": "PUBLISHED",
            "category": "专家经验",
            "expert_name": str(row.get("expert_name") or ""),
            "publisher_name": publisher_name,
            "published_at": row.get("published_at"),
            "source_event_id": str(row.get("source_event_id") or ""),
            "source_event_business_id": str(
                row.get("source_event_business_id") or ""
            ),
            "applicable_context": str(row.get("applicable_context") or ""),
            "authorization_scopes": [
                {
                    "scope_type": str(scope.get("scope_type") or ""),
                    "scope_value": str(scope.get("scope_value") or ""),
                }
                for scope in scopes
            ],
            "score": score,
            "relevance": score,
            "content": content,
            "vector_doc_id": vector_doc_id,
            "selection_reason": "RELATIONAL_SOURCE_VERIFIED",
            "source_content_sha256": _sha256(content),
        }
        document = {
            "id": vector_doc_id,
            "content": content,
            "score": score,
            "metadata": dict(reference),
        }
        return _CandidateDecision(True, None, document=document, reference=reference)

    async def _verify_closed_case(
        self,
        hit: dict[str, Any],
        *,
        metadata: dict[str, Any],
        venue_id: str,
    ) -> _CandidateDecision:
        source_id = str(
            metadata.get("source_id")
            or metadata.get("event_id")
            or metadata.get("case_id")
            or ""
        ).strip()
        vector_doc_id = str(hit.get("id") or "").strip()
        if not source_id or not vector_doc_id:
            return _CandidateDecision(False, "SOURCE_ID_MISSING")
        row = await self._database.fetch_one(
            """
            SELECT * FROM confirmed_events
            WHERE venue_id = ?
              AND (event_id = ? OR business_id = ?)
              AND status = 'CLOSED'
            LIMIT 1
            """,
            (venue_id, source_id, source_id),
        )
        if row is None:
            return _CandidateDecision(False, "SOURCE_NOT_FOUND_OR_INACTIVE")
        if str(row.get("vector_doc_id") or "") != vector_doc_id:
            return _CandidateDecision(False, "VECTOR_DOCUMENT_MISMATCH")
        expected_version = str(metadata.get("version") or "1")
        if expected_version != "1":
            return _CandidateDecision(False, "VERSION_MISMATCH")
        if row.get("closed_at") in (None, ""):
            return _CandidateDecision(False, "CLOSED_AT_MISSING")

        content = "\n".join(
            part
            for part in (
                str(row.get("memory_content") or row.get("raw_text") or "").strip(),
                str(row.get("resolution") or "").strip(),
            )
            if part
        )
        score = _safe_score(hit.get("score"))
        reference = {
            "source_id": str(row.get("event_id") or source_id),
            "resource_id": str(row.get("event_id") or source_id),
            "business_id": str(row.get("business_id") or ""),
            "source_type": "CASE",
            "source_label": "已闭环案例",
            "title": str(row.get("business_id") or row.get("event_type") or "已闭环案例"),
            "version": "1",
            "status": "CLOSED",
            "category": str(row.get("event_type") or "现场事件"),
            "expert_name": str(row.get("assigned_to") or ""),
            "publisher_name": str(row.get("assigned_to") or row.get("from_user") or ""),
            "published_at": row.get("closed_at"),
            "score": score,
            "relevance": score,
            "content": content,
            "vector_doc_id": vector_doc_id,
            "selection_reason": "RELATIONAL_SOURCE_VERIFIED",
            "source_content_sha256": _sha256(content),
        }
        document = {
            "id": vector_doc_id,
            "content": content,
            "score": score,
            "metadata": dict(reference),
        }
        return _CandidateDecision(True, None, document=document, reference=reference)

    async def _persist_snapshot(
        self,
        *,
        request: RetrievalRequest,
        status: str,
        attempts: list[dict[str, Any]],
        references: list[dict[str, Any]],
        raw_hit_count: int,
        started_at: float,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> str:
        snapshot_id = uuid4().hex
        completed_at = time.time()
        persisted_references = [_snapshot_reference(reference) for reference in references]
        try:
            await self._database.execute(
                """
                INSERT INTO knowledge_retrieval_snapshots (
                    id, schema_version, venue_id, trace_id, message_id, session_id,
                    agent_id, query_summary, query_sha256, backend, index_name,
                    status, top_k, similarity_threshold, filter_json, attempts_json,
                    references_json, raw_hit_count, selected_count, error_type,
                    error_message, started_at, completed_at, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    self.schema_version,
                    request.venue_id,
                    request.trace_id,
                    request.message_id,
                    request.session_id,
                    request.agent_id,
                    _safe_text(request.query, limit=240),
                    _sha256(request.query),
                    self._backend_name(),
                    self._index_name(),
                    status,
                    request.top_k,
                    float(request.similarity_threshold),
                    json.dumps({"venue_id": request.venue_id}, ensure_ascii=False, sort_keys=True),
                    json.dumps(attempts, ensure_ascii=False, sort_keys=True),
                    json.dumps(persisted_references, ensure_ascii=False, sort_keys=True),
                    raw_hit_count,
                    len(persisted_references),
                    error_type,
                    error_message,
                    started_at,
                    completed_at,
                    max(0, int((completed_at - started_at) * 1000)),
                ),
            )
        except Exception:
            raise KnowledgeSnapshotPersistenceError(
                "知识检索证据无法持久化，已拒绝返回引用"
            ) from None
        return snapshot_id

    def _rerank(
        self, request: RetrievalRequest, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from .reranking import rerank_candidates

        return rerank_candidates(
            self._reranker,
            request.query,
            candidates,
            top_n=max(8, int(request.top_k)),
        )

    def _backend_name(self) -> str:
        if self._vector_store is None:
            return "unavailable"
        return str(
            getattr(self._vector_store, "backend_mode", None)
            or type(self._vector_store).__name__
        )

    def _index_name(self) -> Optional[str]:
        collection = getattr(self._vector_store, "collection", None)
        name = getattr(collection, "name", None)
        return str(name) if name else None


def _safe_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:limit]


def _sha256(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _safe_score(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _hit_record(hit: Any) -> dict[str, Any]:
    if not isinstance(hit, dict):
        return {
            "vector_doc_id": "",
            "score": 0.0,
            "content_sha256": _sha256(""),
            "content_summary": "",
        }
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    content = str(hit.get("content") or "")
    return {
        "vector_doc_id": str(hit.get("id") or ""),
        "score": _safe_score(hit.get("score")),
        "source_type": str(metadata.get("source_type") or metadata.get("asset_type") or "").upper(),
        "source_id": str(
            metadata.get("source_id")
            or metadata.get("card_id")
            or metadata.get("event_id")
            or metadata.get("business_id")
            or ""
        ),
        "version": str(metadata.get("version") or ""),
        "content_sha256": _sha256(content),
        "content_summary": _safe_text(content, limit=160),
    }


def _snapshot_reference(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in reference.items()
        if key != "content"
    }


def _business_reference(reference: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_id",
        "resource_id",
        "business_id",
        "source_type",
        "source_label",
        "title",
        "version",
        "status",
        "category",
        "expert_name",
        "publisher_name",
        "published_at",
        "relevance",
    }
    return {key: value for key, value in reference.items() if key in allowed}


def _decode_json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in decoded if isinstance(item, dict)] if isinstance(decoded, list) else []


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _lexical_relevance(query: str, document: dict[str, Any]) -> float:
    def grams(value: str) -> set[str]:
        normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())
        if len(normalized) < 2:
            return {normalized} if normalized else set()
        return {normalized[index : index + 2] for index in range(len(normalized) - 1)}

    query_grams = grams(query)
    if not query_grams:
        return 0.0
    metadata = document.get("metadata") or {}
    title_grams = grams(str(metadata.get("title") or metadata.get("business_id") or ""))
    content_grams = grams(str(document.get("content") or ""))
    title_score = len(query_grams & title_grams) / len(query_grams)
    content_score = len(query_grams & content_grams) / len(query_grams)
    return round(max(title_score * 1.8, content_score), 4)


def _source_priority(reference: dict[str, Any]) -> int:
    return {
        "SOP": 0,
        "HISTORY": 1,
        "CASE": 1,
        "EXPERIENCE": 2,
        "EXPERIENCE_CARD": 2,
    }.get(str(reference.get("source_type") or "").upper(), 9)


def _experience_content(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("applicable_context") or "").strip(),
        str(row.get("decision_rule") or "").strip(),
        str(row.get("rationale") or "").strip(),
    ]
    for field in (
        "signals_json",
        "recommended_actions_json",
        "prohibitions_json",
        "exceptions_json",
    ):
        value = row.get(field)
        try:
            decoded = json.loads(value or "[]") if not isinstance(value, list) else value
        except (TypeError, json.JSONDecodeError):
            decoded = []
        if isinstance(decoded, list):
            parts.extend(str(item).strip() for item in decoded if str(item).strip())
    return "\n".join(part for part in parts if part)


def _rerank_text(hit_record: dict[str, Any]) -> str:
    for key in ("text", "content", "summary", "title"):
        value = hit_record.get(key)
        if value:
            return str(value)
    metadata = hit_record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("text", "content", "summary", "title", "source_id"):
            value = metadata.get(key)
            if value:
                return str(value)
    return ""
