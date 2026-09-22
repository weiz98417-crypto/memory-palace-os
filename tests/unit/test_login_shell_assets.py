from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "variant"),
    [
        ("static/assistant/index.html", "field"),
        ("static/simulator/wecom/index.html", "integration"),
    ],
)
def test_legacy_entries_use_the_shared_login_shell(relative_path: str, variant: str):
    html = (ROOT / relative_path).read_text(encoding="utf-8")

    assert f'data-login-variant="{variant}"' in html
    assert "/shared/login-shell.css" in html
    assert "/shared/login-shell.js" in html
    assert 'data-action="toggle-password"' in html


def test_shared_login_backgrounds_exist_for_all_three_themes():
    for name in ("field", "integration", "operations"):
        assert (ROOT / "static" / "shared" / "login-backgrounds" / f"{name}.webp").is_file()


def test_v2_scenic_entries_reference_shared_login_backgrounds():
    for app, name in (
        ("field", "field"),
        ("integration", "integration"),
        ("operations", "operations"),
    ):
        source = (ROOT / "frontend" / "apps" / app / "src" / "App.vue").read_text(encoding="utf-8")
        assert f"/shared/login-backgrounds/{name}.webp" in source
