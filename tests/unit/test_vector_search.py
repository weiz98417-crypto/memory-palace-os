"""
向量检索单元测试 (Unit Test for Vector Store)

测试核心：验证 ChromaDB 的阈值拦截是否生效，确保 MemoryOps 专家不被低相关数据误导。

工业级测试要点：
  1. 内存数据库：使用 ChromaDB EphemeralClient，测试完即销毁，不产生脏文件
  2. Embedding 解耦：Mock 掉 embedding_client，测试纯检索与阈值逻辑，不依赖 GPU/模型文件
  3. 双向断言：既验证低分被拦截，也验证高分能通过（单边测试无法证明逻辑正确）
  4. 距离方向：ChromaDB cosine distance ∈ [0,2]，distance=0 完全相同，
     similarity = 1 - distance，threshold 比较的是 similarity

原始模板 Bug 修复说明：
  - mock_emb 创建后从未注入任何 patch，是死 Mock → 改为 patch embedding_client
  - monkeypatch.setenv("VECTOR_DB_PATH", ":memory:") ChromaDB 不认此变量
    → 改为直接构造时传入 EphemeralClient
  - 缺少高相似度通过的对照测试 → 补全 test_high_similarity_passes_threshold
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import chromadb
import pytest

from src.memory_palace.knowledge.vector_store import PalaceVectorStore

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMBED_DIM = 1024        # bge-m3 维度
DEFAULT_THRESHOLD = 0.75


def _fixed_vector(value: float = 0.1) -> list[float]:
    """返回固定值填充的单位向量，用于构造可控的相似度场景"""
    vec = [value] * EMBED_DIM
    # 归一化，确保余弦计算结果可预期
    norm = sum(x ** 2 for x in vec) ** 0.5
    return [x / norm for x in vec]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fixtures
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.fixture
def ephemeral_store():
    """
    使用 ChromaDB EphemeralClient（内存模式）+ Mock embedding_client。

    修复原模板 Bug：
      - EphemeralClient 才是正确的内存模式，不是设置路径为 ":memory:"
      - embedding_client 通过 patch 注入，与 GPU/模型文件完全解耦
    每个测试用例获得独立的 collection，互不干扰。
    """
    # 每个测试用例用唯一 collection 名，彻底避免测试间状态污染
    collection_name = f"test_{uuid.uuid4().hex[:8]}"

    mock_embed_client = MagicMock()
    # embed_text 是 async 方法，需要 AsyncMock
    mock_embed_client.embed_text = AsyncMock(return_value=_fixed_vector(0.5))
    mock_embed_client.embed_batch = AsyncMock(
        side_effect=lambda texts: [_fixed_vector(0.5)] * len(texts)
    )
    mock_embed_client.dimension = EMBED_DIM

    with patch(
        "src.memory_palace.knowledge.vector_store.get_embedding_client",
        return_value=mock_embed_client,
    ):
        client = chromadb.EphemeralClient()
        store = PalaceVectorStore(
            chroma_client=client,
            collection_name=collection_name,
        )
        store._embed_client = mock_embed_client
        yield store


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 阈值拦截核心测试（双向验证）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestThresholdFiltering:
    """
    ChromaDB cosine distance 说明：
      distance = 0.0  → similarity = 1.0（完全相同）
      distance = 1.0  → similarity = 0.0（正交，完全无关）
      distance = 0.25 → similarity = 0.75（threshold 临界值）

    threshold 过滤逻辑：similarity = 1 - distance，保留 similarity >= threshold 的结果。
    """

    def test_low_similarity_blocked_by_threshold(self, ephemeral_store):
        """
        【核心】低相似度结果被阈值拦截，返回空列表。
        distance=0.9 → similarity=0.1，低于 threshold=0.75，应被过滤。
        """
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [["中暑了要喝淡盐水，不能喝冰水"]],
            "metadatas": [[{"category": "safety", "doc_id": "test_01"}]],
            "distances": [[0.9]],   # similarity = 0.1，远低于阈值
        })

        results = ephemeral_store.query_experience(
            query="今天天气不错", threshold=DEFAULT_THRESHOLD
        )

        assert len(results) == 0, (
            f"distance=0.9(similarity=0.1) 应被 threshold={DEFAULT_THRESHOLD} 拦截，"
            f"但实际返回了 {len(results)} 条结果"
        )

    def test_high_similarity_passes_threshold(self, ephemeral_store):
        """
        【对照测试】高相似度结果通过阈值，正常返回。
        distance=0.1 → similarity=0.9，高于 threshold=0.75，应正常返回。

        原模板缺少此测试 → 无法证明"通过"逻辑也正确，
        可能 query_experience 直接返回空就能让低分测试通过。
        """
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [["游客晕倒需要立刻呼叫急救"]],
            "metadatas": [[{"category": "emergency", "doc_id": "test_02"}]],
            "distances": [[0.1]],   # similarity = 0.9，高于阈值
        })

        results = ephemeral_store.query_experience(
            query="有游客突然晕倒怎么处理", threshold=DEFAULT_THRESHOLD
        )

        assert len(results) == 1, (
            f"distance=0.1(similarity=0.9) 应通过 threshold={DEFAULT_THRESHOLD}，"
            f"但实际返回了 {len(results)} 条结果"
        )
        assert "晕倒" in results[0]["content"] or "急救" in results[0]["content"]

    def test_threshold_boundary_value(self, ephemeral_store):
        """
        边界值测试：similarity 恰好等于 threshold 时，应通过（≥ 而非 >）。
        distance=0.25 → similarity=0.75，恰好等于 threshold=0.75。
        """
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [["安保人员处置纠纷流程"]],
            "metadatas": [[{"category": "security"}]],
            "distances": [[0.25]],  # similarity = 0.75，恰好等于阈值
        })

        results = ephemeral_store.query_experience(
            query="两个游客吵架了", threshold=DEFAULT_THRESHOLD
        )

        assert len(results) == 1, \
            "similarity 恰好等于 threshold 时应通过（边界包含），不应被拦截"

    def test_mixed_results_partial_filtering(self, ephemeral_store):
        """
        多结果混合：高分通过，低分被过滤，验证逐条判断而非整体判断。
        """
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [["高相关经验：处置溺水", "低相关内容：停车场收费"]],
            "metadatas": [[{"category": "emergency"}, {"category": "misc"}]],
            "distances": [[0.05, 0.85]],  # similarity: 0.95 和 0.15
        })

        results = ephemeral_store.query_experience(
            query="有人溺水了", threshold=DEFAULT_THRESHOLD
        )

        assert len(results) == 1, "两条结果中只有高分的一条应通过阈值"
        assert "溺水" in results[0]["content"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 写入与检索集成验证（真实 EphemeralClient，不 Mock collection.query）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestUpsertAndQuery:
    """
    使用真实的 ChromaDB EphemeralClient 做端到端写入+检索，
    验证 upsert → query 完整链路，不 Mock collection 层。
    """

    @pytest.mark.asyncio
    async def test_upsert_then_query_returns_same_doc(self, ephemeral_store):
        """写入一条经验后，相同内容查询能召回"""
        # embedding 全部返回相同向量，保证距离为 0（完全相同）
        await ephemeral_store.upsert_experience(
            content="游客在景区晕倒，立即静默呼叫医务室",
            metadata={"category": "emergency", "severity": "P0"},
            doc_id="e001",
        )

        # 查询时 embedding 也返回相同向量 → distance ≈ 0 → similarity ≈ 1.0
        results = await ephemeral_store.query_experience(
            query="有游客晕倒了怎么办",
            threshold=0.5,
            top_k=3,
        )

        assert len(results) >= 1
        assert any("晕倒" in r["content"] or "医务室" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_upsert_idempotent(self, ephemeral_store):
        """相同 doc_id 重复写入，不产生重复记录（upsert 语义）"""
        for _ in range(3):
            await ephemeral_store.upsert_experience(
                content="重复内容测试",
                metadata={"version": "1"},
                doc_id="dup_001",
            )

        results = await ephemeral_store.query_experience(
            query="重复内容测试", threshold=0.0
        )
        doc_ids = [r.get("doc_id") for r in results]
        assert doc_ids.count("dup_001") <= 1, "相同 doc_id 不应产生重复记录"

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, ephemeral_store):
        """top_k 参数有效：写入 5 条，top_k=2 只返回 2 条"""
        for i in range(5):
            await ephemeral_store.upsert_experience(
                content=f"景区应急经验第 {i+1} 条",
                metadata={"index": i},
                doc_id=f"doc_{i:03d}",
            )

        results = await ephemeral_store.query_experience(
            query="应急经验", threshold=0.0, top_k=2
        )

        assert len(results) <= 2, f"top_k=2 应最多返回 2 条，实际返回 {len(results)} 条"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 防幻觉红线测试（MemoryOps 专家核心合规要求）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAntiHallucinationGuard:
    """
    验证 vector_store 在无匹配结果时，返回明确的空结果而非捏造内容。
    对应 memory_ops/soul.txt 中的红线：「有据可查，才能开口」。
    """

    def test_empty_store_returns_empty_not_fabricated(self, ephemeral_store):
        """空知识库查询，返回空列表，不抛异常，不返回捏造结果"""
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        })

        results = ephemeral_store.query_experience(
            query="史上最罕见的事故类型", threshold=DEFAULT_THRESHOLD
        )

        assert isinstance(results, list), "返回类型必须是 list"
        assert len(results) == 0, "空知识库应返回空列表，不得捏造结果"

    def test_all_below_threshold_returns_empty(self, ephemeral_store):
        """所有候选结果均低于阈值时，返回空列表，触发 MemoryOps 的'暂无匹配经验'响应"""
        ephemeral_store.collection.query = MagicMock(return_value={
            "documents": [["完全不相关的内容A", "完全不相关的内容B"]],
            "metadatas": [[{"cat": "a"}, {"cat": "b"}]],
            "distances": [[0.95, 0.98]],  # similarity: 0.05, 0.02
        })

        results = ephemeral_store.query_experience(
            query="任意查询", threshold=DEFAULT_THRESHOLD
        )

        assert len(results) == 0, (
            "所有结果低于阈值时应返回空列表，"
            "MemoryOps 层应据此回复'暂无匹配经验'而非强行输出"
        )