"""
三层上下文压缩系统 (Three-Tier Context Compression) — STUB: Phase 1，待激活

架构设计:
- Tier 0 (Hot): 最近 N 条消息，保持完整 fidelity
- Tier 1 (Warm): 被 evict 出 Hot 层消息的 LLM 摘要
- Tier 2 (Cold): 极老会话的叙事性摘要

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class ContextTier(Enum):
    """上下文层级枚举"""
    HOT = "hot"      # 完整 fidelity 消息
    WARM = "warm"    # LLM 生成的摘要
    COLD = "cold"    # 叙事性摘要


@dataclass
class HotMessage:
    """Tier 0: 完整 fidelity 消息"""
    role: str
    content: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WarmSummary:
    """Tier 1: 批次摘要 (当消息从 Hot 层 evict 时生成)"""
    batch_id: str
    message_count: int
    summary: str  # LLM 生成
    time_range_start: float
    time_range_end: float
    tokens_used: int
    created_at: float = field(default_factory=time.time)


@dataclass
class ColdNarrative:
    """Tier 2: 会话叙事摘要 (针对极老会话)"""
    session_id: str
    narrative: str  # LLM 生成
    last_updated: float
    original_messages_count: int


@dataclass
class TieredContext:
    """
    完整三层上下文容器

    设计原则:
    - Hot 层优先保留最新对话的精确 reasoning
    - Warm 层存储被 evict 消息的语义压缩
    - Cold 层提供会话级宏观叙事
    """
    session_id: str
    user_id: str
    venue_id: str = ""

    # Tier 0: Hot - 最近消息 (默认保留 10 条)
    hot_messages: List[HotMessage] = field(default_factory=list)

    # Tier 1: Warm - 批次摘要列表
    warm_summaries: List[WarmSummary] = field(default_factory=list)

    # Tier 2: Cold - 叙事摘要
    cold_narrative: Optional[ColdNarrative] = None

    # 配置参数
    hot_tier_size: int = 10          # Hot 层保留消息数
    warm_batch_size: int = 20        # 每批次摘要包含的消息数
    cold_trigger_turns: int = 50      # 触发 Cold 层生成的轮次

    # 统计
    total_messages: int = 0
    total_tokens_saved: int = 0      # 通过压缩节省的 token 数估算

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "venue_id": self.venue_id,
            "hot_messages": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp, "metadata": m.metadata}
                for m in self.hot_messages
            ],
            "warm_summaries": [
                {
                    "batch_id": s.batch_id,
                    "message_count": s.message_count,
                    "summary": s.summary,
                    "time_range_start": s.time_range_start,
                    "time_range_end": s.time_range_end,
                    "tokens_used": s.tokens_used
                }
                for s in self.warm_summaries
            ],
            "cold_narrative": {
                "narrative": self.cold_narrative.narrative,
                "last_updated": self.cold_narrative.last_updated,
                "original_messages_count": self.cold_narrative.original_messages_count
            } if self.cold_narrative else None,
            "total_messages": self.total_messages,
            "total_tokens_saved": self.total_tokens_saved
        }


class ContextCompressor:
    """
    三层上下文压缩管理器

    工作流程:
    1. 新消息到达 -> 加入 Hot 层
    2. Hot 层溢出 -> 最老批次 evict -> 调用 LLM 生成 Warm 摘要
    3. Warm 层积累到阈值 -> 生成/更新 Cold 叙事摘要
    """

    def __init__(
        self,
        hot_size: int = 10,
        warm_batch: int = 20,
        cold_trigger: int = 50,
        summarization_model: str = "gpt-4o-mini"
    ):
        self.hot_size = hot_size
        self.warm_batch = warm_batch
        self.cold_trigger = cold_trigger
        self.summarization_model = summarization_model

        # [修复] 添加锁保护并发访问
        self._lock = asyncio.Lock()
        # 待处理的待 evict 消息批次
        self._pending_batch: List[HotMessage] = []
        self._batch_counter = 0

    async def add_message(
        self,
        ctx: TieredContext,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> Tuple[TieredContext, bool]:
        """
        添加消息到 Hot 层，触发压缩如果需要

        Returns:
            (updated_context, was_compressed) - 是否发生了压缩
        """
        msg = HotMessage(
            role=role,
            content=content,
            timestamp=time.time(),
            metadata=metadata or {}
        )
        ctx.hot_messages.append(msg)
        ctx.total_messages += 1

        was_compressed = False

        # 检查 Hot 层是否溢出
        if len(ctx.hot_messages) > self.hot_size:
            await self._evict_to_warm(ctx)
            was_compressed = True

        # 检查是否需要生成 Cold 叙事
        if ctx.total_messages >= self.cold_trigger and ctx.cold_narrative is None:
            await self._generate_cold_narrative(ctx)
            was_compressed = True

        return ctx, was_compressed

    async def _evict_to_warm(self, ctx: TieredContext) -> None:
        """
        将 Hot 层最老的消息 evict 到 Warm 层 (生成 LLM 摘要)

        策略: 批量处理，每次 evict 半个 hot_tier_size 的消息
        """
        async with self._lock:
            evict_count = max(1, self.hot_size // 2)
            evicted = ctx.hot_messages[:evict_count]
            ctx.hot_messages = ctx.hot_messages[evict_count:]

            logger.debug(
                f"[ContextCompressor] Evict {len(evicted)} 条消息到 Warm 层, "
                f"Hot 层剩余 {len(ctx.hot_messages)} 条"
            )

            # 加入待处理批次
            self._pending_batch.extend(evicted)

            # 当批次达到阈值时，生成摘要
            if len(self._pending_batch) >= self.warm_batch:
                await self._generate_batch_summary(ctx)

    async def _generate_batch_summary(self, ctx: TieredContext) -> WarmSummary:
        """使用 LLM 生成批次摘要"""
        if not self._pending_batch:
            raise ValueError("No pending batch to summarize")

        self._batch_counter += 1
        batch_id = f"{ctx.session_id}_batch_{self._batch_counter}"

        # 格式化批次内容
        batch_text = "\n".join([
            f"[{m.role}]: {m.content}"
            for m in self._pending_batch
        ])

        # 估算原始 token 数 (粗略: 字符数 / 4)
        estimated_tokens = sum(len(m.content) for m in self._pending_batch) // 4

        # 调用 LLM 生成摘要
        summary_text = await self._call_summarization_llm(batch_text)

        warm_summary = WarmSummary(
            batch_id=batch_id,
            message_count=len(self._pending_batch),
            summary=summary_text,
            time_range_start=self._pending_batch[0].timestamp,
            time_range_end=self._pending_batch[-1].timestamp,
            tokens_used=len(summary_text) // 4  # 估算
        )

        ctx.warm_summaries.append(warm_summary)
        ctx.total_tokens_saved += estimated_tokens - warm_summary.tokens_used

        # 清空待处理批次
        self._pending_batch.clear()

        logger.info(
            f"[ContextCompressor] 生成 Warm 摘要 {batch_id}: "
            f"{len(self._pending_batch)} 条消息 -> {len(summary_text)} 字"
        )

        return warm_summary

    async def _generate_cold_narrative(self, ctx: TieredContext) -> ColdNarrative:
        """
        为极老会话生成叙事性摘要

        Cold 叙事与 Warm 摘要的区别:
        - Warm: 保留更多细节，是批次级别的压缩
        - Cold: 更高层次的叙事，描述整个会话的目标和走向
        """
        # 收集所有 Warm 摘要
        warm_texts = [s.summary for s in ctx.warm_summaries]

        # 如果没有 Warm 层，直接用 Hot 层
        if not warm_texts:
            source_text = "\n".join([
                f"[{m.role}]: {m.content}"
                for m in ctx.hot_messages
            ])
        else:
            source_text = "\n\n".join(warm_texts)

        # 调用 LLM 生成叙事摘要
        narrative = await self._call_narrative_llm(source_text, ctx.session_id)

        ctx.cold_narrative = ColdNarrative(
            session_id=ctx.session_id,
            narrative=narrative,
            last_updated=time.time(),
            original_messages_count=ctx.total_messages
        )

        logger.info(
            f"[ContextCompressor] 生成 Cold 叙事摘要: "
            f"{ctx.total_messages} 条消息 -> {len(narrative)} 字"
        )

        return ctx.cold_narrative

    async def _call_summarization_llm(self, batch_text: str) -> str:
        """[DISABLED] LLM 摘要生成已暂停 — 输出暂未被任何 Agent 消费"""
        logger.debug("[ContextCompressor] summarization disabled — returning placeholder")
        return "[摘要已禁用]"
        try:
            from ..tools.llm_wrapper import get_llm_client
            llm = get_llm_client()

            prompt = f"""请用50字以内总结以下对话的核心内容，保留关键信息（意图、决定、结果）：

{batch_text}

要求：
- 只输出总结内容
- 保留关键信息
- 使用简体中文"""

            response = await llm.ask(
                system_prompt="你是一个对话摘要专家。",
                user_prompt=prompt,
                temperature=0.3,
                model="gpt-4o-mini",
                trace_id=f"summarize_{uuid.uuid4().hex[:8]}"
            )

            return response.content.strip()

        except Exception as e:
            logger.error(f"[ContextCompressor] LLM 摘要生成失败: {e}")
            # 降级: 返回简单拼接
            return f"[摘要] {batch_text[:100]}..."

    async def _call_narrative_llm(self, source_text: str, session_id: str) -> str:
        """调用 LLM 生成叙事性摘要"""
        try:
            from ..tools.llm_wrapper import get_llm_client
            llm = get_llm_client()

            prompt = f"""请用100字以内总结以下会话的整体叙事，描述用户的主要目标和交互走向：

{source_text}

要求：
- 用连贯的段落描述
- 突出主要目标和结果
- 使用简体中文"""

            response = await llm.ask(
                system_prompt="你是一个叙事分析师。",
                user_prompt=prompt,
                temperature=0.3,
                model="gpt-4o-mini",
                trace_id=f"narrative_{session_id}"
            )

            return response.content.strip()

        except Exception as e:
            logger.error(f"[ContextCompressor] LLM 叙事生成失败: {e}")
            return f"[会话叙事] {source_text[:100]}..."

    def assemble_prompt(
        self,
        ctx: TieredContext,
        available_tokens: int = 4000
    ) -> List[Dict[str, str]]:
        """
        将三层上下文组装为 LLM 可消费的 prompt

        策略: 从 Cold -> Warm -> Hot 依次填充分配的 token 预算
        """
        result: List[Dict[str, str]] = []
        remaining_tokens = available_tokens

        # 1. 添加 Cold 叙事 (最优先，但最精简)
        if ctx.cold_narrative:
            narrative_text = f"[会话背景] {ctx.cold_narrative.narrative}"
            estimated_tokens = len(narrative_text) // 4

            if remaining_tokens >= estimated_tokens:
                result.append({"role": "system", "content": narrative_text})
                remaining_tokens -= estimated_tokens

        # 2. 添加 Warm 摘要 (取最近 3 个)
        for summary in ctx.warm_summaries[-3:]:
            if remaining_tokens < 200:
                break

            summary_text = f"[{summary.message_count}条消息摘要] {summary.summary}"
            result.append({"role": "system", "content": summary_text})
            remaining_tokens -= 200  # 估算

        # 3. 添加 Hot 消息 (完整 fidelity)
        for msg in ctx.hot_messages:
            msg_tokens = len(msg.content) // 4
            if remaining_tokens < msg_tokens:
                break
            result.append({"role": msg.role, "content": msg.content})
            remaining_tokens -= msg_tokens

        return result

    def build_tiered_context(self, session_id: str, messages: list,
                             hot_count: int = 10, total_budget: int = 30) -> Dict[str, Any]:
        """
        [M2] 构建三层上下文，用于 Agent 消费。

        Args:
            session_id: 会话 ID
            messages: 消息列表 [{"role": "user"|"assistant", "content": "..."}]
            hot_count: Hot 层保留的消息数
            total_budget: 三层总消息数上限

        Returns:
            {"hot": [...], "warm": [...], "cold": "..."}
            Hot 为完整消息列表，Warm/Cold 当前为空（LLM 摘要后续迭代）
        """
        # 取最近的消息
        recent = messages[-hot_count:] if len(messages) > hot_count else messages
        # 超过预算时截断
        if total_budget and len(recent) > total_budget:
            recent = recent[-total_budget:]

        # TODO: Warm/Cold 层通过 LLM 摘要生成（后续迭代）
        return {
            "hot": recent,
            "warm": [],
            "cold": "",
        }

    def get_stats(self, ctx: TieredContext) -> Dict[str, Any]:
        """获取压缩统计信息"""
        return {
            "total_messages": ctx.total_messages,
            "hot_count": len(ctx.hot_messages),
            "warm_count": len(ctx.warm_summaries),
            "has_cold": ctx.cold_narrative is not None,
            "tokens_saved": ctx.total_tokens_saved,
            "compression_ratio": (
                ctx.total_tokens_saved / max(1, ctx.total_messages * 200) * 100
            )
        }


# 全局压缩器实例
context_compressor = ContextCompressor()
