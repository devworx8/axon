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
    openai_key = str(current_settings.get("openai_api_key") or "").strip()
    azure_configured = bool(azure_key and azure_region)
    openai_configured = bool(openai_key)
    has_ffmpeg = bool(payload.get("ffmpeg_available"))
    local_transcription_ready = bool(payload.get("transcription_available"))
    local_synthesis_ready = bool(payload.get("synthesis_available"))
    azure_cloud_transcription_ready = bool(azure_configured and has_ffmpeg)
    openai_cloud_transcription_ready = bool(openai_configured)
    cloud_transcription_ready = bool(openai_cloud_transcription_ready or azure_cloud_transcription_ready)
    cloud_synthesis_ready = bool(openai_configured or azure_configured)
    cloud_provider = "openai" if openai_configured else ("azure" if azure_configured else "")

    payload["cloud_transcription_available"] = cloud_transcription_ready
    payload["cloud_synthesis_available"] = cloud_synthesis_ready
    payload["cloud_provider"] = cloud_provider
    payload["cloud_transcription_provider"] = (
        "openai"
        if openai_cloud_transcription_ready
        else ("azure" if azure_cloud_transcription_ready else "")
    )
    payload["cloud_synthesis_provider"] = cloud_provider
    payload["transcription_ready"] = local_transcription_ready or cloud_transcription_ready
    payload["synthesis_ready"] = local_synthesis_ready or cloud_synthesis_ready
    payload["available"] = bool(payload.get("available")) or payload["transcription_ready"] or payload["synthesis_ready"]

    detail = str(payload.get("detail") or "").strip()
    if openai_configured and not local_transcription_ready and not local_synthesis_ready:
        payload["preferred_mode"] = "cloud"
        payload["detail"] = (
            f"Cloud voice ready via OpenAI; {detail}"
            if detail
            else "Cloud voice ready via OpenAI."
        )
    elif cloud_transcription_ready and not local_transcription_ready:
        payload["available"] = True
        payload["preferred_mode"] = "cloud"
        payload["detail"] = (
            f"Cloud transcription ready via Azure Speech; {detail}"
            if detail
            else "Cloud transcription ready via Azure Speech."
        )
    elif azure_configured and not has_ffmpeg and not local_transcription_ready:
        cloud_detail = "Azure Speech is configured, but ffmpeg is missing for uploaded mobile audio."
        payload["detail"] = (
            f"{cloud_detail} {detail}"
            if detail
            else cloud_detail
        )

    return payload
