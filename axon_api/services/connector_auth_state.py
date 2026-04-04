"""Connector auth-state helpers for GitHub, Vercel, and Sentry."""
from __future__ import annotations

import os
from typing import Any

import db as devdb
from axon_api.services.vault_secret_lookup import vault_secret_status_by_name
from axon_data import get_setting


def _mask_secret(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "set"
    return f"{token[:4]}...{token[-4:]}"


async def github_auth_state(db) -> dict[str, Any]:
    settings = await devdb.get_all_settings(db)
    token = str(settings.get("github_token") or "").strip()
    return {
        "configured": bool(token),
        "source": "setting" if token else "",
        "present": bool(token),
        "masked_token": _mask_secret(token),
    }


async def vercel_auth_state(db) -> dict[str, Any]:
    setting_token = str(await get_setting(db, "vercel_api_token") or "").strip()
    if setting_token:
        return {
            "configured": True,
            "source": "setting",
            "present": True,
            "locked": False,
            "masked_token": _mask_secret(setting_token),
        }

    env_token = str(os.environ.get("AXON_VERCEL_TOKEN") or os.environ.get("VERCEL_TOKEN") or "").strip()
    if env_token:
        return {
            "configured": True,
            "source": "env",
            "present": True,
            "locked": False,
            "masked_token": _mask_secret(env_token),
        }

    status = await vault_secret_status_by_name(db, secret_names=("AXON_VERCEL_TOKEN",))
    value = str(status.get("value") or "").strip()
    return {
        "configured": bool(value),
        "source": "vault" if value else "",
        "present": bool(status.get("present")),
        "locked": bool(status.get("present")) and not bool(status.get("unlocked")),
        "masked_token": _mask_secret(value),
    }


async def sentry_auth_state(db) -> dict[str, Any]:
    token = str(await get_setting(db, "sentry_api_token") or "").strip()
    org = str(await get_setting(db, "sentry_org_slug") or "").strip()
    projects_raw = str(await get_setting(db, "sentry_project_slugs") or "").strip()
    projects = [item.strip() for item in projects_raw.split(",") if item.strip()]
    return {
        "configured": bool(token and org),
        "present": bool(token),
        "masked_token": _mask_secret(token),
        "org": org,
        "projects": projects,
        "project_count": len(projects),
    }
