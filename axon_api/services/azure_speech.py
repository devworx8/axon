"""Azure speech helpers extracted from server bootstrap code."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from axon_api.services.voice_tuning import (
    DEFAULT_VOICE_PITCH,
    DEFAULT_VOICE_RATE,
    azure_voice_pitch_attr,
    azure_voice_rate_attr,
)


async def issue_azure_speech_token(
    region: str,
    key: str,
    *,
    aiohttp_module: Any,
    http_exception_cls: type[Exception],
) -> str:
    token_url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with aiohttp_module.ClientSession() as session:
        async with session.post(
            token_url,
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=aiohttp_module.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                raise http_exception_cls(400, f"Azure auth failed ({response.status})")
            return await response.text()


async def synthesize_azure_speech(
    text: str,
    *,
    voice: str,
    region: str,
    key: str,
    rate: float | int | str | None = None,
    pitch: float | int | str | None = None,
    aiohttp_module: Any,
    http_exception_cls: type[Exception],
) -> tuple[bytes, str]:
    token = await issue_azure_speech_token(
        region,
        key,
        aiohttp_module=aiohttp_module,
        http_exception_cls=http_exception_cls,
    )
    safe_voice = escape(str(voice or ""), {"'": "&apos;", '"': "&quot;"})
    safe_text = escape(str(text or "")[:3000])
    rate_attr = azure_voice_rate_attr(rate if rate is not None else DEFAULT_VOICE_RATE)
    pitch_attr = azure_voice_pitch_attr(pitch if pitch is not None else DEFAULT_VOICE_PITCH)
    ssml = (
        "<speak version='1.0' xml:lang='en-ZA'>"
        f"<voice name='{safe_voice}'><prosody rate='{rate_attr}' pitch='{pitch_attr}'>{safe_text}</prosody></voice>"
        "</speak>"
    )
    tts_url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    async with aiohttp_module.ClientSession() as session:
        async with session.post(
            tts_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            },
            data=ssml.encode("utf-8"),
            timeout=aiohttp_module.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                raise http_exception_cls(502, f"Azure TTS failed ({response.status})")
            return await response.read(), "audio/mpeg"


async def transcribe_azure_speech(
    wav_path: str,
    *,
    region: str,
    key: str,
    language: str = "en-US",
    aiohttp_module: Any,
    http_exception_cls: type[Exception],
) -> str:
    """Transcribe a WAV file via Azure Speech-to-Text REST v1 (short audio)."""
    from pathlib import Path

    audio_data = Path(wav_path).read_bytes()
    stt_url = (
        f"https://{region}.stt.speech.microsoft.com/"
        f"speech/recognition/conversation/cognitiveservices/v1"
        f"?language={language}"
    )
    async with aiohttp_module.ClientSession() as session:
        async with session.post(
            stt_url,
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
            data=audio_data,
            timeout=aiohttp_module.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                raise http_exception_cls(
                    502, f"Azure STT failed ({response.status})"
                )
            result = await response.json()
            status = result.get("RecognitionStatus", "")
            if status == "Success":
                return result.get("DisplayText", "")
            if status == "NoMatch":
                return ""
            raise http_exception_cls(
                502, f"Azure STT status: {status}"
            )
