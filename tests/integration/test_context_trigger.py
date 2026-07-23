"""
情境触发集成测试 (Context Trigger Integration Test)

验证：Stage1 关键词命中 → ContextTrigger 判断 → 路由到 Commander

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


class TestContextTrigger:

    @pytest.mark.asyncio
    async def test_emergency_keyword_routes_to_commander(self):
        """紧急关键词命中 → 直接路由到 Commander，跳过 Router"""

        ct_output = SkillOutput(
            success=True,
            structured_data={
                "stage": "stage2",
                "should_trigger": True,
                "severity": "P0",
                "event_type": "医疗急救",
                "confidence": 0.95,
                "stage1_result": {"hit_keywords": ["晕倒", "游客"]},
            },
            action_taken="context_trigger_fired",
        )

        commander_output = SkillOutput(
            success=True,
            reply_text="【P0 应急指令】已通知急救团队。",
            action_taken="commander_dispatched",
        )

        def get_skill(name):
            m = MagicMock()
            if name == "context_trigger":
                m.run = AsyncMock(return_value=ct_output)
            elif name == "commander":
                m.run = AsyncMock(return_value=commander_output)
            else:
                m.run = AsyncMock(return_value=SkillOutput(success=True, action_taken="other"))
            return m

        payload = {
            "msg_id": "ct_p0_001",
            "trace_id": "trace_ct",
            "from_user": "on_duty_staff",
            "content": "B区有个游客晕倒了，快来人！",
            "timestamp": 1234567890.0,
        }

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.knowledge.db_client.update_sla_response", side_effect=AsyncMock()):
                    with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                        orch = Orchestrator()
                        result = await orch.process(payload)

        assert result["status"] == "processed"
        route = result["route"]
        assert route["target_agent"] == "commander", f"紧急事件应路由到 Commander，实际: {route['target_agent']}"
        assert route["severity"] == "P0"
        assert "context_trigger_data" in route

    @pytest.mark.asyncio
    async def test_normal_message_goes_to_router(self):
        """非紧急消息：ContextTrigger 不触发 → 走 Router 正常路由"""

        ct_output = SkillOutput(
            success=True,
            structured_data={
                "stage": "stage1",
                "should_trigger": False,
                "excluded": False,
            },
            action_taken="context_trigger_passive",
        )

        router_output = SkillOutput(
            success=True,
            structured_data={
                "intent": "other",
                "severity": "P3",
                "confidence": 0.8,
            },
            action_taken="router_routed",
        )

        def get_skill(name):
            m = MagicMock()
            if name == "context_trigger":
                m.run = AsyncMock(return_value=ct_output)
            elif name == "router":
                m.run = AsyncMock(return_value=router_output)
            else:
                m.run = AsyncMock(return_value=SkillOutput(success=True, action_taken="persona_replied"))
            return m

        payload = {
            "msg_id": "ct_normal_001",
            "trace_id": "trace_normal",
            "from_user": "staff_a",
            "content": "今天天气不错，适合带团。",
        }

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    orch = Orchestrator()
                    result = await orch.process(payload)

        assert result["status"] == "processed"
        assert result["route"]["target_agent"] != "commander", "非紧急消息不应路由到 Commander"
