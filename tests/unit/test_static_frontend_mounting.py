from pathlib import Path

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory_palace.api.static_frontend import frontend_v2_enabled, mount_frontend_v2


def test_feature_flag_controls_v2_mount_and_returns_legacy_when_disabled(tmp_path: Path):
    app_root = tmp_path / "operations"
    app_root.mkdir()
    (app_root / "index.html").write_text("<html>v2 operations</html>", encoding="utf-8")
    app = FastAPI()

    assert mount_frontend_v2(
        app,
        app_name="operations",
        route="/operations",
        directory=app_root,
        environ={"FRONTEND_V2_APPS": "console,operations"},
    )
    assert TestClient(app).get("/operations/scenic").status_code == 200

    disabled = FastAPI()
    assert not mount_frontend_v2(
        disabled,
        app_name="operations",
        route="/operations",
        directory=app_root,
        environ={"FRONTEND_V2_APPS": "console"},
    )
    assert frontend_v2_enabled("operations", {"FRONTEND_V2_APPS": "console"}) is False



def test_each_entry_can_be_mounted_independently(tmp_path: Path):
    from src.memory_palace.api.static_frontend import mount_configured_frontend_apps

    root = tmp_path / "client"
    for app_name in ("console", "field", "integration", "operations"):
        app_dir = root / app_name
        app_dir.mkdir(parents=True)
        (app_dir / "index.html").write_text(f"<html>{app_name}</html>", encoding="utf-8")

    for enabled_app in ("console", "field", "integration", "operations"):
        app = FastAPI()
        mounted = mount_configured_frontend_apps(
            app,
            root=root,
            environ={"FRONTEND_V2_APPS": enabled_app},
        )
        assert mounted == {
            app_name: app_name == enabled_app
            for app_name in ("console", "field", "integration", "operations")
        }
        route = {
            "console": "/admin/command-center",
            "field": "/assistant/work/task/1",
            "integration": "/simulator/wecom/session/1",
            "operations": "/operations/scenic",
        }[enabled_app]
        assert TestClient(app).get(route).text == f"<html>{enabled_app}</html>"


def test_enabled_frontend_with_missing_output_fails_instead_of_silent_fallback(tmp_path: Path):
    app = FastAPI()
    with pytest.raises(RuntimeError, match="frontend V2 asset missing"):
        mount_frontend_v2(
            app,
            app_name="console",
            route="/admin",
            directory=tmp_path / "console",
            environ={"FRONTEND_V2_APPS": "console"},
        )


def test_configured_frontend_mounts_are_independent_per_app(tmp_path: Path):
    from src.memory_palace.api.static_frontend import mount_configured_frontend_apps

    root = tmp_path / "client"
    for app_name in ("console", "field", "integration", "operations"):
        app_dir = root / app_name
        app_dir.mkdir(parents=True)
        (app_dir / "index.html").write_text(f"<html>{app_name}</html>", encoding="utf-8")

    app = FastAPI()
    mounted = mount_configured_frontend_apps(
        app,
        root=root,
        environ={"FRONTEND_V2_APPS": "console,integration"},
    )

    assert mounted == {"console": True, "field": False, "integration": True, "operations": False}
    client = TestClient(app)
    assert client.get("/admin/command-center").status_code == 200
    assert client.get("/simulator/wecom/session").status_code == 200