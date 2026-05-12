"""
三层上下文压缩 (ContextTier) 单元测试

覆盖: 数据模型、层级枚举、TieredContext 操作

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import time
import pytest
from src.memory_palace.core.context_tier import (
    ContextTier,
    HotMessage,
    WarmSummary,
    ColdNarrative,
    TieredContext,
    ContextCompressor,
)


class TestContextTierEnum:

    def test_all_tiers_defined(self):
        """三个层级枚举值存在"""
        assert ContextTier.HOT.value == "hot"
        assert ContextTier.WARM.value == "warm"
        assert ContextTier.COLD.value == "cold"

    def test_tier_comparison(self):
        """枚举可以直接比较"""
        assert ContextTier.HOT != ContextTier.COLD
        assert ContextTier.HOT == ContextTier("hot")


class TestHotMessage:

    def test_creation(self):
        """HotMessage 正常创建"""
        msg = HotMessage(role="user", content="Hello", timestamp=time.time())
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.metadata == {}

    def test_with_metadata(self):
        """HotMessage 支持 metadata"""
        msg = HotMessage(
            role="assistant",
            content="response",
            timestamp=time.time(),
            metadata={"trace_id": "abc123"},
        )
        assert msg.metadata["trace_id"] == "abc123"


class TestWarmSummary:

    def test_creation(self):
        """WarmSummary 正常创建"""
        now = time.time()
        ws = WarmSummary(
            batch_id="batch-1",
            message_count=10,
            summary="用户询问了天气并获得了回复",
            time_range_start=now - 3600,
            time_range_end=now,
            tokens_used=150,
        )
        assert ws.batch_id == "batch-1"
        assert ws.message_count == 10
        assert ws.tokens_used == 150


class TestColdNarrative:

    def test_creation(self):
        """ColdNarrative 正常创建"""
        cn = ColdNarrative(
            session_id="session-1",
            narrative="这是一段关于景区运营的长对话...",
            last_updated=time.time(),
            original_messages_count=200,
        )
        assert cn.session_id == "session-1"
        assert cn.original_messages_count == 200


class TestTieredContext:

    def test_initialization(self):
        """TieredContext 初始为空"""
        ctx = TieredContext(
            session_id="s1",
            user_id="u1",
            venue_id="v1",
        )
        assert ctx.session_id == "s1"
        assert ctx.hot_messages == []
        assert ctx.warm_summaries == []
        assert ctx.cold_narrative is None
        assert ctx.total_messages == 0

    def test_add_hot_message(self):
        """添加消息到 Hot 层"""
        ctx = TieredContext(session_id="s1", user_id="u1")
        ctx.hot_messages.append(
            HotMessage(role="user", content="msg1", timestamp=time.time())
        )
        ctx.total_messages += 1
        assert len(ctx.hot_messages) == 1
        assert ctx.total_messages == 1

    def test_to_dict(self):
        """to_dict 返回完整数据结构"""
        ctx = TieredContext(session_id="s1", user_id="u1", venue_id="v1")
        ctx.hot_messages.append(
            HotMessage(role="user", content="hello", timestamp=1000.0)
        )
        ctx.total_messages = 1
        d = ctx.to_dict()
        assert d["session_id"] == "s1"
        assert d["user_id"] == "u1"
        assert d["total_messages"] == 1
        assert len(d["hot_messages"]) == 1
        assert d["hot_messages"][0]["role"] == "user"


class TestContextCompressor:

    def test_compressor_initialization(self):
        """ContextCompressor 正常实例化"""
        comp = ContextCompressor(hot_size=10)
        assert comp.hot_size == 10

    def test_compressor_defaults(self):
        """默认参数正确"""
        comp = ContextCompressor()
        assert comp.hot_size == 10

    @pytest.mark.asyncio
    async def test_disabled_summarization(self):
        """LLM 摘要已禁用，_call_summarization_llm 返回占位符"""
        comp = ContextCompressor()
        result = await comp._call_summarization_llm("test batch")
        assert "已禁用" in result

    def test_build_tiered_context(self):
        """从消息列表构建 TieredContext"""
        comp = ContextCompressor()
        messages = [
            {"role": "user", "content": f"msg{i}", "timestamp": float(i)}
            for i in range(25)
        ]
        result = comp.build_tiered_context(
            session_id="s1",
            messages=messages,
            hot_count=10,
            total_budget=30,
        )
        assert "hot" in result
        assert "warm" in result

    def test_get_stats(self):
        """get_stats 返回统计数据"""
        comp = ContextCompressor()
        ctx = TieredContext(session_id="s1", user_id="u1")
        ctx.hot_messages.append(
            HotMessage(role="user", content="msg", timestamp=time.time())
        )
        ctx.total_messages = 1
        stats = comp.get_stats(ctx)
        assert stats["total_messages"] == 1
        assert stats["hot_count"] == 1
        assert "tokens_saved" in stats
