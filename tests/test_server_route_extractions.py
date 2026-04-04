from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import server


class PromptTaskRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_create_prompt_compat_alias_uses_server_devdb(self):
        row = {
            "id": 12,
            "project_id": 3,
            "title": "Launch checklist",
            "content": "Ship it",
            "tags": "release",
            "meta_json": '{"kind":"ops"}',
        }

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "save_prompt", AsyncMock(return_value=12)) as save_prompt, \
             patch.object(server.devdb, "log_event", AsyncMock(return_value=None)) as log_event, \
             patch.object(server.devdb, "get_prompt", AsyncMock(return_value=row)):
            payload = await server.create_prompt(
                server.PromptCreate(
                    project_id=3,
                    title="Launch checklist",
                    content="Ship it",
                    tags="release",
                    meta={"kind": "ops"},
                )
            )

        save_prompt.assert_awaited_once()
        self.assertEqual(save_prompt.await_args.kwargs["meta_json"], '{"kind": "ops"}')
        log_event.assert_awaited_once()
        self.assertEqual(payload["meta"], {"kind": "ops"})
        self.assertEqual(payload["title"], "Launch checklist")

    async def test_update_task_status_only_uses_status_helper(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "update_task_status", AsyncMock(return_value=None)) as update_task_status, \
             patch.object(server.devdb, "update_task", AsyncMock(return_value=None)) as update_task:
            payload = await server.update_task(
                44,
                server.TaskUpdate(status="done"),
            )

        update_task_status.assert_awaited_once_with(unittest.mock.ANY, 44, "done")
        update_task.assert_not_called()
        self.assertEqual(payload, {"updated": True})


class UserRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_user_alias_rejects_empty_patch(self):
        with self.assertRaises(server.HTTPException) as ctx:
            await server.update_user(7, {})

        self.assertEqual(ctx.exception.status_code, 400)


class TaskSandboxRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_task_sandbox_run_uses_server_background_alias(self):
        fake_background = AsyncMock()
        with patch.object(server, "_run_task_sandbox_background", fake_background), \
             patch.object(
                 server._task_sandbox_handlers,
                 "queue_task_sandbox_run",
                 AsyncMock(return_value={"started": True, "resume": True}),
             ) as queue_task_sandbox_run:
            payload = await server._queue_task_sandbox_run(
                17,
                resume=True,
                runtime_override={"backend": "cli"},
            )

        self.assertTrue(payload["started"])
        self.assertTrue(payload["resume"])
        queue_task_sandbox_run.assert_awaited_once()
        self.assertEqual(queue_task_sandbox_run.await_args.args[0], 17)
        self.assertEqual(queue_task_sandbox_run.await_args.kwargs["resume"], True)
        self.assertEqual(queue_task_sandbox_run.await_args.kwargs["runtime_override"], {"backend": "cli"})
        self.assertIs(queue_task_sandbox_run.await_args.kwargs["run_task_sandbox_background"], fake_background)


class ChatRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_get_chat_history_alias_uses_server_loader(self):
        row = {
            "role": "assistant",
            "content": server._stored_chat_message("Reply ready", mode="chat", thread_mode="ask"),
            "created_at": "2026-04-04T00:00:00Z",
            "tokens_used": 3,
        }

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server, "_load_chat_history_rows", AsyncMock(return_value=[row])) as load_rows:
            payload = await server.get_chat_history(project_id=4, limit=5)

        load_rows.assert_awaited_once_with(unittest.mock.ANY, project_id=4, limit=5)
        self.assertEqual(payload[0]["content"], "Reply ready")
        self.assertEqual(payload[0]["thread_mode"], "ask")
        self.assertEqual(payload[0]["tokens_used"], 3)


class AuthRuntimeExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_session_async_uses_server_valid_session_wrapper(self):
        with patch.object(server, "_valid_session", return_value=True) as valid_session, \
             patch.object(
                 server.companion_auth_service,
                 "resolve_companion_auth_session",
                 AsyncMock(return_value=None),
             ) as resolve_companion_auth_session:
            result = await server._valid_session_async("session-123")

        self.assertTrue(result)
        valid_session.assert_called_once_with("session-123")
        resolve_companion_auth_session.assert_not_called()


class TerminalRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_terminal_execute_request_uses_server_start_wrapper(self):
        session_row = {
            "id": 9,
            "status": "idle",
            "mode": "approval_required",
            "workspace_id": 0,
            "cwd": str(Path.home() / ".devbrain"),
        }

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", AsyncMock(return_value={"terminal_default_mode": "approval_required"})), \
             patch.object(server.devdb, "get_terminal_session", AsyncMock(return_value=session_row)), \
             patch.object(server.devdb, "update_terminal_session", AsyncMock(return_value=None)) as update_terminal_session, \
             patch.object(server, "_resolve_terminal_cwd", AsyncMock(return_value=Path.home() / ".devbrain")) as resolve_terminal_cwd, \
             patch.object(server, "_terminal_timeout_seconds", return_value=42) as terminal_timeout_seconds, \
             patch.object(server, "_start_terminal_command", AsyncMock(return_value={"status": "running", "timeout_seconds": 42})) as start_terminal_command:
            payload = await server._terminal_execute_request(
                9,
                server.TerminalCommandBody(command="pwd"),
                approved=True,
            )

        resolve_terminal_cwd.assert_awaited_once()
        terminal_timeout_seconds.assert_called_once()
        update_terminal_session.assert_awaited_once_with(
            unittest.mock.ANY,
            9,
            mode="approval_required",
            cwd=str(Path.home() / ".devbrain"),
            status="idle",
        )
        start_terminal_command.assert_awaited_once_with(
            session_id=9,
            command="pwd",
            cwd=Path.home() / ".devbrain",
            timeout_seconds=42,
        )
        self.assertEqual(payload["status"], "running")


class WorkspaceSandboxExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_preview_target_uses_service_with_server_dependencies(self):
        expected = (
            {"id": 22, "path": "/src/dashpro"},
            {"session_id": "auto-22", "sandbox_path": "/tmp/axon-auto-22"},
            "/tmp/axon-auto-22",
        )

        with patch.object(
            server.workspace_sandbox_service,
            "workspace_preview_target",
            AsyncMock(return_value=expected),
        ) as workspace_preview_target:
            result = await server._workspace_preview_target(22, "auto-22")

        workspace_preview_target.assert_awaited_once()
        self.assertEqual(workspace_preview_target.await_args.args, (22, "auto-22"))
        self.assertIs(workspace_preview_target.await_args.kwargs["db_module"], server.devdb)
        self.assertIs(workspace_preview_target.await_args.kwargs["auto_session_service"], server.auto_session_service)
        self.assertIs(workspace_preview_target.await_args.kwargs["http_exception_cls"], server.HTTPException)
        self.assertEqual(result, expected)


class AutoSessionRuntimeExtractionTests(unittest.IsolatedAsyncioTestCase):
    def test_auto_runtime_summary_uses_service_with_server_dependencies(self):
        expected = {"backend": "cli", "label": "Codex CLI", "model": "gpt-5.4"}

        with patch.object(
            server.auto_session_runtime_service,
            "auto_runtime_summary",
            return_value=expected,
        ) as auto_runtime_summary:
            result = server._auto_runtime_summary({"backend": "cli", "cli_model": "gpt-5.4"})

        auto_runtime_summary.assert_called_once()
        self.assertEqual(auto_runtime_summary.call_args.args[0], {"backend": "cli", "cli_model": "gpt-5.4"})
        self.assertIs(auto_runtime_summary.call_args.kwargs["provider_registry_module"], server.provider_registry)
        self.assertIs(auto_runtime_summary.call_args.kwargs["path_cls"], Path)
        self.assertEqual(result, expected)


class RuntimeTruthExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_truth_for_settings_uses_service_with_server_dependencies(self):
        expected = ({"effective_runtime": "codex_cli"}, {"cli_runtime": {"runtime_id": "codex"}})

        with patch.object(
            server.runtime_truth_service,
            "runtime_truth_for_settings",
            AsyncMock(return_value=expected),
        ) as runtime_truth_for_settings:
            result = await server._runtime_truth_for_settings({"ai_backend": "cli"}, backend_override="api")

        runtime_truth_for_settings.assert_awaited_once()
        self.assertEqual(runtime_truth_for_settings.await_args.args[0], {"ai_backend": "cli"})
        self.assertEqual(runtime_truth_for_settings.await_args.kwargs["backend_override"], "api")
        self.assertEqual(result, expected)


class ChatHistoryExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_chat_history_rows_uses_service_with_server_dependencies(self):
        expected = [{"role": "assistant", "content": "ready"}]
        conn = object()

        with patch.object(
            server.chat_history_runtime_service,
            "load_chat_history_rows",
            AsyncMock(return_value=expected),
        ) as load_chat_history_rows:
            result = await server._load_chat_history_rows(conn, project_id=7, limit=11, degrade_to_empty=True)

        load_chat_history_rows.assert_awaited_once()
        self.assertIs(load_chat_history_rows.await_args.args[0], conn)
        self.assertIs(load_chat_history_rows.await_args.kwargs["db_module"], server.devdb)
        self.assertEqual(load_chat_history_rows.await_args.kwargs["project_id"], 7)
        self.assertEqual(load_chat_history_rows.await_args.kwargs["limit"], 11)
        self.assertEqual(load_chat_history_rows.await_args.kwargs["degrade_to_empty"], True)
        self.assertIs(load_chat_history_rows.await_args.kwargs["http_exception_cls"], server.HTTPException)
        self.assertEqual(result, expected)


class SettingsConnectionExtractionTests(unittest.IsolatedAsyncioTestCase):
    def test_read_settings_sync_uses_service_with_server_dependencies(self):
        expected = {"ai_backend": "cli"}

        with patch.object(
            server.settings_runtime_state_service,
            "read_settings_sync",
            return_value=expected,
        ) as read_settings_sync:
            result = server._read_settings_sync()

        read_settings_sync.assert_called_once_with(
            server.devdb.DB_PATH,
            managed_connection_fn=server.managed_connection,
            sqlite_row_factory=server._sqlite3.Row,
        )
        self.assertEqual(result, expected)

    def test_connection_config_uses_service_with_server_dependencies(self):
        expected = {"stable_domain": "example.com", "named_tunnel_ready": True}

        with patch.object(
            server.connection_config_state_service,
            "connection_config",
            return_value=expected,
        ) as connection_config:
            result = server._connection_config({"stable_domain": "example.com"})

        connection_config.assert_called_once_with(
            {"stable_domain": "example.com"},
            read_settings_sync_fn=server._read_settings_sync,
            setting_truthy_fn=server._setting_truthy,
        )
        self.assertEqual(result, expected)


class ResourceRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_resource_bytes_uses_service_with_server_dependencies(self):
        expected = {"id": 4, "title": "Run log"}
        conn = object()

        with patch.object(
            server.resource_route_state_service,
            "ingest_resource_bytes",
            AsyncMock(return_value=expected),
        ) as ingest_resource_bytes:
            result = await server._ingest_resource_bytes(
                conn,
                title="Run log",
                filename="run.log",
                content=b"ok",
                mime_type="text/plain",
                source_type="upload",
                source_url="",
                settings={},
            )

        ingest_resource_bytes.assert_awaited_once()
        self.assertIs(ingest_resource_bytes.await_args.args[0], conn)
        self.assertIs(ingest_resource_bytes.await_args.kwargs["db_module"], server.devdb)
        self.assertIs(ingest_resource_bytes.await_args.kwargs["resource_bank_module"], server.resource_bank)
        self.assertIs(ingest_resource_bytes.await_args.kwargs["http_exception_cls"], server.HTTPException)
        self.assertEqual(result, expected)


class RuntimeFacadeExtractionTests(unittest.TestCase):
    def test_ops_runtime_helpers_are_bound_to_ops_facade(self):
        self.assertIs(server._set_live_operator.__self__, server._ops_runtime_facade)
        self.assertIs(server._attach_preview_browser.__self__, server._ops_runtime_facade)
        self.assertIs(server._connection_snapshot.__self__, server._ops_runtime_facade)

    def test_chat_runtime_helpers_are_bound_to_chat_facade(self):
        self.assertIs(server._effective_ai_params.__self__, server._chat_runtime_facade)
        self.assertIs(server._maybe_handle_chat_console_command.__self__, server._chat_runtime_facade)
        self.assertIs(server._stored_chat_message.__self__, server._chat_runtime_facade)
        self.assertIs(server._resource_bundle.__self__, server._chat_runtime_facade)


class LocalVoiceExtractionTests(unittest.IsolatedAsyncioTestCase):
    def test_resolve_ffmpeg_path_uses_service_with_server_dependencies(self):
        with patch.object(
            server.local_voice_dependencies_service,
            "resolve_ffmpeg_path",
            return_value="/tmp/ffmpeg",
        ) as resolve_ffmpeg_path:
            result = server._resolve_ffmpeg_path()

        resolve_ffmpeg_path.assert_called_once_with(
            shutil_module=shutil,
            python_module_available_fn=server._python_module_available,
            pathlib_path_cls=Path,
        )
        self.assertEqual(result, "/tmp/ffmpeg")

    def test_speak_local_text_uses_service_with_server_dependencies(self):
        expected = (b"wav", "piper")

        with patch.object(
            server.local_voice_execution_service,
            "speak_local_text",
            return_value=expected,
        ) as speak_local_text:
            result = server._speak_local_text("hello", model_path="/tmp/model.onnx", config_path="/tmp/model.json")

        speak_local_text.assert_called_once_with(
            "hello",
            model_path="/tmp/model.onnx",
            config_path="/tmp/model.json",
            shutil_module=shutil,
            pathlib_path_cls=Path,
            tempfile_module=tempfile,
            subprocess_module=subprocess,
            piper_python_available_fn=server._piper_python_available,
            piper_voice_cache=server._piper_voice_cache,
            io_module=io,
            wave_module=wave,
            http_exception_cls=server.HTTPException,
        )
        self.assertEqual(result, expected)

    def test_python_module_available_uses_service_with_server_dependencies(self):
        with patch.object(
            server.local_voice_dependencies_service,
            "python_module_available",
            return_value=True,
        ) as python_module_available:
            result = server._python_module_available("whisper")

        python_module_available.assert_called_once_with(
            "whisper",
            importlib_util_module=importlib.util,
        )
        self.assertTrue(result)


class AuthRouteExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_setup_rejects_short_pin(self):
        with self.assertRaises(server.HTTPException) as ctx:
            await server.auth_setup(server.PinSetup(pin="12"))

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
