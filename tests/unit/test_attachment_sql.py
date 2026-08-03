from pathlib import Path


def test_attachment_queries_do_not_use_postgres_user_keyword_as_alias():
    project_root = Path(__file__).parents[2]
    sources = (
        project_root / "src" / "memory_palace" / "core" / "attachments.py",
        project_root
        / "src"
        / "memory_palace"
        / "api"
        / "v1"
        / "endpoints"
        / "attachments.py",
    )

    for source in sources:
        sql = source.read_text(encoding="utf-8")
        assert " AS user" not in sql
        assert "user.display_name" not in sql
