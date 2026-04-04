"""Workspace-scoped mobile control actions."""

from __future__ import annotations

from typing import Any

from axon_api.services.connector_reconcile import inspect_workspace_connectors, reconcile_workspace_connectors
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_data import get_project, list_attention_items


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


async def execute_workspace_inspect(
    db,
    *,
    workspace_id: int,
) -> dict[str, Any]:
    workspace = _row(await get_project(db, workspace_id))
    relationships = (
        await list_workspace_relationships_for_workspace(db, workspace_id=int(workspace.get("id") or 0), limit=20)
        if workspace.get("id")
        else []
    )
    attention = (
        [dict(row) for row in await list_attention_items(db, workspace_id=int(workspace.get("id") or 0), limit=10)]
        if workspace.get("id")
        else []
    )
    connector_state = (
        await inspect_workspace_connectors(db, workspace_id=int(workspace.get("id") or 0))
        if workspace.get("id")
        else {}
    )
    repo = dict(connector_state.get("repo") or {})
    return {
        "workspace": workspace,
        "relationships": relationships,
        "attention": attention,
        "repo": repo,
        "connector_reconcile": {
            "status": connector_state.get("status"),
            "summary": connector_state.get("summary"),
            "planned_repairs": connector_state.get("planned_repairs") or [],
        },
        "summary": (
            f"{workspace.get('name') or 'Workspace'}"
            + (f" on {repo.get('branch')}" if repo.get("branch") else "")
            + (f" · {repo.get('dirty_count')} local change(s)" if repo else "")
        ).strip(),
    }


async def execute_workspace_focus_set(
    db,
    *,
    workspace_id: int | None,
) -> dict[str, Any]:
    workspace = _row(await get_project(db, int(workspace_id or 0))) if workspace_id else {}
    return {
        "workspace_id": workspace_id,
        "workspace": workspace,
        "summary": "Focused workspace updated for Axon Online.",
    }


async def execute_workspace_connector_reconcile(
    db,
    *,
    workspace_id: int,
    allow_repo_writes: bool = False,
) -> dict[str, Any]:
    return await reconcile_workspace_connectors(
        db,
        workspace_id=workspace_id,
        allow_repo_writes=allow_repo_writes,
    )
