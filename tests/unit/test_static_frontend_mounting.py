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
