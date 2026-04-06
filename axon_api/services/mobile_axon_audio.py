"""Speech synthesis payloads for Axon mobile replies."""

from __future__ import annotations

import base64
from typing import Any

import aiohttp
from fastapi import HTTPException

from axon_api.services.azure_speech import synthesize_azure_speech
from axon_api.services.mobile_axon_state import extract_axon_state
from axon_api.services.mobile_axon_voice import (
    DEFAULT_AZURE_VOICE,
    resolve_axon_voice_profile,
    speak_local_mobile_text,
    voice_dependency_snapshot,
)
from axon_data import get_all_settings, get_companion_presence


async def build_mobile_axon_audio_payload(
    db,
    *,
    device_id: int,
    text: str,
    preferred_provider: str = "",
    voice_identity: str = "",
) -> dict[str, Any]:
    message = str(text or "").strip()
    if not message:
        raise HTTPException(400, "Speech text is required.")

    settings = dict(await get_all_settings(db) or {})
    presence = await get_companion_presence(db, device_id)
    state = extract_axon_state(presence)
    voice_status = voice_dependency_snapshot(settings)
    profile = resolve_axon_voice_profile(
        settings,
        voice_status,
        preferred_provider=preferred_provider or state.get("voice_provider_preference") or "cloud",
        preferred_voice=voice_identity or state.get("voice_identity_preference") or "",
    )

    provider = str(profile.get("voice_provider") or "unavailable")
    voice_identity_value = str(profile.get("voice_identity") or "")
    audio = b""
    media_type = ""
    detail = str(profile.get("voice_provider_detail") or "")

    if provider == "cloud":
        try:
            audio, media_type = await synthesize_azure_speech(
                message,
                voice=str(profile.get("voice_identity") or settings.get("azure_voice") or DEFAULT_AZURE_VOICE),
                region=str(settings.get("azure_speech_region") or "eastus").strip() or "eastus",
                key=str(settings.get("azure_speech_key") or "").strip(),
                rate=settings.get("voice_speech_rate"),
                pitch=settings.get("voice_speech_pitch"),
                aiohttp_module=aiohttp,
                http_exception_cls=HTTPException,
            )
        except Exception as exc:
            if profile.get("local_ready"):
                audio, local_engine = speak_local_mobile_text(settings, message)
                provider = "local"
                voice_identity_value = str(local_engine or "local").strip() or "local"
                media_type = "audio/wav"
                detail = f"{detail} · Fell back to local synthesis"
            else:
                if isinstance(exc, HTTPException):
                    raise exc
                raise HTTPException(502, f"Cloud speech failed: {exc}") from exc
    elif provider == "local":
        audio, local_engine = speak_local_mobile_text(settings, message)
        voice_identity_value = str(local_engine or "local").strip() or "local"
        media_type = "audio/wav"
    else:
        raise HTTPException(503, detail or "Speech reply is not ready.")

    return {
        "provider": provider,
        "voice_identity": voice_identity_value,
        "detail": detail,
        "media_type": media_type,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
    }
