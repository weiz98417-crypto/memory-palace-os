"""Feature-flagged static mounting for the Vite frontend applications."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)

def frontend_v2_enabled(app_name: str, environ: Mapping[str, str] | None = None) -> bool:
    values = os.environ if environ is None else environ
    enabled = {
        item.strip()
        for item in str(values.get("FRONTEND_V2_APPS") or "").split(",")
        if item.strip()
    }
    return app_name in enabled


def mount_frontend_v2(
    app: FastAPI,
    *,
    app_name: str,
    route: str,
    directory: Path,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if not frontend_v2_enabled(app_name, environ):
        return False
    if not (directory / "index.html").is_file():
        return False
    app.mount(route, SpaStaticFiles(directory=directory, html=True), name=f"{app_name}_v2_static")
    return True


FRONTEND_APPS = {
    "console": "/admin",
    "field": "/assistant",
    "integration": "/simulator/wecom",
    "operations": "/operations",
}


def mount_configured_frontend_apps(
    app: FastAPI,
    *,
    root: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, bool]:
    mounted: dict[str, bool] = {}
    for app_name, route in FRONTEND_APPS.items():
        mounted[app_name] = mount_frontend_v2(
            app,
            app_name=app_name,
            route=route,
            directory=root / app_name,
            environ=environ,
        )
    return mounted

__all__ = ["FRONTEND_APPS", "SpaStaticFiles", "frontend_v2_enabled", "mount_configured_frontend_apps", "mount_frontend_v2"]
