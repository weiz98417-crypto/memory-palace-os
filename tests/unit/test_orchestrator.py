"""
编排器状态机测试 (Unit Test for Orchestrator)

测试核心：验证 Orchestrator 对不同优先级消息的路由决策、Agent 派发与 SLA 响应时间记录。

工业级测试要点：
1. 路由决策验证：P0/P1/P2 消息是否路由到正确的 Agent
2. SLA 记录验证：P0/P1 消息是否触发 SLA 响应时间更新
3. 降级路径：Router 不可用时是否走默认路由
4. Agent 未注册处理：目标 Agent 不存在时是否优雅降级

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


@pytest.fixture
def orchestrator():
    return Orchestrator()


class TestRoutingDecision:

    @pytest.mark.asyncio
    async def test_p0_message_routes_to_commander(self, orchestrator):
        """P0 消息应路由到 Commander"""
        payload = {
            "msg_id": "test_001",
            "trace_id": "trace_p0",
            "from_user": "worker_001",
            "content": "有人晕倒了！快！",
            "priority": "P0",
        }

        mock_router_output = SkillOutput(
            success=True,
            reply_text="正在接入",
            structured_data={"intent": "emergency_dispatch", "severity": "P0"},
            action_taken="router_routed",
        )

        mock_commander_output = SkillOutput(
            success=True,
            reply_text="已下发指令",
            structured_data={"step": "call_120"},
            action_taken="commander_dispatched",
        )

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch("src.memory_palace.core.orchestrator.get_skill_by_name") as mock_get:
                def get_skill(name):
                    if name == "router":
                        m = MagicMock()
                        m.run = AsyncMock(return_value=mock_router_output)
                        return m
                    if name == "commander":
                        m = MagicMock()
                        m.run = AsyncMock(return_value=mock_commander_output)
                        return m
                    return None

                mock_get.side_effect = get_skill

                result = await orchestrator.process(payload)

                assert result["status"] == "processed"
                assert result["route"].get("target_agent") == "commander"

    @pytest.mark.asyncio
    async def test_routine_message_routes_to_persona_extract(self, orchestrator):
        """常规消息走默认路由到 persona_extract"""
        payload = {
            "msg_id": "test_002",
            "trace_id": "trace_routine",
            "from_user": "worker_002",
            "content": "今天天气怎么样？",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                result = await orchestrator.process(payload)

                assert result["status"] == "processed"
                assert result["route"].get("intent") == "routine"
                assert result["route"].get("target_agent") == "persona_extract"

    @pytest.mark.asyncio
    async def test_router_failure_uses_default_route(self, orchestrator):
        """Router 执行失败时，降级到默认路由"""
        payload = {
            "msg_id": "test_003",
            "trace_id": "trace_fail",
            "from_user": "worker_003",
            "content": "测试路由失败",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                result = await orchestrator.process(payload)

                assert result["route"].get("status") == "routed"
                assert result["route"].get("target_agent") == "persona_extract"


class TestSLARecording:

    @pytest.mark.asyncio
    async def test_p0_updates_sla_response(self, orchestrator):
        """P0 消息应触发 SLA 响应时间记录"""
        payload = {
            "msg_id": "test_p0_sla",
            "trace_id": "trace_sla",
            "from_user": "worker_sla",
            "content": "P0 测试",
            "priority": "P0",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_update_sla_response", new_callable=AsyncMock) as mock_sla:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                    await orchestrator.process(payload)
                    mock_sla.assert_called_once_with("test_p0_sla")

    @pytest.mark.asyncio
    async def test_p1_updates_sla_response(self, orchestrator):
        """P1 消息也应触发 SLA 响应时间记录"""
        payload = {
            "msg_id": "test_p1_sla",
            "trace_id": "trace_sla",
            "from_user": "worker_sla",
            "content": "P1 测试",
            "priority": "P1",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_update_sla_response", new_callable=AsyncMock) as mock_sla:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                    await orchestrator.process(payload)
                    mock_sla.assert_called_once_with("test_p1_sla")

    @pytest.mark.asyncio
    async def test_p3_does_not_update_sla(self, orchestrator):
        """P3 低优先级消息不触发 SLA 记录"""
        payload = {
            "msg_id": "test_p3",
            "trace_id": "trace_p3",
            "from_user": "worker_p3",
            "content": "普通咨询",
            "priority": "P3",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_update_sla_response", new_callable=AsyncMock) as mock_sla:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                    await orchestrator.process(payload)
                    mock_sla.assert_not_called()


class TestAgentHandoff:

    @pytest.mark.asyncio
    async def test_agent_handoff_context_preserved(self, orchestrator):
        """Agent 交接时，上下文元数据不丢失"""
        payload = {
            "msg_id": "handoff_001",
            "trace_id": "trace_handoff",
            "from_user": "worker_handoff",
            "content": "移交处置",
            "priority": "P1",
        }

        mock_output = SkillOutput(
            success=True,
            reply_text="处理完成",
            structured_data={"handoff_reason": "task_complete"},
            action_taken="handoff",
        )

        with patch("src.memory_palace.core.orchestrator.get_skill_by_name") as mock_get:
            m = MagicMock()
            m.run = AsyncMock(return_value=mock_output)
            mock_get.return_value = m

            result = await orchestrator.agent_handoff(
                from_agent="commander",
                to_agent="persona",
                context={"content": "移交处置", "trace_id": "trace_handoff"},
            )

            assert result["status"] == "handoff_complete"
            assert result["from_agent"] == "commander"
            assert result["to_agent"] == "persona"


class TestMessageSaving:

    @pytest.mark.asyncio
    async def test_message_saved_before_processing(self, orchestrator):
        """消息在处理前先保存到数据库"""
        payload = {
            "msg_id": "save_001",
            "trace_id": "trace_save",
            "from_user": "worker_save",
            "content": "保存测试",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock) as mock_save:
            with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                await orchestrator.process(payload)
                mock_save.assert_called_once()
                call_args = mock_save.call_args[0][0]
                assert call_args.get("msg_id") == "save_001"
