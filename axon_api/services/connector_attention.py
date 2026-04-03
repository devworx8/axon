"""Normalize GitHub, Vercel, and Sentry signals into attention items."""

from __future__ import annotations

import json
from typing import Any

import db as devdb
import integrations as integ
from axon_api.services.attention_ingest import ingest_attention_signal
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_core.github_orchestrator import normalize_repo_cwd
from axon_data import get_project, get_projects, get_unresolved_errors


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    payload = str(raw or "").strip()
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _workspace_name(project: dict[str, Any]) -> str:
    return str(project.get("name") or project.get("project_name") or "Workspace").strip() or "Workspace"


async def sync_github_attention(db, *, workspace_id: int) -> list[dict[str, Any]]:
    project = _row(await get_project(db, workspace_id))
    repo_path = str(project.get("path") or "").strip()
    if not repo_path:
        return []

    settings = await devdb.get_all_settings(db)
    status = await integ.github_full_status(normalize_repo_cwd(repo_path), settings.get("github_token", ""))
    items: list[dict[str, Any]] = []
    workspace_name = _workspace_name(project)

    latest_ci = dict((status.get("ci") or {}).get("latest") or {})
    ci_state = str(latest_ci.get("conclusion") or latest_ci.get("status") or "").strip().lower()
    if ci_state in {"failure", "failed", "cancelled", "timed_out", "action_required"}:
        items.append(
            await ingest_attention_signal(
                db,
                source="github",
                external_system="github",
                external_id=str((status.get("repo") or {}).get("nameWithOwner") or "").strip(),
                source_event_id=str(latest_ci.get("url") or latest_ci.get("createdAt") or ci_state),
                item_type="github_ci",
                title=f"GitHub CI needs attention for {workspace_name}",
                summary=str(latest_ci.get("name") or "Latest workflow run failed").strip(),
                detail=f"{workspace_name}: latest workflow concluded as {ci_state}.",
                workspace_id=workspace_id,
                project_name=workspace_name,
                severity="high",
                status="new",
                link_url=str(latest_ci.get("url") or "").strip(),
                meta={
                    "ci": latest_ci,
                    "repo": status.get("repo") or {},
                },
            )
        )

    review_prs = [
        dict(pr)
        for pr in list(status.get("prs") or [])
        if str(dict(pr).get("reviewDecision") or "").strip().upper() in {"CHANGES_REQUESTED", "REVIEW_REQUIRED"}
    ]
    if review_prs:
        first_pr = review_prs[0]
        items.append(
            await ingest_attention_signal(
                db,
                source="github",
                external_system="github",
                external_id=str((status.get("repo") or {}).get("nameWithOwner") or "").strip(),
                source_event_id="review-needed",
                item_type="github_pr_review",
                title=f"GitHub PR review needs attention for {workspace_name}",
                summary=f"{len(review_prs)} open PR(s) need review follow-up.",
                detail="; ".join(
                    f"#{pr.get('number')}: {str(pr.get('title') or '').strip()}"
                    for pr in review_prs[:3]
                ),
                workspace_id=workspace_id,
                project_name=workspace_name,
                severity="medium",
                status="new",
                link_url=str(first_pr.get("url") or "").strip(),
                meta={
                    "prs": review_prs,
                    "repo": status.get("repo") or {},
                },
            )
        )

    return items


async def sync_vercel_attention(db, *, workspace_id: int) -> list[dict[str, Any]]:
    project = _row(await get_project(db, workspace_id))
    workspace_name = _workspace_name(project)
    relationships = await list_workspace_relationships_for_workspace(
        db,
        workspace_id=workspace_id,
        external_system="vercel",
        limit=20,
    )
    if not relationships:
        return []

    active_links = [rel for rel in relationships if str(rel.get("source") or "").strip().lower() == "persisted"]
    inferred_links = [rel for rel in relationships if str(rel.get("status") or "").strip().lower() == "inferred"]
    if active_links or not inferred_links:
        return []

    first_link = inferred_links[0]
    meta = _parse_meta(first_link.get("meta_json"))
    external_id = str(first_link.get("external_id") or meta.get("project_id") or "").strip()
    return [
        await ingest_attention_signal(
            db,
            source="vercel",
            external_system="vercel",
            external_id=external_id,
            source_event_id=external_id or "relationship-inferred",
            item_type="vercel_link_review",
            title=f"Confirm Vercel link for {workspace_name}",
            summary="Vercel was inferred from local project metadata and should be confirmed.",
            detail=f"{workspace_name} has a Vercel relationship inferred from .vercel/project.json.",
            workspace_id=workspace_id,
            project_name=workspace_name,
            severity="low",
            status="new",
            link_url=str(first_link.get("external_url") or "").strip(),
            meta={"relationship": first_link},
        )
    ]


async def sync_sentry_attention(db, *, workspace_id: int, limit: int = 25) -> list[dict[str, Any]]:
    project = _row(await get_project(db, workspace_id))
    workspace_name = _workspace_name(project)
    unresolved = await get_unresolved_errors(db, source="sentry", workspace_id=workspace_id, limit=limit)
    if not unresolved:
        return []

    first = unresolved[0]
    meta = _parse_meta(first.get("meta_json"))
    return [
        await ingest_attention_signal(
            db,
            source="sentry",
            external_system="sentry",
            external_id=str(first.get("project_name") or "").strip(),
            source_event_id=str(first.get("event_id") or first.get("id") or "").strip(),
            item_type="sentry_issue",
            title=f"Sentry issues need attention for {workspace_name}",
            summary=f"{len(unresolved)} unresolved Sentry issue(s) detected.",
            detail="; ".join(str(item.get("title") or "").strip() for item in unresolved[:3]),
            workspace_id=workspace_id,
            project_name=workspace_name,
            severity="high",
            status="new",
            link_url=str(meta.get("sentry_link") or "").strip(),
            meta={"issues": unresolved[:5]},
        )
    ]


async def sync_workspace_connector_attention(
    db,
    *,
    workspace_id: int,
    limit: int = 25,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(await sync_github_attention(db, workspace_id=workspace_id))
    items.extend(await sync_vercel_attention(db, workspace_id=workspace_id))
    items.extend(await sync_sentry_attention(db, workspace_id=workspace_id, limit=limit))
    return items


async def sync_all_connector_attention(db, *, limit: int = 25, max_workspaces: int = 50) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    projects = await get_projects(db, status="active")
    for project in list(projects or [])[: max(1, max_workspaces)]:
        workspace_id = int(project["id"])
        items.extend(await sync_workspace_connector_attention(db, workspace_id=workspace_id, limit=limit))
    return items
