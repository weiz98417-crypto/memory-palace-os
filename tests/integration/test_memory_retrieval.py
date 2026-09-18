"""RAG interface integration coverage using the PostgreSQL pgvector seam."""

from src.memory_palace.knowledge.vector_store import get_vector_client
from tests.pgvector_fake import build_fake_pgvector_store


def test_upsert_query_and_global_client_roundtrip(monkeypatch):
    store, _database = build_fake_pgvector_store()
    monkeypatch.setattr(
        "src.memory_palace.knowledge.vector_store._vector_client",
        store,
    )
    content = "2024 年同类票务纠纷通过核实身份后补差价解决。"
    store.upsert_experience(
        content,
        {"case_id": "HIST_999", "date": "2024-05", "venue_id": "venue-a"},
        "history-999",
        strict=True,
    )
    results = store.query_experience(
        content,
        top_k=3,
        threshold=0.99,
        venue_id="venue-a",
        strict=True,
    )
    assert results[0]["content"] == content
    assert get_vector_client() is store


def test_delete_removes_pgvector_document():
    store, _database = build_fake_pgvector_store()
    store.upsert_experience(
        "售票系统故障处理流程",
        {"venue_id": "venue-a"},
        "ticketing-delete",
        strict=True,
    )
    assert store.delete_experience("ticketing-delete", strict=True) is True
    assert store.verify_documents(["ticketing-delete"])["document_count"] == 0
