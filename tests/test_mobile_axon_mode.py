from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from axon_api.routes import mobile_axon
from axon_api.services import mobile_axon_audio, mobile_axon_mode


class MobileAxonModeServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_axon_state_reads_presence_meta(self):
        presence = {
            "active_route": "/voice",
            "app_state": "foreground",
            "meta_json": (
                '{"axon_mode":{"armed":true,"monitoring_state":"engaged","wake_phrase":"Computer",'
                '"boot_sound_enabled":false,"continuous_monitoring_enabled":true,'
                '"last_command_text":"open the dashboard","last_error":""}}'
            ),
        }

        state = mobile_axon_mode.extract_axon_state(presence)

        self.assertTrue(state["armed"])
        self.assertEqual(state["monitoring_state"], "engaged")
        self.assertEqual(state["wake_phrase"], "Computer")
        self.assertEqual(state["last_command_text"], "open the dashboard")
        self.assertEqual(state["active_route"], "/voice")

    async def test_arm_mobile_axon_mode_marks_degraded_when_transcription_missing(self):
        with patch.object(
            mobile_axon_mode,
            "local_voice_snapshot",
            AsyncMock(return_value={"available": False, "transcription_available": False, "detail": "Local transcription unavailable"}),
        ), patch.object(
            mobile_axon_mode,
            "_persist_axon_state",
            AsyncMock(return_value=({"device_id": 7}, {"monitoring_state": "degraded", "last_error": "Local transcription unavailable"})),
        ) as persist:
            _presence, snapshot = await mobile_axon_mode.arm_mobile_axon_mode(
                object(),
                device_id=7,
                wake_phrase="Axon",
            )

        kwargs = persist.await_args.kwargs
        self.assertEqual(kwargs["state_patch"]["monitoring_state"], "degraded")
        self.assertIn("Local transcription unavailable", kwargs["state_patch"]["last_error"])
        self.assertEqual(snapshot["monitoring_state"], "degraded")

    async def test_build_mobile_axon_snapshot_resolves_cloud_voice_identity(self):
        presence = {
            "active_route": "/voice",
            "app_state": "foreground",
            "meta_json": (
                '{"axon_mode":{"armed":true,"monitoring_state":"armed","wake_phrase":"Axon",'
                '"voice_provider_preference":"cloud","voice_identity_preference":"en-US-AriaNeural"}}'
            ),
        }

        with patch.object(
            mobile_axon_mode,
            "get_all_settings",
            AsyncMock(return_value={"azure_speech_key": "test", "azure_speech_region": "eastus", "azure_voice": "en-ZA-LeahNeural"}),
        ), patch.object(
            mobile_axon_mode,
            "local_voice_snapshot",
            AsyncMock(return_value={"available": True, "transcription_available": True, "synthesis_available": True, "detail": "ready"}),
        ):
            snapshot = await mobile_axon_mode.build_mobile_axon_snapshot(object(), device_id=7, presence_row=presence)

        self.assertEqual(snapshot["voice_provider"], "cloud")
        self.assertEqual(snapshot["voice_identity"], "en-US-AriaNeural")
        self.assertTrue(snapshot["voice_provider_ready"])

    async def test_arm_mobile_axon_mode_treats_active_state_as_foreground(self):
        with patch.object(
            mobile_axon_mode,
            "local_voice_snapshot",
            AsyncMock(return_value={"available": True, "transcription_available": True, "synthesis_available": True, "detail": "ready"}),
        ), patch.object(
            mobile_axon_mode,
            "_persist_axon_state",
            AsyncMock(return_value=({"device_id": 7}, {"monitoring_state": "armed"})),
        ) as persist:
            _presence, snapshot = await mobile_axon_mode.arm_mobile_axon_mode(
                object(),
                device_id=7,
                wake_phrase="Axon",
                app_state="active",
            )

        kwargs = persist.await_args.kwargs
        self.assertEqual(kwargs["state_patch"]["monitoring_state"], "armed")
        self.assertEqual(kwargs["app_state"], "active")
        self.assertEqual(snapshot["monitoring_state"], "armed")

    async def test_record_mobile_axon_event_promotes_wake_detected_to_engaged(self):
        with patch.object(
            mobile_axon_mode,
            "_persist_axon_state",
            AsyncMock(return_value=({"device_id": 7}, {"monitoring_state": "engaged", "last_command_text": "open workspace"})),
        ) as persist:
            _presence, snapshot = await mobile_axon_mode.record_mobile_axon_event(
                object(),
                device_id=7,
                event_type="wake_detected",
                transcript="Axon open workspace",
                command_text="open workspace",
            )

        kwargs = persist.await_args.kwargs
        self.assertEqual(kwargs["state_patch"]["monitoring_state"], "engaged")
        self.assertEqual(kwargs["state_patch"]["last_command_text"], "open workspace")
        self.assertIn("last_wake_at", kwargs["state_patch"])
        self.assertEqual(snapshot["monitoring_state"], "engaged")

    async def test_record_mobile_axon_event_marks_listening_started_as_listening(self):
        with patch.object(
            mobile_axon_mode,
            "_persist_axon_state",
            AsyncMock(return_value=({"device_id": 7}, {"monitoring_state": "listening"})),
        ) as persist:
            _presence, snapshot = await mobile_axon_mode.record_mobile_axon_event(
                object(),
                device_id=7,
                event_type="listening_started",
            )

        kwargs = persist.await_args.kwargs
        self.assertEqual(kwargs["state_patch"]["monitoring_state"], "listening")
        self.assertTrue(kwargs["state_patch"]["armed"])
        self.assertEqual(snapshot["monitoring_state"], "listening")

    async def test_record_mobile_axon_event_backgrounded_marks_degraded(self):
        with patch.object(
            mobile_axon_mode,
            "_persist_axon_state",
            AsyncMock(return_value=({"device_id": 7}, {"monitoring_state": "degraded"})),
        ) as persist:
            _presence, snapshot = await mobile_axon_mode.record_mobile_axon_event(
                object(),
                device_id=7,
                event_type="backgrounded",
                error="App left the foreground, so Axon mode paused.",
            )

        kwargs = persist.await_args.kwargs
        self.assertEqual(kwargs["state_patch"]["monitoring_state"], "degraded")
        self.assertEqual(kwargs["state_patch"]["degraded_reason"], "App left the foreground, so Axon mode paused.")
        self.assertEqual(snapshot["monitoring_state"], "degraded")

    async def test_record_mobile_axon_event_rejects_unknown_event(self):
        with self.assertRaises(ValueError):
            await mobile_axon_mode.record_mobile_axon_event(
                object(),
                device_id=7,
                event_type="unsupported",
            )

    async def test_build_mobile_axon_audio_payload_falls_back_to_local_when_cloud_fails(self):
        with patch.object(
            mobile_axon_audio,
            "get_all_settings",
            AsyncMock(return_value={"azure_speech_key": "test", "azure_speech_region": "eastus"}),
        ), patch.object(
            mobile_axon_audio,
            "get_companion_presence",
            AsyncMock(return_value={"meta_json": '{"axon_mode":{"voice_provider_preference":"cloud"}}'}),
        ), patch.object(
            mobile_axon_audio,
            "voice_dependency_snapshot",
            return_value={"synthesis_available": True, "piper_engine": "piper"},
        ), patch.object(
            mobile_axon_audio,
            "resolve_axon_voice_profile",
            return_value={
                "voice_provider": "cloud",
                "voice_provider_detail": "Azure speech ready · en-ZA-LeahNeural",
                "voice_identity": "en-ZA-LeahNeural",
                "local_ready": True,
            },
        ), patch.object(
            mobile_axon_audio,
            "synthesize_azure_speech",
            AsyncMock(side_effect=RuntimeError("azure down")),
        ), patch.object(
            mobile_axon_audio,
            "speak_local_mobile_text",
            return_value=(b"wav-bytes", "piper"),
        ):
            payload = await mobile_axon_audio.build_mobile_axon_audio_payload(
                object(),
                device_id=7,
                text="Status report",
            )

        self.assertEqual(payload["provider"], "local")
        self.assertEqual(payload["voice_identity"], "piper")
        self.assertEqual(payload["media_type"], "audio/wav")
        self.assertIn("Fell back to local synthesis", payload["detail"])

    async def test_build_mobile_axon_audio_payload_rejects_blank_text(self):
        with self.assertRaises(HTTPException) as exc:
            await mobile_axon_audio.build_mobile_axon_audio_payload(
                object(),
                device_id=7,
                text="   ",
            )

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Speech text is required", str(exc.exception.detail))

    async def test_build_mobile_axon_audio_payload_applies_configured_voice_rate_and_pitch(self):
        synth = AsyncMock(return_value=(b"mp3-bytes", "audio/mpeg"))
        with patch.object(
            mobile_axon_audio,
            "get_all_settings",
            AsyncMock(
                return_value={
                    "azure_speech_key": "test",
                    "azure_speech_region": "eastus",
                    "voice_speech_rate": "0.85",
                    "voice_speech_pitch": "1.04",
                }
            ),
        ), patch.object(
            mobile_axon_audio,
            "get_companion_presence",
            AsyncMock(return_value={"meta_json": '{"axon_mode":{"voice_provider_preference":"cloud"}}'}),
        ), patch.object(
            mobile_axon_audio,
            "voice_dependency_snapshot",
            return_value={"synthesis_available": False},
        ), patch.object(
            mobile_axon_audio,
            "resolve_axon_voice_profile",
            return_value={
                "voice_provider": "cloud",
                "voice_provider_detail": "Azure speech ready · en-ZA-LeahNeural",
                "voice_identity": "en-ZA-LeahNeural",
                "local_ready": False,
            },
        ), patch.object(
            mobile_axon_audio,
            "synthesize_azure_speech",
            synth,
        ):
            payload = await mobile_axon_audio.build_mobile_axon_audio_payload(
                object(),
                device_id=7,
                text="Status report",
            )

        self.assertEqual(payload["provider"], "cloud")
        self.assertEqual(payload["media_type"], "audio/mpeg")
        self.assertEqual(synth.await_args.kwargs["rate"], "0.85")
        self.assertEqual(synth.await_args.kwargs["pitch"], "1.04")


class MobileAxonRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_mobile_axon_status_returns_snapshot(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(mobile_axon, "build_mobile_axon_snapshot", AsyncMock(return_value={"armed": True, "monitoring_state": "armed"})):
            payload = await mobile_axon.mobile_axon_status(request)

        self.assertTrue(payload["axon"]["armed"])
        self.assertEqual(payload["axon"]["monitoring_state"], "armed")

    async def test_mobile_axon_arm_forwards_voice_preferences(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonArmRequest(
            wake_phrase="Axon",
            voice_provider_preference="local",
            voice_identity_preference="piper",
            active_route="/voice",
            app_state="active",
        )

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(
                 mobile_axon,
                 "arm_mobile_axon_mode",
                 AsyncMock(return_value=({"device_id": 7}, {"armed": True, "monitoring_state": "armed"})),
             ) as arm_call:
            payload = await mobile_axon.mobile_axon_arm(request, body)

        kwargs = arm_call.await_args.kwargs
        self.assertEqual(kwargs["voice_provider_preference"], "local")
        self.assertEqual(kwargs["voice_identity_preference"], "piper")
        self.assertEqual(kwargs["app_state"], "active")
        self.assertTrue(payload["axon"]["armed"])

    async def test_mobile_axon_disarm_returns_snapshot(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonDisarmRequest()

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(
                 mobile_axon,
                 "disarm_mobile_axon_mode",
                 AsyncMock(return_value=({"device_id": 7}, {"armed": False, "monitoring_state": "idle"})),
             ):
            payload = await mobile_axon.mobile_axon_disarm(request, body)

        self.assertFalse(payload["axon"]["armed"])
        self.assertEqual(payload["axon"]["monitoring_state"], "idle")

    async def test_mobile_axon_event_maps_value_error_to_bad_request(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonEventRequest(event_type="bad")

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(mobile_axon, "record_mobile_axon_event", AsyncMock(side_effect=ValueError("Unsupported Axon event 'bad'."))):
            with self.assertRaises(HTTPException) as exc:
                await mobile_axon.mobile_axon_event(request, body)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Unsupported Axon event", str(exc.exception.detail))

    async def test_mobile_axon_event_success_returns_snapshot(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonEventRequest(event_type="backgrounded", error="App left the foreground, so Axon mode paused.")

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(
                 mobile_axon,
                 "record_mobile_axon_event",
                 AsyncMock(return_value=({"device_id": 7}, {"armed": True, "monitoring_state": "degraded"})),
             ):
            payload = await mobile_axon.mobile_axon_event(request, body)

        self.assertTrue(payload["axon"]["armed"])
        self.assertEqual(payload["axon"]["monitoring_state"], "degraded")

    async def test_mobile_axon_speak_returns_audio_payload(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonSpeakRequest(text="Status report")

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(
                 mobile_axon,
                 "build_mobile_axon_audio_payload",
                 AsyncMock(return_value={"provider": "cloud", "voice_identity": "en-ZA-LeahNeural", "media_type": "audio/mpeg", "audio_base64": "YWJj"}),
             ):
            payload = await mobile_axon.mobile_axon_speak(request, body)

        self.assertEqual(payload["provider"], "cloud")
        self.assertEqual(payload["media_type"], "audio/mpeg")
        self.assertEqual(payload["audio_base64"], "YWJj")

    async def test_mobile_axon_speak_forwards_provider_preferences(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        request = SimpleNamespace()
        body = mobile_axon.MobileAxonSpeakRequest(
            text="Status report",
            preferred_provider="local",
            voice_identity="piper",
        )

        with patch.object(mobile_axon, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_axon, "get_db", fake_db), \
             patch.object(
                 mobile_axon,
                 "build_mobile_axon_audio_payload",
                 AsyncMock(return_value={"provider": "local", "voice_identity": "piper", "media_type": "audio/wav", "audio_base64": "YWJj"}),
             ) as speak_call:
            payload = await mobile_axon.mobile_axon_speak(request, body)

        kwargs = speak_call.await_args.kwargs
        self.assertEqual(kwargs["preferred_provider"], "local")
        self.assertEqual(kwargs["voice_identity"], "piper")
        self.assertEqual(payload["provider"], "local")


if __name__ == "__main__":
    unittest.main()
