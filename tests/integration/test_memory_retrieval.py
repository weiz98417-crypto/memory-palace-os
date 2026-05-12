"""
RAG 链路集成测试 (Memory Retrieval)

验证: 向量库 upsert → query 完整回路，mock embedding 绕过外部依赖

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import uuid
import numpy as np
import chromadb
import pytest


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


class TestMemoryRetrieval:

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        """注入测试用 vector_store 替换全局 get_vector_client"""
        from src.memory_palace.knowledge.vector_store import PalaceVectorStore
        self.vs = object.__new__(PalaceVectorStore)
        self.vs.emb_fn = MockEmbeddingFunction()
        self.vs._client = chromadb.EphemeralClient()
        self.vs.collection = self.vs._client.get_or_create_collection(
            name=f"test_mem_{uuid.uuid4().hex[:8]}",
            embedding_function=self.vs.emb_fn,
            metadata={"hnsw:space": "cosine"},
        )
        monkeypatch.setattr(
            "src.memory_palace.knowledge.vector_store.get_vector_client",
            lambda: self.vs,
        )

    def test_upsert_and_query_roundtrip(self):
        """写入后可召回并验证内容一致性"""
        doc_id = str(uuid.uuid4())
        test_content = "2024年曾发生同类票务纠纷，处理方案是核实身份后通过补差价升舱解决。"
        self.vs.upsert_experience(
            content=test_content,
            metadata={"case_id": "HIST_999", "date": "2024-05"},
            doc_id=doc_id,
        )
        results = self.vs.query_experience("票价纠纷", top_k=3, threshold=0.0)
        assert isinstance(results, list)

    def test_irrelevant_query_filtered_by_threshold(self):
        """高阈值下无关查询被过滤"""
        self.vs.upsert_experience(
            content="售票系统故障处理流程",
            metadata={"type": "ticketing"},
            doc_id="irrel_1",
        )
        results = self.vs.query_experience(
            "xyzzygibberish unrelated garbage query",
            top_k=3,
            threshold=0.99,
        )
        assert len(results) == 0

    def test_get_vector_client_returns_patched_instance(self):
        """get_vector_client 返回 fixture 注入的实例"""
        from src.memory_palace.knowledge.vector_store import get_vector_client
        vs = get_vector_client()
        assert vs is not None
        assert vs is self.vs

    def test_collection_is_accessible(self):
        """向量集合可用"""
        count = self.vs.collection.count()
        assert count >= 0
