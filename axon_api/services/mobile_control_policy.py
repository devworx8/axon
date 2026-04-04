"""Typed action catalog and risk policy for Axon Online mobile control."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from axon_data import get_control_capability, list_control_capabilities, upsert_control_capability

RISK_ORDER = {
    "observe": 0,
    "act": 1,
    "destructive": 2,
    "break_glass": 3,
}

CONTROL_CAPABILITY_CATALOG: list[dict[str, Any]] = [
    {
        "action_type": "workspace.inspect",
        "system_name": "workspace",
        "scope": "workspace",
        "risk_tier": "observe",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Inspect the active workspace and return a concise operational summary.",
        "meta": {"quick_action": "inspect", "label": "Inspect workspace"},
    },
    {
        "action_type": "workspace.run_agent",
        "system_name": "workspace",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": False,
        "destructive": False,
        "available": True,
        "description": "Run an Axon command or agent task against the focused workspace.",
        "meta": {"quick_action": "talk", "label": "Talk to Axon"},
    },
    {
        "action_type": "workspace.connectors.reconcile",
        "system_name": "connectors",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Inspect and safely repair connector state for the focused workspace.",
        "meta": {"quick_action": "repair", "label": "Repair connectors"},
    },
    {
        "action_type": "workspace.preview.restart",
        "system_name": "preview",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Restart or launch the focused workspace preview from mobile.",
        "meta": {"quick_action": "preview", "label": "Restart preview"},
    },
    {
        "action_type": "workspace.preview.stop",
        "system_name": "preview",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Stop the focused workspace preview from mobile.",
        "meta": {"label": "Stop preview"},
    },
    {
        "action_type": "workspace.focus.set",
        "system_name": "workspace",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Move mobile focus to a different workspace.",
        "meta": {"quick_action": "focus", "label": "Open workspace"},
    },
    {
        "action_type": "attention.resolve",
        "system_name": "attention",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Resolve an attention item from mobile.",
        "meta": {"label": "Resolve item"},
    },
    {
        "action_type": "attention.sync",
        "system_name": "attention",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": False,
        "destructive": False,
        "available": True,
        "description": "Refresh connector-backed attention signals.",
        "meta": {"quick_action": "sync", "label": "Sync signals"},
    },
    {
        "action_type": "agent.approve",
        "system_name": "agent",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": False,
        "destructive": False,
        "available": True,
        "description": "Approve the exact blocked action and resume the interrupted Axon run.",
        "meta": {"quick_action": "approve", "label": "Approve pending"},
    },
    {
        "action_type": "session.resume",
        "system_name": "session",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Refresh and resume the focused mobile session.",
        "meta": {"label": "Resume session"},
    },
    {
        "action_type": "session.stop",
        "system_name": "session",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Close the focused mobile session and stand Axon down on mobile.",
        "meta": {"quick_action": "stop", "label": "Stop current run"},
    },
    {
        "action_type": "runtime.permissions.set",
        "system_name": "runtime",
        "scope": "global",
        "risk_tier": "destructive",
        "mobile_direct_allowed": False,
        "destructive": True,
        "available": True,
        "description": "Change Axon's runtime permission mode from mobile.",
        "meta": {"quick_action": "permissions", "label": "Change permissions"},
    },
    {
        "action_type": "runtime.restart",
        "system_name": "runtime",
        "scope": "global",
        "risk_tier": "destructive",
        "mobile_direct_allowed": False,
        "destructive": True,
        "available": True,
        "description": "Restart the Axon runtime safely.",
        "meta": {"quick_action": "restart", "label": "Restart runtime"},
    },
    {
        "action_type": "expo.project.status",
        "system_name": "expo",
        "scope": "workspace",
        "risk_tier": "observe",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "Inspect the linked Expo / EAS project and credential state.",
        "meta": {"label": "Expo status"},
    },
    {
        "action_type": "expo.build.list",
        "system_name": "expo",
        "scope": "workspace",
        "risk_tier": "observe",
        "mobile_direct_allowed": True,
        "destructive": False,
        "available": True,
        "description": "List recent Expo / EAS builds for the focused workspace.",
        "meta": {"label": "Expo builds"},
    },
    {
        "action_type": "expo.build.android.dev",
        "system_name": "expo",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": False,
        "destructive": False,
        "available": True,
        "description": "Queue an Android development build in Expo / EAS.",
        "meta": {"label": "Android dev build"},
    },
    {
        "action_type": "expo.build.ios.dev",
        "system_name": "expo",
        "scope": "workspace",
        "risk_tier": "act",
        "mobile_direct_allowed": False,
        "destructive": False,
        "available": True,
        "description": "Queue an iOS development build in Expo / EAS.",
        "meta": {"label": "iOS dev build"},
    },
    {
        "action_type": "expo.update.publish",
        "system_name": "expo",
        "scope": "workspace",
        "risk_tier": "destructive",
        "mobile_direct_allowed": False,
        "destructive": True,
        "available": True,
        "description": "Publish an Expo over-the-air update from mobile.",
        "meta": {"label": "Publish update"},
    },
    {
        "action_type": "vercel.deploy.promote",
        "system_name": "vercel",
        "scope": "workspace",
        "risk_tier": "destructive",
        "mobile_direct_allowed": False,
        "destructive": True,
        "available": True,
        "description": "Promote a Vercel deployment from mobile.",
        "meta": {"quick_action": "deploy", "label": "Deploy"},
    },
    {
        "action_type": "vercel.deploy.rollback",
        "system_name": "vercel",
        "scope": "workspace",
        "risk_tier": "destructive",
        "mobile_direct_allowed": False,
        "destructive": True,
        "available": True,
        "description": "Rollback a Vercel deployment from mobile.",
        "meta": {"quick_action": "rollback", "label": "Rollback"},
    },
]

_SEED_LOCK = asyncio.Lock()


def _json_meta(meta: dict[str, Any] | None) -> str:
    return "{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True)


def risk_rank(value: str) -> int:
    return RISK_ORDER.get(str(value or "").strip().lower(), 0)


def risk_tier_at_least(value: str, target: str) -> bool:
    return risk_rank(value) >= risk_rank(target)


def challenge_required_for_risk(risk_tier: str) -> bool:
    return risk_tier_at_least(risk_tier, "destructive")


def capability_label(capability: dict[str, Any]) -> str:
    meta = parse_meta(capability.get("meta_json") or capability.get("meta") or {})
    return str(meta.get("label") or capability.get("action_type") or "").strip()


def parse_meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _catalog_action_types() -> set[str]:
    return {str(item.get("action_type") or "").strip() for item in CONTROL_CAPABILITY_CATALOG if str(item.get("action_type") or "").strip()}


def _row_matches_catalog(existing: dict[str, Any], capability: dict[str, Any]) -> bool:
    return (
        str(existing.get("system_name") or "") == str(capability.get("system_name") or "axon")
        and str(existing.get("scope") or "") == str(capability.get("scope") or "global")
        and str(existing.get("risk_tier") or "") == str(capability.get("risk_tier") or "observe")
        and bool(existing.get("mobile_direct_allowed")) == bool(capability.get("mobile_direct_allowed"))
        and bool(existing.get("destructive")) == bool(capability.get("destructive"))
        and bool(existing.get("available")) == bool(capability.get("available", True))
        and str(existing.get("description") or "") == str(capability.get("description") or "")
        and str(existing.get("meta_json") or "{}") == _json_meta(capability.get("meta") if isinstance(capability.get("meta"), dict) else {})
    )


def _rows_cover_catalog(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    existing_action_types = {str(row.get("action_type") or "").strip() for row in rows if str(row.get("action_type") or "").strip()}
    return _catalog_action_types().issubset(existing_action_types)


async def seed_control_capabilities(db) -> list[dict[str, Any]]:
    rows = [dict(row) for row in await list_control_capabilities(db, limit=250)]
    if _rows_cover_catalog(rows):
        return rows

    async with _SEED_LOCK:
        rows = [dict(row) for row in await list_control_capabilities(db, limit=250)]
        if _rows_cover_catalog(rows):
            return rows

        existing_by_action = {
            str(row.get("action_type") or "").strip(): row
            for row in rows
            if str(row.get("action_type") or "").strip()
        }
        changed = False
        for capability in CONTROL_CAPABILITY_CATALOG:
            action_type = str(capability.get("action_type") or "").strip()
            if not action_type:
                continue
            existing = existing_by_action.get(action_type)
            if existing and _row_matches_catalog(existing, capability):
                continue
            await upsert_control_capability(
                db,
                action_type=action_type,
                system_name=str(capability.get("system_name") or "axon"),
                scope=str(capability.get("scope") or "global"),
                risk_tier=str(capability.get("risk_tier") or "observe"),
                mobile_direct_allowed=bool(capability.get("mobile_direct_allowed")),
                destructive=bool(capability.get("destructive")),
                available=bool(capability.get("available", True)),
                description=str(capability.get("description") or ""),
                meta_json=_json_meta(capability.get("meta") if isinstance(capability.get("meta"), dict) else {}),
                commit=False,
            )
            changed = True
        if changed:
            await db.commit()
        rows = await list_control_capabilities(db, limit=250)
        return [dict(row) for row in rows]


async def get_seeded_control_capability(db, action_type: str) -> dict[str, Any] | None:
    row = await get_control_capability(db, action_type)
    if row:
        return dict(row)
    await seed_control_capabilities(db)
    row = await get_control_capability(db, action_type)
    return dict(row) if row else None


def capability_requires_elevation(capability: dict[str, Any]) -> bool:
    return challenge_required_for_risk(str(capability.get("risk_tier") or "observe"))


def mobile_control_capabilities() -> list[dict[str, Any]]:
    return [dict(item) for item in CONTROL_CAPABILITY_CATALOG]
