"""Shared Mission Control snapshot sections for mobile surfaces."""

from __future__ import annotations

from typing import Any

from axon_api.services import live_preview_sessions as live_preview_service
from axon_api.services.attention_query import attention_summary
from axon_api.services.browser_runtime_state import serialize_browser_action_state
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_api.services.workspace_sandbox_state import serialize_preview_session
from axon_data import get_all_settings, get_projects, list_attention_items


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def project_payload(project: dict[str, Any] | None) -> dict[str, Any]:
    project = dict(project or {})
    if not project:
        return {}
    return {
        "id": project.get("id"),
        "name": str(project.get("name") or "").strip(),
        "path": str(project.get("path") or "").strip(),
        "git_branch": str(project.get("git_branch") or "").strip(),
        "status": str(project.get("status") or "").strip(),
    }


def status_payload(
    key: str,
    label: str,
    *,
    status: str,
    summary: str,
    linked: bool = False,
    urgent: bool = False,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "linked": linked,
        "urgent": urgent,
        "summary": summary,
        "meta": meta or {},
    }


async def build_workspace_cards(
    db,
    *,
    limit: int = 8,
    focus_workspace_id: int | None = None,
    focus_expo: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    projects = await get_projects(db, status="active")
    cards: list[dict[str, Any]] = []
    for project in list(projects or [])[: max(1, limit)]:
        workspace = row_dict(project)
        workspace_id = int(workspace.get("id") or 0)
        relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, limit=12)
        attention = await attention_summary(db, workspace_id=workspace_id, limit=8)
        cards.append(
            {
                "workspace": project_payload(workspace),
                "preview": serialize_preview_session(
                    live_preview_service.get_preview_session(workspace_id=workspace_id)
                ),
                "relationships": relationships,
                "attention": attention,
                "expo": (
                    dict(focus_expo or {})
                    if focus_workspace_id and workspace_id == focus_workspace_id and focus_expo
                    else None
                ),
            }
        )
    return cards


async def build_system_strip(
    db,
    *,
    workspace_id: int | None,
    live_snapshot: dict[str, Any],
    expo_overview: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    relationships = []
    if workspace_id:
        relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, limit=20)
    relationship_systems = {
        str(item.get("external_system") or "").strip().lower()
        for item in relationships
    }

    def relation_exists(name: str) -> bool:
        return name in relationship_systems

    async def source_attention(source: str) -> list[dict[str, Any]]:
        rows = await list_attention_items(db, workspace_id=workspace_id, source=source, limit=10)
        return [
            dict(row)
            for row in rows
            if str(dict(row).get("status") or "").strip().lower()
            not in {"resolved", "ignored", "dismissed"}
        ]

    github_items = await source_attention("github")
    vercel_items = await source_attention("vercel")
    sentry_items = await source_attention("sentry")
    runtime_items = await source_attention("runtime")
    browser_items = await source_attention("browser")

    browser_state = serialize_browser_action_state()
    settings = await get_all_settings(db)
    runtime_label = str(settings.get("ai_backend") or "api").strip().lower() or "api"
    runtime_mode = str(settings.get("runtime_permissions_mode") or "default").strip().lower() or "default"
    operator = dict(live_snapshot.get("operator") or {})
    expo_projects = list(dict(expo_overview or {}).get("projects") or [])
    expo_project = (
        next(
            (
                item
                for item in expo_projects
                if int(item.get("workspace_id") or 0) == int(workspace_id or 0)
            ),
            None,
        )
        if workspace_id
        else (expo_projects[0] if expo_projects else None)
    )
    expo_status = str((expo_project or {}).get("status") or dict(expo_overview or {}).get("status") or "").strip().lower()
    expo_linked = bool((expo_project or {}).get("project_id") or (expo_project or {}).get("slug"))
    expo_summary = str((expo_project or {}).get("project_name") or "").strip()
    if not expo_summary:
        expo_summary = str(dict(expo_overview or {}).get("summary") or "Expo / EAS not linked").strip()

    return [
        status_payload(
            "github",
            "GitHub",
            status="attention" if github_items else ("linked" if relation_exists("github") else "unlinked"),
            summary=(
                github_items[0].get("title")
                if github_items
                else ("Repository linked" if relation_exists("github") else "No GitHub relationship")
            ),
            linked=relation_exists("github"),
            urgent=bool(github_items),
        ),
        status_payload(
            "vercel",
            "Vercel",
            status="attention" if vercel_items else ("linked" if relation_exists("vercel") else "unlinked"),
            summary=(
                vercel_items[0].get("title")
                if vercel_items
                else ("Project linked" if relation_exists("vercel") else "No Vercel project linked")
            ),
            linked=relation_exists("vercel"),
            urgent=bool(vercel_items),
        ),
        status_payload(
            "sentry",
            "Sentry",
            status="attention" if sentry_items else ("linked" if relation_exists("sentry") else "unlinked"),
            summary=(
                sentry_items[0].get("title")
                if sentry_items
                else ("Monitoring linked" if relation_exists("sentry") else "No Sentry project linked")
            ),
            linked=relation_exists("sentry"),
            urgent=bool(sentry_items),
        ),
        status_payload(
            "expo",
            "Expo / EAS",
            status=expo_status or ("linked" if expo_linked else "unlinked"),
            summary=expo_summary,
            linked=expo_linked,
            urgent=expo_status in {"blocked", "expo_auth_failed", "expo_cli_failed"},
        ),
        status_payload(
            "runtime",
            "Axon runtime",
            status="live" if operator.get("active") else ("attention" if runtime_items else "ready"),
            summary=f"{runtime_label.upper()} backend · permissions {runtime_mode.replace('_', ' ')}",
            linked=True,
            urgent=bool(runtime_items),
            meta={"permissions_mode": runtime_mode},
        ),
        status_payload(
            "browser",
            "Browser / preview",
            status=(
                "connected"
                if browser_state.get("session", {}).get("connected")
                else ("attention" if browser_items else "idle")
            ),
            summary=str(
                browser_state.get("session", {}).get("ownership_label") or "No browser attached"
            ),
            linked=bool(browser_state.get("session", {}).get("connected")),
            urgent=bool(browser_items),
        ),
        status_payload(
            "tasks",
            "Tasks / sandbox",
            status="active" if operator.get("active") else "idle",
            summary=str(operator.get("title") or "No active task orchestration"),
            linked=True,
            urgent=False,
        ),
    ]
