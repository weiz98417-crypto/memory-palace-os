"""
核心消息处理链路集成测试 (Core Pipeline Integration Test)

验证：消息入队 → 消费者取出 → Orchestrator 路由 → Agent 执行

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.queue_worker import MessageQueueWorker
from src.memory_palace.core.skill_base import SkillOutput


class TestCorePipeline:

    @pytest.mark.asyncio
    async def test_message_enqueue_dequeue_dispatch(self):
        """消息入队后消费者取出并派发给 Orchestrator"""
        queue = asyncio.Queue(maxsize=100)

        router_output = SkillOutput(
            success=True,
            structured_data={"intent": "other", "severity": "P3"},
            action_taken="router_routed",
        )

        agent_output = SkillOutput(
            success=True,
            reply_text="你好，有什么可以帮您？",
            action_taken="persona_replied",
        )

        async def mock_save(payload):
            pass

        def get_skill(name):
            m = MagicMock()
            m.run = AsyncMock(return_value=agent_output)
            return m

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=mock_save):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    orch = Orchestrator()
                    worker = MessageQueueWorker(queue=queue, concurrency=1, orchestrator=orch)

                    consumer = asyncio.create_task(worker.start())

                    # 模拟网关入队
                    await queue.put({
                        "msg_id": "test_001",
                        "trace_id": "trace_core",
                        "from_user": "test_user",
                        "msg_type": "text",
                        "content": "你好",
                        "timestamp": 1234567890.0,
                    })

                    # 等待消费
                    await asyncio.sleep(0.5)
                    worker.stop()
                    consumer.cancel()
                    try:
                        await consumer
                    except asyncio.CancelledError:
                        pass

        assert queue.empty(), "消息应被消费"

    @pytest.mark.asyncio
    async def test_orchestrator_process_returns_structured_result(self):
        """Orchestrator.process() 返回正确结构"""
        payload = {
            "msg_id": "test_struct_001",
            "trace_id": "trace_struct",
            "from_user": "user_a",
            "content": "例行巡检报告",
        }

        agent_output = SkillOutput(
            success=True,
            reply_text="收到巡检报告",
            action_taken="persona_replied",
        )

        def get_skill(name):
            m = MagicMock()
            m.run = AsyncMock(return_value=agent_output)
            return m

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    orch = Orchestrator()
                    result = await orch.process(payload)

        assert "status" in result, "结果必须包含 status"
        assert "route" in result, "结果必须包含 route"
        assert "agent_result" in result, "结果必须包含 agent_result"
