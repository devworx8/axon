"""Public voice-status payload helpers shared across route surfaces."""

from __future__ import annotations

from typing import Any


def build_voice_status_payload(
    settings: dict[str, Any] | None,
    local_status: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(local_status or {})
    current_settings = dict(settings or {})
    azure_key = str(current_settings.get("azure_speech_key") or "").strip()
    azure_region = str(current_settings.get("azure_speech_region") or "").strip()
    cloud_configured = bool(azure_key and azure_region)
    has_ffmpeg = bool(payload.get("ffmpeg_available"))
    local_transcription_ready = bool(payload.get("transcription_available"))
    cloud_transcription_ready = bool(cloud_configured and has_ffmpeg)

    payload["cloud_transcription_available"] = cloud_transcription_ready
    payload["transcription_ready"] = local_transcription_ready or cloud_transcription_ready

    detail = str(payload.get("detail") or "").strip()
    if cloud_transcription_ready and not local_transcription_ready:
        payload["available"] = True
        payload["preferred_mode"] = "cloud"
        payload["detail"] = (
            f"Cloud transcription ready via Azure Speech; {detail}"
            if detail
            else "Cloud transcription ready via Azure Speech."
        )
    elif cloud_configured and not has_ffmpeg and not local_transcription_ready:
        cloud_detail = "Azure Speech is configured, but ffmpeg is missing for uploaded mobile audio."
        payload["detail"] = (
            f"{cloud_detail} {detail}"
            if detail
            else cloud_detail
        )

    return payload
