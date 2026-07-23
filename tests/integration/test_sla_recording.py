"""
SLA 记录集成测试 (SLA Recording Test)

验证：P0/P1 事件触发后 SLA 响应时间正确写入数据库

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


class TestSLARecording:

    @pytest.mark.asyncio
    async def test_p0_event_triggers_sla_update(self):
        """P0 事件必须触发 SLA 响应时间记录"""
        ct_output = SkillOutput(
            success=True,
            structured_data={
                "stage": "stage2",
                "should_trigger": True,
                "severity": "P0",
                "event_type": "设施故障",
                "confidence": 0.92,
                "stage1_result": {"hit_keywords": ["过山车", "停了"]},
            },
            action_taken="context_trigger_fired",
        )

        commander_output = SkillOutput(
            success=True,
            reply_text="【P0 指令】已通知运维团队。",
            action_taken="commander_dispatched",
        )

        sla_called = {"called": False}

        async def mock_update_sla(msg_id):
            sla_called["called"] = True

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
            "msg_id": "sla_p0_001",
            "trace_id": "trace_sla",
            "from_user": "ops_staff",
            "content": "过山车突然停了，上面有游客！",
        }

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.knowledge.db_client.update_sla_response", side_effect=mock_update_sla):
                    with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                        orch = Orchestrator()
                        result = await orch.process(payload)

        assert result["status"] == "processed"
        assert sla_called["called"], "P0 事件必须触发 SLA 响应时间记录"

    @pytest.mark.asyncio
    async def test_p3_message_no_sla_update(self):
        """P3 低优先级消息不应触发 SLA 记录"""
        ct_output = SkillOutput(
            success=True,
            structured_data={"should_trigger": False, "excluded": False},
            action_taken="passive",
        )

        router_output = SkillOutput(
            success=True,
            structured_data={"intent": "chitchat", "severity": "P3", "confidence": 0.9},
            action_taken="router_routed",
        )

        sla_called = {"called": False}

        async def mock_update_sla(msg_id):
            sla_called["called"] = True

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
            "msg_id": "sla_p3_001",
            "trace_id": "trace_p3",
            "from_user": "staff_b",
            "content": "今天天气不错",
        }

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.knowledge.db_client.update_sla_response", side_effect=mock_update_sla):
                    with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                        orch = Orchestrator()
                        result = await orch.process(payload)

        assert result["status"] == "processed"
        assert not sla_called["called"], "P3 低优先级消息不应触发 SLA 记录"
