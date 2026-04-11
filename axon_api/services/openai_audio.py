"""OpenAI audio helpers for speech synthesis and transcription."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "alloy"
DEFAULT_OPENAI_STT_MODEL = "gpt-4o-transcribe"

_OPENAI_VOICE_ALIASES = {
    "en-za-leahneural": "coral",
    "en-za-lukeneural": "verse",
    "en-gb-sonianeural": "coral",
    "en-gb-ryanneural": "verse",
    "en-us-arianeural": "coral",
    "en-us-davisneural": "verse",
    "af-za-adrineural": "sage",
    "af-za-willemneural": "echo",
}


def openai_audio_configured(settings: dict[str, Any] | None) -> bool:
    current_settings = dict(settings or {})
    return bool(str(current_settings.get("openai_api_key") or "").strip())


def resolve_openai_tts_voice(value: str = "") -> str:
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_OPENAI_TTS_VOICE
    normalized = raw.lower()
    if normalized in {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"}:
        return normalized
    return _OPENAI_VOICE_ALIASES.get(normalized, DEFAULT_OPENAI_TTS_VOICE)


def _normalize_openai_base_url(value: str = "") -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_transcription_language(value: str = "") -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw.split("-", 1)[0].lower() or None


def _normalize_tts_speed(value: float | int | str | None) -> float | None:
    if value is None:
        return None
    try:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("%"):
            return max(0.25, min(4.0, 1.0 + (float(raw[:-1]) / 100.0)))
        return max(0.25, min(4.0, float(raw)))
    except (TypeError, ValueError):
        return None


def _media_type_for_format(response_format: str) -> str:
    normalized = str(response_format or "mp3").strip().lower() or "mp3"
    return {
        "aac": "audio/aac",
        "flac": "audio/flac",
        "mp3": "audio/mpeg",
        "opus": "audio/opus",
        "pcm": "audio/wav",
        "wav": "audio/wav",
    }.get(normalized, "audio/mpeg")


def _build_client(*, api_key: str, base_url: str = ""):
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": api_key}
    normalized_base_url = _normalize_openai_base_url(base_url)
    if normalized_base_url:
        kwargs["base_url"] = normalized_base_url
    return OpenAI(**kwargs)


def _synthesize_openai_speech_sync(
    text: str,
    *,
    api_key: str,
    base_url: str = "",
    voice: str = "",
    model: str = "",
    rate: float | int | str | None = None,
    response_format: str = "mp3",
) -> tuple[bytes, str]:
    message = str(text or "").strip()
    if not message:
        return b"", _media_type_for_format(response_format)
    client = _build_client(api_key=api_key, base_url=base_url)
    output_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f".{str(response_format or 'mp3').strip().lower() or 'mp3'}",
            delete=False,
        ) as tmp_file:
            output_path = tmp_file.name
        request: dict[str, Any] = {
            "model": str(model or DEFAULT_OPENAI_TTS_MODEL).strip() or DEFAULT_OPENAI_TTS_MODEL,
            "voice": resolve_openai_tts_voice(voice),
            "input": message[:3000],
            "response_format": str(response_format or "mp3").strip().lower() or "mp3",
        }
        speed = _normalize_tts_speed(rate)
        if speed is not None:
            request["speed"] = speed
        with client.audio.speech.with_streaming_response.create(**request) as response:
            response.stream_to_file(output_path)
        return Path(output_path).read_bytes(), _media_type_for_format(request["response_format"])
    finally:
        if output_path:
            Path(output_path).unlink(missing_ok=True)


async def synthesize_openai_speech(
    text: str,
    *,
    api_key: str,
    base_url: str = "",
    voice: str = "",
    model: str = "",
    rate: float | int | str | None = None,
    response_format: str = "mp3",
) -> tuple[bytes, str]:
    return await asyncio.to_thread(
        _synthesize_openai_speech_sync,
        text,
        api_key=api_key,
        base_url=base_url,
        voice=voice,
        model=model,
        rate=rate,
        response_format=response_format,
    )


def _transcribe_openai_audio_sync(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    api_key: str,
    base_url: str = "",
    model: str = "",
    language: str = "",
) -> str:
    payload = bytes(audio_bytes or b"")
    if not payload:
        return ""
    suffix = Path(filename or "audio.webm").suffix or ".webm"
    temp_path = ""
    client = _build_client(api_key=api_key, base_url=base_url)
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(payload)
            temp_path = tmp_file.name
        request: dict[str, Any] = {
            "model": str(model or DEFAULT_OPENAI_STT_MODEL).strip() or DEFAULT_OPENAI_STT_MODEL,
        }
        normalized_language = _normalize_transcription_language(language)
        if normalized_language:
            request["language"] = normalized_language
        with Path(temp_path).open("rb") as audio_file:
            transcript = client.audio.transcriptions.create(file=audio_file, **request)
        return str(getattr(transcript, "text", "") or "").strip()
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


async def transcribe_openai_audio(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    api_key: str,
    base_url: str = "",
    model: str = "",
    language: str = "",
) -> str:
    return await asyncio.to_thread(
        _transcribe_openai_audio_sync,
        audio_bytes,
        filename=filename,
        api_key=api_key,
        base_url=base_url,
        model=model,
        language=language,
    )
