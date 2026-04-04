"""Mobile companion vault access routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import vault as devvault
from axon_api.services.companion_request_auth import require_companion_context
from axon_api.services.mobile_vault_biometric import (
    arm_vault_biometric_unlock,
    mark_vault_biometric_unlock_used,
    vault_biometric_state,
)
from axon_data import get_db, log_event

router = APIRouter(tags=["mobile-vault"])


class MobileVaultUnlockRequest(BaseModel):
    master_password: str
    totp_code: str
    remember_me: bool = False


class MobileVaultBiometricUnlockRequest(BaseModel):
    master_password: str
    remember_me: bool = False
    verified_via: str = "biometric_local"


@router.get("/api/mobile/vault/status")
async def mobile_vault_status(request: Request):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        is_setup = await devvault.vault_is_setup(db)
        biometric = await vault_biometric_state(db, device_id=int(device_row.get("id") or 0))
    return {
        "is_setup": is_setup,
        "is_unlocked": devvault.VaultSession.is_unlocked(),
        "ttl_remaining": devvault.VaultSession.ttl_remaining(),
        "biometric_reunlock_enabled": bool(biometric.get("enabled")),
        "biometric_reunlock_available": bool(biometric.get("available")),
        "biometric_reunlock_expires_at": biometric.get("expires_at"),
        "biometric_reunlock_last_used_at": biometric.get("last_used_at"),
    }


@router.get("/api/mobile/vault/provider-keys")
async def mobile_vault_provider_keys(request: Request):
    await require_companion_context(request)
    resolved: dict[str, bool] = {}
    if devvault.VaultSession.is_unlocked():
        async with get_db() as db:
            provider_keys = await devvault.vault_resolve_all_provider_keys(db)
        for provider_id in provider_keys:
            resolved[str(provider_id)] = True
    return {
        "unlocked": devvault.VaultSession.is_unlocked(),
        "resolved": resolved,
    }


@router.post("/api/mobile/vault/unlock")
async def mobile_vault_unlock(request: Request, body: MobileVaultUnlockRequest):
    _, _, device_row = await require_companion_context(request)
    ttl = devvault.VaultSession.EXTENDED_TTL if body.remember_me else devvault.VaultSession.DEFAULT_TTL
    async with get_db() as db:
        ok, err = await devvault.unlock_vault(
            db,
            body.master_password,
            body.totp_code,
            session_ttl=ttl,
        )
        if not ok:
            raise HTTPException(401, err)
        biometric = await arm_vault_biometric_unlock(db, device_id=int(device_row.get("id") or 0))
        await log_event(db, "vault", f"Mobile vault unlocked from device {device_row.get('name') or device_row.get('id')}")
        await db.commit()
    return {
        "unlocked": True,
        "session_ttl": ttl,
        "ttl_label": "24 hours" if body.remember_me else "1 hour",
        "biometric_reunlock_enabled": bool(biometric.get("enabled")),
        "biometric_reunlock_expires_at": biometric.get("expires_at"),
    }


@router.post("/api/mobile/vault/unlock/biometric")
async def mobile_vault_biometric_unlock(request: Request, body: MobileVaultBiometricUnlockRequest):
    _, _, device_row = await require_companion_context(request)
    if str(body.verified_via or "").strip() != "biometric_local":
        raise HTTPException(400, "Biometric verification is required for this unlock path.")
    ttl = devvault.VaultSession.EXTENDED_TTL if body.remember_me else devvault.VaultSession.DEFAULT_TTL
    async with get_db() as db:
        biometric = await vault_biometric_state(db, device_id=int(device_row.get("id") or 0))
        if not bool(biometric.get("available")):
            raise HTTPException(403, "Biometric vault re-unlock is not enabled for this device yet.")
        ok, err = await devvault.unlock_vault_with_password_only(
            db,
            body.master_password,
            session_ttl=ttl,
        )
        if not ok:
            raise HTTPException(401, err)
        biometric = await mark_vault_biometric_unlock_used(db, device_id=int(device_row.get("id") or 0))
        await log_event(db, "vault", f"Mobile biometric vault re-unlock from device {device_row.get('name') or device_row.get('id')}")
        await db.commit()
    return {
        "unlocked": True,
        "session_ttl": ttl,
        "ttl_label": "24 hours" if body.remember_me else "1 hour",
        "biometric_reunlock_enabled": bool(biometric.get("enabled")),
        "biometric_reunlock_expires_at": biometric.get("expires_at"),
    }


@router.post("/api/mobile/vault/lock")
async def mobile_vault_lock(request: Request):
    _, _, device_row = await require_companion_context(request)
    devvault.VaultSession.lock()
    async with get_db() as db:
        await log_event(db, "vault", f"Mobile vault locked from device {device_row.get('name') or device_row.get('id')}")
        await db.commit()
    return {"locked": True}
