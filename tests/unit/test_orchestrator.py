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
    async def test_other_message_routes_to_memory_ops(self, orchestrator):
        """日常咨询进入确权知识检索，不冒充专家 Persona。"""
        payload = {
            "msg_id": "test_002",
            "trace_id": "trace_routine",
            "from_user": "worker_002",
            "content": "今天天气怎么样？",
        }

        def get_skill(name):
            if name == "router":
                skill = MagicMock()
                skill.run = AsyncMock(
                    return_value=SkillOutput(
                        success=True,
                        structured_data={
                            "intent": "other",
                            "severity": "P3",
                            "confidence": 0.9,
                        },
                        action_taken="router_routed",
                    )
                )
                return skill
            return None

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(
                orchestrator,
                "_execute_agent",
                new_callable=AsyncMock,
                return_value=SkillOutput(
                    success=True,
                    reply_text="知识库暂无相关营业时间，请咨询值班经理。",
                    structured_data={"references": []},
                    action_taken="rag_experience_advice",
                ),
            ) as execute_agent:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    result = await orchestrator.process(payload)

        assert result["status"] == "processed"
        assert result["route"].get("intent") == "other"
        assert result["route"].get("target_agent") == "memory_ops"
        assert execute_agent.await_args.args[0]["target_agent"] == "memory_ops"
        assert all(
            step["agent_id"] != "Persona"
            for step in result["agent_trace"]
        )

    @pytest.mark.asyncio
    async def test_router_unavailable_fails_closed_without_default_agent(self, orchestrator):
        """Router 不可用时失败关闭，不调用默认 Agent。"""
        payload = {
            "msg_id": "test_003",
            "trace_id": "trace_fail",
            "from_user": "worker_003",
            "content": "测试路由失败",
        }

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_execute_agent", new_callable=AsyncMock) as execute_agent:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", return_value=None):
                    result = await orchestrator.process(payload)

        assert result["status"] == "failed"
        assert result["route"].get("status") == "failed"
        assert result["route"].get("target_agent") == "router"
        execute_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_agent_output_is_reported_as_failed_run(self, orchestrator):
        payload = {
            "msg_id": "test_agent_failure",
            "trace_id": "trace_agent_failure",
            "from_user": "worker_failure",
            "content": "东门游客晕倒",
        }
        route = {
            "status": "routed",
            "target_agent": "commander",
            "priority": "P3",
        }
        failed_output = SkillOutput(
            success=False,
            reply_text="系统正忙，请稍后再试。",
            error_msg="DeepSeek authentication failed",
            action_taken="fatal_error_fallback",
        )

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_route", new_callable=AsyncMock, return_value=route):
                with patch.object(orchestrator, "_execute_agent", new_callable=AsyncMock, return_value=failed_output):
                    result = await orchestrator.process(payload)

        assert result["status"] == "failed"
        assert result["error"] == "DeepSeek authentication failed"
        assert result["reply_text"] == "系统正忙，请稍后再试。"

    @pytest.mark.asyncio
    async def test_router_skill_failure_stops_before_default_agent_execution(self, orchestrator):
        payload = {
            "msg_id": "test_router_skill_failure",
            "trace_id": "trace_router_skill_failure",
            "from_user": "worker_failure",
            "content": "西侧扶梯出现焦糊味",
        }
        router_failure = SkillOutput(
            success=False,
            reply_text="系统正忙，请稍后再试。",
            error_msg="DeepSeek authentication failed",
            action_taken="fatal_error_fallback",
        )

        def get_skill(name):
            if name == "router":
                skill = MagicMock()
                skill.run = AsyncMock(return_value=router_failure)
                return skill
            return None

        with patch.object(orchestrator, "_save_message", new_callable=AsyncMock):
            with patch.object(orchestrator, "_execute_agent", new_callable=AsyncMock) as execute_agent:
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    result = await orchestrator.process(payload)

        assert result["status"] == "failed"
        assert result["route"]["target_agent"] == "router"
        assert result["error"] == "DeepSeek authentication failed"
        execute_agent.assert_not_called()


class TestSLARecording:

    @staticmethod
    def _successful_route(priority):
        return {
            "status": "routed",
            "target_agent": "memory_ops",
            "priority": priority,
            "intent": "knowledge_query",
            "agent_trace": [],
        }

    @staticmethod
    def _successful_agent_output():
        return SkillOutput(
            success=True,
            reply_text="处理完成",
            action_taken="rag_experience_advice",
        )

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
            with patch.object(
                orchestrator,
                "_route",
                new_callable=AsyncMock,
                return_value=self._successful_route("P0"),
            ):
                with patch.object(
                    orchestrator,
                    "_execute_agent",
                    new_callable=AsyncMock,
                    return_value=self._successful_agent_output(),
                ):
                    with patch.object(
                        orchestrator,
                        "_save_live_event",
                        new_callable=AsyncMock,
                        return_value=None,
                    ):
                        with patch.object(
                            orchestrator,
                            "_update_sla_response",
                            new_callable=AsyncMock,
                        ) as mock_sla:
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
            with patch.object(
                orchestrator,
                "_route",
                new_callable=AsyncMock,
                return_value=self._successful_route("P1"),
            ):
                with patch.object(
                    orchestrator,
                    "_execute_agent",
                    new_callable=AsyncMock,
                    return_value=self._successful_agent_output(),
                ):
                    with patch.object(
                        orchestrator,
                        "_save_live_event",
                        new_callable=AsyncMock,
                        return_value=None,
                    ):
                        with patch.object(
                            orchestrator,
                            "_update_sla_response",
                            new_callable=AsyncMock,
                        ) as mock_sla:
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
            with patch.object(
                orchestrator,
                "_route",
                new_callable=AsyncMock,
                return_value=self._successful_route("P3"),
            ):
                with patch.object(
                    orchestrator,
                    "_execute_agent",
                    new_callable=AsyncMock,
                    return_value=self._successful_agent_output(),
                ):
                    with patch.object(
                        orchestrator,
                        "_save_live_event",
                        new_callable=AsyncMock,
                        return_value=None,
                    ):
                        with patch.object(
                            orchestrator,
                            "_update_sla_response",
                            new_callable=AsyncMock,
                        ) as mock_sla:
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
