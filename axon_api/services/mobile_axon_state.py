"""State helpers for mobile Axon mode presence metadata."""

from __future__ import annotations

import logging
import json
from typing import Any

DEFAULT_WAKE_PHRASE = "Axon"
DEFAULT_ACTIVE_ROUTE = "/voice"
DEFAULT_VOICE_PROVIDER = "cloud"
AXON_META_KEY = "axon_mode"
AXON_MONITORING_STATES = {"idle", "armed", "listening", "engaged", "speaking", "degraded"}
AXON_EVENT_TYPES = {
    "armed",
    "backgrounded",
    "boot_sound_played",
    "command_submitted",
    "degraded",
    "disarmed",
    "error",
    "foregrounded",
    "listening_started",
    "wake_detected",
}


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def parse_meta(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        logging.getLogger(__name__).warning("Failed to parse meta JSON", exc_info=True)
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def normalise_wake_phrase(value: Any) -> str:
    phrase = str(value or DEFAULT_WAKE_PHRASE).strip()
    return phrase or DEFAULT_WAKE_PHRASE


def normalise_monitoring_state(value: Any, *, armed: bool) -> str:
    state = str(value or "").strip().lower()
    if state in AXON_MONITORING_STATES:
        return state
    return "armed" if armed else "idle"


def normalise_voice_provider(value: Any) -> str:
    provider = str(value or DEFAULT_VOICE_PROVIDER).strip().lower()
    if provider in {"cloud", "local", "device"}:
        return provider
    return DEFAULT_VOICE_PROVIDER


def normalise_voice_identity(value: Any) -> str:
    return str(value or "").strip()


def normalise_app_state(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in {"active", "foreground"}:
        return "foreground"
    if state in {"background", "inactive"}:
        return "background"
    return state or "foreground"


def is_foreground_app_state(value: Any) -> bool:
    return normalise_app_state(value) == "foreground"


def extract_axon_state(presence_row: Any) -> dict[str, Any]:
    presence = row_dict(presence_row)
    meta = parse_meta(presence.get("meta_json"))
    state = parse_meta(meta.get(AXON_META_KEY))
    armed = bool(state.get("armed"))
    return {
        "armed": armed,
        "foreground_only": True,
        "monitoring_state": normalise_monitoring_state(state.get("monitoring_state"), armed=armed),
        "wake_phrase": normalise_wake_phrase(state.get("wake_phrase")),
        "boot_sound_enabled": bool(state.get("boot_sound_enabled", True)),
        "spoken_reply_enabled": bool(state.get("spoken_reply_enabled", True)),
        "continuous_monitoring_enabled": bool(state.get("continuous_monitoring_enabled", True)),
        "voice_provider_preference": normalise_voice_provider(state.get("voice_provider_preference")),
        "voice_identity_preference": normalise_voice_identity(state.get("voice_identity_preference")),
        "last_event_type": str(state.get("last_event_type") or "").strip().lower(),
        "last_event_at": str(state.get("last_event_at") or "").strip(),
        "last_wake_at": str(state.get("last_wake_at") or "").strip(),
        "last_transcript": str(state.get("last_transcript") or "").strip(),
        "last_command_text": str(state.get("last_command_text") or "").strip(),
        "last_command_at": str(state.get("last_command_at") or "").strip(),
        "last_error": str(state.get("last_error") or "").strip(),
        "degraded_reason": str(state.get("degraded_reason") or "").strip(),
        "active_route": str(state.get("active_route") or presence.get("active_route") or DEFAULT_ACTIVE_ROUTE).strip(),
        "app_state": normalise_app_state(state.get("app_state") or presence.get("app_state") or "foreground"),
        "updated_at": str(
            state.get("updated_at") or presence.get("updated_at") or presence.get("last_seen_at") or ""
        ).strip(),
    }
