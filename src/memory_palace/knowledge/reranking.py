"""Reranker seam for knowledge retrieval.

Callers never see the TEI URL, rerank scores or the failure strategy: they hand over
verified candidates and get an ordered list back. A rerank failure must never turn into
"no basis" — it only falls back to the pgvector order.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Protocol


DEFAULT_RERANK_TEXT_LIMIT = 2048
RERANKER_BASE_URL_ENV = "SCENIC_TEI_RERANKER_URL"


class RerankerBackend(Protocol):
    model_name: str

    def rerank_sync(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> list[dict[str, Any]]: ...


class NoopRerankerBackend:
    """Keeps the pgvector order; used when no reranker is configured."""

    model_name = "none"

    def rerank_sync(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for candidate in list(candidates)[: max(0, int(top_n))]:
            item = dict(candidate)
            item["rerank_status"] = "DISABLED"
            item["rerank_score"] = None
            item["rerank_model"] = None
            ranked.append(item)
        return ranked


class TEIRerankerBackend:
    """bge-reranker-base served by text-embeddings-inference over HTTP."""

    model_name = "BAAI/bge-reranker-base"

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float | None = None,
        max_text_length: int = DEFAULT_RERANK_TEXT_LIMIT,
        transport=None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.timeout = float(
            timeout if timeout is not None else os.environ.get("TEI_RERANKER_TIMEOUT", "20")
        )
        self.max_text_length = max_text_length
        self._transport = transport

    def _client(self):
        if self._transport is not None:
            return self._transport
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a hard dependency
            raise RuntimeError("httpx is required for the TEI reranker backend") from exc
        return httpx.Client(timeout=self.timeout)

    def rerank_sync(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        texts = [self._candidate_text(candidate) for candidate in candidates]
        client = self._client()
        owns_client = self._transport is None
        try:
            try:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json={"query": str(query), "texts": texts},
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                raise RuntimeError(
                    f"TEI rerank request failed: {type(exc).__name__}"
                ) from exc
        finally:
            if owns_client:
                close = getattr(client, "close", None)
                if callable(close):
                    close()

        scored = self._scored_candidates(payload, candidates)
        limit = max(0, int(top_n))
        return scored[:limit] if limit else scored

    def _candidate_text(self, candidate: dict[str, Any]) -> str:
        for key in ("text", "content", "summary", "title"):
            value = candidate.get(key)
            if value:
                return str(value)[: self.max_text_length]
        return ""

    @staticmethod
    def _scored_candidates(
        payload: object, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise RuntimeError("TEI rerank response must be a list")
        best_by_index: dict[int, float] = {}
        for entry in payload:
            if not isinstance(entry, dict):
                raise RuntimeError("TEI rerank response contained a non-object entry")
            try:
                index = int(entry["index"])
                score = float(entry["score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("TEI rerank response entry was malformed") from exc
            if index < 0 or index >= len(candidates):
                raise RuntimeError(f"TEI rerank returned out-of-range index {index}")
            if not math.isfinite(score):
                raise RuntimeError("TEI rerank returned a non-finite score")
            if index not in best_by_index or score > best_by_index[index]:
                best_by_index[index] = score

        ranked: list[dict[str, Any]] = []
        for index, score in sorted(
            best_by_index.items(), key=lambda item: (-item[1], item[0])
        ):
            item = dict(candidates[index])
            item["rerank_score"] = score
            item["rerank_status"] = "SUCCEEDED"
            item["rerank_model"] = TEIRerankerBackend.model_name
            ranked.append(item)
        return ranked


def build_reranker_backend() -> RerankerBackend:
    """Return the TEI reranker when configured, else a no-op that keeps vector order."""

    base_url = os.environ.get(RERANKER_BASE_URL_ENV, "").strip()
    if base_url:
        return TEIRerankerBackend(base_url=base_url)
    return NoopRerankerBackend()

def rerank_candidates(
    reranker: RerankerBackend | None,
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply the reranker to verified candidates and report what actually happened.

    Returns the reranked candidates plus a compact metadata block for the retrieval
    snapshot. A failure is reported as ``FAILED`` and leaves the caller's original
    order untouched — it must never be turned into "no basis".
    """

    if not candidates:
        return [], {"rerank_status": "DISABLED", "rerank_model": None}
    if reranker is None:
        return list(candidates), {"rerank_status": "DISABLED", "rerank_model": None}
    model_name = str(getattr(reranker, "model_name", "") or "") or None
    started = time.perf_counter()
    try:
        ranked = reranker.rerank_sync(query, candidates, top_n=top_n)
    except Exception as exc:
        return list(candidates), {
            "rerank_status": "FAILED",
            "rerank_model": model_name,
            "rerank_error_type": type(exc).__name__,
            "rerank_latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    status = "DISABLED" if model_name in (None, "none") else "SUCCEEDED"
    return list(ranked), {
        "rerank_status": status,
        "rerank_model": model_name,
        "rerank_latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }
