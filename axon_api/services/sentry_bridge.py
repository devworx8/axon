"""Axon — Sentry bridge service.

Polls Sentry's Issues API and ingests unresolved errors into axon_data.
Can also handle incoming Sentry webhooks when wired to a route.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from axon_data import get_setting, get_db, ingest_error_event
from axon_api.services.attention_ingest import ingest_attention_signal
from axon_api.services.workspace_relationships import resolve_workspace_for_connector_signal

log = logging.getLogger(__name__)


def _attention_severity(level: str) -> str:
    normalized = str(level or "error").strip().lower()
    if normalized in {"fatal", "critical"}:
        return "critical"
    if normalized in {"error"}:
        return "high"
    if normalized in {"warning", "warn"}:
        return "medium"
    return "low"


async def _get_sentry_settings() -> dict[str, str]:
    async with get_db() as db:
        token = await get_setting(db, "sentry_api_token")
        org = await get_setting(db, "sentry_org_slug")
        projects = await get_setting(db, "sentry_project_slugs")
    return {
        "token": token or "",
        "org": org or "",
        "projects": [p.strip() for p in (projects or "").split(",") if p.strip()],
    }


async def poll_sentry_issues() -> list[dict]:
    """Fetch unresolved issues from Sentry and ingest them."""
    cfg = await _get_sentry_settings()
    if not cfg["token"] or not cfg["org"]:
        log.debug("Sentry bridge: no token or org configured, skipping poll")
        return []

    ingested: list[dict] = []
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    base = "https://sentry.io/api/0"
    project_slugs = list(cfg["projects"])
    issue_targets = (
        [("organization", f"{base}/organizations/{cfg['org']}/issues/")]
        if not project_slugs
        else [("project", f"{base}/projects/{cfg['org']}/{project_slug}/issues/") for project_slug in project_slugs]
    )

    async with aiohttp.ClientSession(headers=headers) as session:
        for scope, url in issue_targets:
            params = {"query": "is:unresolved", "limit": "25"}
            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        log.warning("Sentry API %s returned %s", url, resp.status)
                        continue
                    issues = await resp.json()
            except Exception as exc:
                log.warning("Sentry poll failed for %s: %s", scope, exc)
                continue

            async with get_db() as db:
                for issue in issues:
                    project_slug = str(
                        issue.get("project", {}).get("slug")
                        or issue.get("projectSlug")
                        or ""
                    ).strip()
                    if not project_slug and scope == "project":
                        project_slug = url.rstrip("/").split("/")[-2]
                    workspace_id = await resolve_workspace_for_connector_signal(
                        db,
                        external_system="sentry",
                        external_id=project_slug,
                        project_name=project_slug,
                    )
                    meta = {
                        "sentry_link": issue.get("permalink", ""),
                        "culprit": issue.get("culprit", ""),
                        "platform": issue.get("platform", ""),
                        "short_id": issue.get("shortId", ""),
                    }
                    row_id = await ingest_error_event(
                        db,
                        source="sentry",
                        event_id=str(issue.get("id", "")),
                        title=issue.get("title", "Unknown"),
                        level=issue.get("level", "error"),
                        fingerprint=issue.get("culprit", ""),
                        project_name=project_slug,
                        workspace_id=workspace_id,
                        meta_json=json.dumps(meta),
                    )
                    await ingest_attention_signal(
                        db,
                        source="sentry",
                        external_system="sentry",
                        external_id=project_slug,
                        source_event_id=str(issue.get("id", "")),
                        item_type="sentry_issue",
                        title=issue.get("title", "Unknown"),
                        summary=f"{project_slug}: unresolved issue detected.",
                        detail=str(issue.get("culprit") or issue.get("metadata", {}).get("value") or "").strip(),
                        workspace_id=workspace_id,
                        project_name=project_slug,
                        severity=_attention_severity(issue.get("level", "error")),
                        status="new",
                        link_url=issue.get("permalink", ""),
                        meta=meta,
                    )
                    ingested.append({"id": row_id, "title": issue.get("title", "")})

    log.info("Sentry bridge: ingested %d issues", len(ingested))
    return ingested


async def handle_sentry_webhook(payload: dict[str, Any]) -> dict:
    """Process an inbound Sentry webhook payload."""
    action = payload.get("action", "")
    data = payload.get("data", {})
    issue = data.get("issue", {})
    if not issue:
        return {"status": "ignored", "reason": "no issue in payload"}

    project_slug = str(issue.get("project", {}).get("slug", "")).strip()

    async with get_db() as db:
        workspace_id = await resolve_workspace_for_connector_signal(
            db,
            external_system="sentry",
            external_id=project_slug,
            project_name=project_slug,
        )
        row_id = await ingest_error_event(
            db,
            source="sentry",
            event_id=str(issue.get("id", "")),
            title=issue.get("title", "Unknown"),
            level=issue.get("level", "error"),
            fingerprint=issue.get("culprit", ""),
            project_name=project_slug,
            workspace_id=workspace_id,
            meta_json=json.dumps({
                "action": action,
                "sentry_link": issue.get("permalink", ""),
            }),
        )
        await ingest_attention_signal(
            db,
            source="sentry",
            external_system="sentry",
            external_id=project_slug,
            source_event_id=str(issue.get("id", "")),
            item_type="sentry_issue",
            title=issue.get("title", "Unknown"),
            summary=f"{project_slug or 'Sentry'} webhook event: {action or 'issue update'}.",
            detail=str(issue.get("culprit") or "").strip(),
            workspace_id=workspace_id,
            project_name=project_slug,
            severity=_attention_severity(issue.get("level", "error")),
            status="new",
            link_url=issue.get("permalink", ""),
            meta={
                "action": action,
                "sentry_link": issue.get("permalink", ""),
            },
        )

    return {"status": "ingested", "id": row_id, "action": action}
