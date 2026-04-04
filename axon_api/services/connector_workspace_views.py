"""Shared builders for connector workspace summary payloads."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def group_workspace_relationships(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        workspace_id = int(row.get("workspace_id") or 0)
        if workspace_id:
            grouped[workspace_id].append(row)
    return grouped


async def workspace_connector_summary(
    db,
    *,
    workspace_id: int,
    external_system: str = "",
    get_project_fn,
    list_workspace_relationships_for_workspace_fn,
    attention_summary_fn,
) -> dict[str, Any]:
    project = await get_project_fn(db, workspace_id)
    relationships = await list_workspace_relationships_for_workspace_fn(
        db,
        workspace_id=workspace_id,
        external_system=external_system,
        limit=50,
    )
    inbox = await attention_summary_fn(db, workspace_id=workspace_id, limit=50)
    return {
        "workspace": row_dict(project),
        "relationships": relationships,
        "attention": inbox,
    }


async def connector_workspaces_for_system(
    db,
    *,
    external_system: str,
    limit: int,
    get_projects_fn,
    get_project_fn,
    list_workspace_relationships_fn,
    list_workspace_relationships_for_workspace_fn,
    attention_summary_fn,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for project in list(await get_projects_fn(db, status="active") or [])[: max(1, limit)]:
        project_dict = row_dict(project)
        workspace_id = int(project_dict.get("id") or 0)
        if workspace_id <= 0:
            continue
        relationships = await list_workspace_relationships_for_workspace_fn(
            db,
            workspace_id=workspace_id,
            external_system=external_system,
            limit=50,
        )
        if not relationships:
            continue
        summaries.append(
            await workspace_connector_summary(
                db,
                workspace_id=workspace_id,
                external_system=external_system,
                get_project_fn=get_project_fn,
                list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace_fn,
                attention_summary_fn=attention_summary_fn,
            )
        )
    if summaries:
        return summaries

    seen: set[int] = set()
    rows = await list_workspace_relationships_fn(db, external_system=external_system, limit=limit)
    for row in rows:
        workspace_id = int(dict(row).get("workspace_id") or 0)
        if workspace_id <= 0 or workspace_id in seen:
            continue
        seen.add(workspace_id)
        summaries.append(
            await workspace_connector_summary(
                db,
                workspace_id=workspace_id,
                external_system=external_system,
                get_project_fn=get_project_fn,
                list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace_fn,
                attention_summary_fn=attention_summary_fn,
            )
        )
    return summaries
