"""Unit coverage for the PostgreSQL pgvector knowledge interface."""

import pytest

from tests.pgvector_fake import build_fake_pgvector_store


@pytest.fixture
def vector_store():
    store, _database = build_fake_pgvector_store()
    return store


def test_upsert_and_query_is_tenant_scoped(vector_store):
    vector_store.upsert_experience(
        "暴雨红色预警时关闭玻璃栈道",
        {"event_type": "safety", "venue_id": "venue-a"},
        "safety-1",
        strict=True,
    )
    assert vector_store.query_experience(
        "暴雨红色预警时关闭玻璃栈道",
        top_k=3,
        threshold=0.99,
        venue_id="venue-a",
        strict=True,
    )[0]["id"] == "safety-1"
    assert vector_store.query_experience(
        "暴雨红色预警时关闭玻璃栈道",
        venue_id="venue-b",
        strict=True,
    ) == []


def test_query_requires_tenant_scope(vector_store):
    with pytest.raises(TypeError, match="venue_id"):
        vector_store.query_experience("暴雨天气怎么处理")
    with pytest.raises(ValueError, match="venue_id"):
        vector_store.query_experience("暴雨天气怎么处理", venue_id="")


def test_source_type_filter_restricts_retrieval_to_requested_types(vector_store):
    vector_store.upsert_experience(
        "雨后复运检查观光车轮胎与制动",
        {"venue_id": "venue-a", "source_type": "SOP", "source_id": "sop-1"},
        "sop:venue-a:1",
        strict=True,
    )
    for index in range(3):
        vector_store.upsert_experience(
            "雨后复运检查观光车轮胎与制动的历史处置案例",
            {"venue_id": "venue-a", "source_type": "CASE", "source_id": f"case-{index}"},
            f"evt-case-{index}",
            strict=True,
        )

    sop_only = vector_store.query_experience(
        "雨后复运检查观光车轮胎与制动",
        top_k=5,
        threshold=0.0,
        venue_id="venue-a",
        source_types=["SOP"],
        strict=True,
    )
    assert [hit["id"] for hit in sop_only] == ["sop:venue-a:1"]

    case_only = vector_store.query_experience(
        "雨后复运检查观光车轮胎与制动",
        top_k=5,
        threshold=0.0,
        venue_id="venue-a",
        source_types=["CASE"],
        strict=True,
    )
    assert len(case_only) == 3
    assert all(hit["metadata"]["source_type"] == "CASE" for hit in case_only)


def test_high_threshold_filters_unrelated_content(vector_store):
    vector_store.upsert_experience(
        "售票系统故障处理流程",
        {"venue_id": "venue-a"},
        "ticketing-1",
        strict=True,
    )
    assert vector_store.query_experience(
        "完全无关的东门客流查询",
        top_k=5,
        threshold=0.99,
        venue_id="venue-a",
        strict=True,
    ) == []


def test_query_result_and_migration_verification_contract(vector_store):
    vector_store.upsert_experience(
        "游客投诉处理标准流程：倾听、记录、安抚、解决",
        {"type": "complaint", "venue_id": "venue-a"},
        "complaint-1",
        strict=True,
    )
    result = vector_store.query_experience(
        "游客投诉处理标准流程：倾听、记录、安抚、解决",
        top_k=1,
        threshold=0.99,
        venue_id="venue-a",
        strict=True,
    )[0]
    assert set(result) == {"id", "content", "metadata", "score"}
    assert vector_store.verify_documents(["complaint-1"]) == {
        "document_count": 1,
        "min_dimension": 1024,
        "max_dimension": 1024,
        "index_name": "knowledge_vectors_bge_m3_v1",
        "model_name": "BAAI/bge-m3",
        "model_version": "local-bge-m3-1024-v1",
        "dimension": 1024,
        "status": "READY",
    }
