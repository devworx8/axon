"""Azure speech helpers extracted from server bootstrap code."""

from __future__ import annotations

from typing import Any


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
    aiohttp_module: Any,
    http_exception_cls: type[Exception],
) -> tuple[bytes, str]:
    token = await issue_azure_speech_token(
        region,
        key,
        aiohttp_module=aiohttp_module,
        http_exception_cls=http_exception_cls,
    )
    ssml = (
        "<speak version='1.0' xml:lang='en-ZA'>"
        f"<voice name='{voice}'>{str(text or '')[:3000]}</voice>"
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
