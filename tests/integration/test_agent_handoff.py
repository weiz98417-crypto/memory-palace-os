"""
智能体转办集成测试 (Integration Test for Agent Handoff)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput

@pytest.mark.asyncio
async def test_router_to_commander_flow():
    """
    用户报告紧急事件 → Router → Commander。
    """
    mock_payload = {
        "msg_id": "test_handoff_001",
        "trace_id": "trace_handoff",
        "from_user": "worker_001",
        "content": "快来人！有人晕倒了，呼吸微弱！",
    }

    with patch("src.memory_palace.core.orchestrator.get_skill_by_name") as mock_get:
        router_output = SkillOutput(
            success=True,
            structured_data={"intent": "emergency_dispatch", "severity": "P0"},
            reply_text="正在接入指挥中心...",
        )
        router = MagicMock()
        router.run = AsyncMock(return_value=router_output)

        commander_output = SkillOutput(
            success=True,
            reply_text="收到！1.拨打120 2.找AED 3.维持秩序",
        )
        commander = MagicMock()
        commander.run = AsyncMock(return_value=commander_output)

        def get_skill(name):
            if name == "context_trigger":
                return None
            if name == "router":
                return router
            if name == "commander":
                return commander
            return None

        mock_get.side_effect = get_skill

        with patch.object(Orchestrator, "_save_message", new_callable=AsyncMock):
            with patch("src.memory_palace.tools.wechat_client.get_wechat_client",
                       return_value=MagicMock(send_text=AsyncMock(return_value=True))):
                orchestrator = Orchestrator()
                result = await orchestrator.dispatch(mock_payload)

                assert result["status"] == "processed"
                assert result["route"].get("target_agent") == "commander"
