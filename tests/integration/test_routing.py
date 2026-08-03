"""
路由分发集成测试 (Routing Integration Test)

验证：通用对话不会冒充专家 Persona，路由失败不会误启动经验萃取

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


class TestRouting:

    @pytest.mark.asyncio
    async def test_chitchat_never_invokes_persona(self):
        """闲聊由统一助手直接回应，不调用专家 Persona。"""

        router_output = SkillOutput(
            success=True,
            structured_data={
                "intent": "chitchat",
                "severity": "P3",
                "confidence": 0.9,
            },
            action_taken="router_routed",
        )

        def get_skill(name):
            if name == "context_trigger":
                m = MagicMock()
                m.run = AsyncMock(return_value=SkillOutput(
                    success=True,
                    structured_data={"should_trigger": False, "excluded": False},
                    action_taken="passive",
                ))
                return m
            if name == "router":
                m = MagicMock()
                m.run = AsyncMock(return_value=router_output)
                return m
            return None

        payload = {
            "msg_id": "route_chat_001",
            "trace_id": "trace_chat",
            "from_user": "tourist_a",
            "content": "请问景区几点关门？",
        }

        orch = Orchestrator()
        with patch.object(orch, "_save_message", new_callable=AsyncMock):
            with patch.object(orch, "_execute_agent", new_callable=AsyncMock) as execute_agent:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    result = await orch.process(payload)

        assert result["status"] == "processed"
        assert result["route"]["status"] == "responded"
        assert result["route"]["target_agent"] is None
        assert "企业运营助手" in result["reply_text"]
        execute_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_route_fails_closed_without_persona_extract(self):
        """路由不可用时返回可恢复失败，不启动经验萃取。"""

        orch = Orchestrator()
        default = await orch._default_route({"from_user": "unknown", "content": "..."})

        assert default["target_agent"] == "router"
        assert default["status"] == "failed"
        assert "未能判断" in default["reply_text"]
