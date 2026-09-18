"""Rerank behaviour observed through the retrieval seam."""

from __future__ import annotations

import json

import pytest

from src.memory_palace.knowledge.evidence_backed_retrieval import (
    EvidenceBackedKnowledgeRetriever,
)
from tests.integration.test_evidence_backed_retrieval import (
    retrieval_request,
    seeded_database,
)

pytestmark = pytest.mark.asyncio


async def _add_second_sop(database) -> None:
    """Mirror the seeded SOP so the relational verification path accepts it."""

    title = "\u540e\u68c0\u4fee SOP"
    content = "\u5148\u505c\u8fd0\u3002"
    now = 1785283200.0
    await database.execute(
        """
        INSERT INTO sop_documents (
            id, venue_id, category, title, content, priority, version, status,
            created_by, reviewed_by, published_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?, ?, ?)
        """,
        (
            2102,
            "west-lake-park",
            "\u8bbe\u5907\u5b89\u5168",
            title,
            content,
            2,
            "1.0",
            "knowledge-owner",
            "knowledge-owner",
            now,
            now,
            now,
        ),
    )
    await database.execute(
        """
        INSERT INTO knowledge_documents (
            id, venue_id, title, content, category, source_type, source_id,
            version, status, tags_json, vector_doc_id, created_by, updated_by,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'SOP', ?, ?, 'ACTIVE', '[]', ?, ?, ?, ?, ?)
        """,
        (
            "sop-2102",
            "west-lake-park",
            title,
            content,
            "\u8bbe\u5907\u5b89\u5168",
            "2102",
            1,
            "sop:west-lake-park:2102",
            "knowledge-owner",
            "knowledge-owner",
            now,
            now,
        ),
    )


class TwoSopVectorStore:
    backend_mode = "test"

    def query_experience(self, text, top_k, threshold, venue_id, strict=False):
        return [
            {
                "id": "sop:west-lake-park:2101",
                "content": "\u9ad8\u5411\u91cf\u5206",
                "score": 0.91,
                "metadata": {
                    "source_id": "2101",
                    "source_type": "SOP",
                    "title": "\u9ad8\u5411\u91cf\u5206 SOP",
                    "version": "2.1",
                    "status": "PUBLISHED",
                    "venue_id": venue_id,
                },
            },
            {
                "id": "sop:west-lake-park:2102",
                "content": "\u4f4e\u5411\u91cf\u5206",
                "score": 0.55,
                "metadata": {
                    "source_id": "2102",
                    "source_type": "SOP",
                    "title": "\u4f4e\u5411\u91cf\u5206 SOP",
                    "version": "1.0",
                    "status": "PUBLISHED",
                    "venue_id": venue_id,
                },
            },
        ]


class ReversingReranker:
    model_name = "BAAI/bge-reranker-base"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def rerank_sync(self, query, candidates, *, top_n):
        self.calls.append({"query": query, "top_n": top_n, "count": len(candidates)})
        ranked = []
        for candidate in candidates:
            item = dict(candidate)
            # The later (lower vector score) candidate is the better answer.
            item["rerank_score"] = 0.95 if candidate["index"] == 1 else 0.35
            ranked.append(item)
        ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return ranked[:top_n]


class ExplodingReranker:
    model_name = "BAAI/bge-reranker-base"

    def rerank_sync(self, query, candidates, *, top_n):
        raise TimeoutError("simulated reranker outage")


async def _snapshot(database, snapshot_id):
    return await database.fetch_one(
        "SELECT * FROM knowledge_retrieval_snapshots WHERE id = ?", (snapshot_id,)
    )


async def test_reranker_can_promote_a_lower_vector_candidate(tmp_path):
    database = await seeded_database(tmp_path)
    await _add_second_sop(database)
    reranker = ReversingReranker()
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=TwoSopVectorStore(),
        reranker=reranker,
    )

    result = await retriever.retrieve(retrieval_request("trace-rerank-success"))

    assert result.references
    assert reranker.calls == [
        {"query": retrieval_request("trace-rerank-success").query, "top_n": 8, "count": 2}
    ]
    selected = [reference["vector_doc_id"] for reference in result.references]
    assert selected[0] == "sop:west-lake-park:2102"

    row = await _snapshot(database, result.snapshot_id)
    attempts = json.loads(row["attempts_json"])
    assert attempts[0]["rerank_status"] == "SUCCEEDED"
    assert attempts[0]["rerank_model"] == "BAAI/bge-reranker-base"
    assert row["schema_version"] == 2
    await database.close()


async def test_reranker_failure_falls_back_to_vector_order_without_losing_evidence(tmp_path):
    database = await seeded_database(tmp_path)
    await _add_second_sop(database)
    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=TwoSopVectorStore(),
        reranker=ExplodingReranker(),
    )

    result = await retriever.retrieve(retrieval_request("trace-rerank-failure"))

    assert result.status == "SUCCEEDED"
    assert result.references, "a rerank outage must not become 'no basis'"
    assert result.references[0]["vector_doc_id"] == "sop:west-lake-park:2101"

    row = await _snapshot(database, result.snapshot_id)
    attempts = json.loads(row["attempts_json"])
    assert attempts[0]["rerank_status"] == "FAILED"
    assert attempts[0]["rerank_error_type"] == "TimeoutError"
    await database.close()


async def test_no_reranker_is_reported_as_disabled(tmp_path):
    database = await seeded_database(tmp_path)

    await _add_second_sop(database)

    class Disabled:
        model_name = "none"

        def rerank_sync(self, query, candidates, *, top_n):
            return [dict(candidate) for candidate in candidates[:top_n]]

    retriever = EvidenceBackedKnowledgeRetriever(
        database=database,
        vector_store=TwoSopVectorStore(),
        reranker=Disabled(),
    )
    result = await retriever.retrieve(retrieval_request("trace-rerank-disabled"))

    row = await _snapshot(database, result.snapshot_id)
    attempts = json.loads(row["attempts_json"])
    assert attempts[0]["rerank_status"] == "DISABLED"
    await database.close()
