"""Workspace preview actions for Axon Online mobile control."""

from __future__ import annotations

import asyncio
from typing import Any

from axon_api.services import live_preview_sessions as live_preview_service
from axon_api.services.workspace_sandbox_state import serialize_preview_session
from axon_data import get_project, log_event


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


async def restart_workspace_preview(
    db,
    *,
    workspace_id: int,
    restart: bool = True,
) -> dict[str, Any]:
    workspace = _row(await get_project(db, workspace_id))
    if not workspace:
        raise ValueError("Workspace not found")
    preview = await asyncio.to_thread(
        lambda: live_preview_service.ensure_preview_session(
            workspace_id=workspace_id,
            workspace_name=str(workspace.get("name") or ""),
            source_path=str(workspace.get("path") or ""),
            source_workspace_path=str(workspace.get("path") or ""),
            restart=restart,
        )
    )
    await log_event(
        db,
        "preview",
        f"Mobile preview restart requested for {workspace.get('name') or workspace_id}",
        project_id=workspace_id,
    )
    return {
        "workspace_id": workspace_id,
        "workspace": workspace,
        "preview": serialize_preview_session(preview),
        "summary": f"Preview {str(preview.get('status') or 'starting').replace('_', ' ')} for {workspace.get('name') or 'workspace'}.",
    }


async def stop_workspace_preview(
    db,
    *,
    workspace_id: int,
) -> dict[str, Any]:
    workspace = _row(await get_project(db, workspace_id))
    if not workspace:
        raise ValueError("Workspace not found")
    preview = await asyncio.to_thread(
        lambda: live_preview_service.stop_preview_session(workspace_id=workspace_id)
    )
    await log_event(
        db,
        "preview",
        f"Mobile preview stop requested for {workspace.get('name') or workspace_id}",
        project_id=workspace_id,
    )
    return {
        "workspace_id": workspace_id,
        "workspace": workspace,
        "preview": serialize_preview_session(preview),
        "summary": f"Preview stopped for {workspace.get('name') or 'workspace'}.",
    }
