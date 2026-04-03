"""Companion device registration and auth-session helpers."""

from __future__ import annotations

import json
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from axon_data import (
    get_active_companion_auth_sessions_for_device,
    get_companion_auth_session,
    get_companion_auth_session_by_access_hash,
    get_companion_auth_session_by_refresh_hash,
    get_companion_device,
    get_companion_device_by_key,
    revoke_companion_auth_session,
    revoke_companion_auth_sessions_for_device,
    upsert_companion_auth_session,
    upsert_companion_device,
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_tokens() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


async def register_companion_device(
    db,
    *,
    device_key: str,
    name: str,
    user_id: int | None = None,
    kind: str = "mobile",
    platform: str = "",
    model: str = "",
    os_version: str = "",
    status: str = "active",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    device_id = await upsert_companion_device(
        db,
        device_key=device_key,
        name=name,
        user_id=user_id,
        kind=kind,
        platform=platform,
        model=model,
        os_version=os_version,
        status=status,
        meta_json="{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    row = await get_companion_device(db, device_id)
    return dict(row) if row else {"id": device_id, "device_key": device_key, "name": name}


async def issue_companion_auth_session(
    db,
    *,
    device_id: int,
    ttl_seconds: int = 60 * 60 * 24 * 30,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await revoke_companion_auth_sessions_for_device(db, device_id)
    access_token, refresh_token = _issue_tokens()
    expires_at = (datetime.now(UTC) + timedelta(seconds=max(60, int(ttl_seconds)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    session_id = await upsert_companion_auth_session(
        db,
        device_id=device_id,
        access_token_hash=_hash_token(access_token),
        refresh_token_hash=_hash_token(refresh_token),
        expires_at=expires_at,
        meta_json="{}" if meta is None else __import__("json").dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    row = await get_companion_auth_session(db, session_id)
    return {
        "auth_session": dict(row) if row else {"id": session_id, "device_id": device_id},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }


async def refresh_companion_auth_session(
    db,
    *,
    refresh_token: str,
    ttl_seconds: int = 60 * 60 * 24 * 30,
) -> dict[str, Any] | None:
    existing = await get_companion_auth_session_by_refresh_hash(db, _hash_token(refresh_token))
    if not existing:
        return None
    await revoke_companion_auth_session(db, session_id=int(existing["id"]))
    return await issue_companion_auth_session(
        db,
        device_id=int(existing["device_id"]),
        ttl_seconds=ttl_seconds,
        meta={"refreshed_from": int(existing["id"])},
    )


async def resolve_companion_auth_session(
    db,
    *,
    access_token: str = "",
    refresh_token: str = "",
) -> dict[str, Any] | None:
    if access_token:
        row = await get_companion_auth_session_by_access_hash(db, _hash_token(access_token))
        return dict(row) if row else None
    if refresh_token:
        row = await get_companion_auth_session_by_refresh_hash(db, _hash_token(refresh_token))
        return dict(row) if row else None
    return None


async def revoke_companion_device_auth(
    db,
    *,
    device_id: int | None = None,
    auth_session_id: int | None = None,
    access_token: str = "",
    refresh_token: str = "",
) -> bool:
    if device_id is not None:
        await revoke_companion_auth_sessions_for_device(db, device_id)
        return True
    if auth_session_id is not None:
        await revoke_companion_auth_session(db, session_id=auth_session_id)
        return True
    if access_token:
        await revoke_companion_auth_session(db, access_token_hash=_hash_token(access_token))
        return True
    if refresh_token:
        await revoke_companion_auth_session(db, refresh_token_hash=_hash_token(refresh_token))
        return True
    return False
