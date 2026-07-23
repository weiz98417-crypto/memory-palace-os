"""
路由分发集成测试 (Routing Integration Test)

验证：非紧急消息通过 Router 正常路由到 Persona/PersonaExtract

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


class TestRouting:

    @pytest.mark.asyncio
    async def test_chitchat_routes_to_persona(self):
        """闲聊消息 → Router 识别为 chitchat → 路由到 Persona"""

        router_output = SkillOutput(
            success=True,
            structured_data={
                "intent": "chitchat",
                "severity": "P3",
                "confidence": 0.9,
            },
            action_taken="router_routed",
        )

        persona_output = SkillOutput(
            success=True,
            reply_text="你好！最近景区人挺多的，有什么需要帮忙的？",
            action_taken="persona_replied",
        )

        def get_skill(name):
            m = MagicMock()
            if name == "context_trigger":
                m.run = AsyncMock(return_value=SkillOutput(
                    success=True,
                    structured_data={"should_trigger": False, "excluded": False},
                    action_taken="passive",
                ))
            elif name == "router":
                m.run = AsyncMock(return_value=router_output)
            elif name == "persona":
                m.run = AsyncMock(return_value=persona_output)
            else:
                m.run = AsyncMock(return_value=SkillOutput(success=True, action_taken="other"))
            return m

        payload = {
            "msg_id": "route_chat_001",
            "trace_id": "trace_chat",
            "from_user": "tourist_a",
            "content": "请问景区几点关门？",
        }

        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    orch = Orchestrator()
                    result = await orch.process(payload)

        assert result["status"] == "processed"
        assert result["route"]["target_agent"] == "persona", f"闲聊应路由到 Persona，实际: {result['route']['target_agent']}"

    @pytest.mark.asyncio
    async def test_default_route_falls_back_to_persona_extract(self):
        """路由失败时 _default_route() 返回 persona_extract"""

        orch = Orchestrator()
        default = await orch._default_route({"from_user": "unknown", "content": "..."})

        assert default["target_agent"] == "persona_extract", f"默认路由应为 persona_extract，实际: {default['target_agent']}"
        assert default["status"] == "routed"
