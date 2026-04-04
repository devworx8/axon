"""Browser runtime session and proposal state helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import HTTPException


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_browser_session() -> dict[str, object]:
    return {
        "connected": False,
        "url": "",
        "title": "",
        "last_seen_at": "",
        "mode": "approval_required",
        "control_owner": "manual",
        "control_state": "idle",
        "ownership_label": "Manual browser",
        "attached_preview_url": "",
        "attached_preview_status": "",
        "attached_workspace_id": None,
        "attached_workspace_name": "",
        "attached_auto_session_id": "",
        "attached_scope_key": "",
        "attached_source_workspace_path": "",
    }


def normalize_browser_session(session: dict | None = None, **updates: object) -> dict[str, object]:
    item = {**default_browser_session(), **(session or {})}
    for key, value in updates.items():
        if value is not None:
            item[key] = value

    mode = str(item.get("mode") or "approval_required").strip().lower()
    item["mode"] = mode if mode in {"approval_required", "inspect_auto"} else "approval_required"

    owner = str(item.get("control_owner") or "manual").strip().lower()
    item["control_owner"] = "axon" if owner == "axon" else "manual"
    item["connected"] = bool(item.get("connected"))
    item["url"] = str(item.get("url") or "")
    item["title"] = str(item.get("title") or "")
    item["last_seen_at"] = str(item.get("last_seen_at") or "")
    item["attached_preview_url"] = str(item.get("attached_preview_url") or "")
    item["attached_preview_status"] = str(item.get("attached_preview_status") or "")
    item["attached_workspace_name"] = str(item.get("attached_workspace_name") or "")
    item["attached_auto_session_id"] = str(item.get("attached_auto_session_id") or "")
    item["attached_scope_key"] = str(item.get("attached_scope_key") or "")
    item["attached_source_workspace_path"] = str(item.get("attached_source_workspace_path") or "")

    workspace_id = item.get("attached_workspace_id")
    if workspace_id in ("", 0, "0"):
        item["attached_workspace_id"] = None

    if item["control_owner"] == "axon":
        item["ownership_label"] = "Axon controls this browser now"
    else:
        item["ownership_label"] = "Manual browser"
        item["attached_preview_url"] = ""
        item["attached_preview_status"] = ""
        item["attached_workspace_id"] = None
        item["attached_workspace_name"] = ""
        item["attached_auto_session_id"] = ""
        item["attached_scope_key"] = ""
        item["attached_source_workspace_path"] = ""

    control_state = str(item.get("control_state") or "").strip().lower()
    if control_state not in {"idle", "attached", "blocked"}:
        control_state = "attached" if item["control_owner"] == "axon" and item["connected"] else ("connected" if item["connected"] else "idle")
    item["control_state"] = control_state
    return item


BROWSER_ACTION_STATE: dict[str, Any] = {
    "session": default_browser_session(),
    "proposals": [],
    "history": [],
    "next_id": 1,
}

_BROWSER_ALLOWED_ACTION_TYPES = {
    "navigate",
    "click",
    "type",
    "scroll",
    "screenshot",
    "inspect",
    "wait",
    "go_back",
    "go_forward",
    "evaluate",
}


def serialize_browser_action_state(browser_action_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = browser_action_state or BROWSER_ACTION_STATE
    proposals = sorted(
        state["proposals"],
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
    history = sorted(
        state["history"],
        key=lambda item: item.get("updated_at", item.get("created_at", "")),
        reverse=True,
    )
    session = normalize_browser_session(state["session"])
    return {
        "session": session,
        "pending_count": sum(1 for item in proposals if item.get("status") == "pending"),
        "proposals": [dict(item) for item in proposals[:20]],
        "history": [dict(item) for item in history[:20]],
        "approval_mode": session.get("mode", "approval_required"),
    }


def next_browser_action_id(browser_action_state: dict[str, Any] | None = None) -> int:
    state = browser_action_state or BROWSER_ACTION_STATE
    current = int(state.get("next_id") or 1)
    state["next_id"] = current + 1
    return current


def normalize_browser_action_payload(action: dict[str, object]) -> dict[str, object]:
    action_type = str(action.get("action_type") or "inspect").strip().lower()
    if action_type not in _BROWSER_ALLOWED_ACTION_TYPES:
        raise HTTPException(400, f"Unsupported browser action_type: {action_type}")

    risk = str(action.get("risk") or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"

    normalized: dict[str, object] = {
        "action_type": action_type,
        "summary": str(action.get("summary") or "Browser action requested").strip() or "Browser action requested",
        "target": str(action.get("target") or "").strip(),
        "value": str(action.get("value") or "").strip(),
        "url": str(action.get("url") or "").strip(),
        "risk": risk,
        "scope": str(action.get("scope") or "browser_act").strip().lower() or "browser_act",
        "requires_confirmation": bool(action.get("requires_confirmation", True)),
        "metadata": action.get("metadata") if isinstance(action.get("metadata"), dict) else {},
    }
    for key in ("id", "created_at", "updated_at", "status", "executed_at", "execution_result"):
        if key not in action or action.get(key) is None:
            continue
        normalized[key] = action.get(key)
    return normalized


def find_approved_browser_action(proposal_id: int, browser_action_state: dict[str, Any] | None = None) -> Optional[dict]:
    state = browser_action_state or BROWSER_ACTION_STATE
    for item in state["history"] or []:
        if int(item.get("id") or 0) == proposal_id and str(item.get("status") or "") == "approved":
            return item
    return None


def release_browser_preview_attachment(
    preview: dict | None = None,
    *,
    browser_action_state: dict[str, Any] | None = None,
) -> None:
    state = browser_action_state or BROWSER_ACTION_STATE
    session = normalize_browser_session(state.get("session") or {})
    preview_url = str((preview or {}).get("url") or "")
    scope_key = str((preview or {}).get("scope_key") or "")
    if preview_url and session.get("attached_preview_url") not in {"", preview_url}:
        return
    if scope_key and session.get("attached_scope_key") not in {"", scope_key}:
        return
    state["session"] = normalize_browser_session(
        session,
        control_owner="manual",
        control_state="connected" if session.get("connected") else "idle",
    )


async def attach_preview_browser(
    url: str,
    *,
    preview: dict | None = None,
    workspace: dict | None = None,
    auto_meta: dict | None = None,
    browser_action_state: dict[str, Any] | None = None,
) -> dict[str, object]:
    if not url:
        return {"attached": False, "result": "No preview URL available"}

    state = browser_action_state or BROWSER_ACTION_STATE
    try:
        import browser_bridge

        bridge = browser_bridge.get_bridge()
        if not bridge.is_running:
            await bridge.start(headless=False)
        result = await bridge.execute_action({"action_type": "navigate", "url": url})
        bridge_status = bridge.status()
        state["session"] = normalize_browser_session(
            state["session"],
            connected=bool(result.get("success")),
            url=url,
            title=str(bridge_status.get("title") or state["session"].get("title") or ""),
            last_seen_at=_now_iso(),
            control_owner="axon" if result.get("success") else "manual",
            control_state="attached" if result.get("success") else "blocked",
            attached_preview_url=url,
            attached_preview_status=str((preview or {}).get("status") or ""),
            attached_workspace_id=int((workspace or {}).get("id") or 0) or None,
            attached_workspace_name=str((workspace or {}).get("name") or (auto_meta or {}).get("workspace_name") or ""),
            attached_auto_session_id=str((auto_meta or {}).get("session_id") or ""),
            attached_scope_key=str((preview or {}).get("scope_key") or ""),
            attached_source_workspace_path=str((preview or {}).get("source_workspace_path") or (workspace or {}).get("path") or ""),
        )
        return {"attached": bool(result.get("success")), "result": result}
    except Exception as exc:
        return {"attached": False, "result": str(exc)}
