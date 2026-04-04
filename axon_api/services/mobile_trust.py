"""Trusted-device state and elevation helpers for Axon Online mobile control."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from axon_api.services.mobile_control_policy import risk_rank, risk_tier_at_least
from axon_data import (
    create_mobile_elevation_session,
    get_mobile_elevation_session,
    get_trusted_device_state,
    list_mobile_elevation_sessions,
    upsert_trusted_device_state,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _expires_at(minutes: int) -> str:
    return (_now() + timedelta(minutes=max(1, int(minutes)))).isoformat().replace("+00:00", "Z")


def _parse_meta(raw: Any) -> dict[str, Any]:
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


def _json_meta(meta: dict[str, Any] | None) -> str:
    return "{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True)


def _is_future_iso(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return False
    return parsed > datetime.now(UTC)


async def ensure_trusted_device_state(db, *, device_id: int) -> dict[str, Any]:
    row = await get_trusted_device_state(db, device_id)
    if row:
        return dict(row)
    await upsert_trusted_device_state(
        db,
        device_id=device_id,
        trust_state="paired",
        max_risk_tier="act",
        biometric_enabled=False,
        meta_json="{}",
        commit=False,
    )
    return {
        "device_id": device_id,
        "trust_state": "paired",
        "max_risk_tier": "act",
        "biometric_enabled": 0,
        "last_biometric_at": None,
        "elevated_until": None,
        "meta_json": "{}",
    }


async def get_trust_snapshot(
    db,
    *,
    device_id: int,
) -> dict[str, Any]:
    trusted = await ensure_trusted_device_state(db, device_id=device_id)
    sessions = [
        dict(row)
        for row in await list_mobile_elevation_sessions(db, device_id=device_id, status="active", limit=10)
    ]
    active_sessions = [
        session for session in sessions if _is_future_iso(str(session.get("expires_at") or ""))
    ]
    highest_elevation = "observe"
    for session in active_sessions:
        risk_tier = str(session.get("risk_tier") or "observe").strip().lower()
        if risk_rank(risk_tier) > risk_rank(highest_elevation):
            highest_elevation = risk_tier
    return {
        "device_id": device_id,
        "trusted": trusted,
        "elevation": {
            "active": bool(active_sessions),
            "highest_risk_tier": highest_elevation,
            "sessions": active_sessions,
        },
        "effective_max_risk_tier": highest_elevation if active_sessions else str(trusted.get("max_risk_tier") or "act"),
        "challenge_required": not bool(active_sessions),
    }


async def has_active_elevation(
    db,
    *,
    device_id: int,
    required_risk_tier: str = "destructive",
) -> bool:
    sessions = await list_mobile_elevation_sessions(db, device_id=device_id, status="active", limit=20)
    for session in sessions:
        candidate = dict(session)
        if not _is_future_iso(str(candidate.get("expires_at") or "")):
            continue
        if risk_tier_at_least(str(candidate.get("risk_tier") or "observe"), required_risk_tier):
            return True
    return False


async def create_elevation(
    db,
    *,
    device_id: int,
    target_risk_tier: str = "destructive",
    verified_via: str = "biometric_local",
    ttl_minutes: int = 15,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = await ensure_trusted_device_state(db, device_id=device_id)
    merged_meta = {
        **_parse_meta(existing.get("meta_json")),
        "last_elevation_request": now_iso(),
        **(meta or {}),
    }
    expires_at = _expires_at(ttl_minutes)
    await upsert_trusted_device_state(
        db,
        device_id=device_id,
        trust_state="trusted",
        max_risk_tier=str(existing.get("max_risk_tier") or "act"),
        biometric_enabled=True,
        last_biometric_at=now_iso(),
        elevated_until=expires_at,
        meta_json=_json_meta(merged_meta),
        commit=False,
    )
    elevation_key = f"elev:{device_id}:{secrets.token_urlsafe(8)}"
    session_id = await create_mobile_elevation_session(
        db,
        device_id=device_id,
        elevation_key=elevation_key,
        risk_tier=target_risk_tier,
        granted_scopes_json=json.dumps([target_risk_tier], sort_keys=True, ensure_ascii=True),
        verified_via=verified_via,
        verified_at=now_iso(),
        expires_at=expires_at,
        meta_json=_json_meta(meta),
        commit=False,
    )
    session = await get_mobile_elevation_session(db, session_id)
    trusted = await get_trusted_device_state(db, device_id)
    return {
        "trusted": dict(trusted) if trusted else {"device_id": device_id},
        "elevation_session": dict(session) if session else {"id": session_id, "device_id": device_id, "risk_tier": target_risk_tier},
    }
