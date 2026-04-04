"""Mission Control routes for the Axon Online mobile command center."""

from __future__ import annotations

from fastapi import APIRouter, Request

from axon_api.services.companion_request_auth import require_companion_context
from axon_api.services.mobile_platform_snapshot import build_platform_snapshot
from axon_data import get_db

router = APIRouter(prefix="/api/mobile/mission", tags=["mobile-mission"])


@router.get("/snapshot")
async def mobile_mission_snapshot(
    request: Request,
    workspace_id: int | None = None,
    session_id: int | None = None,
):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        snapshot = await build_platform_snapshot(
            db,
            device_id=int(device_row["id"]),
            workspace_id=workspace_id,
            session_id=session_id,
        )
    return snapshot


@router.get("/digest")
async def mobile_mission_digest(
    request: Request,
    workspace_id: int | None = None,
    session_id: int | None = None,
):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        snapshot = await build_platform_snapshot(
            db,
            device_id=int(device_row["id"]),
            workspace_id=workspace_id,
            session_id=session_id,
        )
    focus = dict(snapshot.get("focus") or {})
    workspace = dict(focus.get("workspace") or {})
    attention = dict(dict(snapshot.get("attention") or {}).get("summary") or {})
    counts = dict(attention.get("counts") or {})
    next_required = snapshot.get("next_required_action") or {}
    lines = [
        f"Platform posture: {str(snapshot.get('posture') or 'healthy').replace('_', ' ')}.",
        f"Focused workspace: {workspace.get('name') or 'Global context'}.",
        f"Attention: now={int(counts.get('now') or 0)}, waiting={int(counts.get('waiting_on_me') or 0)}, watch={int(counts.get('watch') or 0)}.",
    ]
    if next_required:
        title = str(dict(next_required).get("title") or dict(next_required).get("summary") or "").strip()
        if title:
            lines.append(f"Next required action: {title}.")
    return {
        "digest": " ".join(lines),
        "snapshot": snapshot,
    }
