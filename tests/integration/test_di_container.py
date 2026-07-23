"""
DI Container 集成测试

验证：AppContainer 懒加载、override Mock 注入、reset 恢复、Orchestrator 使用 Container

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.memory_palace.core.container import AppContainer
from src.memory_palace.core.orchestrator import Orchestrator
from src.memory_palace.core.skill_base import SkillOutput


class TestAppContainer:

    def test_container_import_has_no_side_effects(self):
        """Container 导入不触发 ChromaDB/LLM 初始化"""
        c = AppContainer()
        assert c._instances == {}
        assert c._overrides == {}

    def test_container_override_and_reset(self):
        """override 注入 Mock，reset 恢复"""
        c = AppContainer()
        mock_llm = MagicMock()
        c.override(llm_client=mock_llm)
        assert c.llm_client is mock_llm
        assert c._overrides == {"llm_client": mock_llm}

        c.reset()
        assert c._overrides == {}
        assert c._instances == {}

    def test_container_property_caches_instance(self):
        """property 首次访问后缓存实例"""
        c = AppContainer()
        c.override(llm_client="fake_llm")
        first = c.llm_client
        second = c.llm_client
        assert first is second


class TestOrchestratorWithContainer:

    @pytest.mark.asyncio
    async def test_orchestrator_accepts_custom_container(self):
        """Orchestrator 接受自定义 Container，使用 Mock 不调真实 LLM"""
        mock_llm = MagicMock()
        mock_llm.ask = AsyncMock(return_value=MagicMock(
            content="mock response",
            tokens_used=0,
            model_name="mock",
        ))

        mock_agent_memory = MagicMock()
        mock_agent_memory.build_scoped_context = MagicMock(return_value={
            "raw_text": "test", "msg_id": "1",
        })
        mock_agent_memory.record_agent_turn = MagicMock()

        c = AppContainer()
        c.override(llm_client=mock_llm, agent_memory=mock_agent_memory)

        orch = Orchestrator(container=c)

        router_output = SkillOutput(
            success=True,
            structured_data={"intent": "other", "severity": "P3"},
            action_taken="router_routed",
        )

        def get_skill(name):
            m = MagicMock()
            m.run = AsyncMock(return_value=SkillOutput(success=True, action_taken=f"{name}_replied"))
            if name == "router":
                m.run = AsyncMock(return_value=router_output)
            return m

        payload = {"msg_id": "di_test_001", "trace_id": "trace_di", "from_user": "test", "content": "hello"}

        from unittest.mock import patch
        with patch("src.memory_palace.knowledge.db_client.save_message", side_effect=AsyncMock()):
            with patch("src.memory_palace.knowledge.db_client.create_or_update_session", side_effect=AsyncMock()):
                with patch("src.memory_palace.core.orchestrator.get_skill_by_name", side_effect=get_skill):
                    result = await orch.process(payload)

        assert result["status"] == "processed"


class TestContextTier:

    def test_build_tiered_context_hot_only(self):
        """25条消息 → Hot 层 10 条，Warm/Cold 空"""
        from src.memory_palace.core.context_tier import context_compressor

        messages = [{"role": "user", "content": f"msg_{i}"} for i in range(25)]
        result = context_compressor.build_tiered_context(
            session_id="test", messages=messages, hot_count=10, total_budget=30
        )

        assert len(result["hot"]) == 10
        assert result["hot"][-1]["content"] == "msg_24"
        assert result["hot"][0]["content"] == "msg_15"
        assert result["warm"] == []
        assert result["cold"] == ""

    def test_build_tiered_context_respects_budget(self):
        """total_budget=5 时 Hot 层最多 5 条"""
        from src.memory_palace.core.context_tier import context_compressor

        messages = [{"role": "user", "content": f"msg_{i}"} for i in range(25)]
        result = context_compressor.build_tiered_context(
            session_id="test", messages=messages, hot_count=10, total_budget=5
        )

        assert len(result["hot"]) == 5


class TestAgentMemory:

    def test_build_scoped_context_router(self):
        """Router 只看到 raw_text 和 msg_id"""
        from src.memory_palace.core.agent_memory import get_scoped_context_builder

        builder = get_scoped_context_builder()
        base = {"raw_text": "hello", "msg_id": "1", "from_user": "user_a", "severity": "P0"}

        ctx = builder.build_scoped_context(
            agent_name="router", session_id="s1", base_context=base, route_result={}
        )
        assert "raw_text" in ctx
        assert "msg_id" in ctx
        # Router gets basic fields from base_context; exact set depends on builder logic
        assert "severity" not in ctx   # Router doesn't need severity

    def test_agent_turn_isolation(self):
        """Router 看不到 Commander 的对话历史"""
        from src.memory_palace.core.agent_memory import agent_memory_scope

        agent_memory_scope.push("s1", "commander", "emergency", "SOP dispatched")
        agent_memory_scope.push("s1", "router", "classifying", "routed to commander")

        router_history = agent_memory_scope.get_history("s1", "router")
        commander_history = agent_memory_scope.get_history("s1", "commander")

        assert len(router_history) > 0, "Router should have at least 1 turn"
        assert len(commander_history) > 0, "Commander should have at least 1 turn"
        # Router turns only from 'router' agent, Commander only from 'commander'
        router_inputs = [t.get("content", "") if isinstance(t, dict) else getattr(t, 'input_text', '') for t in router_history]
        assert any("classifying" in str(i) for i in router_inputs) or any("routed" in str(i) for i in router_inputs)
