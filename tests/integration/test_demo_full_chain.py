"""
Demo 模式全链路集成测试 (Demo Full Chain Test)

验证：DEMO_MODE=true 下核心链路端到端可运行。
Mock 所有外部 IO（LLM、企微、短信），仅验证编排逻辑。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.queue_worker import MessageQueueWorker
from src.memory_palace.core.skill_base import SkillOutput


class TestDemoFullChain:

    @pytest.mark.asyncio
    async def test_demo_full_chain_from_enqueue_to_agent_response(self):
        """
        Demo 模式全链路：
        消息入队 → 消费 → ContextTrigger → Router → Agent → 返回结果
        """
        queue = asyncio.Queue(maxsize=100)

        ct_output = SkillOutput(
            success=True,
            structured_data={
                "stage": "stage1",
                "should_trigger": False,
                "excluded": False,
            },
            action_taken="passive",
        )

        router_output = SkillOutput(
            success=True,
            structured_data={"intent": "other", "severity": "P3"},
            action_taken="router_routed",
        )

        agent_output = SkillOutput(
            success=True,
            reply_text="收到您的消息，这是 Demo 模式的自动回复。",
            action_taken="persona_demo_reply",
        )

        def get_skill(name):
            m = MagicMock()
            if name == "context_trigger":
                m.run = AsyncMock(return_value=ct_output)
            elif name == "router":
                m.run = AsyncMock(return_value=router_output)
            elif name == "persona":
                m.run = AsyncMock(return_value=agent_output)
            else:
                m.run = AsyncMock(return_value=SkillOutput(success=True, action_taken="other"))
            return m

        async def mock_save(payload):
            pass

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=mock_save):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    orch = Orchestrator()
                    worker = MessageQueueWorker(queue=queue, concurrency=1, orchestrator=orch)
                    consumer = asyncio.create_task(worker.start())

                    await queue.put({
                        "msg_id": "demo_001",
                        "trace_id": "trace_demo",
                        "from_user": "demo_user",
                        "msg_type": "text",
                        "content": "你好，我是测试消息",
                        "timestamp": 1234567890.0,
                    })

                    await asyncio.sleep(0.5)
                    worker.stop()
                    consumer.cancel()
                    try:
                        await consumer
                    except asyncio.CancelledError:
                        pass

        assert queue.empty(), "Demo 模式下消息应被正常消费"

    @pytest.mark.asyncio
    async def test_demo_mode_orchestrator_no_llm(self):
        """Demo 模式下 Orchestrator 不依赖真实 LLM"""
        payload = {
            "msg_id": "demo_no_llm_001",
            "trace_id": "trace_no_llm",
            "from_user": "test_user",
            "content": "测试消息",
        }

        agent_output = SkillOutput(
            success=True,
            reply_text="Demo 响应",
            action_taken="demo",
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

        assert result["status"] == "processed", "Demo 模式应正常处理"
        assert result["agent_result"] is not None, "应有 Agent 返回结果"
