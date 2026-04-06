"""Pairing, restore, and device routes for Axon's mobile companion surface."""

from __future__ import annotations

import hmac
from hashlib import sha256

from fastapi import APIRouter, HTTPException, Request

from axon_api.routes.companion_models import (
    CompanionDeviceTouchRequest,
    CompanionPairRequest,
    CompanionRefreshRequest,
    CompanionRestoreRequest,
    CompanionRevokeRequest,
)
from axon_api.services import companion_auth as companion_auth_service
from axon_api.services.companion_request_auth import (
    companion_auth_context,
    require_companion_context,
    require_same_device,
)
from axon_data import (
    get_companion_device,
    get_companion_device_by_key,
    get_companion_presence,
    get_db,
    get_setting,
    revoke_companion_device,
    touch_companion_device,
    update_companion_device_status,
)

router = APIRouter(prefix="/api/companion", tags=["companion"])


@router.post("/auth/pair")
async def companion_pair(body: CompanionPairRequest, request: Request):
    async with get_db() as db:
        pin_hash = await get_setting(db, "auth_pin_hash")
        if pin_hash:
            if not body.pin or not body.pin.strip():
                raise HTTPException(401, "PIN required")
            expected = sha256(f"devbrain-pin-{body.pin.strip()}".encode()).hexdigest()
            if not hmac.compare_digest(expected, pin_hash):
                raise HTTPException(401, "Wrong PIN")
        device = await companion_auth_service.register_companion_device(
            db,
            device_key=body.device_key,
            name=body.name,
            user_id=body.user_id,
            kind=body.kind,
            platform=body.platform,
            model=body.model,
            os_version=body.os_version,
            status=body.status,
            meta=body.meta or {
                "paired_via": "companion_auth_pair",
                "client_ip": getattr(getattr(request, "client", None), "host", "") or "",
            },
        )
        ttl_seconds = int(body.ttl_seconds or 0) or (60 * 60 * 24 * 30)
        session = await companion_auth_service.issue_companion_auth_session(
            db,
            device_id=int(device["id"]),
            ttl_seconds=max(60, ttl_seconds),
            meta={"paired_from": "companion_auth_pair"},
        )
        restore_token = await companion_auth_service.issue_companion_device_restore_token(
            db,
            device_id=int(device["id"]),
        )
        await touch_companion_device(db, int(device["id"]))
        latest_device = await get_companion_device(db, int(device["id"]))
    return {
        "device": dict(latest_device) if latest_device else device,
        "restore_token": restore_token,
        **session,
    }


@router.post("/auth/restore")
async def companion_restore(body: CompanionRestoreRequest):
    async with get_db() as db:
        ttl_seconds = int(body.ttl_seconds or 0) or (60 * 60 * 24 * 30)
        session = await companion_auth_service.restore_companion_auth_session(
            db,
            device_key=body.device_key,
            restore_token=body.restore_token,
            ttl_seconds=max(60, ttl_seconds),
        )
        if session and session.get("device", {}).get("id"):
            await touch_companion_device(db, int(session["device"]["id"]))
    if not session:
        raise HTTPException(401, "Saved device trust is no longer valid. Pair this device again.")
    return session


@router.post("/auth/refresh")
async def companion_refresh(body: CompanionRefreshRequest):
    async with get_db() as db:
        ttl_seconds = int(body.ttl_seconds or 0) or (60 * 60 * 24 * 30)
        session = await companion_auth_service.refresh_companion_auth_session(
            db,
            refresh_token=body.refresh_token,
            ttl_seconds=max(60, ttl_seconds),
        )
        if not session:
            raise HTTPException(401, "Invalid refresh token")
        device_id = int(session["auth_session"]["device_id"])
        restore_token = await companion_auth_service.issue_companion_device_restore_token(
            db,
            device_id=device_id,
        )
        await touch_companion_device(db, device_id)
        device_row = await get_companion_device(db, device_id)
    return {
        "device": dict(device_row) if device_row else {"id": device_id},
        "restore_token": restore_token,
        **session,
    }


@router.post("/auth/revoke")
async def companion_revoke(body: CompanionRevokeRequest, request: Request):
    if body.device_id is not None or body.auth_session_id is not None:
        _, auth_row, device_row = await require_companion_context(request)
        if body.device_id is not None:
            require_same_device(device_row, int(body.device_id))
        if body.auth_session_id is not None and int(body.auth_session_id) != int(auth_row.get("id") or 0):
            raise HTTPException(403, "This companion token cannot revoke another auth session")
    async with get_db() as db:
        revoked = await companion_auth_service.revoke_companion_device_auth(
            db,
            device_id=body.device_id,
            auth_session_id=body.auth_session_id,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
        )
    if not revoked:
        raise HTTPException(400, "Provide device_id, auth_session_id, access_token, or refresh_token")
    return {"revoked": True}


@router.get("/devices")
async def companion_devices(request: Request):
    _, _, device_row = await require_companion_context(request)
    return {"devices": [device_row]}


@router.get("/devices/current")
async def companion_current_device(request: Request):
    _, _, device_row = await companion_auth_context(request)
    if not device_row:
        raise HTTPException(401, "Companion auth token required")
    async with get_db() as db:
        presence_row = await get_companion_presence(db, int(device_row["id"]))
    return {"device": device_row, "presence": dict(presence_row) if presence_row else None}


@router.get("/devices/{device_id}")
async def companion_device_detail(device_id: int, request: Request):
    _, _, device_row = await require_companion_context(request)
    require_same_device(device_row, device_id)
    async with get_db() as db:
        row = await get_companion_device(db, device_id)
    if not row:
        raise HTTPException(404, "Device not found")
    return dict(row)


@router.get("/devices/by-key/{device_key}")
async def companion_device_detail_by_key(device_key: str, request: Request):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        row = await get_companion_device_by_key(db, device_key)
    if not row:
        raise HTTPException(404, "Device not found")
    resolved = dict(row)
    require_same_device(device_row, int(resolved.get("id") or 0))
    return resolved


@router.post("/devices/{device_id}/touch")
async def companion_device_touch(device_id: int, body: CompanionDeviceTouchRequest, request: Request):
    _, _, device_row = await require_companion_context(request)
    require_same_device(device_row, device_id)
    async with get_db() as db:
        if body.status == "revoked":
            await revoke_companion_device(db, device_id)
        else:
            await touch_companion_device(db, device_id)
            if body.status and body.status != "active":
                await update_companion_device_status(db, device_id, status=body.status)
        row = await get_companion_device(db, device_id)
    if not row:
        raise HTTPException(404, "Device not found")
    return {"device": dict(row)}


@router.post("/devices/{device_id}/revoke")
async def companion_device_revoke(device_id: int, request: Request):
    _, _, device_row = await require_companion_context(request)
    require_same_device(device_row, device_id)
    async with get_db() as db:
        await revoke_companion_device(db, device_id)
        row = await get_companion_device(db, device_id)
    if not row:
        raise HTTPException(404, "Device not found")
    return {"device": dict(row), "revoked": True}
