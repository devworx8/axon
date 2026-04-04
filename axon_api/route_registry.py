from __future__ import annotations

from fastapi import FastAPI

from axon_api.routes import connectors, mobile_vault


def register_core_routers(
    app: FastAPI,
    *,
    auto_session_router,
    agent_control_router,
) -> None:
    """Attach extracted compatibility routers to the shared FastAPI app."""
    app.include_router(auto_session_router)
    app.include_router(agent_control_router)
    app.include_router(connectors.router)
    app.include_router(mobile_vault.router)
