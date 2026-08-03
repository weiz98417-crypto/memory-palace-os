from src.memory_palace.knowledge.experience_schema import _TABLE_STATEMENTS


def test_experience_candidate_boolean_default_is_postgres_compatible():
    candidate_table = next(
        statement
        for statement in _TABLE_STATEMENTS
        if "CREATE TABLE IF NOT EXISTS experience_candidates" in statement
    )

    assert "retryable BOOLEAN NOT NULL DEFAULT TRUE" in candidate_table
    assert "retryable BOOLEAN NOT NULL DEFAULT 1" not in candidate_table
