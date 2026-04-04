"""MCP registry and built-in gateway routes for Axon Online."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from axon_api.services.companion_request_auth import require_companion_context
from axon_api.services.mobile_mcp_registry import invoke_builtin_mcp_capability, registry_health_summary
from axon_data import get_db

router = APIRouter(prefix="/api/mcp", tags=["mobile-mcp"])


class McpInvokeRequest(BaseModel):
    capability_key: str
    workspace_id: int | None = None
    arguments: dict[str, Any] | None = Field(default=None)


@router.get("/servers")
async def mcp_servers(request: Request):
    await require_companion_context(request)
    async with get_db() as db:
        registry = await registry_health_summary(db)
    return {"servers": registry["servers"], "capabilities": registry["capabilities"]}


@router.get("/sessions")
async def mcp_sessions(request: Request):
    await require_companion_context(request)
    async with get_db() as db:
        registry = await registry_health_summary(db)
    return {"sessions": registry["sessions"], "hybrid_enabled": registry["hybrid_enabled"]}


@router.post("/invoke")
async def mcp_invoke(request: Request, body: McpInvokeRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        try:
            result = await invoke_builtin_mcp_capability(
                db,
                device_id=int(device_row["id"]),
                workspace_id=body.workspace_id,
                capability_key=body.capability_key,
                arguments=body.arguments or {},
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    return result
