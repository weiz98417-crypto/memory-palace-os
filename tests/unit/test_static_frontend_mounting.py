from pathlib import Path

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