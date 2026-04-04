"""GitHub status builders for workspace connector routes."""

from __future__ import annotations

from typing import Any

import db as devdb
import integrations as integ
from axon_api.services.connector_workspace_views import row_dict
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_core.github_orchestrator import normalize_repo_cwd, read_workflow_status
from axon_data import get_project


async def github_status_for_workspace(db, workspace_id: int, branch: str = "", repo_path: str = "") -> dict[str, Any]:
    project = await get_project(db, workspace_id)
    if not project and not repo_path:
        raise ValueError("Workspace not found")
    settings = await devdb.get_all_settings(db)
    token = settings.get("github_token", "")
    project_dict = row_dict(project)
    resolved_repo_path = repo_path or str(project_dict.get("path") or "")
    if not resolved_repo_path:
        raise ValueError("Repository path not found")
    normalized_repo = normalize_repo_cwd(resolved_repo_path)
    status = await integ.github_full_status(normalized_repo, token)
    workflow_preview = {}
    if branch.strip():
        cwd, command = read_workflow_status(repo_path=normalized_repo, branch_name=branch)
        workflow_preview = {"cwd": cwd, "command": command}
    relationships = await list_workspace_relationships_for_workspace(
        db,
        workspace_id=workspace_id,
        external_system="github",
        limit=50,
    )
    return {
        "workspace": row_dict(project),
        "repo_path": normalized_repo,
        "relationships": relationships,
        "github": status,
        "workflow_preview": workflow_preview,
    }
