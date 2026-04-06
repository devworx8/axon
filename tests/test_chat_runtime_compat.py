from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import server
from axon_api.routes.chat_routes import ChatMessage, ChatRouteHandlers
from axon_api.services import companion_runtime, companion_voice_runtime
from axon_core import auto_fix


class _DummyDb:
    @asynccontextmanager
    async def get_db(self):
        yield object()


class ServerChatStreamCompatTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_server_route_uses_extracted_handler(self):
        route = next(
            route for route in server.app.routes
            if getattr(route, "path", "") == "/api/chat/stream" and "POST" in getattr(route, "methods", set())
        )
        body = server.ChatMessage(message="Hello", project_id=2)
        request = object()
        expected = object()

        with patch.object(server._chat_route_handlers, "chat_stream", AsyncMock(return_value=expected)) as chat_stream:
            result = await route.endpoint(body, request)

        self.assertIs(result, expected)
        chat_stream.assert_awaited_once_with(body, request)


class ChatRouteHandlerCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonstreaming_chat_omits_workspace_path_kwarg(self):
        brain_module = SimpleNamespace(chat=AsyncMock(return_value={"content": "Reply ready.", "tokens": 5}))
        handler = ChatRouteHandlers(
            db_module=_DummyDb(),
            brain_module=brain_module,
            devvault_module=SimpleNamespace(
                VaultSession=SimpleNamespace(is_unlocked=lambda: False),
                vault_resolve_provider_key=AsyncMock(return_value=""),
            ),
            provider_registry_module=object(),
            load_chat_history_rows=AsyncMock(return_value=[]),
            serialize_chat_history_row=lambda row: row,
            composer_options_dict=lambda value: value or {},
            thread_mode_from_composer_options=lambda _opts: "ask",
            maybe_handle_chat_console_command=AsyncMock(return_value=None),
            effective_ai_params=AsyncMock(return_value={"backend": "cli"}),
            workspace_snapshot_bundle=AsyncMock(return_value={}),
            chat_history_bundle=AsyncMock(return_value={"history": []}),
            resource_bundle=AsyncMock(
                return_value={
                    "resources": [],
                    "context_block": "",
                    "image_paths": [],
                    "vision_model": "",
                    "warnings": [],
                }
            ),
            auto_route_vision_runtime=AsyncMock(return_value=({"backend": "cli"}, [])),
            auto_route_image_generation_runtime=AsyncMock(return_value=({"backend": "cli"}, [])),
            memory_bundle=AsyncMock(return_value={}),
            composer_instruction_block=lambda _settings: "",
            maybe_local_fast_chat_response=AsyncMock(return_value=None),
            persist_chat_reply=AsyncMock(return_value=None),
            set_live_operator=lambda **_kwargs: None,
            model_call_kwargs=lambda ai: ai,
            setting_int=lambda _settings, _key, default, **_kwargs: default,
            stored_chat_message=lambda content, **_kwargs: content,
        )
        handler._build_request_context = AsyncMock(
            return_value={
                "settings": {},
                "snapshot_bundle": {},
                "memory_bundle": {},
                "merged_context_block": "workspace context",
                "history": [{"role": "user", "content": "Hello"}],
                "project_name": "Axon",
                "workspace_path": "/tmp/axon",
                "resource_bundle": {
                    "resources": [],
                    "context_block": "",
                    "image_paths": [],
                    "vision_model": "",
                    "warnings": [],
                },
                "chat_thread_mode": "ask",
                "ai": {"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.4"},
            }
        )
        handler._special_intents.maybe_handle_nonstreaming = AsyncMock(return_value=None)

        result = await handler.chat(ChatMessage(message="Hello", project_id=2))

        self.assertEqual(result["response"], "Reply ready.")
        self.assertNotIn("workspace_path", brain_module.chat.await_args.kwargs)


class CompanionRuntimeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_turn_direct_chat_omits_workspace_path_kwarg(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain"}
        user_turn = {"id": 100, "role": "user", "content": "Say hello from companion."}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Voice reply ready."}
        refreshed_session = dict(session) | {"summary": "Voice reply ready."}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 1, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])), \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "_requires_local_operator_execution", return_value=False), \
             patch.object(companion_runtime.companion_agent_bridge, "needs_local_operator_upgrade", return_value=False), \
             patch.object(companion_voice_runtime, "companion_voice_timeout_seconds", return_value=8.0), \
             patch.object(companion_voice_runtime.brain, "chat", AsyncMock(return_value={"content": "Voice reply ready.", "tokens": 42})) as chat_mock:
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="Say hello from companion.",
                transcript="Say hello from companion.",
            )

        self.assertEqual(result["response_text"], "Voice reply ready.")
        self.assertNotIn("workspace_path", chat_mock.await_args.kwargs)

    def test_companion_voice_runtime_prefers_quick_codex_model(self):
        kwargs = companion_voice_runtime.companion_voice_model_kwargs(
            {
                "ai_backend": "cli",
                "cli_runtime_path": "/tmp/codex",
                "cli_runtime_model": "gpt-5.4",
            }
        )

        self.assertEqual(kwargs["backend"], "cli")
        self.assertEqual(kwargs["cli_model"], "gpt-5.1-codex-mini")

    async def test_companion_voice_runtime_prefers_api_quick_model_when_vault_key_is_live(self):
        settings = {
            "ai_backend": "cli",
            "api_provider": "deepseek",
            "cli_runtime_path": "/tmp/codex",
            "cli_runtime_model": "gpt-5.4",
            "companion_voice_runtime_mode": "auto_fastest",
        }

        with patch.object(companion_voice_runtime.vault.VaultSession, "is_unlocked", return_value=True), \
             patch.object(
                 companion_voice_runtime.vault,
                 "vault_resolve_provider_key",
                 AsyncMock(side_effect=lambda _db, provider_id: "anthropic-key" if provider_id == "anthropic" else ""),
             ):
            kwargs = await companion_voice_runtime.resolve_companion_voice_model_kwargs(object(), settings)

        self.assertEqual(kwargs["backend"], "api")
        self.assertEqual(kwargs["api_provider"], "anthropic")
        self.assertEqual(kwargs["api_model"], "claude-haiku-4-5")

    async def test_companion_voice_runtime_default_stays_on_cli_even_with_vault_key(self):
        settings = {
            "ai_backend": "cli",
            "api_provider": "anthropic",
            "cli_runtime_path": "/tmp/codex",
            "cli_runtime_model": "gpt-5.4",
        }

        with patch.object(companion_voice_runtime.vault.VaultSession, "is_unlocked", return_value=True), \
             patch.object(
                 companion_voice_runtime.vault,
                 "vault_resolve_provider_key",
                 AsyncMock(return_value="anthropic-key"),
             ):
            kwargs = await companion_voice_runtime.resolve_companion_voice_model_kwargs(object(), settings)

        self.assertEqual(kwargs["backend"], "cli")
        self.assertEqual(kwargs["cli_model"], "gpt-5.1-codex-mini")


class AutoFixCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_chat_fix_omits_workspace_path_kwarg(self):
        with patch.object(auto_fix, "_resolve_runtime_kwargs", AsyncMock(return_value={"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.4"})), \
             patch("brain.chat", AsyncMock(return_value={"content": "Fixed it.", "tokens": 3})) as chat_mock:
            result = await auto_fix._run_chat_fix("Fix the error", {"project_name": "Axon"})

        self.assertTrue(result["success"])
        self.assertNotIn("workspace_path", chat_mock.await_args.kwargs)
