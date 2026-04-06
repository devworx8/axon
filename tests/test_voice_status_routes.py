from __future__ import annotations

import io
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from fastapi.responses import Response
from starlette.datastructures import UploadFile

from axon_api.routes import integration_tools, voice_status


class VoiceStatusRouteTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_voice_status_marks_cloud_transcription_ready_without_local_whisper(self):
        db_module = SimpleNamespace(
            get_db=self._fake_db,
            get_all_settings=AsyncMock(
                return_value={
                    "azure_speech_key": "secret",
                    "azure_speech_region": "eastus",
                }
            ),
        )
        handlers = voice_status.VoiceStatusRouteHandlers(
            db_module=db_module,
            local_voice_status=lambda _settings: {
                "available": False,
                "preferred_mode": "browser",
                "transcription_available": False,
                "synthesis_available": False,
                "ffmpeg_available": True,
                "detail": "Whisper backend missing; Piper runtime missing",
            },
        )

        payload = await handlers.voice_status()

        self.assertTrue(payload["cloud_transcription_available"])
        self.assertTrue(payload["transcription_ready"])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["preferred_mode"], "cloud")
        self.assertIn("Cloud transcription ready via Azure Speech", payload["detail"])

    async def test_voice_status_reports_ffmpeg_gap_when_azure_is_configured(self):
        db_module = SimpleNamespace(
            get_db=self._fake_db,
            get_all_settings=AsyncMock(
                return_value={
                    "azure_speech_key": "secret",
                    "azure_speech_region": "eastus",
                }
            ),
        )
        handlers = voice_status.VoiceStatusRouteHandlers(
            db_module=db_module,
            local_voice_status=lambda _settings: {
                "available": False,
                "preferred_mode": "browser",
                "transcription_available": False,
                "synthesis_available": False,
                "ffmpeg_available": False,
                "detail": "ffmpeg missing; Whisper backend missing; Piper runtime missing",
            },
        )

        payload = await handlers.voice_status()

        self.assertFalse(payload["cloud_transcription_available"])
        self.assertFalse(payload["transcription_ready"])
        self.assertEqual(payload["preferred_mode"], "browser")
        self.assertIn("Azure Speech is configured, but ffmpeg is missing", payload["detail"])
        self.assertIn("Whisper backend missing", payload["detail"])

    async def test_voice_transcribe_rejects_azure_uploads_before_ffmpeg_conversion_when_not_ready(self):
        db_module = SimpleNamespace(
            get_db=self._fake_db,
            get_all_settings=AsyncMock(
                return_value={
                    "azure_speech_key": "secret",
                    "azure_speech_region": "eastus",
                }
            ),
        )
        handlers = integration_tools.IntegrationToolsRouteHandlers(
            db_module=db_module,
            integrations_module=SimpleNamespace(),
            fastapi_response_cls=Response,
            local_voice_state={},
            home_path=Path("/tmp"),
            now_iso=lambda: "2026-04-06T00:00:00Z",
            issue_azure_speech_token=AsyncMock(),
            local_voice_status=lambda _settings: {
                "available": False,
                "preferred_mode": "browser",
                "transcription_available": False,
                "synthesis_available": False,
                "ffmpeg_available": False,
                "detail": "ffmpeg missing; Whisper backend missing; Piper runtime missing",
            },
            local_voice_paths=lambda _settings=None: {},
            run_ffmpeg_to_wav=lambda _src, _dst: None,
            transcribe_local_audio=lambda *_args, **_kwargs: ("", ""),
            speak_local_text=lambda *_args, **_kwargs: (b"", ""),
            safe_path=lambda _path: Path("/tmp"),
        )

        with self.assertRaises(HTTPException) as exc:
            await handlers.voice_transcribe(
                file=UploadFile(filename="voice.webm", file=io.BytesIO(b"audio")),
                language="en",
            )

        self.assertEqual(exc.exception.status_code, 503)
        self.assertIn("ffmpeg is missing", str(exc.exception.detail))


if __name__ == "__main__":
    unittest.main()
