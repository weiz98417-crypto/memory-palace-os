from src.memory_palace.operations.sourced_showcase import SCENARIOS, SOURCES, neutral_answers


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
