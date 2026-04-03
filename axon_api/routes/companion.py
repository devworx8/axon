"""API routes for Axon's mobile companion surface."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from axon_api.services import (
    companion_auth as companion_auth_service,
    companion_presence as companion_presence_service,
    companion_push as companion_push_service,
    companion_runtime as companion_runtime_service,
    companion_sessions as companion_sessions_service,
    companion_voice as companion_voice_service,
)
from axon_data import (
    clear_companion_presence,
    get_companion_auth_session,
    get_companion_device,
    get_companion_device_by_key,
    get_companion_presence,
    get_companion_session,
    get_companion_session_by_key,
    get_companion_voice_turn,
    get_db,
    get_setting,
    list_companion_devices,
    list_companion_presence,
    list_companion_push_subscriptions,
    list_companion_sessions,
    list_companion_voice_turns,
    revoke_companion_device,
    touch_companion_device,
    update_companion_device_status,
)

router = APIRouter(prefix="/api/companion", tags=["companion"])


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (
        request.headers.get("X-Axon-Token")
        or request.headers.get("X-DevBrain-Token")
        or request.headers.get("X-Session-Token")
        or request.query_params.get("token")
        or ""
    ).strip()


def _expires_at_passed(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return expiry <= datetime.now(timezone.utc)


async def _companion_auth_context(request: Request) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    token = _token_from_request(request)
    if not token:
        return "", None, None
    async with get_db() as db:
        auth_row = await companion_auth_service.resolve_companion_auth_session(db, access_token=token)
        if not auth_row or _expires_at_passed(str(auth_row.get("expires_at") or "")):
            return token, None, None
        device_row = await get_companion_device(db, int(auth_row["device_id"]))
    return token, dict(auth_row), dict(device_row) if device_row else None


async def _require_companion_context(request: Request) -> tuple[str, dict[str, Any], dict[str, Any]]:
    token, auth_row, device_row = await _companion_auth_context(request)
    if not token or not auth_row or not device_row:
        raise HTTPException(401, "Companion auth token required")
    return token, auth_row, device_row


class CompanionPairRequest(BaseModel):
    device_key: str
    name: str
    pin: str = ""
    user_id: int | None = None
    kind: str = "mobile"
    platform: str = ""
    model: str = ""
    os_version: str = ""
    status: str = "active"
    ttl_seconds: int = 60 * 60 * 24 * 30
    meta: dict[str, Any] | None = Field(default=None)


class CompanionRefreshRequest(BaseModel):
    refresh_token: str
    ttl_seconds: int = 60 * 60 * 24 * 30


class CompanionRevokeRequest(BaseModel):
    device_id: int | None = None
    auth_session_id: int | None = None
    access_token: str = ""
    refresh_token: str = ""


class CompanionDeviceTouchRequest(BaseModel):
    status: str = "active"


class CompanionPresenceRequest(BaseModel):
    device_id: int | None = None
    session_id: int | None = None
    workspace_id: int | None = None
    presence_state: str = "online"
    voice_state: str = "idle"
    app_state: str = "foreground"
    active_route: str = ""
    meta: dict[str, Any] | None = Field(default=None)


class CompanionSessionRequest(BaseModel):
    session_key: str = ""
    device_id: int | None = None
    workspace_id: int | None = None
    agent_session_id: str = ""
    status: str = "active"
    mode: str = "companion"
    current_route: str = ""
    current_view: str = ""
    active_task: str = ""
    summary: str = ""
    meta: dict[str, Any] | None = Field(default=None)


class CompanionSessionResumeRequest(BaseModel):
    agent_session_id: str = ""
    status: str = "active"


class CompanionSessionTouchRequest(BaseModel):
    current_route: str | None = None
    current_view: str | None = None
    active_task: str | None = None
    summary: str | None = None


class CompanionVoiceTurnRequest(BaseModel):
    session_id: int | None = None
    workspace_id: int | None = None
    role: str = "user"
    content: str
    transcript: str = ""
    response_text: str = ""
    provider: str = ""
    voice_mode: str = ""
    language: str = ""
    audio_format: str = ""
    duration_ms: int = 0
    tokens_used: int = 0
    status: str = "recorded"
    meta: dict[str, Any] | None = Field(default=None)


class CompanionPushSubscriptionRequest(BaseModel):
    device_id: int | None = None
    endpoint: str
    provider: str = "webpush"
    auth: dict[str, Any] | None = Field(default=None)
    p256dh: str = ""
    expiration_at: str | None = None
    status: str = "active"
    meta: dict[str, Any] | None = Field(default=None)


@router.get("/status")
async def companion_status(request: Request):
    token, auth_row, device_row = await _companion_auth_context(request)
    async with get_db() as db:
        auth_enabled = bool(await get_setting(db, "auth_pin_hash"))
        device_count = len(await list_companion_devices(db, limit=10))
        session_count = len(await list_companion_sessions(db, limit=10))
        presence_count = len(await list_companion_presence(db, limit=10))
    return {
        "auth_enabled": auth_enabled,
        "session_valid": bool(auth_row),
        "device": device_row,
        "auth_session": auth_row,
        "counts": {
            "devices": device_count,
            "sessions": session_count,
            "presence": presence_count,
        },
        "token_present": bool(token),
    }


@router.get("/identity")
async def companion_identity(request: Request):
    token, auth_row, device_row = await _companion_auth_context(request)
    if not token or not auth_row or not device_row:
        return {"device": None, "auth_session": None, "presence": None, "sessions": []}
    async with get_db() as db:
        presence_row = await get_companion_presence(db, int(device_row["id"]))
        sessions = await list_companion_sessions(db, device_id=int(device_row["id"]), limit=10)
    return {
        "device": device_row,
        "auth_session": auth_row,
        "presence": dict(presence_row) if presence_row else None,
        "sessions": [dict(row) for row in sessions],
    }


@router.post("/auth/pair")
async def companion_pair(body: CompanionPairRequest, request: Request):
    async with get_db() as db:
        pin_hash = await get_setting(db, "auth_pin_hash")
        if pin_hash:
            from hashlib import sha256

            expected = sha256(f"devbrain-pin-{body.pin.strip()}".encode()).hexdigest()
            if not body.pin.strip() or expected != pin_hash:
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
        session = await companion_auth_service.issue_companion_auth_session(
            db,
            device_id=int(device["id"]),
            ttl_seconds=max(60, int(body.ttl_seconds or 0) or 60),
            meta={"paired_from": "companion_auth_pair"},
        )
    return {"device": device, **session}


@router.post("/auth/refresh")
async def companion_refresh(body: CompanionRefreshRequest):
    async with get_db() as db:
        session = await companion_auth_service.refresh_companion_auth_session(
            db,
            refresh_token=body.refresh_token,
            ttl_seconds=max(60, int(body.ttl_seconds or 0) or 60),
        )
    if not session:
        raise HTTPException(401, "Invalid refresh token")
    return session


@router.post("/auth/revoke")
async def companion_revoke(body: CompanionRevokeRequest):
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
async def companion_devices(status: str = "", limit: int = 100):
    async with get_db() as db:
        rows = await list_companion_devices(db, status=status, limit=limit)
    return {"devices": [dict(row) for row in rows]}


@router.get("/devices/current")
async def companion_current_device(request: Request):
    _, _, device_row = await _companion_auth_context(request)
    if not device_row:
        raise HTTPException(401, "Companion auth token required")
    async with get_db() as db:
        presence_row = await get_companion_presence(db, int(device_row["id"]))
    return {"device": device_row, "presence": dict(presence_row) if presence_row else None}


@router.get("/devices/{device_id}")
async def companion_device_detail(device_id: int):
    async with get_db() as db:
        row = await get_companion_device(db, device_id)
    if not row:
        raise HTTPException(404, "Device not found")
    return dict(row)


@router.get("/devices/by-key/{device_key}")
async def companion_device_detail_by_key(device_key: str):
    async with get_db() as db:
        row = await get_companion_device_by_key(db, device_key)
    if not row:
        raise HTTPException(404, "Device not found")
    return dict(row)


@router.post("/devices/{device_id}/touch")
async def companion_device_touch(device_id: int, body: CompanionDeviceTouchRequest):
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
async def companion_device_revoke(device_id: int):
    async with get_db() as db:
        await revoke_companion_device(db, device_id)
        row = await get_companion_device(db, device_id)
    if not row:
        raise HTTPException(404, "Device not found")
    return {"device": dict(row), "revoked": True}


@router.get("/presence/current")
async def companion_presence_current(request: Request, device_id: int | None = None):
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if not device_row:
            raise HTTPException(401, "Companion auth token required")
        device_id = int(device_row["id"])
    async with get_db() as db:
        row = await get_companion_presence(db, device_id)
    return {"presence": dict(row) if row else None}


@router.get("/presence/workspace/{workspace_id}")
async def companion_presence_workspace(workspace_id: int, limit: int = 100):
    async with get_db() as db:
        rows = await list_companion_presence(db, workspace_id=workspace_id, limit=limit)
    return {"presence": [dict(row) for row in rows]}


@router.post("/presence/heartbeat")
async def companion_presence_heartbeat(body: CompanionPresenceRequest, request: Request):
    device_id = body.device_id
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if not device_row:
            raise HTTPException(401, "Companion auth token required")
        device_id = int(device_row["id"])
    async with get_db() as db:
        row = await companion_presence_service.heartbeat_companion_presence(
            db,
            device_id=device_id,
            session_id=body.session_id,
            workspace_id=body.workspace_id,
            presence_state=body.presence_state,
            voice_state=body.voice_state,
            app_state=body.app_state,
            active_route=body.active_route,
            meta=body.meta or {},
        )
        await touch_companion_device(db, device_id)
    return {"presence": row}


@router.post("/presence/clear")
async def companion_presence_clear(request: Request, device_id: int | None = None):
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if not device_row:
            raise HTTPException(401, "Companion auth token required")
        device_id = int(device_row["id"])
    async with get_db() as db:
        await clear_companion_presence(db, device_id)
    return {"cleared": True, "device_id": device_id}


@router.get("/sessions")
async def companion_sessions(
    request: Request,
    device_id: int | None = None,
    workspace_id: int | None = None,
    status: str = "",
    limit: int = 100,
):
    if device_id is None and workspace_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if device_row:
            device_id = int(device_row["id"])
    async with get_db() as db:
        rows = await list_companion_sessions(
            db,
            device_id=device_id,
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )
    return {"sessions": [dict(row) for row in rows]}


@router.get("/sessions/{session_id}")
async def companion_session_detail(session_id: int):
    async with get_db() as db:
        row = await get_companion_session(db, session_id)
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


@router.get("/sessions/by-key/{session_key}")
async def companion_session_detail_by_key(session_key: str):
    async with get_db() as db:
        row = await get_companion_session_by_key(db, session_key)
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


@router.post("/sessions")
async def companion_session_upsert(body: CompanionSessionRequest, request: Request):
    device_id = body.device_id
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if not device_row:
            raise HTTPException(401, "Companion auth token required")
        device_id = int(device_row["id"])
    session_key = body.session_key.strip() or companion_sessions_service.companion_session_key(
        device_id,
        body.workspace_id,
        body.agent_session_id,
    )
    async with get_db() as db:
        row = await companion_sessions_service.ensure_companion_session(
            db,
            session_key=session_key,
            device_id=device_id,
            workspace_id=body.workspace_id,
            agent_session_id=body.agent_session_id,
            status=body.status,
            mode=body.mode,
            current_route=body.current_route,
            current_view=body.current_view,
            active_task=body.active_task,
            summary=body.summary,
            meta=body.meta or {},
        )
        await touch_companion_device(db, device_id)
    return {"session": row}


@router.post("/sessions/{session_id}/resume")
async def companion_session_resume(session_id: int, body: CompanionSessionResumeRequest):
    async with get_db() as db:
        row = await get_companion_session(db, session_id)
        if not row:
            raise HTTPException(404, "Session not found")
        resumed = await companion_sessions_service.resume_companion_session(
            db,
            session_key=str(row["session_key"] or ""),
            agent_session_id=body.agent_session_id,
            status=body.status,
        )
    return {"session": resumed}


@router.post("/sessions/{session_id}/touch")
async def companion_session_touch(session_id: int, body: CompanionSessionTouchRequest):
    async with get_db() as db:
        ok = await companion_sessions_service.touch_companion_session(
            db,
            session_id=session_id,
            current_route=body.current_route,
            current_view=body.current_view,
            active_task=body.active_task,
            summary=body.summary,
        )
        row = await get_companion_session(db, session_id)
    if not ok or not row:
        raise HTTPException(404, "Session not found")
    return {"session": dict(row)}


@router.post("/sessions/{session_id}/close")
async def companion_session_close(session_id: int):
    async with get_db() as db:
        ok = await companion_sessions_service.close_companion_workspace_session(db, session_id=session_id)
        row = await get_companion_session(db, session_id)
    if not ok or not row:
        raise HTTPException(404, "Session not found")
    return {"session": dict(row)}


@router.get("/voice/turns")
async def companion_voice_turns(
    session_id: int | None = None,
    workspace_id: int | None = None,
    limit: int = 100,
):
    async with get_db() as db:
        rows = await list_companion_voice_turns(db, session_id=session_id, workspace_id=workspace_id, limit=limit)
    return {"turns": [dict(row) for row in rows]}


@router.get("/voice/turns/{turn_id}")
async def companion_voice_turn_detail(turn_id: int):
    async with get_db() as db:
        row = await get_companion_voice_turn(db, turn_id)
    if not row:
        raise HTTPException(404, "Voice turn not found")
    return dict(row)


@router.post("/voice/turns")
async def companion_voice_turn_create(body: CompanionVoiceTurnRequest, request: Request):
    token, auth_row, device_row = await _companion_auth_context(request)
    device_id = int(device_row["id"]) if device_row else None
    async with get_db() as db:
        if str(body.role or "user").strip().lower() == "user":
            if device_id is None:
                raise HTTPException(401, "Companion auth token required for voice turns")
            result = await companion_runtime_service.process_companion_voice_turn(
                db,
                device_id=device_id,
                session_id=body.session_id,
                workspace_id=body.workspace_id,
                content=body.content,
                transcript=body.transcript,
                provider=body.provider,
                voice_mode=body.voice_mode,
                language=body.language,
                audio_format=body.audio_format,
                duration_ms=body.duration_ms,
                meta=body.meta or {},
            )
            presence_row = await companion_presence_service.heartbeat_companion_presence(
                db,
                device_id=device_id,
                session_id=int((result.get("session") or {}).get("id") or 0) or None,
                workspace_id=(result.get("session") or {}).get("workspace_id"),
                presence_state="online",
                voice_state="idle",
                app_state="foreground",
                active_route="/voice",
                meta={"surface": "companion_voice", "token_present": bool(token), "auth_session_id": auth_row.get("id") if auth_row else None},
            )
            result["presence"] = presence_row
            return result

        if body.session_id is None:
            raise HTTPException(400, "session_id is required when recording a non-user voice turn")
        row = await companion_voice_service.record_companion_voice_turn(
            db,
            session_id=body.session_id,
            workspace_id=body.workspace_id,
            role=body.role,
            content=body.content,
            transcript=body.transcript,
            response_text=body.response_text,
            provider=body.provider,
            voice_mode=body.voice_mode,
            language=body.language,
            audio_format=body.audio_format,
            duration_ms=body.duration_ms,
            tokens_used=body.tokens_used,
            status=body.status,
            meta=body.meta or {},
        )
    return {"turn": row}


@router.get("/push/subscriptions")
async def companion_push_subscriptions(
    request: Request,
    device_id: int | None = None,
    status: str = "",
    limit: int = 100,
):
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if device_row:
            device_id = int(device_row["id"])
    async with get_db() as db:
        rows = await list_companion_push_subscriptions(db, device_id=device_id, status=status, limit=limit)
    return {"subscriptions": [dict(row) for row in rows]}


@router.post("/push/subscriptions")
async def companion_push_subscription_create(body: CompanionPushSubscriptionRequest, request: Request):
    device_id = body.device_id
    if device_id is None:
        _, _, device_row = await _companion_auth_context(request)
        if not device_row:
            raise HTTPException(401, "Companion auth token required")
        device_id = int(device_row["id"])
    async with get_db() as db:
        row = await companion_push_service.register_companion_push_subscription(
            db,
            device_id=device_id,
            endpoint=body.endpoint,
            provider=body.provider,
            auth=body.auth or {},
            p256dh=body.p256dh,
            expiration_at=body.expiration_at,
            status=body.status,
            meta=body.meta or {},
        )
    return {"subscription": row}


@router.post("/push/subscriptions/{subscription_id}/disable")
async def companion_push_subscription_disable(subscription_id: int):
    async with get_db() as db:
        ok = await companion_push_service.disable_companion_push_target(db, subscription_id=subscription_id)
    if not ok:
        raise HTTPException(404, "Push subscription not found")
    return {"disabled": True, "subscription_id": subscription_id}
