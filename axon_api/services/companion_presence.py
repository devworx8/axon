"""Companion device presence helpers."""

from __future__ import annotations

from typing import Any

from axon_data import get_companion_presence, list_companion_presence, upsert_companion_presence


async def heartbeat_companion_presence(
    db,
    *,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
    presence_state: str = "online",
    voice_state: str = "idle",
    app_state: str = "foreground",
    active_route: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = await upsert_companion_presence(
        db,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        presence_state=presence_state,
        voice_state=voice_state,
        app_state=app_state,
        active_route=active_route,
        meta_json="{}" if meta is None else __import__("json").dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    return dict(row) if row else {"device_id": device_id, "workspace_id": workspace_id}


async def current_companion_presence(db, *, device_id: int) -> dict[str, Any] | None:
    row = await get_companion_presence(db, device_id)
    return dict(row) if row else None


async def list_workspace_presence(db, *, workspace_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = await list_companion_presence(db, workspace_id=workspace_id, limit=limit)
    return [dict(row) for row in rows]

