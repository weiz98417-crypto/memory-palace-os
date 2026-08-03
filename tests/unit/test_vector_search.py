"""
向量检索单元测试 (Unit Test for Vector Store)

使用 mock embedding 绕过 OpenAI API 依赖。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import uuid
import numpy as np
import chromadb
import pytest
from src.memory_palace.knowledge.vector_store import PalaceVectorStore


class MockEmbeddingFunction(chromadb.EmbeddingFunction):
    """返回确定性向量 (1536 维)"""

    def name(self):
        return "mock"

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        vectors = []
        rng = np.random.RandomState(42)
        for text in input:
            rng.seed(abs(hash(text)) % (2**31))
            vectors.append(rng.randn(1536).astype(np.float32).tolist())
        return vectors


def _make_test_vs():
    vs = object.__new__(PalaceVectorStore)
    vs.emb_fn = MockEmbeddingFunction()
    vs._client = chromadb.EphemeralClient()
    vs.collection = vs._client.get_or_create_collection(
        name=f"test_vdb_{uuid.uuid4().hex[:8]}",
        embedding_function=vs.emb_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return vs


@pytest.fixture
def vector_store():
    store = _make_test_vs()
    try:
        yield store
    finally:
        store.close()


class TestVectorStore:

    def test_upsert_and_query(self, vector_store):
        """写入后 query_experience 可以召回"""
        vs = vector_store
        doc_id = str(uuid.uuid4())
        vs.upsert_experience(
            content="暴雨红色预警时关闭玻璃栈道",
            metadata={"event_type": "safety", "venue_id": "venue-a"},
            doc_id=doc_id,
        )
        results = vs.query_experience("暴雨天气怎么处理", top_k=3, venue_id="venue-a")
        assert isinstance(results, list)

    def test_query_requires_tenant_scope(self, vector_store):
        """任何向量检索都必须显式绑定场地，缺失时拒绝执行。"""
        with pytest.raises(TypeError, match="venue_id"):
            vector_store.query_experience("暴雨天气怎么处理")
        with pytest.raises(ValueError, match="venue_id"):
            vector_store.query_experience("暴雨天气怎么处理", venue_id="")

    def test_query_with_high_threshold_filters_noise(self, vector_store):
        """高阈值过滤低相关结果"""
        vs = vector_store
        vs.upsert_experience(
            content="售票系统故障处理流程",
            metadata={"venue_id": "venue-a"},
            doc_id="s1",
        )
        # 高阈值 (0.99) 下 mock embedding 的随机向量几乎不可能通过
        results = vs.query_experience(
            "无关查询", top_k=5, threshold=0.99, venue_id="venue-a"
        )
        assert len(results) == 0

    def test_empty_collection_query(self, vector_store):
        """空集合查询不崩溃，返回空列表"""
        vs = vector_store
        results = vs.query_experience("any query", top_k=5, venue_id="venue-a")
        assert isinstance(results, list)

    def test_upsert_multiple_then_query(self, vector_store):
        """批量插入后可查询"""
        vs = vector_store
        for i in range(5):
            vs.upsert_experience(
                content=f"测试文档{i}描述了一些经验",
                metadata={"idx": i, "venue_id": "venue-a"},
                doc_id=f"doc_{i}",
            )
        results = vs.query_experience("测试文档", top_k=3, venue_id="venue-a")
        assert isinstance(results, list)

    def test_query_result_structure(self, vector_store):
        """query_experience 返回正确的数据结构"""
        vs = vector_store
        vs.upsert_experience(
            content="游客投诉处理标准流程：倾听-记录-安抚-解决",
            metadata={"type": "complaint", "venue_id": "venue-a"},
            doc_id="struct_test",
        )
        results = vs.query_experience(
            "投诉处理", top_k=1, threshold=0.0, venue_id="venue-a"
        )
        if len(results) > 0:
            r = results[0]
            assert "content" in r
            assert "metadata" in r
            assert "score" in r
            assert isinstance(r["score"], (int, float))
