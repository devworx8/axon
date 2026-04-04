"""Companion workspace/session helpers."""

from __future__ import annotations

from typing import Any

from axon_data import (
    close_companion_session,
    get_companion_session,
    get_companion_session_by_key,
    list_companion_sessions,
    update_companion_session_state,
    upsert_companion_session,
)


def companion_session_key(device_id: int | None, workspace_id: int | None, agent_session_id: str = "") -> str:
    parts = [str(device_id or ""), str(workspace_id or ""), str(agent_session_id or "")]
    return "companion:" + ":".join(parts)


async def ensure_companion_session(
    db,
    *,
    session_key: str,
    device_id: int | None = None,
    workspace_id: int | None = None,
    agent_session_id: str = "",
    status: str = "active",
    mode: str = "companion",
    current_route: str = "",
    current_view: str = "",
    active_task: str = "",
    summary: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = await upsert_companion_session(
        db,
        session_key=session_key,
        device_id=device_id,
        workspace_id=workspace_id,
        agent_session_id=agent_session_id,
        status=status,
        mode=mode,
        current_route=current_route,
        current_view=current_view,
        active_task=active_task,
        summary=summary,
        meta_json="{}" if meta is None else __import__("json").dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    row = await get_companion_session(db, session_id)
    return dict(row) if row else {"id": session_id, "session_key": session_key}


async def touch_companion_session(
    db,
    *,
    session_id: int,
    status: str | None = None,
    agent_session_id: str | None = None,
    current_route: str | None = None,
    current_view: str | None = None,
    active_task: str | None = None,
    summary: str | None = None,
) -> bool:
    await update_companion_session_state(
        db,
        session_id,
        status=status,
        agent_session_id=agent_session_id,
        current_route=current_route,
        current_view=current_view,
        active_task=active_task,
        summary=summary,
    )
    return True


async def resume_companion_session(
    db,
    *,
    session_key: str,
    agent_session_id: str = "",
    status: str = "active",
) -> dict[str, Any] | None:
    row = await get_companion_session_by_key(db, session_key)
    if not row:
        return None
    await update_companion_session_state(
        db,
        int(row["id"]),
        status=status,
        agent_session_id=agent_session_id or str(row["agent_session_id"] or ""),
    )
    refreshed = await get_companion_session(db, int(row["id"]))
    return dict(refreshed) if refreshed else dict(row)


async def close_companion_workspace_session(db, *, session_id: int) -> bool:
    await close_companion_session(db, session_id)
    return True


async def list_companion_workspace_sessions(
    db,
    *,
    device_id: int | None = None,
    workspace_id: int | None = None,
    status: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = await list_companion_sessions(
        db,
        device_id=device_id,
        workspace_id=workspace_id,
        status=status,
        limit=limit,
    )
    return [dict(row) for row in rows]
