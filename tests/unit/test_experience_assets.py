from types import SimpleNamespace

import pytest

from src.memory_palace.core.experience_assets import (
    DeepSeekExperienceDraftExtractor,
    ExperienceDraftExtractionError,
    ExperienceStateError,
    authorization_allows,
    next_experience_status,
    validate_extracted_experience_draft,
)


class _DraftLLM:
    def __init__(self, draft):
        self.draft = draft

    async def ask(self, **kwargs):
        return SimpleNamespace(content="{}", is_mock=False)

    async def parse_json(self, content, *, trace_id):
        return self.draft


@pytest.mark.parametrize(
    ("current", "action", "expected"),
    [
        ("DRAFT", "confirm", "EXPERT_CONFIRMED"),
        ("EXPERT_CONFIRMED", "submit", "IN_REVIEW"),
        ("IN_REVIEW", "reject", "DRAFT"),
        ("IN_REVIEW", "publish", "PUBLISHED"),
        ("PUBLISHED", "deprecate", "DEPRECATED"),
    ],
)
def test_experience_state_machine_accepts_only_governed_transitions(current, action, expected):
    assert next_experience_status(current, action) == expected


@pytest.mark.parametrize(
    ("current", "action"),
    [
        ("DRAFT", "publish"),
        ("DRAFT", "submit"),
        ("EXPERT_CONFIRMED", "publish"),
        ("IN_REVIEW", "confirm"),
        ("PUBLISHED", "reject"),
        ("DEPRECATED", "publish"),
    ],
)
def test_experience_state_machine_rejects_shortcuts(current, action):
    with pytest.raises(ExperienceStateError):
        next_experience_status(current, action)


def test_authorization_requires_tenant_and_one_explicit_matching_scope():
    principal = {
        "user_id": "operator-7",
        "venue_id": "venue-yueshan",
        "role": "operator",
        "department": "设备运营部",
        "job_title": "设备检修员",
    }
    scopes = [
        {"scope_type": "ROLE", "scope_value": "manager"},
        {"scope_type": "JOB_TITLE", "scope_value": "设备检修员"},
    ]

    assert authorization_allows("venue-yueshan", scopes, principal) is True
    assert authorization_allows("venue-other", scopes, principal) is False
    assert authorization_allows(
        "venue-yueshan",
        [{"scope_type": "ROLE", "scope_value": "manager"}],
        principal,
    ) is False
    assert authorization_allows("venue-yueshan", [], principal) is False


def test_extracted_experience_draft_rejects_missing_business_fields():
    evidence = {
        "turns": [
            {
                "answer_text": "异响随轮速变化，先停车断电并检查护板间隙。",
            }
        ]
    }
    incomplete_draft = {
        "title": "雨后观光车异响判断",
        "applicable_context": "雨后复运检查",
    }

    with pytest.raises(ExperienceDraftExtractionError, match="decision_rule"):
        validate_extracted_experience_draft(incomplete_draft, evidence)


def test_extracted_experience_draft_rejects_untraceable_source_excerpts():
    evidence = {
        "turns": [
            {
                "answer_text": "异响随轮速变化，先停车断电并检查护板间隙。",
            }
        ]
    }
    draft = {
        "title": "雨后观光车异响判断",
        "applicable_context": "雨后复运检查",
        "signals": ["异响随轮速变化"],
        "decision_rule": "先停车断电，再检查护板间隙",
        "recommended_actions": ["停车断电", "检查护板间隙"],
        "rationale": "区分护板摩擦与制动故障",
        "prohibitions": ["禁止载客试车"],
        "exceptions": ["制动异常时升级拖车检修"],
        "source_excerpts": ["专家确认可以继续载客运行。"],
    }

    with pytest.raises(ExperienceDraftExtractionError, match="无法回溯"):
        validate_extracted_experience_draft(draft, evidence)


@pytest.mark.asyncio
async def test_extractor_replaces_generated_citations_with_traceable_interview_evidence():
    answer = "异响随轮速变化，先停车断电并检查护板间隙。"
    evidence = {
        "title": "雨后观光车异响判断",
        "expert_name": "张建国",
        "expert_job_title": "设备保障主管",
        "turns": [
            {
                "turn_number": 1,
                "question_text": "哪些现场信号可以区分不同故障原因？",
                "answer_text": answer,
                "source_excerpt": "先停车，再检查。",
            }
        ],
    }
    generated = {
        "title": "雨后观光车异响判断",
        "applicable_context": "雨后复运检查",
        "signals": ["异响随轮速变化"],
        "decision_rule": "先停车断电，再检查护板间隙",
        "recommended_actions": ["停车断电", "检查护板间隙"],
        "rationale": "区分护板摩擦与制动故障",
        "prohibitions": ["禁止载客试车"],
        "exceptions": ["制动异常时升级拖车检修"],
        "source_excerpts": ["专家确认可以继续载客运行。"],
    }

    extracted = await DeepSeekExperienceDraftExtractor(_DraftLLM(generated)).extract(
        evidence,
        trace_id="trace-evidence-citation",
        venue_id="venue-yueshan",
    )

    assert extracted["source_excerpts"] == [answer]
