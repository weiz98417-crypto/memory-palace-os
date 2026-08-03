import pytest
from unittest.mock import AsyncMock, MagicMock

from src.memory_palace.skills.commander.skill import CommanderSkill
from src.memory_palace.skills.context_trigger.skill import ContextTriggerSkill
from src.memory_palace.skills.memory_ops.skill import MemoryOpsSkill
from src.memory_palace.skills.persona.skill import PersonaSkill
from src.memory_palace.skills.persona_extract.invoke import ask_persona, query_persona_logic
from src.memory_palace.skills.router.skill import RouterSkill
from src.memory_palace.skills.todo.skill import TodoWriteSkill
from src.memory_palace.skills.watcher.skill import WatcherSkill
from src.memory_palace.knowledge.evidence_backed_retrieval import RetrievalResult


def empty_json_client():
    client = MagicMock()
    client.ask = AsyncMock(return_value=MagicMock(content="{}", tokens_used=0))
    client.parse_json = AsyncMock(return_value={})
    return client


def zero_hit_retriever():
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=RetrievalResult(
            snapshot_id="snapshot-zero-hit",
            status="ZERO_HITS",
            documents=(),
            references=(),
            raw_hit_count=0,
        )
    )
    return retriever


def authorized_persona_context():
    return {
        "raw_text": "遇到暴雨封园时应先做什么",
        "venue_id": "venue-a",
        "persona_trigger": "AUTHORIZED_RETRIEVAL",
        "knowledge_references": [
            {
                "source_id": "experience-card-a",
                "source_type": "EXPERIENCE_CARD",
                "source_label": "专家经验",
                "title": "暴雨封园处置判断",
                "version": 1,
                "status": "PUBLISHED",
                "expert_name": "张建国",
                "content": "先确认人员安全，再按发布流程执行封园。",
            }
        ],
    }


@pytest.mark.asyncio
async def test_router_fails_when_llm_client_is_unavailable(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.router.skill.llm_client", None)
    skill = RouterSkill()

    output = await skill.run(
        {"raw_text": "东门闸机反复断电，需要判断如何处置", "venue_id": "venue-a"},
        trace_id="trace-router-no-llm",
    )

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "LLM" in output.error_msg


@pytest.mark.asyncio
async def test_router_rejects_empty_structured_model_output(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.router.skill.llm_client", empty_json_client())
    output = await RouterSkill().run(
        {"raw_text": "东门闸机反复断电，需要判断如何处置", "venue_id": "venue-a"},
        trace_id="trace-router-empty-output",
    )

    assert output.success is False
    assert "必需字段" in output.error_msg


@pytest.mark.asyncio
async def test_memory_ops_fails_when_llm_client_is_unavailable(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.memory_ops.skill.llm_client", None)
    skill = MemoryOpsSkill()

    output = await skill.run(
        {"raw_text": "以前怎么处理索道停运游客疏导", "venue_id": "venue-a"},
        trace_id="trace-memory-no-llm",
    )

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "LLM" in output.error_msg


@pytest.mark.asyncio
async def test_memory_ops_rejects_empty_structured_model_output(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.memory_ops.skill.llm_client", empty_json_client())
    output = await MemoryOpsSkill().run(
        {
            "raw_text": "以前怎么处理索道停运游客疏导",
            "venue_id": "venue-a",
            "from_user": "employee-a",
            "_knowledge_retriever": zero_hit_retriever(),
        },
        trace_id="trace-memory-empty-output",
    )

    assert output.success is False
    assert "reply_text" in output.error_msg


@pytest.mark.asyncio
async def test_persona_fails_when_llm_client_is_unavailable(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.persona.skill.llm_client", None)
    skill = PersonaSkill()

    output = await skill.run(authorized_persona_context(), trace_id="trace-persona-no-llm")

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "LLM" in output.error_msg


@pytest.mark.asyncio
async def test_persona_rejects_empty_structured_model_output(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.persona.skill.llm_client", empty_json_client())
    output = await PersonaSkill().run(
        authorized_persona_context(), trace_id="trace-persona-empty-output"
    )

    assert output.success is False
    assert "必需字段" in output.error_msg


@pytest.mark.asyncio
async def test_persona_rejects_general_chat_without_authorized_experience():
    output = await PersonaSkill().run(
        {"raw_text": "你好，今天忙吗", "venue_id": "venue-a"},
        trace_id="trace-persona-general-chat",
    )

    assert output.success is False
    assert output.action_taken == "validation_failed"
    assert "授权" in output.error_msg


@pytest.mark.asyncio
async def test_context_trigger_fails_when_stage2_llm_client_is_unavailable(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.context_trigger.skill.llm_client", None)
    skill = ContextTriggerSkill()

    output = await skill.run(
        {
            "raw_text": "东门有游客倒地需要救护",
            "from_user": "employee-a",
            "venue_id": "venue-a",
        },
        trace_id="trace-context-no-llm",
    )

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "LLM" in output.error_msg


@pytest.mark.asyncio
async def test_watcher_rejects_empty_structured_model_output(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.watcher.skill.llm_client", empty_json_client())
    skill = WatcherSkill()

    output = await skill.run(
        {
            "venue_id": "venue-a",
            "audit_target_logs": [
                {
                    "case_id": "case-1",
                    "severity": "P0",
                    "is_resolved": False,
                    "elapsed_minutes": 8,
                }
            ],
        },
        trace_id="trace-watcher-empty-output",
    )

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "必需字段" in output.error_msg


@pytest.mark.asyncio
async def test_commander_rejects_empty_structured_model_output(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.commander.skill.llm_client", empty_json_client())
    output = await CommanderSkill().run(
        {"raw_text": "东门游客倒地失去意识", "severity": "P0", "venue_id": "venue-a"},
        trace_id="trace-commander-empty-output",
    )

    assert output.success is False
    assert "必需字段" in output.error_msg


@pytest.mark.asyncio
async def test_todo_rejects_decomposition_with_no_valid_tasks(monkeypatch):
    client = MagicMock()
    client.ask = AsyncMock(return_value=MagicMock(content="[{}]", tokens_used=0))
    client.parse_json = AsyncMock(return_value=[{}])
    monkeypatch.setattr("src.memory_palace.skills.todo.skill.llm_client", client)
    skill = TodoWriteSkill()

    output = await skill.run(
        {"goal": "完成东门应急演练", "session_id": "session-a", "venue_id": "venue-a"},
        trace_id="trace-todo-empty-tasks",
    )

    assert output.success is False
    assert output.action_taken == "model_output_invalid"
    assert "有效任务" in output.error_msg


@pytest.mark.asyncio
async def test_persona_invocation_fails_instead_of_composing_a_fake_reply(monkeypatch):
    class PersonaDatabase:
        async def fetch_all(self, sql, parameters):
            return [
                {
                    "id": "persona-a",
                    "venue_id": "venue-a",
                    "job_title": "安保",
                    "logic_entries": '[{"trigger":"游客倒地","behavior":"呼叫救援","reason":"生命优先"}]',
                }
            ]

    monkeypatch.setattr("src.memory_palace.skills.persona_extract.invoke.llm_client", None)

    with pytest.raises(RuntimeError, match="LLM"):
        await ask_persona(
            venue_id="venue-a",
            job_title="安保",
            question="游客倒地",
            trace_id="trace-persona-invoke-no-llm",
            database=PersonaDatabase(),
        )


@pytest.mark.asyncio
async def test_persona_query_binds_requested_persona_and_matches_chinese_incident():
    class PersonaDatabase:
        def __init__(self):
            self.parameters = None

        async def fetch_all(self, sql, parameters):
            self.parameters = parameters
            return [
                {
                    "id": "persona-target",
                    "venue_id": "venue-a",
                    "job_title": "应急值班专家",
                    "logic_entries": (
                        '[{"trigger":"当游客意识不清、抽搐或呼吸异常时",'
                        '"behavior":"立即呼叫120和上级",'
                        '"reason":"需要专业医疗介入"}]'
                    ),
                }
            ]

    database = PersonaDatabase()
    entries = await query_persona_logic(
        venue_id="venue-a",
        job_title="应急值班专家",
        question="北门游客疑似低血糖且意识不清时，现场人员最重要的前三步是什么？",
        persona_id="persona-target",
        database=database,
    )

    assert database.parameters == ("persona-target", "venue-a")
    assert entries
    assert entries[0]["persona_id"] == "persona-target"


@pytest.mark.asyncio
async def test_commander_fails_when_llm_client_is_unavailable(monkeypatch):
    monkeypatch.setattr("src.memory_palace.skills.commander.skill.llm_client", None)
    skill = CommanderSkill()

    output = await skill.run(
        {
            "raw_text": "东门游客倒地失去意识",
            "severity": "P0",
            "venue_id": "venue-a",
        },
        trace_id="trace-commander-no-llm",
    )

    assert output.success is False
    assert output.action_taken == "fatal_error_fallback"
    assert "LLM" in output.error_msg
