"""Trusted-device helpers for biometric-assisted mobile vault unlock."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from axon_data import get_trusted_device_state, upsert_trusted_device_state

BIOMETRIC_GRANT_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _future_iso(days: int = BIOMETRIC_GRANT_DAYS) -> str:
    return (_now() + timedelta(days=max(1, int(days)))).isoformat().replace("+00:00", "Z")


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


def _meta_json(meta: dict[str, Any]) -> str:
    return json.dumps(meta, sort_keys=True, ensure_ascii=True)


def _is_future_iso(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return False
    return parsed > datetime.now(UTC)


async def vault_biometric_state(db, *, device_id: int) -> dict[str, Any]:
    row = await get_trusted_device_state(db, device_id)
    trusted = dict(row) if row else {}
    meta = _parse_meta(trusted.get("meta_json"))
    expires_at = str(meta.get("vault_biometric_expires_at") or "").strip()
    enabled = bool(meta.get("vault_biometric_enabled"))
    available = enabled and _is_future_iso(expires_at)
    return {
        "enabled": enabled,
        "available": available,
        "expires_at": expires_at or None,
        "granted_at": str(meta.get("vault_biometric_granted_at") or "").strip() or None,
        "last_used_at": str(meta.get("vault_biometric_last_used_at") or "").strip() or None,
    }


async def arm_vault_biometric_unlock(db, *, device_id: int) -> dict[str, Any]:
    row = await get_trusted_device_state(db, device_id)
    trusted = dict(row) if row else {}
    meta = _parse_meta(trusted.get("meta_json"))
    meta.update(
        {
            "vault_biometric_enabled": True,
            "vault_biometric_granted_at": now_iso(),
            "vault_biometric_expires_at": _future_iso(),
        }
    )
    await upsert_trusted_device_state(
        db,
        device_id=device_id,
        trust_state=str(trusted.get("trust_state") or "trusted"),
        max_risk_tier=str(trusted.get("max_risk_tier") or "act"),
        biometric_enabled=True,
        last_biometric_at=str(trusted.get("last_biometric_at") or None),
        elevated_until=str(trusted.get("elevated_until") or None),
        meta_json=_meta_json(meta),
        commit=False,
    )
    return await vault_biometric_state(db, device_id=device_id)


async def mark_vault_biometric_unlock_used(db, *, device_id: int) -> dict[str, Any]:
    row = await get_trusted_device_state(db, device_id)
    trusted = dict(row) if row else {}
    meta = _parse_meta(trusted.get("meta_json"))
    meta["vault_biometric_last_used_at"] = now_iso()
    if not meta.get("vault_biometric_expires_at"):
        meta["vault_biometric_expires_at"] = _future_iso()
    await upsert_trusted_device_state(
        db,
        device_id=device_id,
        trust_state=str(trusted.get("trust_state") or "trusted"),
        max_risk_tier=str(trusted.get("max_risk_tier") or "act"),
        biometric_enabled=True,
        last_biometric_at=now_iso(),
        elevated_until=str(trusted.get("elevated_until") or None),
        meta_json=_meta_json(meta),
        commit=False,
    )
    return await vault_biometric_state(db, device_id=device_id)
