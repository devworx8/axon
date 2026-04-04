"""Connector connection helpers for workspace-bound auth and relationship setup."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Callable


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_SYSTEM_ALIASES = {
    "gh": "github",
    "git_hub": "github",
    "github": "github",
    "sentry": "sentry",
    "slack": "slack",
    "webhook": "webhook",
    "webhooks": "webhook",
    "generic_webhook": "webhook",
    "dash_bridge": "dash_bridge",
    "dashbridge": "dash_bridge",
    "bridge": "dash_bridge",
    "ad_hoc": "adhoc",
    "ad_hoc_connector": "adhoc",
    "adhoc": "adhoc",
    "ad_hocs": "adhoc",
    "custom": "adhoc",
    "generic": "adhoc",
}


def normalize_connector_system(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if not cleaned:
        return ""
    return _SYSTEM_ALIASES.get(cleaned, cleaned)


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def mask_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 10:
        return "set"
    return f"{raw[:4]}...{raw[-4:]}"


def _loads_json_object(raw: str) -> dict[str, Any]:
    payload = str(raw or "").strip()
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _relationship_defaults(
    workspace: dict[str, Any],
    *,
    external_system: str,
    infer_workspace_relationships_fn: Callable[[Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    for relationship in infer_workspace_relationships_fn(workspace):
        if normalize_connector_system(relationship.get("external_system", "")) == external_system:
            return dict(relationship)
    return {}


async def connect_workspace_connector(
    db,
    *,
    workspace: dict[str, Any],
    external_system: str,
    external_id: str = "",
    relationship_type: str = "primary",
    external_name: str = "",
    external_url: str = "",
    status: str = "active",
    token: str = "",
    secret: str = "",
    url: str = "",
    org_slug: str = "",
    project_slugs: str = "",
    mode: str = "",
    auth: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    set_setting_fn,
    get_setting_fn,
    link_workspace_relationship_fn,
    infer_workspace_relationships_fn,
) -> dict[str, Any]:
    workspace_id = int((workspace or {}).get("id") or 0)
    if workspace_id <= 0:
        raise ValueError("Workspace id is required before Axon can connect a connector.")

    system = normalize_connector_system(external_system)
    if not system:
        raise ValueError("external_system is required.")

    inferred = _relationship_defaults(
        workspace,
        external_system=system,
        infer_workspace_relationships_fn=infer_workspace_relationships_fn,
    )
    resolved_external_id = str(external_id or inferred.get("external_id") or "").strip()
    resolved_name = str(external_name or inferred.get("external_name") or system.replace("_", " ").title()).strip()
    resolved_url = str(external_url or inferred.get("external_url") or "").strip()
    meta_payload = dict(meta or {})
    saved_settings: dict[str, Any] = {}

    if system == "github":
        if token:
            await set_setting_fn(db, "github_token", token)
            saved_settings["github_token"] = mask_secret(token)
        if resolved_external_id and not resolved_url:
            resolved_url = f"https://github.com/{resolved_external_id}"
        meta_payload["auth_mode"] = "token" if token else "gh_cli_or_existing_token"
    elif system == "vercel":
        if token:
            await set_setting_fn(db, "vercel_api_token", token)
            saved_settings["vercel_api_token"] = mask_secret(token)
        if resolved_external_id:
            meta_payload["project_id"] = resolved_external_id
        if org_slug:
            meta_payload["org_id"] = org_slug
        if resolved_name:
            meta_payload["project_name"] = resolved_name
        meta_payload["auth_mode"] = "token" if token else "existing_token_or_env"
    elif system == "sentry":
        project_slug_list = split_csv(project_slugs or resolved_external_id)
        if token:
            await set_setting_fn(db, "sentry_api_token", token)
            saved_settings["sentry_api_token"] = mask_secret(token)
        if org_slug:
            await set_setting_fn(db, "sentry_org_slug", org_slug)
            saved_settings["sentry_org_slug"] = org_slug
        if project_slugs:
            await set_setting_fn(db, "sentry_project_slugs", ",".join(project_slug_list))
            saved_settings["sentry_project_slugs"] = project_slug_list
        if not resolved_external_id and project_slug_list:
            resolved_external_id = project_slug_list[0]
        if project_slug_list and not external_name:
            resolved_name = project_slug_list[0]
        if org_slug:
            meta_payload["org_slug"] = org_slug
        if project_slug_list:
            meta_payload["project_slugs"] = project_slug_list
        if org_slug and resolved_external_id and not resolved_url:
            resolved_url = f"https://sentry.io/organizations/{org_slug}/projects/{resolved_external_id}/"
    elif system == "slack":
        webhook_url = str(url or resolved_url).strip()
        if webhook_url:
            await set_setting_fn(db, "slack_webhook_url", webhook_url)
            saved_settings["slack_webhook_url"] = mask_secret(webhook_url)
            if not resolved_url:
                resolved_url = webhook_url
        meta_payload["delivery"] = "incoming_webhook"
    elif system == "webhook":
        webhook_urls = str(url or resolved_url).strip()
        if webhook_urls:
            await set_setting_fn(db, "webhook_urls", webhook_urls)
            saved_settings["webhook_urls"] = split_csv(webhook_urls)
            if not resolved_url:
                resolved_url = split_csv(webhook_urls)[0]
        if secret:
            await set_setting_fn(db, "webhook_secret", secret)
            saved_settings["webhook_secret"] = mask_secret(secret)
        meta_payload["delivery"] = "generic_webhook"
    elif system == "dash_bridge":
        bridge_url = str(url or resolved_url).strip()
        if bridge_url:
            await set_setting_fn(db, "dash_bridge_url", bridge_url)
            saved_settings["dash_bridge_url"] = bridge_url
            if not resolved_url:
                resolved_url = bridge_url
        if token:
            await set_setting_fn(db, "dash_bridge_token", token)
            saved_settings["dash_bridge_token"] = mask_secret(token)
        if mode:
            await set_setting_fn(db, "dash_bridge_mode", mode)
            saved_settings["dash_bridge_mode"] = mode
        await set_setting_fn(db, "dash_bridge_enabled", "1")
        saved_settings["dash_bridge_enabled"] = True
    else:
        credential_store = _loads_json_object(await get_setting_fn(db, "connector_credentials_json") or "")
        identifier = resolved_external_id or resolved_name or f"{system}-{workspace_id}"
        credential_key = f"{workspace_id}:{system}:{identifier}"
        credential_store[credential_key] = {
            "external_system": system,
            "external_id": resolved_external_id,
            "external_name": resolved_name,
            "external_url": str(url or resolved_url).strip(),
            "token": str(token or "").strip(),
            "secret": str(secret or "").strip(),
            "auth": dict(auth or {}),
            "updated_at": _now_iso(),
        }
        await set_setting_fn(
            db,
            "connector_credentials_json",
            json.dumps(credential_store, sort_keys=True, ensure_ascii=True),
        )
        meta_payload["credential_key"] = credential_key
        saved_settings["connector_credentials_json"] = credential_key

    if auth:
        meta_payload["auth_fields"] = sorted(str(key) for key in auth.keys())
    if mode:
        meta_payload["mode"] = mode
    if url and system not in {"slack", "webhook", "dash_bridge"}:
        meta_payload["url"] = str(url).strip()

    relationship = await link_workspace_relationship_fn(
        db,
        workspace_id=workspace_id,
        external_system=system,
        external_id=resolved_external_id,
        relationship_type=relationship_type,
        external_name=resolved_name,
        external_url=resolved_url,
        status=status,
        meta=meta_payload,
    )
    return {
        "relationship": relationship,
        "saved_settings": saved_settings,
        "workspace_id": workspace_id,
        "external_system": system,
    }
