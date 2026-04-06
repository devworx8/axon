from __future__ import annotations

import unittest
from contextlib import asynccontextmanager

from axon_api.routes.settings_memory import SettingsMemoryRouteHandlers
from axon_api.settings_models import SettingsUpdate


class _FakeDbModule:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self.settings = dict(settings or {})
        self.saved: list[tuple[str, str]] = []

    @asynccontextmanager
    async def get_db(self):
        yield object()

    async def get_all_settings(self, _conn):
        return dict(self.settings)

    async def set_setting(self, _conn, key: str, value: str):
        self.settings[key] = value
        self.saved.append((key, value))


class _FakeProviderRegistry:
    PROVIDERS: list[object] = []

    @staticmethod
    def selected_api_provider_id(settings: dict[str, str]) -> str:
        return settings.get("api_provider") or "deepseek"

    @staticmethod
    def mask_secret(value: str) -> str:
        raw = str(value or "").strip()
        if len(raw) <= 10:
            return "set" if raw else ""
        return f"{raw[:4]}...{raw[-4:]}"


class SettingsMemoryRouteTests(unittest.IsolatedAsyncioTestCase):
    def _handlers(self, db_module: _FakeDbModule) -> SettingsMemoryRouteHandlers:
        return SettingsMemoryRouteHandlers(
            db_module=db_module,
            memory_engine_module=object(),
            provider_registry_module=_FakeProviderRegistry(),
            devvault_module=object(),
            normalized_autonomy_profile=lambda value, **_kwargs: str(value or "workspace_auto"),
            normalized_runtime_permissions_mode=lambda value, **_kwargs: str(value or "default"),
            normalized_external_fetch_policy=lambda value: str(value or "cache_first"),
            normalized_max_history_turns=lambda settings: str(settings.get("max_history_turns") or "10"),
            selected_cli_path=lambda settings: str(settings.get("cli_runtime_path") or ""),
            selected_cli_model=lambda settings: str(settings.get("cli_runtime_model") or ""),
            stored_ollama_runtime_mode=lambda settings: str(settings.get("ollama_runtime_mode") or "gpu_default"),
            apply_cli_runtime_settings=lambda data, current: None,
            setting_int=lambda data, key, default, **_kwargs: int(data.get(key) or default),
            ensure_memory_layers_synced=self._ensure_memory_layers_synced,
            serialize_memory_item=lambda row: dict(row),
        )

    @staticmethod
    async def _ensure_memory_layers_synced(_conn, _settings, force: bool = False):
        return {"force": force}

    async def test_get_settings_masks_vercel_token(self):
        handlers = self._handlers(_FakeDbModule({"vercel_api_token": "vercel_secret_token"}))

        payload = await handlers.get_settings()

        self.assertTrue(payload["vercel_api_token_set"])
        self.assertEqual(payload["vercel_api_token"], "verc...oken")

    async def test_update_settings_persists_vercel_token(self):
        db_module = _FakeDbModule()
        handlers = self._handlers(db_module)

        payload = await handlers.update_settings(SettingsUpdate(vercel_api_token="vercel_secret_token"))

        self.assertEqual(db_module.settings["vercel_api_token"], "vercel_secret_token")
        self.assertEqual(payload["updated"], ["vercel_api_token"])

    async def test_update_settings_persists_voice_runtime_fields(self):
        db_module = _FakeDbModule()
        handlers = self._handlers(db_module)

        payload = await handlers.update_settings(
            SettingsUpdate(
                voice_speech_rate="0.91",
                voice_speech_pitch="1.08",
                voice_attention_enabled=True,
                voice_attention_autowake=False,
                local_stt_model="small",
                local_stt_language="en",
                local_tts_model_path="/tmp/piper.onnx",
                local_tts_config_path="/tmp/piper.onnx.json",
            )
        )

        self.assertEqual(db_module.settings["voice_speech_rate"], "0.91")
        self.assertEqual(db_module.settings["voice_speech_pitch"], "1.08")
        self.assertEqual(db_module.settings["voice_attention_enabled"], "1")
        self.assertEqual(db_module.settings["voice_attention_autowake"], "0")
        self.assertEqual(db_module.settings["local_stt_model"], "small")
        self.assertEqual(db_module.settings["local_stt_language"], "en")
        self.assertEqual(db_module.settings["local_tts_model_path"], "/tmp/piper.onnx")
        self.assertEqual(db_module.settings["local_tts_config_path"], "/tmp/piper.onnx.json")
        self.assertIn("voice_speech_rate", payload["updated"])


if __name__ == "__main__":
    unittest.main()
