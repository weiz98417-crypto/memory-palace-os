"""
TodoWrite 任务分解 Skill 单元测试

覆盖: 输入校验、LLM 返回格式错误处理、消毒集成

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.memory_palace.skills.todo.skill import TodoWriteSkill
from src.memory_palace.core.skill_base import SkillValidationError, SkillOutput


class TestTodoWriteSkill:

    @pytest.fixture
    def skill(self):
        return TodoWriteSkill()

    # ── 10.1 输入校验 ──────────────────────────────────────────────────────

    def test_missing_goal_raises_validation_error(self, skill):
        """缺少 goal 字段应抛出 SkillValidationError"""
        with pytest.raises(SkillValidationError, match="goal"):
            skill._validate_context({"session_id": "s1"})

    def test_missing_session_id_raises_validation_error(self, skill):
        """缺少 session_id 字段应抛出 SkillValidationError"""
        with pytest.raises(SkillValidationError, match="session_id"):
            skill._validate_context({"goal": "完成代码审查"})

    def test_valid_context_passes(self, skill):
        """完整上下文通过校验"""
        result = skill._validate_context({
            "goal": "修复所有 LLM 信任边界问题",
            "session_id": "session-001",
        })
        assert result is True

    # ── 10.2 实例化与配置 ──────────────────────────────────────────────────

    def test_skill_instantiation(self, skill):
        """Skill 正常实例化"""
        assert skill.skill_name == "todo_write"
        assert skill.config is not None

    def test_default_prompt_is_defined(self, skill):
        """默认分解 prompt 已定义"""
        assert "任务分解专家" in skill.DEFAULT_DECOMPOSITION_PROMPT
        assert "{goal}" in skill.DEFAULT_DECOMPOSITION_PROMPT

    # ── 10.3 执行流程 (Mock LLM) ─────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_llm_response(self, skill):
        """LLM 返回空内容时返回 success=False"""
        mock_response = MagicMock()
        mock_response.content = ""
        mock_response.tokens_used = 0

        with patch.object(skill, 'model_name', 'test-model'):
            with patch(
                "src.memory_palace.skills.todo.skill.llm_client.ask",
                new_callable=AsyncMock,
                return_value=mock_response,
            ):
                with patch(
                    "src.memory_palace.skills.todo.skill.llm_client.parse_json",
                    new_callable=AsyncMock,
                    return_value={},
                ):
                    output = await skill.run(
                        {"goal": "test", "session_id": "s1"},
                        trace_id="t1",
                    )
                    assert output.success is False
                    assert "格式错误" in output.error_msg

    @pytest.mark.asyncio
    async def test_non_list_llm_response(self, skill):
        """LLM 返回非列表 JSON 时返回 success=False"""
        mock_response = MagicMock()
        mock_response.content = '{"key": "value"}'
        mock_response.tokens_used = 10

        with patch.object(skill, 'model_name', 'test-model'):
            with patch(
                "src.memory_palace.skills.todo.skill.llm_client.ask",
                new_callable=AsyncMock,
                return_value=mock_response,
            ):
                with patch(
                    "src.memory_palace.skills.todo.skill.llm_client.parse_json",
                    new_callable=AsyncMock,
                    return_value={"not": "a list"},
                ):
                    output = await skill.run(
                        {"goal": "test", "session_id": "s1"},
                        trace_id="t2",
                    )
                    assert output.success is False
                    assert "格式错误" in output.error_msg

    @pytest.mark.asyncio
    async def test_llm_exception_caught(self, skill):
        """LLM 调用异常时返回 success=False"""
        with patch.object(skill, 'model_name', 'test-model'):
            with patch(
                "src.memory_palace.skills.todo.skill.llm_client.ask",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM timeout"),
            ):
                output = await skill.run(
                    {"goal": "test", "session_id": "s1"},
                    trace_id="t3",
                )
                assert output.success is False
                assert "失败" in output.error_msg
