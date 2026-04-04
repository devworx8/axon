"""Public companion-status summary helpers."""

from __future__ import annotations

from typing import Any


def build_latest_presence_payload(latest_presence: dict[str, Any] | None) -> dict[str, Any] | None:
    if not latest_presence:
        return None
    device_meta = dict(latest_presence.get("_device") or {})
    return {
        "device_id": int(latest_presence.get("device_id") or 0),
        "device_name": str(device_meta.get("name") or "").strip(),
        "device_platform": str(device_meta.get("platform") or "").strip(),
        "presence_state": str(latest_presence.get("presence_state") or "").strip(),
        "voice_state": str(latest_presence.get("voice_state") or "").strip(),
        "app_state": str(latest_presence.get("app_state") or "").strip(),
        "active_route": str(latest_presence.get("active_route") or "").strip(),
        "workspace_id": latest_presence.get("workspace_id"),
        "session_id": latest_presence.get("session_id"),
        "last_seen_at": str(latest_presence.get("last_seen_at") or ""),
        "active_recently": bool(latest_presence.get("_active_recently")),
        "meta_json": str(latest_presence.get("meta_json") or ""),
    }
