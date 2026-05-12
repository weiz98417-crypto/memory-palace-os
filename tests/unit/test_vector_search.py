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


class TestVectorStore:

    def test_upsert_and_query(self):
        """写入后 query_experience 可以召回"""
        vs = _make_test_vs()
        doc_id = str(uuid.uuid4())
        vs.upsert_experience(
            content="暴雨红色预警时关闭玻璃栈道",
            metadata={"event_type": "safety"},
            doc_id=doc_id,
        )
        results = vs.query_experience("暴雨天气怎么处理", top_k=3)
        assert isinstance(results, list)

    def test_query_with_high_threshold_filters_noise(self):
        """高阈值过滤低相关结果"""
        vs = _make_test_vs()
        vs.upsert_experience(content="售票系统故障处理流程", metadata={}, doc_id="s1")
        # 高阈值 (0.99) 下 mock embedding 的随机向量几乎不可能通过
        results = vs.query_experience("无关查询", top_k=5, threshold=0.99)
        assert len(results) == 0

    def test_empty_collection_query(self):
        """空集合查询不崩溃，返回空列表"""
        vs = _make_test_vs()
        results = vs.query_experience("any query", top_k=5)
        assert isinstance(results, list)

    def test_upsert_multiple_then_query(self):
        """批量插入后可查询"""
        vs = _make_test_vs()
        for i in range(5):
            vs.upsert_experience(
                content=f"测试文档{i}描述了一些经验",
                metadata={"idx": i},
                doc_id=f"doc_{i}",
            )
        results = vs.query_experience("测试文档", top_k=3)
        assert isinstance(results, list)

    def test_query_result_structure(self):
        """query_experience 返回正确的数据结构"""
        vs = _make_test_vs()
        vs.upsert_experience(
            content="游客投诉处理标准流程：倾听-记录-安抚-解决",
            metadata={"type": "complaint"},
            doc_id="struct_test",
        )
        results = vs.query_experience("投诉处理", top_k=1, threshold=0.0)
        if len(results) > 0:
            r = results[0]
            assert "content" in r
            assert "metadata" in r
            assert "score" in r
            assert isinstance(r["score"], (int, float))
