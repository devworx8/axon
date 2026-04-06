from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import server
from axon_api import settings_models
from axon_api.routes import integration_tools


class ServerVoiceSettingsFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_update_facade_delegates_to_extracted_handler(self):
        body = settings_models.SettingsUpdate(
            voice_speech_rate="0.91",
            voice_speech_pitch="1.08",
            local_tts_model_path="/tmp/piper.onnx",
        )

        with patch.object(
            server._settings_memory_handlers,
            "update_settings",
            AsyncMock(return_value={"updated": ["voice_speech_rate", "voice_speech_pitch", "local_tts_model_path"]}),
        ) as update_call:
            payload = await server.update_settings(body)

        update_call.assert_awaited_once()
        forwarded = update_call.await_args.args[0]
        self.assertEqual(forwarded.voice_speech_rate, "0.91")
        self.assertEqual(forwarded.voice_speech_pitch, "1.08")
        self.assertEqual(forwarded.local_tts_model_path, "/tmp/piper.onnx")
        self.assertIn("voice_speech_rate", payload["updated"])

    async def test_azure_tts_facade_uses_shared_azure_speech_service(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        with patch.object(server.devdb, "get_db", fake_db), patch.object(
            server.devdb,
            "get_all_settings",
            AsyncMock(return_value={"azure_speech_key": "secret", "azure_speech_region": "eastus"}),
        ), patch.object(
            server.azure_speech_service,
            "synthesize_azure_speech",
            AsyncMock(return_value=(b"audio-bytes", "audio/mpeg")),
        ) as synth_call:
            response = await server.azure_tts(
                integration_tools.TTSRequest(
                    text="Status report",
                    voice="en-ZA-LeahNeural",
                    rate="+5%",
                    pitch="+4%",
                )
            )

        synth_call.assert_awaited_once()
        kwargs = synth_call.await_args.kwargs
        self.assertEqual(kwargs["rate"], "+5%")
        self.assertEqual(kwargs["pitch"], "+4%")
        self.assertEqual(response.body, b"audio-bytes")
        self.assertEqual(response.media_type, "audio/mpeg")


if __name__ == "__main__":
    unittest.main()
