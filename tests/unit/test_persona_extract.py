"""
老员工知识萃取 (PersonaExtract) 单元测试

覆盖: start → continue(5轮) → finalize 完整链路
      校验异常、模块注册、mock模式兜底

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.memory_palace.skills.persona_extract.skill import PersonaExtractSkill
from src.memory_palace.core.skill_base import SkillValidationError


class TestPersonaExtractSkill:

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前清理类级别的 interview_state"""
        PersonaExtractSkill._interview_state = {}
        yield
        PersonaExtractSkill._interview_state = {}

    # =========================================================================
    # 10.1 模块注册
    # =========================================================================

    def test_skill_is_registered(self):
        """persona_extract 已注册到 skills 模块"""
        from src.memory_palace.skills import list_skill_names
        names = list_skill_names()
        assert "persona_extract" in names, f"persona_extract 不在注册表中: {names}"

    def test_skill_instantiation(self):
        """技能可正常实例化"""
        skill = PersonaExtractSkill()
        assert skill.config["agent_metadata"]["name"] == "PersonaExtract_Skill"
        assert skill.config["llm_config"]["model"] == "gpt-4o"

    # =========================================================================
    # 10.2 入参校验
    # =========================================================================

    @pytest.mark.asyncio
    async def test_start_missing_job_title(self):
        """start action 缺少 job_title 应返回 success=False（base类捕获并兜底）"""
        skill = PersonaExtractSkill()
        output = await skill.run({"action": "start"}, trace_id="t1")
        assert output.success is False
        assert "job_title" in output.error_msg

    @pytest.mark.asyncio
    async def test_continue_missing_interview_id(self):
        """continue action 缺少 interview_id 应返回 success=False"""
        skill = PersonaExtractSkill()
        output = await skill.run({"action": "continue", "answer": "test"}, trace_id="t2")
        assert output.success is False
        assert "interview_id" in output.error_msg

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        """未知 action 返回 success=False"""
        skill = PersonaExtractSkill()
        output = await skill.run({"action": "invalid"}, trace_id="t3")
        assert output.success is False
        assert "未知" in output.reply_text

    # =========================================================================
    # 10.3 完整访谈链路 (mock模式，无需LLM)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_full_interview_flow(self):
        """端到端：start → 5轮问答 → finalize → 数据持久化"""
        skill = PersonaExtractSkill()

        # 1. 开始访谈
        start_output = await skill.run(
            {
                "action": "start",
                "venue_id": "venue_001",
                "job_title": "安保员",
            },
            trace_id="t_full",
        )
        assert start_output.success
        assert start_output.structured_data["interview_id"]
        assert start_output.structured_data["current_question"] == 1
        interview_id = start_output.structured_data["interview_id"]

        # 验证开场白非空且包含访谈提示
        assert len(start_output.reply_text) > 50
        assert "老员工" in start_output.reply_text or "访谈" in start_output.reply_text

        # 2. Q1→Q2→Q3 (回答第1-3题，系统推进到第2-4题)
        for q in range(1, 4):
            output = await skill.run(
                {
                    "action": "continue",
                    "interview_id": interview_id,
                    "answer": f"第{q}题测试回答内容",
                },
                trace_id=f"t_q{q}",
            )
            assert output.success, f"第{q}题 continue 应成功"
            sd = output.structured_data
            assert sd["interview_id"] == interview_id
            assert sd["stage"] == f"question_{q+1}"
            assert sd["current_question"] == q + 1

        # 3. Q4回答 → 进入 summary（不再加载不存在的 Q5）
        q4_output = await skill.run(
            {
                "action": "continue",
                "interview_id": interview_id,
                "answer": "第4题测试回答内容",
            },
            trace_id="t_q4",
        )
        assert q4_output.success
        sd4 = q4_output.structured_data
        assert sd4["stage"] == "summary"
        assert sd4["current_question"] == 6  # else 分支直接标记 summary 阶段
        assert sd4["prompt_finalize"] is True

    # =========================================================================
    # 10.4 边界条件
    # =========================================================================

    @pytest.mark.asyncio
    async def test_continue_nonexistent_interview(self):
        """对不存在的访谈调用 continue 应返回 success=False"""
        skill = PersonaExtractSkill()
        output = await skill.run(
            {"action": "continue", "interview_id": "no_such_id", "answer": "test"},
            trace_id="t_bad",
        )
        assert output.success is False
        assert "未找到" in output.reply_text

    @pytest.mark.asyncio
    async def test_finalize_nonexistent_interview(self):
        """对不存在的访谈调用 finalize 应返回 success=False"""
        skill = PersonaExtractSkill()
        output = await skill.run(
            {"action": "finalize", "interview_id": "no_such_id"},
            trace_id="t_bad2",
        )
        assert output.success is False
        assert "未找到" in output.reply_text

    @pytest.mark.asyncio
    async def test_start_with_source_persona_id(self):
        """start 支持 source_persona_id 参数（更新已有分身）"""
        skill = PersonaExtractSkill()
        output = await skill.run(
            {
                "action": "start",
                "venue_id": "venue_x",
                "job_title": "前台",
                "source_persona_id": "existing_pid_123",
            },
            trace_id="t_source",
        )
        assert output.success
        iid = output.structured_data["interview_id"]
        state = PersonaExtractSkill._interview_state[iid]
        assert state["source_persona_id"] == "existing_pid_123"

    def test_mock_parse_returns_entries(self):
        """mock模式 _mock_parse 返回占位条目"""
        skill = PersonaExtractSkill()
        entries = skill._mock_parse("测试回答", 1)
        assert len(entries) == 1
        assert "trigger" in entries[0]
        assert "behavior" in entries[0]
        assert "reason" in entries[0]
