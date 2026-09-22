from src.memory_palace.operations.sourced_showcase import SCENARIOS, SOURCES, neutral_answers, watcher_policy_metadata


def test_sourced_showcase_has_three_x_volume_and_provenance():
    assert len(SOURCES) >= 8
    assert len(SCENARIOS) >= 24
    assert len({scenario["key"] for scenario in SCENARIOS}) == len(SCENARIOS)
    for scenario in SCENARIOS:
        assert scenario["source"] in SOURCES
        answers = neutral_answers(scenario)
        assert len(answers) == 4
        assert all(SOURCES[scenario["source"]]["title"] in answer for answer in answers)
        assert "演示数据改编" in answers[3]
        assert SOURCES[scenario["source"]]["url"] in answers[3]


def test_sourced_watcher_policy_copy_is_production_safe():
    scenario = next(item for item in SCENARIOS if item["source"] == "safe-city")
    name, description = watcher_policy_metadata(scenario)

    assert name == f"基于国家安全发展示范城市建设指导手册的安全巡检-{scenario['title']}"
    assert description == "依据国家安全发展示范城市建设指导手册开展的安全巡检。"
    assert "公开资料改编" not in name + description
    assert "演示" not in name + description
