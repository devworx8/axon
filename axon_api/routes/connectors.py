"""API routes for external connectors and workspace relationship views."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import db as devdb
import integrations as integ
from axon_api.routes.connector_models import (
    WorkspaceConnectorConnectRequest,
    WorkspaceConnectorReconcileRequest,
    WorkspaceRelationshipRequest,
)
from axon_api.services.attention_query import attention_summary
from axon_api.services.connector_connection_state import connect_workspace_connector
from axon_api.services.connector_github_status import github_status_for_workspace
from axon_api.services.connector_reconcile import reconcile_workspace_connectors
from axon_api.services.connector_workspace_views import (
    connector_workspaces_for_system,
    group_workspace_relationships,
    row_dict,
    workspace_connector_summary,
)
from axon_api.services.connector_attention import (
    sync_all_connector_attention,
    sync_github_attention,
    sync_sentry_attention,
    sync_vercel_attention,
    sync_workspace_connector_attention,
)
from axon_api.services.workspace_relationships import (
    infer_workspace_relationships,
    link_workspace_relationship,
    list_workspace_relationships_for_workspace,
)
from axon_core.github_orchestrator import normalize_repo_cwd, read_workflow_status
from axon_data import (
    get_db,
    get_project,
    get_projects,
    list_error_events,
    list_workspace_relationships,
)

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("/")
async def connectors_overview(limit: int = 25):
    async with get_db() as db:
        summary: list[dict[str, Any]] = []
        projects = await get_projects(db, status="active")
        for project in list(projects or [])[: max(1, limit)]:
            summary.append(
                await workspace_connector_summary(
                    db,
                    workspace_id=int(project["id"]),
                    get_project_fn=get_project,
                    list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
                    attention_summary_fn=attention_summary,
                )
            )
        if not summary:
            relationship_rows = await list_workspace_relationships(db, limit=limit)
            grouped = group_workspace_relationships([dict(row) for row in relationship_rows])
            for workspace_id in grouped:
                summary.append(
                    await workspace_connector_summary(
                        db,
                        workspace_id=workspace_id,
                        get_project_fn=get_project,
                        list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
                        attention_summary_fn=attention_summary,
                    )
                )
    return {"workspaces": summary}


@router.get("/overview")
async def connectors_overview_alias(limit: int = 25):
    return await connectors_overview(limit=limit)


@router.get("/workspaces/{workspace_id}")
async def connectors_workspace(workspace_id: int):
    async with get_db() as db:
        return await workspace_connector_summary(
            db,
            workspace_id=workspace_id,
            get_project_fn=get_project,
            list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
            attention_summary_fn=attention_summary,
        )


@router.post("/workspaces/{workspace_id}/relationships")
async def connectors_link_workspace(workspace_id: int, body: WorkspaceRelationshipRequest):
    async with get_db() as db:
        project = await get_project(db, workspace_id)
        if not project:
            raise HTTPException(404, "Workspace not found")
        relationship = await link_workspace_relationship(
            db,
            workspace_id=workspace_id,
            external_system=body.external_system,
            external_id=body.external_id,
            relationship_type=body.relationship_type,
            external_name=body.external_name,
            external_url=body.external_url,
            status=body.status,
            meta=body.meta,
        )
    return {"relationship": relationship}


@router.post("/workspaces/{workspace_id}/connect")
async def connectors_connect_workspace(workspace_id: int, body: WorkspaceConnectorConnectRequest):
    async with get_db() as db:
        project = await get_project(db, workspace_id)
        if not project:
            raise HTTPException(404, "Workspace not found")
        try:
            result = await connect_workspace_connector(
                db,
                workspace=row_dict(project),
                external_system=body.external_system,
                external_id=body.external_id,
                relationship_type=body.relationship_type,
                external_name=body.external_name,
                external_url=body.external_url,
                status=body.status,
                token=body.token,
                secret=body.secret,
                url=body.url,
                org_slug=body.org_slug,
                project_slugs=body.project_slugs,
                mode=body.mode,
                auth=body.auth,
                meta=body.meta,
                set_setting_fn=devdb.set_setting,
                get_setting_fn=devdb.get_setting,
                link_workspace_relationship_fn=link_workspace_relationship,
                infer_workspace_relationships_fn=infer_workspace_relationships,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        summary = await workspace_connector_summary(
            db,
            workspace_id=workspace_id,
            get_project_fn=get_project,
            list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
            attention_summary_fn=attention_summary,
        )
    return {**result, "summary": summary}


@router.post("/workspaces/{workspace_id}/reconcile")
async def connectors_reconcile_workspace(
    workspace_id: int,
    body: WorkspaceConnectorReconcileRequest | None = None,
):
    request = body or WorkspaceConnectorReconcileRequest()
    async with get_db() as db:
        project = await get_project(db, workspace_id)
        if not project:
            raise HTTPException(404, "Workspace not found")
        try:
            return await reconcile_workspace_connectors(
                db,
                workspace_id=workspace_id,
                persist_inferred=request.persist_inferred,
                allow_repo_writes=request.allow_repo_writes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@router.get("/github/status")
async def github_status(
    workspace_id: int | None = None,
    repo_path: str = "",
    branch: str = "",
):
    async with get_db() as db:
        if workspace_id is None and not repo_path.strip():
            raise HTTPException(400, "Provide workspace_id or repo_path")
        if workspace_id is not None:
            try:
                return await github_status_for_workspace(db, workspace_id, branch=branch)
            except ValueError as exc:
                raise HTTPException(404, str(exc))
        settings = await devdb.get_all_settings(db)
        token = settings.get("github_token", "")
        normalized_repo = normalize_repo_cwd(repo_path)
        status = await integ.github_full_status(normalized_repo, token)
        workflow_preview = {}
        if branch.strip():
            cwd, command = read_workflow_status(repo_path=normalized_repo, branch_name=branch)
            workflow_preview = {"cwd": cwd, "command": command}
        return {
            "workspace": None,
            "repo_path": normalized_repo,
            "relationships": [],
            "github": status,
            "workflow_preview": workflow_preview,
        }


@router.get("/github/workspaces/{workspace_id}/status")
async def github_workspace_status(workspace_id: int, branch: str = ""):
    async with get_db() as db:
        try:
            return await github_status_for_workspace(db, workspace_id, branch=branch)
        except ValueError as exc:
            raise HTTPException(404, str(exc))


@router.post("/github/workspaces/{workspace_id}/attention-sync")
async def github_workspace_attention_sync(workspace_id: int):
    async with get_db() as db:
        items = await sync_github_attention(db, workspace_id=workspace_id)
    return {"ingested": len(items), "items": items}


@router.get("/github/workspaces/{workspace_id}/workflow-preview")
async def github_workflow_preview(workspace_id: int, branch: str = ""):
    async with get_db() as db:
        project = await get_project(db, workspace_id)
        if not project:
            raise HTTPException(404, "Workspace not found")
        project_dict = row_dict(project)
        repo_path = normalize_repo_cwd(str(project_dict.get("path") or ""))
        cwd, command = read_workflow_status(repo_path=repo_path, branch_name=branch)
    return {"workspace": project_dict, "cwd": cwd, "command": command}


@router.get("/vercel/status")
async def vercel_status(workspace_id: int | None = None):
    async with get_db() as db:
        if workspace_id is None:
            workspaces = await connector_workspaces_for_system(
                db,
                external_system="vercel",
                limit=100,
                get_projects_fn=get_projects,
                get_project_fn=get_project,
                list_workspace_relationships_fn=list_workspace_relationships,
                list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
                attention_summary_fn=attention_summary,
            )
            return {"workspaces": workspaces}
        project = await get_project(db, workspace_id)
        relationships = await list_workspace_relationships_for_workspace(
            db,
            workspace_id=workspace_id,
            external_system="vercel",
            limit=50,
        )
        inbox = await attention_summary(db, workspace_id=workspace_id, limit=50)
    return {
        "workspace": row_dict(project),
        "relationships": relationships,
        "attention": inbox,
        "status": "linked" if relationships else "unlinked",
    }


@router.get("/vercel/workspaces/{workspace_id}/status")
async def vercel_workspace_status(workspace_id: int):
    return await vercel_status(workspace_id=workspace_id)


@router.post("/vercel/workspaces/{workspace_id}/attention-sync")
async def vercel_workspace_attention_sync(workspace_id: int):
    async with get_db() as db:
        items = await sync_vercel_attention(db, workspace_id=workspace_id)
    return {"ingested": len(items), "items": items}


@router.get("/sentry/status")
async def sentry_status(workspace_id: int | None = None, limit: int = 25):
    async with get_db() as db:
        if workspace_id is None:
            workspaces = await connector_workspaces_for_system(
                db,
                external_system="sentry",
                limit=max(100, limit),
                get_projects_fn=get_projects,
                get_project_fn=get_project,
                list_workspace_relationships_fn=list_workspace_relationships,
                list_workspace_relationships_for_workspace_fn=list_workspace_relationships_for_workspace,
                attention_summary_fn=attention_summary,
            )
            unresolved = await list_error_events(db, source="sentry", status="", limit=limit)
            return {"workspaces": workspaces, "unresolved": unresolved}
        project = await get_project(db, workspace_id)
        relationships = await list_workspace_relationships_for_workspace(
            db,
            workspace_id=workspace_id,
            external_system="sentry",
            limit=50,
        )
        unresolved = await list_error_events(db, source="sentry", status="", limit=limit)
        inbox = await attention_summary(db, workspace_id=workspace_id, limit=50)
    return {
        "workspace": row_dict(project),
        "relationships": relationships,
        "attention": inbox,
        "unresolved": unresolved,
        "status": "linked" if relationships else "unlinked",
    }


@router.get("/sentry/workspaces/{workspace_id}/status")
async def sentry_workspace_status(workspace_id: int, limit: int = 25):
    return await sentry_status(workspace_id=workspace_id, limit=limit)


@router.post("/sentry/workspaces/{workspace_id}/attention-sync")
async def sentry_workspace_attention_sync(workspace_id: int, limit: int = 25):
    async with get_db() as db:
        items = await sync_sentry_attention(db, workspace_id=workspace_id, limit=limit)
    return {"ingested": len(items), "items": items}


@router.post("/sentry/poll")
async def sentry_poll():
    from axon_api.services.sentry_bridge import poll_sentry_issues

    ingested = await poll_sentry_issues()
    return {"ingested": len(ingested), "issues": ingested}


@router.post("/attention/sync")
async def connectors_attention_sync(workspace_id: int | None = None, limit: int = 25):
    async with get_db() as db:
        if workspace_id is None:
            items = await sync_all_connector_attention(db, limit=limit)
        else:
            items = await sync_workspace_connector_attention(db, workspace_id=workspace_id, limit=limit)
    return {"ingested": len(items), "items": items}
