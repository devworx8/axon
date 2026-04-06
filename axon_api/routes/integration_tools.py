"""Voice, integration, and file browser routes extracted from server.py."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-ZA-LeahNeural"
    rate: float = 0.92


class VoiceSpeakRequest(BaseModel):
    text: str
    format: str = "wav"


class SlackTestRequest(BaseModel):
    webhook_url: str


class WebhookTestRequest(BaseModel):
    url: str
    secret: str = ""


class FileWriteBody(BaseModel):
    path: str
    content: str


def _normalized_voice_rate(value: float | int | str | None) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = 0.85
    return max(0.50, min(1.15, rate))


def _azure_voice_rate_attr(value: float | int | str | None) -> str:
    rate = _normalized_voice_rate(value)
    delta = int(round((rate - 1.0) * 100))
    return f"{delta:+d}%"


class IntegrationToolsRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        integrations_module: Any,
        fastapi_response_cls: type[Response],
        local_voice_state: dict[str, Any],
        home_path: Path,
        now_iso: Callable[[], str],
        issue_azure_speech_token: Callable[[str, str], Any],
        local_voice_status: Callable[[Optional[dict]], dict[str, Any]],
        local_voice_paths: Callable[[Optional[dict]], dict[str, Any]],
        run_ffmpeg_to_wav: Callable[[str, str], None],
        transcribe_local_audio: Callable[..., tuple[str, str]],
        speak_local_text: Callable[..., tuple[bytes, str]],
        safe_path: Callable[[str], Path],
    ) -> None:
        self._db = db_module
        self._integ = integrations_module
        self._fastapi_response_cls = fastapi_response_cls
        self._local_voice_state = local_voice_state
        self._home = home_path
        self._now_iso = now_iso
        self._issue_azure_speech_token = issue_azure_speech_token
        self._local_voice_status = local_voice_status
        self._local_voice_paths = local_voice_paths
        self._run_ffmpeg_to_wav = run_ffmpeg_to_wav
        self._transcribe_local_audio = transcribe_local_audio
        self._speak_local_text = speak_local_text
        self._safe_path = safe_path

    async def azure_tts(self, body: TTSRequest):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        key = settings.get("azure_speech_key", "")
        region = settings.get("azure_speech_region", "eastus")
        if not key:
            raise HTTPException(400, "Azure Speech key not set in Settings")

        safe_voice = escape(body.voice, {"'": "&apos;", '"': "&quot;"})
        safe_text = escape(body.text[:900])
        rate_attr = _azure_voice_rate_attr(body.rate)
        ssml = f"""<speak version='1.0' xml:lang='en-ZA'>
        <voice name='{safe_voice}'><prosody rate='{rate_attr}'>{safe_text}</prosody></voice>
    </speak>"""
        tts_url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

        import aiohttp

        try:
            token = await self._issue_azure_speech_token(region, key)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    tts_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/ssml+xml",
                        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                    },
                    data=ssml.encode("utf-8"),
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        raise HTTPException(502, "Azure TTS failed")
                    audio = await response.read()
            return self._fastapi_response_cls(content=audio, media_type="audio/mpeg")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"TTS error: {exc}")

    async def azure_stt_token(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        key = settings.get("azure_speech_key", "")
        region = settings.get("azure_speech_region", "eastus")
        if not key:
            raise HTTPException(400, "Azure Speech key not set in Settings")
        token = await self._issue_azure_speech_token(region, key)
        return {"token": token, "region": region, "expires_in": 540}

    async def list_tts_voices(self):
        return {
            "voices": [
                {"id": "en-ZA-LeahNeural", "name": "Leah (SA English)", "lang": "en-ZA", "gender": "Female"},
                {"id": "en-ZA-LukeNeural", "name": "Luke (SA English)", "lang": "en-ZA", "gender": "Male"},
                {"id": "en-GB-SoniaNeural", "name": "Sonia (British)", "lang": "en-GB", "gender": "Female"},
                {"id": "en-GB-RyanNeural", "name": "Ryan (British)", "lang": "en-GB", "gender": "Male"},
                {"id": "en-US-AriaNeural", "name": "Aria (US)", "lang": "en-US", "gender": "Female"},
                {"id": "en-US-DavisNeural", "name": "Davis (US)", "lang": "en-US", "gender": "Male"},
                {"id": "af-ZA-AdriNeural", "name": "Adri (Afrikaans)", "lang": "af-ZA", "gender": "Female"},
                {"id": "af-ZA-WillemNeural", "name": "Willem (Afrikaans)", "lang": "af-ZA", "gender": "Male"},
            ]
        }

    async def voice_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        return self._local_voice_status(settings)

    async def voice_transcribe(self, file: UploadFile = File(...), language: str = Query(default="en")):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        status = self._local_voice_status(settings)
        if not status["transcription_available"]:
            raise HTTPException(503, status["detail"])

        suffix = Path(file.filename or "voice.webm").suffix or ".webm"
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(400, "No audio payload received")

        input_path = ""
        wav_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as input_file:
                input_file.write(raw_bytes)
                input_path = input_file.name
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = wav_file.name
            self._run_ffmpeg_to_wav(input_path, wav_path)
            text, engine = self._transcribe_local_audio(
                wav_path,
                model_name=status["stt_model"],
                language=language or status["language"],
            )
            self._local_voice_state.update({"last_engine": engine, "last_error": "", "updated_at": self._now_iso()})
            return {"text": text, "engine": engine, "language": language or status["language"]}
        except HTTPException as exc:
            self._local_voice_state.update({"last_error": str(exc.detail), "updated_at": self._now_iso()})
            raise
        except Exception as exc:
            self._local_voice_state.update({"last_error": str(exc), "updated_at": self._now_iso()})
            raise HTTPException(502, f"Voice transcription failed: {exc}")
        finally:
            if input_path:
                Path(input_path).unlink(missing_ok=True)
            if wav_path:
                Path(wav_path).unlink(missing_ok=True)

    async def voice_speak(self, body: VoiceSpeakRequest):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        status = self._local_voice_status(settings)
        if not status["synthesis_available"]:
            raise HTTPException(503, status["detail"])
        paths = self._local_voice_paths(settings)
        self._local_voice_state.update({"speaking": True, "last_error": "", "updated_at": self._now_iso()})
        try:
            audio, engine = self._speak_local_text(
                body.text,
                model_path=paths["piper_model_path"],
                config_path=paths["piper_config_path"],
            )
            self._local_voice_state.update({"speaking": False, "last_engine": engine, "updated_at": self._now_iso()})
            return self._fastapi_response_cls(content=audio, media_type="audio/wav")
        except HTTPException as exc:
            self._local_voice_state.update({"speaking": False, "last_error": str(exc.detail), "updated_at": self._now_iso()})
            raise
        except Exception as exc:
            self._local_voice_state.update({"speaking": False, "last_error": str(exc), "updated_at": self._now_iso()})
            raise HTTPException(502, f"Voice synthesis failed: {exc}")

    async def voice_stop(self):
        self._local_voice_state.update({"speaking": False, "updated_at": self._now_iso()})
        return {"stopped": True}

    async def github_status(self):
        return {"available": self._integ.is_gh_available()}

    async def project_github(self, project_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_project(conn, project_id)
            settings = await self._db.get_all_settings(conn)
        if not row:
            raise HTTPException(404, "Project not found")
        token = settings.get("github_token", "")
        return await self._integ.github_full_status(row["path"], token)

    async def test_slack(self, body: SlackTestRequest):
        ok = await self._integ.slack_send(
            body.webhook_url,
            "✅ Axon connected to Slack successfully. Morning Briefs will appear here.",
        )
        if not ok:
            raise HTTPException(400, "Slack webhook failed. Check your URL.")
        return {"sent": True}

    async def test_webhook(self, body: WebhookTestRequest):
        ok = await self._integ.fire_webhook(
            body.url,
            "devbrain.test",
            {"message": "Axon webhook test", "timestamp": "now"},
            body.secret,
        )
        if not ok:
            raise HTTPException(400, "Webhook failed. Check your URL.")
        return {"sent": True}

    async def files_browse(self, path: str = "~"):
        target = self._safe_path(path)
        if not target.exists():
            raise HTTPException(404, "Path not found")
        if not target.is_dir():
            raise HTTPException(400, "Path is not a directory — use /read")
        items = []
        try:
            for entry in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
                if entry.name.startswith(".") and entry.name not in (".env", ".envrc"):
                    continue
                stat = entry.stat()
                items.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "rel": str(entry.relative_to(self._home)),
                        "is_dir": entry.is_dir(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "ext": entry.suffix.lower() if entry.is_file() else "",
                    }
                )
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        return {
            "path": str(target),
            "rel": str(target.relative_to(self._home)),
            "parent": str(target.parent.relative_to(self._home)) if target != self._home else None,
            "items": items,
        }

    async def files_read(self, path: str):
        target = self._safe_path(path)
        if not target.exists():
            raise HTTPException(404, "File not found")
        if target.is_dir():
            raise HTTPException(400, "Path is a directory — use /browse")
        size = target.stat().st_size
        if size > 512 * 1024:
            raise HTTPException(413, f"File too large ({size // 1024}KB > 512KB limit)")
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        return {"path": str(target), "rel": str(target.relative_to(self._home)), "content": content, "size": size, "ext": target.suffix.lower()}

    async def files_write(self, body: FileWriteBody):
        target = self._safe_path(body.path)
        if target.is_dir():
            raise HTTPException(400, "Path is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(body.content, encoding="utf-8")
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        return {"path": str(target), "rel": str(target.relative_to(self._home)), "size": len(body.content.encode()), "written": True}


def build_integration_tools_router(
    *,
    db_module: Any,
    integrations_module: Any,
    fastapi_response_cls: type[Response],
    local_voice_state: dict[str, Any],
    home_path: Path,
    now_iso: Callable[[], str],
    issue_azure_speech_token: Callable[[str, str], Any],
    local_voice_status: Callable[[Optional[dict]], dict[str, Any]],
    local_voice_paths: Callable[[Optional[dict]], dict[str, Any]],
    run_ffmpeg_to_wav: Callable[[str, str], None],
    transcribe_local_audio: Callable[..., tuple[str, str]],
    speak_local_text: Callable[..., tuple[bytes, str]],
    safe_path: Callable[[str], Path],
):
    handlers = IntegrationToolsRouteHandlers(
        db_module=db_module,
        integrations_module=integrations_module,
        fastapi_response_cls=fastapi_response_cls,
        local_voice_state=local_voice_state,
        home_path=home_path,
        now_iso=now_iso,
        issue_azure_speech_token=issue_azure_speech_token,
        local_voice_status=local_voice_status,
        local_voice_paths=local_voice_paths,
        run_ffmpeg_to_wav=run_ffmpeg_to_wav,
        transcribe_local_audio=transcribe_local_audio,
        speak_local_text=speak_local_text,
        safe_path=safe_path,
    )
    router = APIRouter()
    router.add_api_route("/api/tts", handlers.azure_tts, methods=["POST"])
    router.add_api_route("/api/stt/token", handlers.azure_stt_token, methods=["GET"])
    router.add_api_route("/api/tts/voices", handlers.list_tts_voices, methods=["GET"])
    router.add_api_route("/api/voice/status", handlers.voice_status, methods=["GET"])
    router.add_api_route("/api/voice/transcribe", handlers.voice_transcribe, methods=["POST"])
    router.add_api_route("/api/voice/speak", handlers.voice_speak, methods=["POST"])
    router.add_api_route("/api/voice/stop", handlers.voice_stop, methods=["POST"])
    router.add_api_route("/api/github/status", handlers.github_status, methods=["GET"])
    router.add_api_route("/api/projects/{project_id}/github", handlers.project_github, methods=["GET"])
    router.add_api_route("/api/slack/test", handlers.test_slack, methods=["POST"])
    router.add_api_route("/api/webhooks/test", handlers.test_webhook, methods=["POST"])
    router.add_api_route("/api/files/browse", handlers.files_browse, methods=["GET"])
    router.add_api_route("/api/files/read", handlers.files_read, methods=["GET"])
    router.add_api_route("/api/files/write", handlers.files_write, methods=["POST"])
    return router, handlers
