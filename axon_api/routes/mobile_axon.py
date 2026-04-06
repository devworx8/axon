"""Axon mode routes for foreground mobile monitoring."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from axon_api.routes.mobile_axon_models import (
    MobileAxonArmRequest,
    MobileAxonDisarmRequest,
    MobileAxonEventRequest,
    MobileAxonSpeakRequest,
    MobileVoiceSettingsRequest,
)
from axon_api.services.mobile_axon_audio import build_mobile_axon_audio_payload
from axon_api.services.companion_request_auth import require_companion_context
from axon_api.services.mobile_axon_mode import (
    arm_mobile_axon_mode,
    build_mobile_axon_snapshot,
    disarm_mobile_axon_mode,
    record_mobile_axon_event,
)
from axon_data import get_db

router = APIRouter(tags=["mobile-axon"])


@router.get("/api/mobile/axon/status")
async def mobile_axon_status(request: Request):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        snapshot = await build_mobile_axon_snapshot(db, device_id=int(device_row["id"]))
    return {"axon": snapshot}


@router.post("/api/mobile/axon/arm")
async def mobile_axon_arm(request: Request, body: MobileAxonArmRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        presence, snapshot = await arm_mobile_axon_mode(
            db,
            device_id=int(device_row["id"]),
            workspace_id=body.workspace_id,
            session_id=body.session_id,
            wake_phrase=body.wake_phrase,
            boot_sound_enabled=body.boot_sound_enabled,
            spoken_reply_enabled=body.spoken_reply_enabled,
            continuous_monitoring_enabled=body.continuous_monitoring_enabled,
            voice_provider_preference=body.voice_provider_preference,
            voice_identity_preference=body.voice_identity_preference,
            active_route=body.active_route,
            app_state=body.app_state,
            meta=body.meta,
        )
    return {"axon": snapshot, "presence": presence}


@router.post("/api/mobile/axon/disarm")
async def mobile_axon_disarm(request: Request, body: MobileAxonDisarmRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        presence, snapshot = await disarm_mobile_axon_mode(
            db,
            device_id=int(device_row["id"]),
            workspace_id=body.workspace_id,
            session_id=body.session_id,
            active_route=body.active_route,
            app_state=body.app_state,
        )
    return {"axon": snapshot, "presence": presence}


@router.post("/api/mobile/axon/event")
async def mobile_axon_event(request: Request, body: MobileAxonEventRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        try:
            presence, snapshot = await record_mobile_axon_event(
                db,
                device_id=int(device_row["id"]),
                event_type=body.event_type,
                workspace_id=body.workspace_id,
                session_id=body.session_id,
                active_route=body.active_route,
                app_state=body.app_state,
                monitoring_state=body.monitoring_state,
                wake_phrase=body.wake_phrase,
                transcript=body.transcript,
                command_text=body.command_text,
                error=body.error,
                meta=body.meta,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {"axon": snapshot, "presence": presence}


@router.post("/api/mobile/axon/speak")
async def mobile_axon_speak(request: Request, body: MobileAxonSpeakRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        payload = await build_mobile_axon_audio_payload(
            db,
            device_id=int(device_row["id"]),
            text=body.text,
            preferred_provider=body.preferred_provider,
            voice_identity=body.voice_identity,
        )
    return payload


@router.post("/api/mobile/axon/voice-settings")
async def mobile_axon_voice_settings(request: Request, body: MobileVoiceSettingsRequest):
    """Push Azure speech credentials and voice tuning from mobile to backend settings."""
    await require_companion_context(request)
    ALLOWED_KEYS = {
        "azure_speech_key",
        "azure_speech_region",
        "voice_speech_rate",
        "voice_speech_pitch",
    }
    updates = {k: v for k, v in body.settings.items() if k in ALLOWED_KEYS and v is not None}
    if not updates:
        return {"ok": True, "updated": []}
    async with get_db() as db:
        from axon_data.settings import set_setting
        for key, value in updates.items():
            await set_setting(db, key, str(value))
    return {"ok": True, "updated": list(updates.keys())}
