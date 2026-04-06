from __future__ import annotations

from fastapi import FastAPI

from axon_api.routes import companion, companion_access, connectors, file_links, mcp_routes, media_routes, mobile_control, mobile_mission, mobile_vault


def register_core_routers(
    app: FastAPI,
    *,
    auto_session_router,
    agent_control_router,
    voice_status_router=None,
) -> None:
    """Attach extracted compatibility routers to the shared FastAPI app."""
    app.include_router(auto_session_router)
    app.include_router(agent_control_router)
    app.include_router(connectors.router)
    app.include_router(companion.router)
    app.include_router(companion_access.router)
    app.include_router(mobile_control.router)
    app.include_router(mobile_mission.router)
    app.include_router(mcp_routes.router)
    app.include_router(mobile_vault.router)
    app.include_router(file_links.router)
    app.include_router(media_routes.router)
    if voice_status_router is not None:
        app.include_router(voice_status_router)
