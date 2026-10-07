from src.memory_palace.operations.sourced_showcase import (
    SCENARIOS,
    SOURCES,
    find_existing_interview,
    knowledge_content,
    neutral_answers,
    source_notes,
    watcher_policy_metadata,
)


def test_sourced_showcase_has_three_x_volume_and_provenance():
    assert len(SOURCES) >= 8
    assert len(SCENARIOS) >= 24
    assert len({scenario["key"] for scenario in SCENARIOS}) == len(SCENARIOS)
    for scenario in SCENARIOS:
        assert scenario["source"] in SOURCES
        answers = neutral_answers(scenario)
        assert len(answers) == 4
        assert all(SOURCES[scenario["source"]]["title"] not in answer for answer in answers)
        assert "非现场" not in "".join(answers)
        assert "实际处置以现场制度为准" in answers[3]
        assert SOURCES[scenario["source"]]["url"] in source_notes(scenario["source"])
        assert "公开资料中性改编" not in knowledge_content(scenario)
        assert "资料整理示例" not in knowledge_content(scenario)
        assert SOURCES[scenario["source"]]["url"] in knowledge_content(scenario)


def test_sourced_watcher_policy_copy_is_production_safe():
    scenario = next(item for item in SCENARIOS if item["source"] == "safe-city")
    name, description = watcher_policy_metadata(scenario)

    assert name == f"安全巡检-{scenario['title']}"
    assert scenario["signals"] in description
    assert "公开资料改编" not in name + description
    assert "演示" not in name + description


def test_seed_reuses_legacy_titled_interview_instead_of_duplicating():
    legacy_row = {
        "id": "iv-1",
        "source_event_id": "event-1",
        "expert_id": "expert-1",
        "title": "【公开资料改编·结构化】缆车急停疏散",
    }
    exact_index = {
        ("event-1", "缆车急停疏散（结构化）", "expert-2"): {"id": "iv-2"},
    }
    grouped = {("event-1", "expert-1"): [legacy_row]}

    matched = find_existing_interview(
        title="缆车急停疏散（结构化）",
        scenario_title="缆车急停疏散",
        event_id="event-1",
        expert_id="expert-1",
        exact_index=exact_index,
        grouped=grouped,
    )

    assert matched is legacy_row


def test_seed_exact_match_wins_and_unknown_rows_are_created_fresh():
    exact_row = {"id": "iv-exact"}
    exact_index = {("event-2", "旱厕满溢处置（结构化）", "expert-1"): exact_row}
    grouped: dict[tuple[str, str], list] = {}

    assert (
        find_existing_interview(
            title="旱厕满溢处置（结构化）",
            scenario_title="旱厕满溢处置",
            event_id="event-2",
            expert_id="expert-1",
            exact_index=exact_index,
            grouped=grouped,
        )
        is exact_row
    )
    assert (
        find_existing_interview(
            title="全新场景（结构化）",
            scenario_title="全新场景",
            event_id="event-3",
            expert_id="expert-9",
            exact_index={},
            grouped={},
        )
        is None
    )
