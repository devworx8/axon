"""UI shell and PWA asset routes extracted from the legacy server facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


class ShellAssetRouteHandlers:
    def __init__(self, *, ui_renderer: Any, ui_dir: Path, sw_cache_version: str) -> None:
        self._ui_renderer = ui_renderer
        self._ui_dir = ui_dir
        self._sw_cache_version = sw_cache_version

    async def serve_ui(self):
        return self._ui_renderer.render_index(self._ui_dir, self._sw_cache_version)

    async def serve_manual(self):
        return self._ui_renderer.render_manual(self._ui_dir, self._sw_cache_version)

    async def pwa_manifest(self):
        return self._ui_renderer.render_manifest()

    async def serve_styles(self):
        return self._ui_renderer.render_styles(self._ui_dir)

    async def serve_js(self, filename: str):
        return self._ui_renderer.render_js(self._ui_dir, filename)

    async def serve_icon(self, filename: str):
        return self._ui_renderer.render_icon(self._ui_dir, filename)

    async def service_worker(self):
        return self._ui_renderer.render_service_worker(self._sw_cache_version)


def build_shell_asset_router(*, ui_renderer: Any, ui_dir: Path, sw_cache_version: str) -> tuple[APIRouter, ShellAssetRouteHandlers]:
    handlers = ShellAssetRouteHandlers(
        ui_renderer=ui_renderer,
        ui_dir=ui_dir,
        sw_cache_version=sw_cache_version,
    )
    router = APIRouter(tags=["shell"])
    router.add_api_route("/", handlers.serve_ui, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route("/manual", handlers.serve_manual, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route("/manual.html", handlers.serve_manual, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route("/manifest.json", handlers.pwa_manifest, methods=["GET"])
    router.add_api_route("/styles.css", handlers.serve_styles, methods=["GET"])
    router.add_api_route("/js/{filename:path}", handlers.serve_js, methods=["GET"])
    router.add_api_route("/icons/{filename}", handlers.serve_icon, methods=["GET"])
    router.add_api_route("/sw.js", handlers.service_worker, methods=["GET"])
    return router, handlers
