"""Foreground Axon mode state for mobile command surfaces."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from axon_api.services.companion_presence import heartbeat_companion_presence
from axon_api.services.mobile_axon_state import (
    AXON_EVENT_TYPES,
    AXON_META_KEY,
    DEFAULT_ACTIVE_ROUTE,
    DEFAULT_WAKE_PHRASE,
    extract_axon_state,
    is_foreground_app_state,
    normalise_monitoring_state,
    normalise_app_state,
    normalise_voice_identity,
    normalise_voice_provider,
    normalise_wake_phrase,
    parse_meta,
    row_dict,
)
from axon_api.services.mobile_axon_voice import local_voice_snapshot, resolve_axon_voice_profile
from axon_data import get_all_settings, get_companion_presence


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_summary(state: dict[str, Any], voice_status: dict[str, Any]) -> str:
    provider_detail = str(state.get("voice_provider_detail") or "").strip()
    monitoring_state = str(state.get("monitoring_state") or "idle").replace("_", " ")
    if not state.get("armed"):
        return provider_detail or "Axon mode is standing by."
    if not voice_status.get("transcription_available"):
        return str(voice_status.get("detail") or "Local transcription is not ready.")
    if not is_foreground_app_state(state.get("app_state")):
        return "Axon mode is armed but paused because the app is backgrounded."
    if state.get("monitoring_state") == "engaged":
        command = str(state.get("last_command_text") or "").strip()
        return f"Wake phrase detected. {command or 'Awaiting a spoken command.'}"
    if state.get("monitoring_state") == "degraded":
        return str(state.get("degraded_reason") or state.get("last_error") or "Axon mode needs attention.")
    return f"Listening for '{state.get('wake_phrase')}' · {provider_detail or 'Speech route ready'}."


async def build_mobile_axon_snapshot(
    db,
    *,
    device_id: int,
    presence_row: Any | None = None,
) -> dict[str, Any]:
    presence = row_dict(presence_row) if presence_row is not None else row_dict(await get_companion_presence(db, device_id))
    state = extract_axon_state(presence)
    settings = dict(await get_all_settings(db) or {})
    voice_status = await local_voice_snapshot(db)
    local_voice_ready = bool(voice_status.get("transcription_available"))
    monitoring_state = str(state.get("monitoring_state") or "idle")
    degraded_reason = str(state.get("degraded_reason") or "")
    voice_profile = resolve_axon_voice_profile(
        settings,
        voice_status,
        preferred_provider=str(state.get("voice_provider_preference") or ""),
        preferred_voice=str(state.get("voice_identity_preference") or ""),
    )

    if state["armed"] and not local_voice_ready:
        monitoring_state = "degraded"
        degraded_reason = str(voice_status.get("detail") or "Local transcription is not ready.")
    elif state["armed"] and not is_foreground_app_state(state.get("app_state")):
        monitoring_state = "degraded"
        degraded_reason = "App left the foreground, so Axon mode paused."
    elif not state["armed"]:
        monitoring_state = "idle"

    resolved = {
        **state,
        "monitoring_state": monitoring_state,
        "available": bool(voice_status.get("available")),
        "foreground_only": True,
        "local_voice_ready": local_voice_ready,
        "voice_provider_preference": str(voice_profile.get("voice_provider_preference") or ""),
        "voice_provider": str(voice_profile.get("voice_provider") or "unavailable"),
        "voice_provider_ready": bool(voice_profile.get("voice_provider_ready")),
        "voice_provider_detail": str(voice_profile.get("voice_provider_detail") or ""),
        "voice_identity": str(voice_profile.get("voice_identity") or ""),
        "voice_identity_label": str(voice_profile.get("voice_identity_label") or ""),
        "local_voice_status": {
            "available": bool(voice_status.get("available")),
            "transcription_available": bool(voice_status.get("transcription_available")),
            "synthesis_available": bool(voice_status.get("synthesis_available")),
            "preferred_mode": str(voice_status.get("preferred_mode") or ""),
            "detail": str(voice_status.get("detail") or ""),
        },
        "degraded_reason": degraded_reason,
    }
    resolved["summary"] = _status_summary(resolved, voice_status)
    return resolved


async def _persist_axon_state(
    db,
    *,
    device_id: int,
    state_patch: dict[str, Any],
    workspace_id: int | None = None,
    session_id: int | None = None,
    active_route: str = "",
    app_state: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    current_presence = row_dict(await get_companion_presence(db, device_id))
    current_state = extract_axon_state(current_presence)
    merged_state = {
        **current_state,
        **{key: value for key, value in dict(state_patch or {}).items() if value is not None},
    }
    armed = bool(merged_state.get("armed"))
    merged_state["monitoring_state"] = normalise_monitoring_state(
        merged_state.get("monitoring_state"),
        armed=armed,
    )
    merged_state["wake_phrase"] = normalise_wake_phrase(merged_state.get("wake_phrase"))
    merged_state["voice_provider_preference"] = normalise_voice_provider(merged_state.get("voice_provider_preference"))
    merged_state["voice_identity_preference"] = normalise_voice_identity(merged_state.get("voice_identity_preference"))
    merged_state["foreground_only"] = True
    merged_state["updated_at"] = _now_iso()
    merged_state["active_route"] = str(active_route or merged_state.get("active_route") or current_presence.get("active_route") or DEFAULT_ACTIVE_ROUTE).strip()
    merged_state["app_state"] = normalise_app_state(
        app_state or merged_state.get("app_state") or current_presence.get("app_state") or "foreground"
    )

    next_meta = parse_meta(current_presence.get("meta_json"))
    next_meta[AXON_META_KEY] = merged_state

    next_monitoring_state = str(merged_state.get("monitoring_state") or "idle")
    next_voice_state = (
        "idle"
        if not armed
        else (
            "axon_degraded"
            if next_monitoring_state == "degraded"
            else ("axon_engaged" if next_monitoring_state == "engaged" else "axon_armed")
        )
    )
    next_presence_state = "degraded" if next_monitoring_state == "degraded" else str(current_presence.get("presence_state") or "online")

    row = await heartbeat_companion_presence(
        db,
        device_id=device_id,
        session_id=session_id if session_id is not None else (int(current_presence.get("session_id") or 0) or None),
        workspace_id=workspace_id if workspace_id is not None else (int(current_presence.get("workspace_id") or 0) or None),
        presence_state=next_presence_state,
        voice_state=next_voice_state,
        app_state=merged_state["app_state"],
        active_route=merged_state["active_route"],
        meta=next_meta,
    )
    snapshot = await build_mobile_axon_snapshot(db, device_id=device_id, presence_row=row)
    return row, snapshot


async def arm_mobile_axon_mode(
    db,
    *,
    device_id: int,
    workspace_id: int | None = None,
    session_id: int | None = None,
    wake_phrase: str = DEFAULT_WAKE_PHRASE,
    boot_sound_enabled: bool = True,
    spoken_reply_enabled: bool = True,
    continuous_monitoring_enabled: bool = True,
    voice_provider_preference: str = "cloud",
    voice_identity_preference: str = "",
    active_route: str = DEFAULT_ACTIVE_ROUTE,
    app_state: str = "foreground",
    meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    voice_status = await local_voice_snapshot(db)
    local_voice_ready = bool(voice_status.get("transcription_available"))
    degraded_reason = ""
    monitoring_state = "armed"
    if not local_voice_ready:
        monitoring_state = "degraded"
        degraded_reason = str(voice_status.get("detail") or "Local transcription is not ready.")
    elif not is_foreground_app_state(app_state):
        monitoring_state = "degraded"
        degraded_reason = "App left the foreground, so Axon mode paused."
    state_patch = {
        "armed": True,
        "monitoring_state": monitoring_state,
        "wake_phrase": wake_phrase,
        "boot_sound_enabled": bool(boot_sound_enabled),
        "spoken_reply_enabled": bool(spoken_reply_enabled),
        "continuous_monitoring_enabled": bool(continuous_monitoring_enabled),
        "voice_provider_preference": voice_provider_preference,
        "voice_identity_preference": voice_identity_preference,
        "last_event_type": "armed",
        "last_event_at": _now_iso(),
        "last_error": "" if local_voice_ready else degraded_reason,
        "degraded_reason": degraded_reason,
    }
    if isinstance(meta, dict) and meta:
        state_patch["client_meta"] = dict(meta)
    return await _persist_axon_state(
        db,
        device_id=device_id,
        workspace_id=workspace_id,
        session_id=session_id,
        active_route=active_route,
        app_state=app_state,
        state_patch=state_patch,
    )


async def disarm_mobile_axon_mode(
    db,
    *,
    device_id: int,
    workspace_id: int | None = None,
    session_id: int | None = None,
    active_route: str = DEFAULT_ACTIVE_ROUTE,
    app_state: str = "foreground",
) -> tuple[dict[str, Any], dict[str, Any]]:
    return await _persist_axon_state(
        db,
        device_id=device_id,
        workspace_id=workspace_id,
        session_id=session_id,
        active_route=active_route,
        app_state=app_state,
        state_patch={
            "armed": False,
            "monitoring_state": "idle",
            "last_event_type": "disarmed",
            "last_event_at": _now_iso(),
            "degraded_reason": "",
            "last_error": "",
        },
    )


async def record_mobile_axon_event(
    db,
    *,
    device_id: int,
    event_type: str,
    workspace_id: int | None = None,
    session_id: int | None = None,
    active_route: str = DEFAULT_ACTIVE_ROUTE,
    app_state: str = "",
    monitoring_state: str = "",
    wake_phrase: str = "",
    transcript: str = "",
    command_text: str = "",
    error: str = "",
    meta: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_name = str(event_type or "").strip().lower()
    if event_name not in AXON_EVENT_TYPES:
        raise ValueError(f"Unsupported Axon event '{event_type}'.")
    state_patch: dict[str, Any] = {
        "last_event_type": event_name,
        "last_event_at": _now_iso(),
    }
    if wake_phrase:
        state_patch["wake_phrase"] = wake_phrase
    if monitoring_state:
        state_patch["monitoring_state"] = monitoring_state
    if transcript:
        state_patch["last_transcript"] = transcript.strip()
    if command_text:
        state_patch["last_command_text"] = command_text.strip()
        state_patch["last_command_at"] = _now_iso()
    if error:
        state_patch["last_error"] = error.strip()

    if event_name == "wake_detected":
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "engaged"
        state_patch["last_wake_at"] = _now_iso()
        state_patch["degraded_reason"] = ""
    elif event_name == "listening_started":
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "listening"
        state_patch["degraded_reason"] = ""
        state_patch["last_error"] = ""
    elif event_name == "boot_sound_played":
        state_patch["armed"] = True
        state_patch["degraded_reason"] = ""
    elif event_name == "command_submitted":
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "armed"
        state_patch["degraded_reason"] = ""
    elif event_name in {"error", "degraded", "backgrounded"}:
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "degraded"
        state_patch["degraded_reason"] = (
            error.strip()
            or ("App left the foreground, so Axon mode paused." if event_name == "backgrounded" else "")
        )
    elif event_name == "foregrounded":
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "armed"
        state_patch["degraded_reason"] = ""
        state_patch["last_error"] = ""
    elif event_name == "disarmed":
        state_patch["armed"] = False
        state_patch["monitoring_state"] = "idle"
        state_patch["degraded_reason"] = ""
        state_patch["last_error"] = ""
    elif event_name == "armed":
        state_patch["armed"] = True
        state_patch["monitoring_state"] = "armed"
        state_patch["degraded_reason"] = ""
        state_patch["last_error"] = ""

    if isinstance(meta, dict) and meta:
        state_patch["client_meta"] = dict(meta)

    return await _persist_axon_state(
        db,
        device_id=device_id,
        workspace_id=workspace_id,
        session_id=session_id,
        active_route=active_route,
        app_state=app_state,
        state_patch=state_patch,
    )
