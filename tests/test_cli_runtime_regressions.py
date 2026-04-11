from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import brain
import browser_bridge
import memory_engine
import server
import runtime_manager
import provider_registry
from axon_data import core as db_core
from axon_data import runtime_state
from axon_core import agent as core_agent
from axon_core import approval_actions
from axon_core import agent_file_actions
from axon_core import agent_fast_path
from axon_core import agent_prompts
from axon_core import cli_pacing
from axon_core import session_store as session_store_module
from axon_core.agent_toolspecs import AgentRuntimeDeps
from axon_core.session_store import SessionStore
from axon_api.settings_models import SettingsUpdate
from axon_api.services import claude_cli_runtime
from axon_api.services import codex_cli_runtime
from axon_api.services import auto_sessions as auto_session_service
from axon_api.services import composer_runtime
from axon_api.services import live_preview_sessions
from axon_api.services import runtime_login_sessions
from axon_api.services import runtime_truth as runtime_truth_service
from axon_api.services import sandbox_sessions
from axon_api.services import task_sandboxes as task_sandbox_service
from axon_core.chat_context import select_history_for_chat
from axon_core import agent_output
from axon_core import agent_runtime_state
from axon_core.vision_runtime import auto_route_vision_runtime


def _writable_tempdir():
    return tempfile.TemporaryDirectory(dir=tempfile.gettempdir())


class SettingsPayloadTests(unittest.TestCase):
    def test_settings_update_accepts_generic_cli_model(self):
        payload = SettingsUpdate(cli_runtime_model="gpt-5.4", ai_backend="cli")

        self.assertEqual(payload.cli_runtime_model, "gpt-5.4")
        self.assertEqual(payload.ai_backend, "cli")

    def test_settings_update_accepts_cli_model(self):
        payload = SettingsUpdate(claude_cli_model="sonnet", ai_backend="cli")

        self.assertEqual(payload.claude_cli_model, "sonnet")
        self.assertEqual(payload.ai_backend, "cli")

    def test_settings_update_accepts_cli_session_persistence_toggle(self):
        payload = SettingsUpdate(claude_cli_session_persistence_enabled=True, ai_backend="cli")

        self.assertTrue(payload.claude_cli_session_persistence_enabled)
        self.assertEqual(payload.ai_backend, "cli")

    @patch.object(brain, "_find_codex_cli", return_value="/tmp/codex")
    @patch.object(brain, "normalize_cli_model", return_value="gpt-5.4")
    def test_selected_cli_path_prefers_codex_binary_for_codex_model_without_override(
        self,
        _normalize_cli_model,
        _find_codex_cli,
    ):
        path = composer_runtime.selected_cli_path({"cli_runtime_model": "gpt-5.4"})

        self.assertEqual(path, "/tmp/codex")

    def test_normalized_autonomy_profile_rejects_future_modes(self):
        with self.assertRaises(server.HTTPException) as exc:
            server._normalized_autonomy_profile("pr_auto", reject_elevated=True)

        self.assertEqual(exc.exception.status_code, 400)

    def test_normalized_external_fetch_policy_coalesces_memory_first_to_cache_first(self):
        self.assertEqual(server._normalized_external_fetch_policy("memory_first"), "cache_first")
        self.assertEqual(server._normalized_external_fetch_policy("cache_first"), "cache_first")

    def test_settings_update_accepts_runtime_permissions_mode(self):
        payload = SettingsUpdate(runtime_permissions_mode="full_access", ai_backend="cli")

        self.assertEqual(payload.runtime_permissions_mode, "full_access")
        self.assertEqual(payload.ai_backend, "cli")

    def test_settings_update_accepts_sentry_connector_fields(self):
        payload = SettingsUpdate(
            sentry_api_token="sntrys_test_token",
            sentry_org_slug="axon",
            sentry_project_slugs="web,api",
        )

        self.assertEqual(payload.sentry_api_token, "sntrys_test_token")
        self.assertEqual(payload.sentry_org_slug, "axon")
        self.assertEqual(payload.sentry_project_slugs, "web,api")

    def test_normalized_runtime_permissions_mode_accepts_full_access(self):
        self.assertEqual(server._normalized_runtime_permissions_mode("full_access"), "full_access")
        self.assertEqual(server._normalized_runtime_permissions_mode("unknown", fallback="ask_first"), "ask_first")

    def test_effective_agent_runtime_permissions_mode_allows_codex_full_access_override(self):
        mode = server._effective_agent_runtime_permissions_mode(
            {"runtime_permissions_mode": "default", "autonomy_profile": "workspace_auto"},
            override="full_access",
            backend="cli",
            cli_path="/tmp/codex",
            autonomy_profile="workspace_auto",
        )

        self.assertEqual(mode, "full_access")

    def test_effective_agent_runtime_permissions_mode_ignores_full_access_override_for_claude(self):
        mode = server._effective_agent_runtime_permissions_mode(
            {"runtime_permissions_mode": "default", "autonomy_profile": "workspace_auto"},
            override="full_access",
            backend="cli",
            cli_path="/tmp/claude",
            autonomy_profile="workspace_auto",
        )

        self.assertEqual(mode, "default")

    def test_effective_agent_runtime_permissions_mode_promotes_isolated_codex_worktree(self):
        mode = server._effective_agent_runtime_permissions_mode(
            {"runtime_permissions_mode": "default", "autonomy_profile": "workspace_auto"},
            backend="cli",
            cli_path="/tmp/codex",
            autonomy_profile="workspace_auto",
            isolated_workspace=True,
        )

        self.assertEqual(mode, "full_access")

    def test_effective_agent_runtime_permissions_mode_keeps_explicit_ask_first_in_isolated_worktree(self):
        mode = server._effective_agent_runtime_permissions_mode(
            {"runtime_permissions_mode": "ask_first", "autonomy_profile": "workspace_auto"},
            backend="cli",
            cli_path="/tmp/codex",
            autonomy_profile="workspace_auto",
            isolated_workspace=True,
        )

        self.assertEqual(mode, "ask_first")


class AgentRuntimeStateTests(unittest.TestCase):
    def tearDown(self):
        agent_runtime_state.drain_steer_messages()
        agent_runtime_state.drain_steer_messages(workspace_id=7)
        agent_runtime_state.drain_steer_messages(workspace_id=11)
        agent_runtime_state.drain_steer_messages(workspace_id=12)

    def test_active_workspace_root_is_context_scoped(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(brain, "_HOME", os.path.realpath(tmp_dir)):
            token = agent_runtime_state.set_active_workspace_path(tmp_dir)
            try:
                self.assertEqual(brain._workspace_root(), os.path.realpath(tmp_dir))
                self.assertEqual(brain._active_workspace_root(), os.path.realpath(tmp_dir))
            finally:
                agent_runtime_state.reset_active_workspace_path(token)

        self.assertEqual(brain._active_workspace_root(), "")

    def test_steer_messages_are_isolated_by_workspace(self):
        agent_runtime_state.enqueue_steer_message("workspace 11", workspace_id=11)
        agent_runtime_state.enqueue_steer_message("workspace 12", workspace_id=12)

        self.assertEqual(agent_runtime_state.drain_steer_messages(workspace_id=11), ["workspace 11"])
        self.assertEqual(agent_runtime_state.drain_steer_messages(workspace_id=12), ["workspace 12"])
        self.assertEqual(agent_runtime_state.drain_steer_messages(workspace_id=11), [])


class AgentRuntimeStateEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_steer_endpoint_queues_message_for_workspace(self):
        payload = await server.steer_agent({"message": "keep going", "project_id": 7})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["workspace_id"], 7)
        self.assertEqual(agent_runtime_state.drain_steer_messages(workspace_id=7), ["keep going"])

    def test_effective_agent_runtime_permissions_mode_ignores_full_access_override_for_api(self):
        mode = server._effective_agent_runtime_permissions_mode(
            {"runtime_permissions_mode": "default", "autonomy_profile": "workspace_auto"},
            override="full_access",
            backend="api",
            cli_path="/tmp/codex",
            autonomy_profile="workspace_auto",
        )

        self.assertEqual(mode, "default")


class SettingsCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_settings_hides_legacy_extra_allowed_cmds(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_get_all_settings(_conn):
            return {
                "extra_allowed_cmds": "curl,rm",
                "external_fetch_policy": "memory_first",
                "max_history_turns": "12",
            }

        with patch.object(server.devdb, "get_db", fake_db), \
             patch.object(server.devdb, "get_all_settings", side_effect=fake_get_all_settings):
            payload = await server.get_settings()

        self.assertNotIn("extra_allowed_cmds", payload)
        self.assertEqual(payload["external_fetch_policy"], "cache_first")
        self.assertEqual(payload["max_history_turns"], "10")
        self.assertEqual(payload["runtime_permissions_mode"], "default")

    async def test_init_db_migrates_legacy_hardening_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "devbrain.db"
            with patch.object(db_core, "DB_PATH", db_path):
                await db_core.init_db()

                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                        ("extra_allowed_cmds", "curl,rm"),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                        ("external_fetch_policy", "memory_first"),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                        ("max_history_turns", "12"),
                    )

                await db_core.init_db()

                with sqlite3.connect(db_path) as conn:
                    rows = dict(conn.execute("SELECT key, value FROM settings"))

        self.assertNotIn("extra_allowed_cmds", rows)
        self.assertEqual(rows["external_fetch_policy"], "cache_first")
        self.assertEqual(rows["max_history_turns"], "10")
        self.assertEqual(rows["autonomy_profile"], "workspace_auto")
        self.assertEqual(rows["runtime_permissions_mode"], "default")

    async def test_get_db_supports_basic_query_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "devbrain.db"
            with patch.object(db_core, "DB_PATH", db_path):
                await db_core.init_db()
                async with db_core.get_db() as conn:
                    cur = await conn.execute(
                        "SELECT value FROM settings WHERE key = ?",
                        ("runtime_permissions_mode",),
                    )
                    row = await cur.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "default")


class ChatTokenAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_chat_returns_streamed_token_count(self):
        async def fake_stream_cli(messages, **kwargs):
            kwargs["usage_sink"]["tokens"] = 321
            yield "OK"

        with patch.object(brain, "_stream_cli", side_effect=fake_stream_cli):
            result = await brain.chat(
                "Reply with the single word OK.",
                [],
                backend="cli",
                cli_path="/tmp/codex",
                cli_model="gpt-5.4",
            )

        self.assertEqual(result["content"], "OK")
        self.assertEqual(result["tokens"], 321)


class ProviderRegistryTests(unittest.TestCase):
    def test_deepseek_platform_url_normalizes_to_api_base(self):
        settings = {
            "api_provider": "deepseek",
            "deepseek_base_url": "https://platform.deepseek.com/",
            "deepseek_api_model": "deepseek-reasoner",
        }

        cfg = provider_registry.runtime_api_config(settings)

        self.assertEqual(cfg["api_base_url"], "https://api.deepseek.com/v1")

    def test_public_runtime_api_config_redacts_api_key(self):
        settings = {
            "api_provider": "anthropic",
            "anthropic_api_key": "anthropic-secret-token",
            "anthropic_base_url": "https://api.anthropic.com",
            "anthropic_api_model": "claude-sonnet-4-5",
        }

        cfg = provider_registry.public_runtime_api_config(settings)

        self.assertNotIn("api_key", cfg)
        self.assertTrue(cfg["api_key_configured"])
        self.assertEqual(cfg["key_hint"], "anth...oken")
        self.assertEqual(cfg["api_base_url"], "https://api.anthropic.com/v1")


class AnthropicClientConfigTests(unittest.TestCase):
    def test_get_client_strips_v1_suffix_for_anthropic_sdk(self):
        captured = {}

        class DummyClient:
            pass

        def fake_anthropic(**kwargs):
            captured.update(kwargs)
            return DummyClient()

        with patch.object(brain.anthropic, "Anthropic", side_effect=fake_anthropic):
            client = brain._get_client("anthropic-key", api_base_url="https://api.anthropic.com/v1")

        self.assertIsInstance(client, DummyClient)
        self.assertEqual(captured["api_key"], "anthropic-key")
        self.assertEqual(captured["base_url"], "https://api.anthropic.com")


class ChatHistoryEnvelopeTests(unittest.TestCase):
    def test_stored_chat_message_round_trip_preserves_thread_metadata(self):
        payload = server._stored_chat_message(
            "Ship the fix",
            resources=[{"id": 52, "title": "Runtime audit", "kind": "note"}],
            mode="agent",
            thread_mode="auto",
            model_label="Codex CLI · gpt-5.4",
        )

        parsed = server._parse_stored_chat_message(payload)

        self.assertEqual(parsed["content"], "Ship the fix")
        self.assertEqual(parsed["mode"], "agent")
        self.assertEqual(parsed["thread_mode"], "auto")
        self.assertEqual(parsed["model_label"], "Codex CLI · gpt-5.4")
        self.assertEqual(parsed["resources"][0]["title"], "Runtime audit")
        self.assertEqual(parsed["resources"][0]["kind"], "note")

    def test_serialize_chat_history_row_exposes_structured_metadata(self):
        row = {
            "role": "assistant",
            "content": server._stored_chat_message(
                "Recovery finished",
                resources=[{"title": "Session log"}],
                mode="chat",
                thread_mode="recover",
                model_label="Claude Code",
            ),
            "created_at": "2026-04-02T08:55:00Z",
            "tokens_used": 11,
        }

        payload = server._serialize_chat_history_row(row)

        self.assertEqual(payload["content"], "Recovery finished")
        self.assertEqual(payload["mode"], "chat")
        self.assertEqual(payload["thread_mode"], "recover")
        self.assertEqual(payload["model_label"], "Claude Code")
        self.assertEqual(payload["resources"][0]["title"], "Session log")

    def test_parse_stored_chat_message_supports_legacy_plain_text_rows(self):
        parsed = server._parse_stored_chat_message("legacy assistant reply")

        self.assertEqual(parsed["content"], "legacy assistant reply")
        self.assertEqual(parsed["resources"], [])
        self.assertEqual(parsed["mode"], "")
        self.assertEqual(parsed["thread_mode"], "")

    def test_parse_stored_chat_message_supports_legacy_resource_suffix_rows(self):
        parsed = server._parse_stored_chat_message(
            "legacy reply\n\n[Attached resources: Spec doc, Screenshot]"
        )

        self.assertEqual(parsed["content"], "legacy reply")
        self.assertEqual([item["title"] for item in parsed["resources"]], ["Spec doc", "Screenshot"])
        self.assertEqual(parsed["mode"], "")
        self.assertEqual(parsed["thread_mode"], "")


class LivePreviewSessionServiceTests(unittest.TestCase):
    def test_infer_preview_launch_uses_workspace_specific_next_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"dev": "next dev"},
                        "dependencies": {"next": "16.2.1"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(live_preview_sessions, "_free_port", return_value=3456):
                launch = live_preview_sessions.infer_preview_launch(str(repo), workspace_id=11)

        self.assertEqual(launch["framework"], "next")
        self.assertEqual(launch["workspace_path"], str(Path(tmp).resolve()))
        self.assertEqual(
            launch["command_parts"],
            ["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3456"],
        )
        self.assertEqual(launch["url"], "http://127.0.0.1:3456")

    def test_infer_preview_launch_uses_expo_web_and_hybrid_source_node_modules_for_auto_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "dashpro"
            sandbox_repo = root / "auto-dashpro"
            (source_repo / "node_modules" / ".bin").mkdir(parents=True)
            (source_repo / "node_modules" / "expo-router" / "build").mkdir(parents=True)
            (sandbox_repo).mkdir()
            (source_repo / "node_modules" / ".bin" / "expo").write_text("#!/bin/sh\n", encoding="utf-8")
            (source_repo / "node_modules" / "expo-router" / "package.json").write_text(
                json.dumps({"name": "expo-router", "version": "6.0.23"}),
                encoding="utf-8",
            )
            (sandbox_repo / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"start": "npx expo start --dev-client --host localhost", "web": "expo start --web"},
                        "dependencies": {"expo": "~54.0.0", "react-native-web": "^0.21.0"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(live_preview_sessions, "_free_port", return_value=3564):
                launch = live_preview_sessions.infer_preview_launch(
                    str(sandbox_repo),
                    workspace_id=2,
                    auto_session_id="auto-2",
                    source_workspace_path=str(source_repo),
                )

            self.assertEqual(launch["framework"], "expo")
            self.assertEqual(launch["script"], "web")
            sandbox_expo = sandbox_repo / "node_modules" / ".bin" / "expo"
            self.assertTrue(sandbox_expo.exists())
            self.assertEqual(sandbox_expo.resolve(), (source_repo / "node_modules" / ".bin" / "expo").resolve())
            self.assertTrue((sandbox_repo / "node_modules" / ".bin").is_symlink())
            sandbox_expo_router = sandbox_repo / "node_modules" / "expo-router"
            self.assertTrue(sandbox_expo_router.exists())
            self.assertFalse(sandbox_expo_router.is_symlink())
            self.assertTrue((sandbox_expo_router / "package.json").is_file())
            self.assertEqual(
                launch["command_parts"],
                [str(sandbox_expo), "start", "--web", "--host", "localhost", "--port", "3564"],
            )
            self.assertFalse((sandbox_repo / "node_modules").is_symlink())
            self.assertEqual(launch["url"], "http://127.0.0.1:3564")

    def test_ensure_preview_session_restarts_stale_expo_symlinked_node_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "dashpro"
            sandbox_repo = root / "auto-dashpro"
            (source_repo / "node_modules").mkdir(parents=True)
            sandbox_repo.mkdir()
            (sandbox_repo / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"web": "expo start --web"},
                        "dependencies": {"expo": "~54.0.0", "react-native-web": "^0.21.0"},
                    }
                ),
                encoding="utf-8",
            )
            (sandbox_repo / "node_modules").symlink_to(source_repo / "node_modules", target_is_directory=True)
            existing = {
                "scope_key": "auto-auto-2",
                "workspace_id": 2,
                "workspace_name": "dashpro",
                "auto_session_id": "auto-2",
                "title": "dashpro",
                "cwd": str(sandbox_repo),
                "command": "expo start --web --host localhost --port 3564",
                "status": "running",
                "source_workspace_path": str(source_repo),
            }
            with patch.object(live_preview_sessions, "refresh_preview_session", return_value=existing), \
                 patch.object(live_preview_sessions, "_stop_process") as stop_process, \
                 patch.object(live_preview_sessions, "infer_preview_launch", return_value={
                     "workspace_path": str(sandbox_repo),
                     "command_parts": ["echo", "preview"],
                     "command_preview": "echo preview",
                     "package_manager": "expo",
                     "framework": "expo",
                     "script": "web",
                     "port": 3564,
                     "url": "http://127.0.0.1:3564",
                     "env": {},
                 }), \
                 patch.object(live_preview_sessions, "session_dir", return_value=root / "preview-session"), \
                 patch.object(live_preview_sessions, "write_preview_session", side_effect=lambda meta: meta), \
                 patch.object(live_preview_sessions, "_wait_until_ready", side_effect=lambda meta, timeout_seconds=18: meta), \
                 patch("subprocess.Popen") as popen:
                popen.return_value.pid = 4242
                result = live_preview_sessions.ensure_preview_session(
                    workspace_id=2,
                    workspace_name="dashpro",
                    source_path=str(sandbox_repo),
                    source_workspace_path=str(source_repo),
                    auto_session_id="auto-2",
                )

        stop_process.assert_called_once_with(existing)
        self.assertEqual(result["framework"], "expo")
        self.assertEqual(result["port"], 3564)

    def test_workspace_env_snapshot_is_isolated_per_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(live_preview_sessions, "SESSION_ROOT", root):
                live_preview_sessions.write_preview_session(
                    {
                        "scope_key": "workspace-7",
                        "workspace_id": 7,
                        "workspace_name": "dashpro",
                        "title": "dashpro",
                        "url": "http://127.0.0.1:3007",
                        "status": "running",
                        "healthy": True,
                        "cwd": "/tmp/dashpro",
                        "command": "npm run dev -- --port 3007",
                        "port": 3007,
                    }
                )
                live_preview_sessions.write_preview_session(
                    {
                        "scope_key": "auto-session-abc",
                        "workspace_id": 7,
                        "auto_session_id": "session-abc",
                        "workspace_name": "dashpro",
                        "title": "auto",
                        "url": "http://127.0.0.1:3407",
                        "status": "running",
                        "healthy": True,
                        "cwd": "/tmp/dashpro/.axon-auto",
                        "command": "npm run dev -- --port 3407",
                        "port": 3407,
                    }
                )

                workspace_snapshot = live_preview_sessions.workspace_env_snapshot("/tmp/dashpro", workspace_id=7)
                auto_snapshot = live_preview_sessions.workspace_env_snapshot(
                    "/tmp/dashpro",
                    workspace_id=7,
                    auto_session_id="session-abc",
                )
                other_snapshot = live_preview_sessions.workspace_env_snapshot("/tmp/other", workspace_id=8)

        self.assertEqual(workspace_snapshot["preview_url"], "http://127.0.0.1:3007")
        self.assertEqual(auto_snapshot["preview_url"], "http://127.0.0.1:3407")
        self.assertEqual(auto_snapshot["preview_auto_session_id"], "session-abc")
        self.assertEqual(other_snapshot, {})


class WorkspacePreviewTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_preview_target_prefers_auto_sandbox_path(self):
        workspace_row = {"id": 22, "name": "dashpro", "path": "/src/dashpro"}

        @asynccontextmanager
        async def fake_db():
            yield object()

        with patch.object(server.devdb, "get_db", fake_db), \
             patch.object(server.devdb, "get_project", return_value=workspace_row), \
             patch.object(
                 server.auto_session_service,
                 "read_auto_session",
                 return_value={
                     "session_id": "auto-22",
                     "workspace_id": 22,
                     "sandbox_path": "/tmp/axon-auto-22",
                 },
             ):
            workspace, auto_meta, target_path = await server._workspace_preview_target(22, "auto-22")

        self.assertEqual(workspace["path"], "/src/dashpro")
        self.assertEqual(auto_meta["sandbox_path"], "/tmp/axon-auto-22")
        self.assertEqual(target_path, "/tmp/axon-auto-22")

    async def test_workspace_env_uses_project_path_and_auto_sandbox_when_path_missing(self):
        workspace_row = {"id": 22, "name": "dashpro", "path": "/src/dashpro"}

        @asynccontextmanager
        async def fake_db():
            yield object()

        with patch.object(server.devdb, "get_db", fake_db), \
             patch.object(server.devdb, "get_project", return_value=workspace_row), \
             patch.object(
                 server.auto_session_service,
                 "read_auto_session",
                 return_value={
                     "session_id": "auto-22",
                     "workspace_id": 22,
                     "sandbox_path": "/tmp/axon-auto-22",
                 },
             ), \
             patch.object(server.runtime_manager, "env_snapshot", return_value={"work_dir": "axon-auto-22"}) as env_snapshot, \
             patch.object(server.live_preview_service, "workspace_env_snapshot", return_value={"preview_url": "http://127.0.0.1:3564"}) as preview_snapshot:
            payload = await server.workspace_env(project_id=22, auto_session_id="auto-22")

        env_snapshot.assert_called_once_with("/tmp/axon-auto-22")
        preview_snapshot.assert_called_once_with("/tmp/axon-auto-22", workspace_id=22, auto_session_id="auto-22")
        self.assertEqual(payload["work_dir"], "axon-auto-22")
        self.assertEqual(payload["preview_url"], "http://127.0.0.1:3564")


class WorkspaceDeletionEndpointTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_delete_project_returns_deleted_workspace(self):
        row = {"id": 7, "name": "dashpro", "path": "/src/dashpro", "status": "active"}

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_project", return_value=row), \
             patch.object(server.devdb, "delete_project", return_value=None) as delete_project, \
             patch.object(server.devdb, "log_event", return_value=None) as log_event:
            payload = await server.delete_project(7)

        delete_project.assert_called_once()
        self.assertEqual(delete_project.call_args.args[1], 7)
        log_event.assert_called_once()
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["project"]["name"], "dashpro")

    async def test_delete_project_raises_404_for_unknown_workspace(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_project", return_value=None):
            with self.assertRaises(server.HTTPException) as ctx:
                await server.delete_project(999)

        self.assertEqual(ctx.exception.status_code, 404)


class ServerAiParamsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_backend_prefers_generic_cli_runtime_keys(self):
        settings = {
            "ai_backend": "cli",
            "api_provider": "deepseek",
            "deepseek_api_key": "",
            "anthropic_api_key": "anth-key",
            "anthropic_base_url": "https://api.anthropic.com/v1",
            "anthropic_api_model": "claude-sonnet-4-5",
            "cli_runtime_path": "/tmp/codex",
            "cli_runtime_model": "gpt-5.4",
            "claude_cli_path": "/tmp/claude",
            "claude_cli_model": "claude-sonnet-4-6",
        }

        with patch.object(server.devvault.VaultSession, "is_unlocked", return_value=False):
            params = await server._ai_params(settings)

        self.assertEqual(params["backend"], "cli")
        self.assertEqual(params["cli_path"], "/tmp/codex")
        self.assertEqual(params["cli_model"], "gpt-5.4")

    async def test_cli_backend_chooses_configured_api_fallback(self):
        settings = {
            "ai_backend": "cli",
            "api_provider": "deepseek",
            "deepseek_api_key": "",
            "anthropic_api_key": "anth-key",
            "anthropic_base_url": "https://api.anthropic.com/v1",
            "anthropic_api_model": "claude-sonnet-4-5",
            "claude_cli_path": "/tmp/claude",
            "claude_cli_model": "claude-sonnet-4-6",
        }

        with patch.object(server.devvault.VaultSession, "is_unlocked", return_value=False):
            params = await server._ai_params(settings)

        self.assertEqual(params["backend"], "cli")
        self.assertEqual(params["api_provider"], "anthropic")
        self.assertEqual(params["api_key"], "anth-key")
        self.assertEqual(params["api_model"], "claude-sonnet-4-5")

    async def test_effective_ai_params_self_heals_api_backend_to_codex(self):
        settings = {
            "ai_backend": "api",
            "api_provider": "deepseek",
            "deepseek_api_key": "",
            "deepseek_base_url": "https://api.deepseek.com/v1",
            "deepseek_api_model": "deepseek-reasoner",
            "cli_runtime_path": "/tmp/codex",
        }

        with patch.object(server.devvault.VaultSession, "is_unlocked", return_value=False), \
             patch.object(server, "_ollama_service_status", return_value={"running": False}), \
             patch.object(
                 claude_cli_runtime,
                 "build_cli_runtime_snapshot",
                 return_value={"installed": True, "binary": "/tmp/claude", "auth": {"logged_in": True, "auth_method": "claude.ai"}},
             ), \
             patch.object(
                 codex_cli_runtime,
                 "build_codex_runtime_snapshot",
                 return_value={"installed": True, "binary": "/tmp/codex", "auth": {"logged_in": True, "auth_method": "chatgpt"}},
             ):
            params = await server._effective_ai_params(settings, {}, requested_model="deepseek-reasoner")

        self.assertEqual(params["backend"], "cli")
        self.assertEqual(params["cli_path"], "/tmp/codex")
        self.assertEqual(params["cli_model"], "gpt-5.4")

    async def test_effective_ai_params_uses_quick_budget_for_plain_chat(self):
        settings = {
            "quick_model": "cheap-model",
            "standard_model": "standard-model",
        }

        with patch.object(server, "_ai_params", return_value={
            "backend": "api",
            "api_key": "key",
            "api_provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_model": "deepseek-reasoner",
        }), patch.object(server, "_runtime_truth_for_settings", return_value=(
            {"effective_runtime": "api", "selected_runtime": "api", "selected_runtime_label": "API", "self_heal_active": False},
            {},
        )):
            params = await server._effective_ai_params(settings, {}, requested_model="")

        self.assertEqual(params["budget_class"], "quick")
        self.assertEqual(params["api_model"], "cheap-model")

    async def test_effective_ai_params_uses_standard_budget_for_agent(self):
        settings = {
            "quick_model": "cheap-model",
            "standard_model": "standard-model",
        }

        with patch.object(server, "_ai_params", return_value={
            "backend": "api",
            "api_key": "key",
            "api_provider": "deepseek",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_model": "deepseek-reasoner",
        }), patch.object(server, "_runtime_truth_for_settings", return_value=(
            {"effective_runtime": "api", "selected_runtime": "api", "selected_runtime_label": "API", "self_heal_active": False},
            {},
        )):
            params = await server._effective_ai_params(settings, {}, agent_request=True, requested_model="")

        self.assertEqual(params["budget_class"], "standard")
        self.assertEqual(params["api_model"], "standard-model")

    async def test_effective_ai_params_falls_back_to_codex_quick_model_when_blank(self):
        settings = {
            "quick_model": "",
            "standard_model": "",
            "deep_model": "",
            "cli_runtime_path": "/tmp/codex",
        }

        with patch.object(server, "_ai_params", return_value={
            "backend": "cli",
            "cli_path": "/tmp/codex",
            "cli_model": "gpt-5.4",
        }), patch.object(server, "_runtime_truth_for_settings", return_value=(
            {"effective_runtime": "cli", "selected_runtime": "cli", "selected_runtime_label": "CLI", "self_heal_active": False},
            {},
        )):
            params = await server._effective_ai_params(settings, {}, requested_model="")

        self.assertEqual(params["budget_class"], "quick")
        self.assertEqual(params["cli_model"], "gpt-5.1-codex-mini")


class LocalFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_workspace_snapshot_fast_path_answers_without_model(self):
        payload = await server._maybe_local_fast_chat_response(
            object(),
            user_message="What is the workspace path?",
            project_id=7,
            settings={"external_fetch_policy": "cache_first"},
            snapshot_bundle={
                "data": {
                    "project": {"name": "dashpro", "path": "/tmp/dashpro", "git_branch": "main"},
                    "tasks": [],
                    "prompts": [],
                    "memory": [],
                }
            },
            memory_bundle={"items": []},
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["evidence_source"], "workspace_snapshot")
        self.assertIn("/tmp/dashpro", payload["content"])
        self.assertTrue(payload["fast_path"])

    async def test_memory_fast_path_answers_without_model(self):
        payload = await server._maybe_local_fast_chat_response(
            object(),
            user_message="What do you remember about this workspace?",
            project_id=7,
            settings={"external_fetch_policy": "cache_first"},
            snapshot_bundle={"data": {}},
            memory_bundle={
                "items": [
                    {"title": "Known fact", "summary": "The payment upload flow was already patched.", "content": "", "layer": "workspace"}
                ]
            },
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["evidence_source"], "memory")
        self.assertIn("payment upload flow", payload["content"])
        self.assertTrue(payload["fast_path"])

    async def test_cached_web_fast_path_prefers_cache_when_available(self):
        fake_row = {
            "title": "Example Domain",
            "summary": "This domain is for use in documentation examples.",
            "content": "Example Domain",
            "status_code": 200,
        }
        with patch.object(server.devdb, "get_external_fetch_cache", return_value=fake_row):
            payload = await server._maybe_local_fast_chat_response(
                object(),
                user_message="What does this page say? https://example.com",
                project_id=7,
                settings={"external_fetch_policy": "cache_first"},
                snapshot_bundle={"data": {}},
                memory_bundle={"items": []},
            )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["evidence_source"], "cached_external")
        self.assertIn("Example Domain", payload["content"])


class ChatConsoleCommandTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    def test_login_console_command_starts_guided_codex_session(self):
        with patch.object(
            server.console_command_service.runtime_login_sessions,
            "start_login_session",
            return_value={
                "session_id": "codex-login-1",
                "family": "codex",
                "status": "waiting",
                "browser_url": "https://auth.openai.com/codex/device",
                "user_code": "ABCD-1234",
                "command_preview": "/home/edp/.devbrain/tools/npm/bin/codex login",
                "binary": "/home/edp/.devbrain/tools/npm/bin/codex",
                "message": "Continue sign-in in the browser.",
            },
        ) as start_login_session:
            payload = server.console_command_service.maybe_handle_console_command("/login codex")

        self.assertEqual(payload["command"], "login")
        self.assertEqual(payload["data"]["family"], "codex")
        self.assertEqual(payload["data"]["session_id"], "codex-login-1")
        self.assertEqual(payload["data"]["user_code"], "ABCD-1234")
        self.assertIn("https://auth.openai.com/codex/device", payload["response"])
        self.assertIn("ABCD-1234", payload["response"])
        start_login_session.assert_called_once_with("codex", override_path="")

    def test_login_console_command_uses_supplied_codex_override_path(self):
        with patch.object(
            server.console_command_service.runtime_login_sessions,
            "start_login_session",
            return_value={
                "session_id": "codex-login-2",
                "family": "codex",
                "status": "waiting",
            },
        ) as start_login_session:
            payload = server.console_command_service.maybe_handle_console_command(
                "/login codex",
                login_overrides={"codex": "/home/edp/.devbrain/tools/npm/bin/codex"},
            )

        self.assertEqual(payload["command"], "login")
        start_login_session.assert_called_once_with(
            "codex",
            override_path="/home/edp/.devbrain/tools/npm/bin/codex",
        )

    async def test_chat_handles_install_console_command_without_loading_model_settings(self):
        persisted: dict[str, object] = {}

        async def fake_persist(_conn, **kwargs):
            persisted.update(kwargs)

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_setting", return_value=""), \
             patch.object(
                 server.console_command_service,
                 "maybe_handle_console_command",
                 return_value={
                     "command": "install",
                     "response": "Installed codex inside Axon.",
                     "event_name": "chat_console_install",
                     "event_summary": "install: @openai/codex",
                     "data": {"status": "completed", "package_name": "@openai/codex"},
                 },
             ), \
             patch.object(server, "_persist_chat_reply", side_effect=fake_persist), \
             patch.object(server.devdb, "get_all_settings", side_effect=AssertionError("settings should not load")), \
             patch.object(server, "_effective_ai_params", side_effect=AssertionError("AI runtime should not resolve")):
            payload = await server.chat(server.ChatMessage(message="/install codex", project_id=7))

        self.assertTrue(payload["console_command"])
        self.assertEqual(payload["command"], "install")
        self.assertEqual(payload["package_name"], "@openai/codex")
        self.assertEqual(persisted["assistant_message"], "Installed codex inside Axon.")
        self.assertEqual(persisted["project_id"], 7)

    async def test_chat_handles_login_console_command_without_loading_model_settings(self):
        persisted: dict[str, object] = {}

        async def fake_persist(_conn, **kwargs):
            persisted.update(kwargs)

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_setting", return_value=""), \
             patch.object(
                 server.console_command_service,
                 "maybe_handle_console_command",
                 return_value={
                     "command": "login",
                     "response": "Codex CLI sign-in is running inside Axon.",
                     "event_name": "chat_console_login",
                     "event_summary": "login: codex",
                     "data": {"status": "waiting", "family": "codex", "session_id": "codex-login-1"},
                 },
             ), \
             patch.object(server, "_persist_chat_reply", side_effect=fake_persist), \
             patch.object(server.devdb, "get_all_settings", side_effect=AssertionError("settings should not load")), \
             patch.object(server, "_effective_ai_params", side_effect=AssertionError("AI runtime should not resolve")):
            payload = await server.chat(server.ChatMessage(message="/login codex", project_id=7))

        self.assertTrue(payload["console_command"])
        self.assertEqual(payload["command"], "login")
        self.assertEqual(payload["family"], "codex")
        self.assertEqual(payload["session_id"], "codex-login-1")
        self.assertEqual(persisted["assistant_message"], "Codex CLI sign-in is running inside Axon.")
        self.assertEqual(persisted["project_id"], 7)


class AgentFastPathTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    def test_fast_path_commit_eligibility_requires_plain_workspace_commit(self):
        self.assertTrue(
            agent_fast_path.fast_path_commit_eligible(
                "Commit the repo",
                workspace_path="/tmp/demo",
                composer_options={},
            )
        )
        self.assertFalse(
            agent_fast_path.fast_path_commit_eligible(
                "Commit the repo",
                workspace_path="",
                composer_options={},
            )
        )
        self.assertFalse(
            agent_fast_path.fast_path_commit_eligible(
                "Commit the repo",
                workspace_path="/tmp/demo",
                resource_ids=[1],
                composer_options={},
            )
        )
        self.assertFalse(
            agent_fast_path.fast_path_commit_eligible(
                "Commit the repo",
                workspace_path="/tmp/demo",
                composer_options={"agent_role": "auto"},
            )
        )

    def test_fast_path_commit_eligibility_rejects_explanatory_question(self):
        self.assertFalse(
            agent_fast_path.fast_path_commit_eligible(
                "How do I commit the repo?",
                workspace_path="/tmp/demo",
                composer_options={},
            )
        )

    def test_fast_path_converts_blocked_commit_into_approval_events(self):
        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=lambda *args, **kwargs: None,
            stream_api_chat=lambda *args, **kwargs: None,
            stream_ollama_chat=lambda *args, **kwargs: None,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-fast-path.db",
        )

        with patch.object(
            agent_fast_path,
            "_direct_agent_action",
            return_value=(
                "shell_cmd",
                {"cmd": "git add -A", "cwd": "/tmp/demo", "_resume_task": 'Commit everything with commit message "feat: update tests".'},
                "BLOCKED_CMD:git:git add -A",
                "BLOCKED_CMD:git:git add -A",
            ),
        ):
            result = agent_fast_path.maybe_run_fast_commit_path(
                "Commit the repo",
                deps=deps,
                workspace_path="/tmp/demo",
                project_name="Demo",
                workspace_id=7,
            )

        self.assertIsNotNone(result)
        self.assertEqual([event["type"] for event in result.events], ["tool_call", "tool_result", "approval_required"])
        self.assertEqual(result.events[2]["action_type"], "git_add")
        self.assertEqual(result.final_text, "")

    def test_fast_path_returns_text_for_successful_commit_step(self):
        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=lambda *args, **kwargs: None,
            stream_api_chat=lambda *args, **kwargs: None,
            stream_ollama_chat=lambda *args, **kwargs: None,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-fast-path.db",
        )

        with patch.object(
            agent_fast_path,
            "_direct_agent_action",
            return_value=(
                "shell_cmd",
                {"cmd": 'git commit -m "feat: update tests"', "cwd": "/tmp/demo"},
                "[axon] committed",
                'ran `git commit -m "feat: update tests"` in `/tmp/demo`.',
            ),
        ):
            result = agent_fast_path.maybe_run_fast_commit_path(
                "Commit the repo",
                deps=deps,
                workspace_path="/tmp/demo",
                project_name="Demo",
                workspace_id=7,
            )

        self.assertIsNotNone(result)
        self.assertEqual([event["type"] for event in result.events], ["tool_call", "tool_result", "text", "done"])
        self.assertIn("git commit", result.final_text)

    async def test_agent_endpoint_uses_fast_commit_path_before_ai_resolution(self):
        class FakeRequest:
            async def is_disconnected(self):
                return False

        persisted = {"count": 0}

        async def fake_save_message(*args, **kwargs):
            persisted["count"] += 1

        async def fake_log_event(*args, **kwargs):
            persisted["logged"] = True

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value={}), \
             patch.object(server.devdb, "get_project", return_value={"id": 7, "name": "Demo", "path": "/tmp/demo"}), \
             patch.object(server.devdb, "save_message", side_effect=fake_save_message), \
             patch.object(server.devdb, "log_event", side_effect=fake_log_event), \
             patch.object(
                 server.agent_fast_path,
                 "maybe_run_fast_commit_path",
                 return_value=agent_fast_path.FastPathResult(
                     events=[
                         {"type": "tool_call", "name": "shell_cmd", "args": {"cmd": "git add -A", "cwd": "/tmp/demo"}},
                         {"type": "tool_result", "name": "shell_cmd", "result": "[axon] staged"},
                         {"type": "text", "chunk": "staged the full worktree"},
                         {"type": "done", "iterations": 1, "fast_path": True},
                     ],
                     final_text="staged the full worktree",
                 ),
             ), \
             patch.object(server, "_effective_ai_params", side_effect=AssertionError("AI runtime should not resolve")):
            response = await server.agent_endpoint(
                server.AgentRequest(message="Commit the repo", project_id=7),
                FakeRequest(),
            )

            chunks = []
            async for item in response.body_iterator:
                chunks.append(item)

        self.assertTrue(chunks)
        self.assertEqual(persisted["count"], 2)
        self.assertTrue(persisted["logged"])

    async def test_chat_login_console_command_uses_selected_codex_override(self):
        persisted: dict[str, object] = {}

        async def fake_persist(_conn, **kwargs):
            persisted.update(kwargs)

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_setting", side_effect=lambda _conn, key: "/tmp/codex" if key == "cli_runtime_path" else ""), \
             patch.object(
                 server.console_command_service.runtime_login_sessions,
                 "start_login_session",
                 return_value={
                     "session_id": "codex-login-2",
                     "family": "codex",
                     "status": "waiting",
                     "command_preview": "/tmp/codex login",
                 },
             ) as start_login_session, \
             patch.object(server, "_persist_chat_reply", side_effect=fake_persist), \
             patch.object(server.devdb, "get_all_settings", side_effect=AssertionError("settings should not load")), \
             patch.object(server, "_effective_ai_params", side_effect=AssertionError("AI runtime should not resolve")):
            payload = await server.chat(server.ChatMessage(message="/login codex", project_id=7))

        self.assertTrue(payload["console_command"])
        self.assertEqual(payload["command"], "login")
        self.assertEqual(payload["family"], "codex")
        start_login_session.assert_called_once_with("codex", override_path="/tmp/codex")
        self.assertIn("codex-login-2", persisted["assistant_message"])


class MemorySearchBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_memory_does_not_touch_rows_on_read(self):
        settings = {"memory_query_cache_ttl_seconds": "45", "embeddings_model": ""}
        row = {
            "id": 1,
            "title": "Dashpro",
            "summary": "Dashboard project",
            "content": "Dashboard project memory",
            "layer": "workspace",
            "trust_level": "high",
            "last_accessed_at": "",
            "updated_at": "",
            "relevance_score": 0.8,
            "workspace_id": 7,
            "embedding_json": "",
        }
        with patch.object(memory_engine.devdb, "search_memory_items_fts", return_value=[row]), \
             patch.object(memory_engine.devdb, "search_memory_items", return_value=[]), \
             patch.object(memory_engine.devdb, "touch_memory_items") as touch_mock:
            results = await memory_engine.search_memory(
                object(),
                query="dashpro",
                settings=settings,
                workspace_id=7,
                limit=3,
            )

        self.assertEqual(len(results), 1)
        touch_mock.assert_not_called()


class RuntimeLoginEndpointTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_runtime_login_start_returns_guided_session(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value={"claude_cli_path": "/tmp/claude"}), \
             patch.object(
                 runtime_login_sessions,
                 "start_login_session",
                 return_value={
                     "session_id": "sess-1",
                     "family": "claude",
                     "status": "waiting",
                     "browser_url": "https://example.com/login",
                 },
             ), \
             patch.object(server.devdb, "log_event", return_value=None):
            payload = await server.runtime_claude_login_start(
                server.RuntimeLoginStartRequest(mode="claudeai", email="user@example.com")
            )

        self.assertEqual(payload["session"]["session_id"], "sess-1")
        self.assertEqual(payload["session"]["browser_url"], "https://example.com/login")

    async def test_runtime_login_start_uses_generic_codex_override_only_for_codex(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(
                 server.devdb,
                 "get_all_settings",
                 return_value={"cli_runtime_path": "/tmp/codex", "claude_cli_path": "/tmp/claude"},
             ), \
             patch.object(
                 runtime_login_sessions,
                 "start_login_session",
                 return_value={"session_id": "sess-codex", "family": "codex", "status": "waiting"},
             ) as start_login_session, \
             patch.object(server.devdb, "log_event", return_value=None):
            await server.runtime_codex_login_start()

        start_login_session.assert_called_once()
        self.assertEqual(start_login_session.call_args.kwargs["override_path"], "/tmp/codex")

    async def test_runtime_login_start_does_not_leak_codex_override_into_claude(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value={"cli_runtime_path": "/tmp/codex"}), \
             patch.object(
                 runtime_login_sessions,
                 "start_login_session",
                 return_value={"session_id": "sess-claude", "family": "claude", "status": "waiting"},
             ) as start_login_session, \
             patch.object(server.devdb, "log_event", return_value=None):
            await server.runtime_claude_login_start()

        start_login_session.assert_called_once()
        self.assertEqual(start_login_session.call_args.kwargs["override_path"], "")

    async def test_runtime_login_refresh_returns_session(self):
        with patch.object(
            runtime_login_sessions,
            "refresh_login_session",
            return_value={
                "session_id": "sess-2",
                "family": "codex",
                "status": "waiting",
                "user_code": "ABCD-1234",
            },
        ):
            payload = await server.runtime_codex_login_status("sess-2")

        self.assertEqual(payload["session"]["user_code"], "ABCD-1234")

    async def test_runtime_codex_status_uses_selected_codex_override(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value={"cli_runtime_path": "/tmp/codex"}), \
             patch.object(codex_cli_runtime, "build_codex_runtime_snapshot", return_value={"binary": "/tmp/codex"}) as build_snapshot:
            payload = await server.runtime_codex_status()

        build_snapshot.assert_called_once_with("/tmp/codex")
        self.assertEqual(payload["binary"], "/tmp/codex")

    async def test_runtime_cli_status_ignores_selected_codex_override(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value={"cli_runtime_path": "/tmp/codex"}), \
             patch.object(claude_cli_runtime, "build_cli_runtime_snapshot", return_value={"binary": "/tmp/claude"}) as build_snapshot:
            payload = await server.runtime_cli_status()

        build_snapshot.assert_called_once_with("")
        self.assertEqual(payload["binary"], "/tmp/claude")

    async def test_runtime_login_cancel_returns_cancelled_session(self):
        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(
                 runtime_login_sessions,
                 "cancel_login_session",
                 return_value={"session_id": "sess-3", "family": "codex", "status": "cancelled"},
             ), \
             patch.object(server.devdb, "log_event", return_value=None):
            payload = await server.runtime_codex_login_cancel("sess-3")

        self.assertEqual(payload["session"]["status"], "cancelled")


class RuntimeLoginSessionServiceTests(unittest.TestCase):
    def test_await_login_session_details_returns_browser_prompt_once_available(self):
        waiting = {
            "session_id": "sess-1",
            "family": "codex",
            "status": "waiting",
            "browser_url": "",
            "user_code": "",
        }
        opened = {
            **waiting,
            "status": "browser_opened",
            "browser_url": "https://auth.openai.com/codex/device",
            "user_code": "XF1T-RC1AX",
        }
        monotonic_values = iter([100.0, 100.05])

        with patch.object(runtime_login_sessions, "refresh_login_session", side_effect=[waiting, opened]), \
             patch.object(runtime_login_sessions._time, "sleep", return_value=None), \
             patch.object(runtime_login_sessions._time, "monotonic", side_effect=lambda: next(monotonic_values)):
            session = runtime_login_sessions._await_login_session_details(
                "codex",
                "sess-1",
                timeout_seconds=1.0,
                poll_interval=0.1,
            )

        self.assertEqual(session["status"], "browser_opened")
        self.assertEqual(session["browser_url"], "https://auth.openai.com/codex/device")
        self.assertEqual(session["user_code"], "XF1T-RC1AX")

    def test_codex_login_status_uses_device_auth_url_and_extracts_standalone_code(self):
        session = runtime_login_sessions._status_from_meta(
            {"family": "codex", "status": "pending"},
            {"auth": {"logged_in": False, "message": "Not logged in"}},
            (
                "Follow these steps to sign in with ChatGPT using device code authorization:\n\n"
                "1. Open this link in your browser and sign in to your account\n"
                "   https://auth.openai.com/codex/device\x1b[0m\n\n"
                "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
                "   XF1T-RC1AX\n"
            ),
        )

        self.assertEqual(session["browser_url"], "https://auth.openai.com/codex/device")
        self.assertEqual(session["user_code"], "XF1T-RC1AX")
        self.assertEqual(session["status"], "waiting")
        self.assertIn("XF1T-RC1AX", session["message"])

    def test_codex_login_status_marks_device_auth_timeout_failed(self):
        session = runtime_login_sessions._status_from_meta(
            {"family": "codex", "status": "waiting", "returncode": 0, "started_at": "2026-04-03T16:00:05Z"},
            {"auth": {"logged_in": False, "message": "Not logged in"}},
            "Error logging in with device code: device auth timed out after 15 minutes\n",
        )

        self.assertEqual(session["status"], "failed")
        self.assertIn("timed out", session["message"].lower())

    def test_codex_login_status_prefers_oauth_url_over_local_callback_server(self):
        session = runtime_login_sessions._status_from_meta(
            {"family": "codex", "status": "pending"},
            {"auth": {"logged_in": False, "message": "Not logged in"}},
            (
                "Starting local login server on http://localhost:1455.\n"
                "If your browser did not open, navigate to this URL to authenticate:\n\n"
                "https://auth.openai.com/oauth/authorize?response_type=code&state=test-state\n"
            ),
        )

        self.assertEqual(
            session["browser_url"],
            "https://auth.openai.com/oauth/authorize?response_type=code&state=test-state",
        )
        self.assertEqual(session["status"], "waiting")

    def test_codex_login_status_keeps_browser_url_empty_until_log_emits_one(self):
        session = runtime_login_sessions._status_from_meta(
            {"family": "codex", "status": "pending", "started_at": "2026-04-03T16:45:09Z"},
            {"auth": {"logged_in": False, "message": "Not logged in"}},
            "",
        )

        self.assertEqual(session["browser_url"], "")
        self.assertEqual(session["status"], "waiting")

    def test_find_active_login_session_ignores_waiting_session_from_different_binary(self):
        waiting = {
            "session_id": "sess-old",
            "family": "codex",
            "status": "waiting",
            "binary": "/tmp/old-codex",
        }
        with patch.object(runtime_login_sessions, "list_login_sessions", return_value=[waiting]), \
             patch.object(runtime_login_sessions, "refresh_login_session", return_value=waiting):
            session = runtime_login_sessions.find_active_login_session("codex", binary="/tmp/new-codex")

        self.assertIsNone(session)

    def test_find_active_login_session_ignores_waiting_session_from_different_command_preview(self):
        waiting = {
            "session_id": "sess-old",
            "family": "codex",
            "status": "waiting",
            "binary": "/tmp/codex",
            "command_preview": "/tmp/codex login --device-auth",
        }
        with patch.object(runtime_login_sessions, "list_login_sessions", return_value=[waiting]), \
             patch.object(runtime_login_sessions, "refresh_login_session", return_value=waiting):
            session = runtime_login_sessions.find_active_login_session(
                "codex",
                binary="/tmp/codex",
                command_preview="/tmp/codex login",
            )

        self.assertIsNone(session)


class RuntimeTruthSelfHealTests(unittest.TestCase):
    def test_runtime_truth_prefers_codex_self_heal_for_missing_api_key(self):
        settings = {
            "ai_backend": "api",
            "api_provider": "deepseek",
        }
        status = {
            "selected_api_provider": {
                "provider_id": "deepseek",
                "provider_label": "DeepSeek",
                "api_key_configured": False,
                "api_base_url": "https://api.deepseek.com/v1",
                "api_model": "deepseek-reasoner",
            },
            "cli_runtime": {
                "runtime_id": "claude",
                "auth": {"logged_in": True, "auth_method": "claude.ai", "subscription_type": "max"},
            },
            "codex_runtime": {
                "installed": True,
                "auth": {"logged_in": True, "auth_method": "chatgpt"},
            },
            "cli_cooldown_remaining_seconds": 0,
        }

        truth = runtime_truth_service.build_runtime_truth(status, settings=settings, ollama_running=False)

        self.assertEqual(truth["selected_runtime"], "deepseek_api")
        self.assertEqual(truth["effective_runtime"], "codex_cli")
        self.assertTrue(truth["self_heal_active"])
        self.assertEqual(truth["self_heal_target_model"], "gpt-5.4")
        self.assertIn("Codex CLI", truth["fallback_reason"])


class RuntimeStatusEndpointTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_runtime_status_adds_truth_fields_and_redacts_provider_key(self):
        settings = {
            "ai_backend": "cli",
            "api_provider": "anthropic",
            "anthropic_api_key": "anthropic-secret-token",
            "anthropic_base_url": "https://api.anthropic.com/v1",
            "anthropic_api_model": "claude-sonnet-4-5",
        }
        base_status = {
            "runtime_state": "active",
            "runtime_label": "Claude CLI",
            "active_model": "Claude default",
            "selected_api_provider": provider_registry.public_runtime_api_config(settings),
            "cli_runtime": {
                "runtime_id": "claude",
                "auth": {"logged_in": True, "auth_method": "claude.ai", "subscription_type": "max"},
            },
            "codex_runtime": {
                "installed": True,
                "auth": {"logged_in": True, "auth_method": "chatgpt"},
            },
            "cli_cooldown_remaining_seconds": 42,
        }

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", return_value=settings), \
             patch.object(server.devvault, "vault_resolve_all_provider_keys", return_value={}), \
             patch.object(server.devdb, "get_projects", return_value=[]), \
             patch.object(server.devdb, "list_resources", return_value=[]), \
             patch.object(memory_engine, "sync_memory_layers", return_value={"total": 0, "layers": {}, "labels": {}}), \
             patch.object(server.devdb, "list_terminal_sessions", return_value=[]), \
             patch.object(brain, "ollama_list_models", return_value=[]), \
             patch.object(server, "_ollama_service_status", return_value={"running": False}), \
             patch.object(runtime_manager, "build_runtime_status", return_value=base_status), \
             patch.object(server.devvault.VaultSession, "is_unlocked", return_value=False), \
             patch.object(brain, "get_session_usage", return_value={"calls": 0}):
            payload = await server.runtime_status()

        self.assertEqual(payload["selected_runtime"], "claude_cli")
        self.assertEqual(payload["effective_runtime"], "codex_cli")
        self.assertEqual(payload["auth_method"], "chatgpt")
        self.assertEqual(payload["cooldown_source"], "claude_cli_rate_limit")
        self.assertIn("Codex CLI", payload["fallback_reason"])
        self.assertNotIn("api_key", payload["selected_api_provider"])


class BrowserPreviewAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_attach_preview_browser_sets_ownership_and_scope_fields(self):
        class _FakeBridge:
            def __init__(self):
                self.is_running = False

            async def start(self, headless=False):
                self.is_running = True

            async def execute_action(self, action):
                return {"success": True, "action": action}

            def status(self):
                return {"running": True, "url": "http://127.0.0.1:3007", "title": "Dashpro Preview"}

        fake_bridge = _FakeBridge()
        original_session = dict(server._browser_action_state["session"])
        server._browser_action_state["session"] = server._default_browser_session()
        try:
            with patch.dict(sys.modules, {"browser_bridge": SimpleNamespace(get_bridge=lambda: fake_bridge)}):
                result = await server._attach_preview_browser(
                    "http://127.0.0.1:3007",
                    preview={
                        "scope_key": "workspace-7",
                        "status": "running",
                        "source_workspace_path": "/src/dashpro",
                    },
                    workspace={"id": 7, "name": "dashpro", "path": "/src/dashpro"},
                    auto_meta={"session_id": "auto-7"},
                )
        finally:
            session = dict(server._browser_action_state["session"])
            server._browser_action_state["session"] = original_session

        self.assertTrue(result["attached"])
        self.assertTrue(session["connected"])
        self.assertEqual(session["control_owner"], "axon")
        self.assertEqual(session["ownership_label"], "Axon controls this browser now")
        self.assertEqual(session["attached_workspace_id"], 7)
        self.assertEqual(session["attached_workspace_name"], "dashpro")
        self.assertEqual(session["attached_auto_session_id"], "auto-7")
        self.assertEqual(session["attached_scope_key"], "workspace-7")


class BrowserBridgeHealthTests(unittest.TestCase):
    def test_is_running_false_when_page_is_closed(self):
        bridge = browser_bridge.BrowserBridge()
        bridge._started = True
        bridge._browser = SimpleNamespace(is_connected=lambda: True)
        bridge._context = object()
        bridge._page = SimpleNamespace(is_closed=lambda: True)

        self.assertFalse(bridge.is_running)

    def test_status_clears_url_when_page_is_closed(self):
        bridge = browser_bridge.BrowserBridge()
        bridge._started = True
        bridge._browser = SimpleNamespace(is_connected=lambda: True)
        bridge._context = object()
        bridge._page = SimpleNamespace(is_closed=lambda: True, url="http://localhost:3002")
        bridge._cached_title = "EduDash Pro"

        self.assertEqual(
            bridge.status(),
            {"running": False, "url": "", "title": ""},
        )


class ChatContextTests(unittest.TestCase):
    def test_image_inspection_turn_drops_old_history(self):
        history = [
            {"role": "user", "content": "What is needed for BKK Innovation Hub?"},
            {"role": "assistant", "content": "Here is a broad project diagnosis."},
        ]

        selected = select_history_for_chat(
            "What do you see in the attached image?",
            history,
            backend="cli",
            resource_image_paths=["/tmp/logo.png"],
        )

        self.assertEqual(selected, [])

    def test_explicit_history_budget_overrides_backend_default(self):
        history = [{"role": "user", "content": f"turn {index}"} for index in range(20)]

        selected = select_history_for_chat(
            "Keep going",
            history,
            backend="cli",
            max_turns=14,
        )

        self.assertEqual(len(selected), 14)


class VisionRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_image_routing_stays_on_cli(self):
        async def fail_if_called(_: str) -> str:
            raise AssertionError("CLI routing should not try to resolve an API provider key")

        routed, warnings = await auto_route_vision_runtime(
            settings={"ai_backend": "cli"},
            ai={"backend": "cli", "api_provider": "anthropic", "api_model": "claude-sonnet-4-5"},
            resource_bundle={"image_paths": ["/tmp/logo.png"], "vision_model": ""},
            resolve_provider_key=fail_if_called,
            vault_unlocked=True,
        )

        self.assertEqual(routed["backend"], "cli")
        self.assertEqual(warnings, [])


class BrainChatRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cli_pacing._next_cli_start_at_by_key.clear()
        cli_pacing._last_cli_cooldown_message_by_key.clear()
        cli_pacing._last_cli_cooldown_until_by_key.clear()

    async def asyncTearDown(self):
        cli_pacing._next_cli_start_at_by_key.clear()
        cli_pacing._last_cli_cooldown_message_by_key.clear()
        cli_pacing._last_cli_cooldown_until_by_key.clear()

    async def test_cli_chat_with_image_does_not_reference_unbound_runtime(self):
        async def fake_stream_cli(messages, **kwargs):
            self.assertTrue(messages)
            yield "image ok"

        with patch.object(brain, "_requires_local_operator_execution", return_value=False), \
             patch.object(brain, "_is_general_planning_request", return_value=False), \
             patch.object(brain, "_stream_cli", side_effect=fake_stream_cli):
            result = await brain.chat(
                "What do you see in this attached image?",
                history=[],
                context_block="",
                backend="cli",
                cli_path="/tmp/claude",
                cli_model="sonnet",
                resource_context="",
                resource_image_paths=["/tmp/example.png"],
                vision_model="",
            )

        self.assertEqual(result["content"], "image ok")
        self.assertEqual(result["tokens"], 0)

    async def test_stream_chat_skips_cli_when_cooldown_is_active(self):
        runtime_key = brain._cli_runtime_key("/tmp/claude")
        cli_pacing._last_cli_cooldown_message_by_key[runtime_key] = "Claude CLI hit a rate limit."
        cli_pacing._last_cli_cooldown_until_by_key[runtime_key] = time.time() + 60

        async def fake_stream_codex_cli(messages, **kwargs):
            self.assertEqual(kwargs["binary"], "/tmp/codex")
            self.assertEqual(kwargs["model"], "gpt-5.4")
            yield "fallback ok"

        with patch.object(brain, "_resolve_selected_cli_binary", return_value="/tmp/claude"), \
             patch.object(brain, "_find_codex_cli", return_value="/tmp/codex"), \
             patch.object(brain, "_stream_codex_cli", side_effect=fake_stream_codex_cli):
            chunks = [
                chunk async for chunk in brain.stream_chat(
                    "hello",
                    history=[],
                    backend="cli",
                    cli_path="/tmp/claude",
                    api_key="key",
                    api_provider="deepseek",
                    api_base_url="https://api.deepseek.com/v1",
                    api_model="deepseek-reasoner",
                )
            ]

        rendered = "".join(chunks).lower()
        self.assertIn("cooling down after a rate limit", rendered)
        self.assertIn("codex cli", rendered)
        self.assertIn("fallback ok", rendered)


class ClaudeCliRuntimeServiceTests(unittest.TestCase):
    @patch.object(claude_cli_runtime.brain, "discover_cli_environments")
    @patch.object(claude_cli_runtime.brain, "_find_cli")
    @patch.object(claude_cli_runtime, "_find_npm_binary")
    @patch.object(claude_cli_runtime, "_cli_version")
    @patch.object(claude_cli_runtime, "_auth_status")
    def test_cli_runtime_snapshot_reports_subscription_auth(
        self,
        auth_status,
        cli_version,
        find_npm_binary,
        find_cli,
        discover_cli_environments,
    ):
        find_cli.return_value = "/tmp/claude"
        find_npm_binary.return_value = "/tmp/npm"
        cli_version.return_value = "2.1.84 (Claude Code)"
        auth_status.return_value = {
            "logged_in": True,
            "auth_method": "claude.ai",
            "subscription_type": "pro",
            "email": "user@example.com",
            "org_id": "",
            "org_name": "",
            "provider_label": "Claude subscription",
            "message": "Claude subscription · pro · user@example.com",
        }
        discover_cli_environments.return_value = [
            {"path": "/tmp/claude", "label": "claude (PATH)", "source": "PATH"}
        ]

        snapshot = claude_cli_runtime.build_cli_runtime_snapshot("")

        self.assertTrue(snapshot["installed"])
        self.assertEqual(snapshot["package_name"], "@anthropic-ai/claude-code")
        self.assertTrue(snapshot["auth"]["logged_in"])
        self.assertEqual(snapshot["auth"]["subscription_type"], "pro")

    @patch.object(claude_cli_runtime.brain, "_find_cli")
    @patch.object(claude_cli_runtime, "_legacy_discover_cli_environments")
    @patch.object(claude_cli_runtime, "_find_npm_binary")
    @patch.object(claude_cli_runtime, "_cli_version")
    @patch.object(claude_cli_runtime, "_auth_status")
    def test_cli_runtime_snapshot_excludes_codex_environments(
        self,
        auth_status,
        cli_version,
        find_npm_binary,
        discover_cli_environments,
        find_cli,
    ):
        find_cli.return_value = "/tmp/claude"
        find_npm_binary.return_value = "/tmp/npm"
        cli_version.return_value = "2.1.88 (Claude Code)"
        auth_status.return_value = {"logged_in": True, "message": "ok"}
        discover_cli_environments.return_value = [
            {"path": "/tmp/claude", "label": "claude (PATH)", "source": "PATH", "family": "claude"},
            {"path": "/tmp/codex", "label": "codex (PATH)", "source": "PATH", "family": "codex"},
        ]

        snapshot = claude_cli_runtime.build_cli_runtime_snapshot("")

        env_paths = [item["path"] for item in snapshot["environments"]]
        self.assertEqual(env_paths, ["/tmp/claude"])

    @patch.object(claude_cli_runtime, "_run_command")
    def test_auth_status_treats_json_logged_out_payload_as_not_signed_in(self, run_command):
        run_command.return_value = subprocess.CompletedProcess(
            args=["/tmp/claude", "auth", "status", "--json"],
            returncode=1,
            stdout='{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}',
            stderr="",
        )

        status = claude_cli_runtime._auth_status("/tmp/claude")

        self.assertFalse(status["logged_in"])
        self.assertEqual(status["provider_label"], "Not signed in")
        self.assertIn("not signed in", status["message"].lower())

    @patch.object(claude_cli_runtime, "build_cli_runtime_snapshot")
    def test_prepare_login_returns_manual_command_for_subscription(self, build_snapshot):
        build_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/claude",
            "install_command": "npm install -g @anthropic-ai/claude-code",
            "status_command": "/tmp/claude auth status --json",
            "auth": {"logged_in": False},
        }

        result = claude_cli_runtime.prepare_claude_cli_login(mode="claudeai", email="user@example.com")

        self.assertEqual(result["status"], "manual_required")
        self.assertIn("auth login --claudeai", result["command_preview"])
        self.assertIn("--email user@example.com", result["command_preview"])

    @patch.object(claude_cli_runtime, "build_cli_runtime_snapshot")
    def test_logout_claude_cli_returns_completed_when_already_signed_out(self, build_snapshot):
        build_snapshot.return_value = {
            "installed": True,
            "status_command": "/tmp/claude auth status --json",
            "auth": {"logged_in": False},
        }

        result = claude_cli_runtime.logout_claude_cli("")

        self.assertEqual(result["status"], "completed")
        self.assertIn("already signed out", result["message"].lower())


class CodexCliRuntimeServiceTests(unittest.TestCase):
    @patch.object(codex_cli_runtime, "_find_codex_cli")
    @patch.object(codex_cli_runtime._shared, "_find_npm_binary")
    @patch.object(codex_cli_runtime, "_codex_version")
    @patch.object(codex_cli_runtime, "_auth_status")
    def test_codex_runtime_snapshot_reports_install_details(self, auth_status, codex_version, find_npm_binary, find_codex_cli):
        find_codex_cli.return_value = "/tmp/codex"
        find_npm_binary.return_value = "/tmp/npm"
        codex_version.return_value = "0.117.0"
        auth_status.return_value = {
            "logged_in": True,
            "auth_method": "chatgpt",
            "provider_label": "ChatGPT",
            "message": "Signed in",
        }

        snapshot = codex_cli_runtime.build_codex_runtime_snapshot()

        self.assertTrue(snapshot["installed"])
        self.assertEqual(snapshot["package_name"], "@openai/codex")
        self.assertEqual(snapshot["binary_name"], "codex")
        self.assertTrue(snapshot["install_available"])

    @patch.object(codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_logout_codex_cli_returns_completed_when_already_signed_out(self, build_snapshot):
        build_snapshot.return_value = {
            "installed": True,
            "status_command": "/tmp/codex login status",
            "auth": {"logged_in": False},
        }

        result = codex_cli_runtime.logout_codex_cli("")

        self.assertEqual(result["status"], "completed")
        self.assertIn("already signed out", result["message"].lower())


class ClaudeCliCommandTests(unittest.TestCase):
    def test_find_cli_ignores_codex_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            override = Path(tmp_dir) / "codex"
            override.write_text("shim")
            override.chmod(0o755)

            with patch.object(brain, "_find_named_cli", return_value="/tmp/claude"):
                resolved = brain._find_cli(str(override))

        self.assertEqual(resolved, "/tmp/claude")

    def test_find_named_cli_prefers_axon_local_binary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            axon_binary = Path(tmp_dir) / "codex"
            axon_binary.write_text("shim")
            axon_binary.chmod(0o755)

            with patch.object(brain.local_tool_env, "axon_binary_path", return_value=axon_binary):
                resolved = brain._find_named_cli("codex")

        self.assertEqual(resolved, str(axon_binary))

    def test_available_cli_models_support_codex_selection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            override = Path(tmp_dir) / "codex"
            override.write_text("shim")
            override.chmod(0o755)

            options = brain.available_cli_models(str(override))

        self.assertEqual(options[0]["label"], "Codex default")
        self.assertEqual({item["id"] for item in options}, {"", "gpt-5.4", "gpt-5.1-codex-max", "gpt-5.1-codex-mini"})

    def test_normalize_cli_model_drops_unsupported_codex_selection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            override = Path(tmp_dir) / "codex"
            override.write_text("shim")
            override.chmod(0o755)

            resolved = brain.normalize_cli_model(str(override), "gpt-5.3-codex")
            allowed = brain.normalize_cli_model(str(override), "gpt-5.4")

        self.assertEqual(resolved, "")
        self.assertEqual(allowed, "gpt-5.4")

    def test_agent_runtime_deps_resolve_selected_codex_binary(self):
        with patch.object(brain, "_resolve_selected_cli_binary", return_value="/tmp/codex"), \
             patch.object(brain, "_find_cli", return_value="/tmp/claude"):
            deps = brain._agent_runtime_deps()

        self.assertEqual(deps.find_cli("/tmp/codex"), "/tmp/codex")

    def test_stream_cli_uses_stateless_mode_by_default(self):
        cmd = brain.build_cli_command("/tmp/claude", model="sonnet", stream_json=True)

        self.assertIn("--no-session-persistence", cmd)
        self.assertIn("--include-partial-messages", cmd)
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "text")

    def test_stream_cli_can_reuse_sessions_when_enabled(self):
        cmd = brain.build_cli_command(
            "/tmp/claude",
            model="sonnet",
            stream_json=True,
            allow_session_persistence=True,
        )

        self.assertNotIn("--no-session-persistence", cmd)
        self.assertIn("--model", cmd)

    def test_codex_exec_command_uses_ephemeral_read_only_mode(self):
        cmd = brain.build_codex_exec_command("/tmp/codex", prompt="Reply with OK", model="gpt-5.1-codex-max", cwd="/tmp/work")

        self.assertIn("--ephemeral", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("read-only", cmd)
        self.assertNotIn("--full-auto", cmd)
        self.assertIn("gpt-5.1-codex-max", cmd)

    def test_codex_exec_command_overrides_reasoning_effort_for_codex_mini(self):
        cmd = brain.build_codex_exec_command(
            "/tmp/codex",
            prompt="Reply with OK",
            model="gpt-5.1-codex-mini",
            cwd="/tmp/work",
        )

        self.assertIn("--model", cmd)
        self.assertIn("gpt-5.1-codex-mini", cmd)
        self.assertIn("-c", cmd)
        self.assertIn('model_reasoning_effort="medium"', cmd)

    def test_codex_exec_command_accepts_workspace_write_mode(self):
        cmd = brain.build_codex_exec_command(
            "/tmp/codex",
            prompt="Reply with OK",
            model="gpt-5.4",
            cwd="/tmp/work",
            sandbox_mode="workspace-write",
        )

        self.assertIn("--full-auto", cmd)
        self.assertNotIn("--sandbox", cmd)

    def test_codex_exec_command_supports_full_access_bypass(self):
        cmd = brain.build_codex_exec_command(
            "/tmp/codex",
            prompt="Reply with OK",
            model="gpt-5.4",
            cwd="/tmp/work",
            sandbox_mode="danger-full-access",
            approval_mode="never",
        )

        self.assertIn("--dangerously-bypass-approvals-and-sandbox", cmd)
        self.assertNotIn("--sandbox", cmd)
        self.assertNotIn("--full-auto", cmd)


class ClaudeCliCooldownGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_cli_falls_back_to_codex_during_cooldown(self):
        async def fake_call_codex(prompt, **kwargs):
            self.assertEqual(kwargs["binary"], "/tmp/codex")
            self.assertEqual(kwargs["model"], "gpt-5.4")
            return "fallback ok", 42

        with patch.object(brain, "_find_cli", return_value="/tmp/claude"), \
             patch.object(brain, "_find_codex_cli", return_value="/tmp/codex"), \
             patch.object(brain, "current_cli_cooldown", return_value={"active": True, "message": "cooling down"}), \
             patch.object(brain, "_call_codex_cli", side_effect=fake_call_codex):
            content, tokens = await brain._call_cli("Reply with OK", system="Do it.")

        self.assertIn("Fell back to Codex CLI", content)
        self.assertIn("fallback ok", content)
        self.assertEqual(tokens, 42)

    async def test_stream_cli_falls_back_to_codex_during_cooldown(self):
        async def fake_stream_codex(messages, **kwargs):
            self.assertEqual(kwargs["binary"], "/tmp/codex")
            self.assertEqual(kwargs["model"], "gpt-5.4")
            yield "fallback "
            yield "stream"

        with patch.object(brain, "_find_cli", return_value="/tmp/claude"), \
             patch.object(brain, "_find_codex_cli", return_value="/tmp/codex"), \
             patch.object(brain, "current_cli_cooldown", return_value={"active": True, "message": "cooling down"}), \
             patch.object(brain, "_stream_codex_cli", side_effect=fake_stream_codex):
            chunks = []
            async for chunk in brain._stream_cli(
                [{"role": "user", "content": "Reply with OK"}],
                model="claude-sonnet-4-6",
            ):
                chunks.append(chunk)

        rendered = "".join(chunks)
        self.assertIn("Falling back to Codex CLI", rendered)
        self.assertIn("fallback stream", rendered)


class ClaudeCliStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_cli_emits_incremental_chunks_from_stream_json(self):
        captured: dict[str, object] = {}

        class FakeStdout:
            def __init__(self, lines):
                self._lines = iter(lines)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._lines)
                except StopIteration as exc:
                    raise StopAsyncIteration from exc

        class FakeStderr:
            async def read(self):
                return b""

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStdout(
                    [
                        (json.dumps({"type": "system", "subtype": "init"}) + "\n").encode("utf-8"),
                        (
                            json.dumps(
                                {
                                    "type": "assistant",
                                    "message": {"content": [{"type": "text", "text": "Planning"}]},
                                }
                            )
                            + "\n"
                        ).encode("utf-8"),
                        (
                            json.dumps(
                                {
                                    "type": "assistant",
                                    "message": {"content": [{"type": "text", "text": "Planning deeper"}]},
                                }
                            )
                            + "\n"
                        ).encode("utf-8"),
                        (
                            json.dumps(
                                {
                                    "type": "result",
                                    "result": "Planning deeper",
                                    "usage": {"input_tokens": 2, "output_tokens": 3},
                                    "total_cost_usd": 1.25,
                                }
                            )
                            + "\n"
                        ).encode("utf-8"),
                    ]
                )
                self.stderr = FakeStderr()
                self.returncode = 0

            def terminate(self):
                self.returncode = -15

            def kill(self):
                self.returncode = -9

            async def wait(self):
                return self.returncode

        async def fake_wait_for_cli_slot(*args, **kwargs):
            return None

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured["limit"] = kwargs.get("limit")
            return FakeProc()

        usage_sink: dict[str, int] = {}
        brain.reset_session_usage()
        try:
            with patch.object(brain, "_resolve_selected_cli_binary", return_value="/tmp/claude"), \
                 patch.object(brain, "current_cli_cooldown", return_value={"active": False}), \
                 patch.object(brain, "wait_for_cli_slot", side_effect=fake_wait_for_cli_slot), \
                 patch.object(brain.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec):
                chunks = [
                    chunk async for chunk in brain._stream_cli(
                        [
                            {"role": "system", "content": "Be helpful."},
                            {"role": "user", "content": "Reply with a short plan."},
                        ],
                        usage_sink=usage_sink,
                    )
                ]
        finally:
            brain.reset_session_usage()

        self.assertEqual("".join(chunks), "Planning deeper")
        self.assertEqual(usage_sink["tokens"], 5)
        self.assertEqual(captured["limit"], brain._CLI_SUBPROCESS_STREAM_LIMIT_BYTES)
        cmd = captured["cmd"]
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "text")

    async def test_stream_codex_cli_filters_runtime_warning_noise(self):
        class FakeStdout:
            def __init__(self, lines):
                self._lines = iter(lines)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._lines)
                except StopIteration as exc:
                    raise StopAsyncIteration from exc

        class FakeStderr:
            async def read(self):
                return b""

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStdout(
                    [
                        (
                            json.dumps(
                                {
                                    "type": "item.completed",
                                    "item": {
                                        "type": "agent_message",
                                        "text": (
                                            "2026-04-10T03:09:41Z WARN codex_core::plugins::manifest: "
                                            "ignoring interface.defaultPrompt\n"
                                            "Reading additional input from stdin...\n"
                                            "Answer ready."
                                        ),
                                    },
                                }
                            )
                            + "\n"
                        ).encode("utf-8"),
                        (
                            json.dumps(
                                {
                                    "type": "turn.completed",
                                    "usage": {"input_tokens": 2, "output_tokens": 3},
                                }
                            )
                            + "\n"
                        ).encode("utf-8"),
                    ]
                )
                self.stderr = FakeStderr()
                self.returncode = 0

            async def wait(self):
                return self.returncode

        async def fake_wait_for_cli_slot(*args, **kwargs):
            return None

        async def fake_create_subprocess_exec(*args, **kwargs):
            return FakeProc()

        with patch.object(brain, "wait_for_cli_slot", side_effect=fake_wait_for_cli_slot), \
             patch.object(brain.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            chunks = [
                chunk async for chunk in brain._stream_codex_cli(
                    [{"role": "user", "content": "Reply with OK."}],
                    binary="/tmp/codex",
                    model="gpt-5.4",
                )
            ]

        self.assertEqual("".join(chunks), "Answer ready.")

    def test_clean_cli_text_filters_timestamped_warning_lines(self):
        raw = (
            "2026-04-10T03:09:41Z WARN codex_core::plugins::manifest: ignoring interface.defaultPrompt\n"
            "Reading additional input from stdin...\n"
            "Answer ready.\n"
        )

        self.assertEqual(brain._clean_cli_text(raw), "Answer ready.")


class RuntimeStatusCliSelectionTests(unittest.TestCase):
    @patch.object(runtime_manager, "active_agents_count", return_value=1)
    @patch.object(runtime_manager, "lifecycle_phases", return_value=[])
    @patch.object(runtime_manager, "registered_agents", return_value=[])
    @patch.object(runtime_manager.gpu_guard, "detect_display_gpu_state", return_value={"warning": "", "connected_outputs": []})
    @patch.object(runtime_manager, "local_model_cards", return_value=[])
    @patch.object(runtime_manager._brain, "discover_cli_environments")
    @patch.object(runtime_manager._brain, "available_cli_models")
    @patch.object(runtime_manager._brain, "_find_codex_cli", return_value="/tmp/codex")
    @patch.object(runtime_manager._claude_cli_runtime, "build_cli_runtime_snapshot")
    @patch.object(runtime_manager._codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_runtime_status_reports_codex_when_selected(
        self,
        build_codex_snapshot,
        build_claude_snapshot,
        _find_codex_cli,
        available_cli_models,
        discover_cli_environments,
        _local_model_cards,
        _detect_display_gpu_state,
        _registered_agents,
        _lifecycle_phases,
        _active_agents_count,
    ):
        build_claude_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/claude",
            "selected_environment": {"path": "/tmp/claude", "family": "claude"},
        }
        build_codex_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/codex",
            "selected_environment": {"path": "/tmp/codex", "family": "codex"},
        }
        discover_cli_environments.return_value = [
            {"path": "/tmp/claude", "label": "claude", "family": "claude"},
            {"path": "/tmp/codex", "label": "codex", "family": "codex"},
        ]
        available_cli_models.return_value = [{"id": "", "label": "Codex default"}]

        status = runtime_manager.build_runtime_status(
            settings={
                "ai_backend": "cli",
                "claude_cli_path": "/tmp/codex",
                "claude_cli_model": "",
            },
            available_models=[],
            ollama_running=False,
            vault_unlocked=False,
            workspace_count=1,
            usage={"calls": 0},
            resource_count=0,
            memory_overview={"total": 0, "layers": {}, "labels": {}},
        )

        self.assertEqual(status["runtime_label"], "Codex CLI")
        self.assertEqual(status["cli_runtime"]["runtime_id"], "codex")
        self.assertEqual(status["cli_binary"], "/tmp/codex")
        self.assertEqual({env["family"] for env in status["cli_environments"]}, {"claude", "codex"})

    @patch.object(runtime_manager, "active_agents_count", return_value=1)
    @patch.object(runtime_manager, "lifecycle_phases", return_value=[])
    @patch.object(runtime_manager, "registered_agents", return_value=[])
    @patch.object(runtime_manager.gpu_guard, "detect_display_gpu_state", return_value={"warning": "", "connected_outputs": []})
    @patch.object(runtime_manager, "local_model_cards", return_value=[])
    @patch.object(runtime_manager._brain, "discover_cli_environments")
    @patch.object(runtime_manager._brain, "available_cli_models")
    @patch.object(runtime_manager._brain, "_find_codex_cli", return_value="/tmp/codex")
    @patch.object(runtime_manager._brain, "normalize_cli_model")
    @patch.object(runtime_manager._claude_cli_runtime, "build_cli_runtime_snapshot")
    @patch.object(runtime_manager._codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_runtime_status_auto_selects_codex_family_for_codex_model_without_path(
        self,
        build_codex_snapshot,
        build_claude_snapshot,
        normalize_cli_model,
        _find_codex_cli,
        available_cli_models,
        discover_cli_environments,
        _local_model_cards,
        _detect_display_gpu_state,
        _registered_agents,
        _lifecycle_phases,
        _active_agents_count,
    ):
        build_claude_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/claude",
            "selected_environment": {"path": "/tmp/claude", "family": "claude"},
        }
        build_codex_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/codex",
            "selected_environment": {"path": "/tmp/codex", "family": "codex"},
        }
        discover_cli_environments.return_value = [
            {"path": "/tmp/claude", "label": "claude", "family": "claude"},
            {"path": "/tmp/codex", "label": "codex", "family": "codex"},
        ]
        available_cli_models.return_value = [{"id": "gpt-5.4", "label": "gpt-5.4"}]
        normalize_cli_model.side_effect = lambda cli_path, model: model if "codex" in str(cli_path) else ""

        status = runtime_manager.build_runtime_status(
            settings={
                "ai_backend": "cli",
                "cli_runtime_model": "gpt-5.4",
            },
            available_models=[],
            ollama_running=False,
            vault_unlocked=False,
            workspace_count=1,
            usage={"calls": 0},
            resource_count=0,
            memory_overview={"total": 0, "layers": {}, "labels": {}},
        )

        self.assertEqual(status["runtime_label"], "Codex CLI")
        self.assertEqual(status["cli_runtime"]["runtime_id"], "codex")
        self.assertEqual(status["cli_binary"], "/tmp/codex")
        self.assertEqual(status["cli_model"], "gpt-5.4")

    @patch.object(runtime_manager, "active_agents_count", return_value=1)
    @patch.object(runtime_manager, "lifecycle_phases", return_value=[])
    @patch.object(runtime_manager, "registered_agents", return_value=[])
    @patch.object(runtime_manager.gpu_guard, "detect_display_gpu_state", return_value={"warning": "", "connected_outputs": []})
    @patch.object(runtime_manager, "local_model_cards", return_value=[])
    @patch.object(runtime_manager._brain, "discover_cli_environments")
    @patch.object(runtime_manager._brain, "available_cli_models")
    @patch.object(runtime_manager._brain, "_find_codex_cli", return_value="/tmp/codex")
    @patch.object(runtime_manager._brain, "normalize_cli_model")
    @patch.object(runtime_manager._claude_cli_runtime, "build_cli_runtime_snapshot")
    @patch.object(runtime_manager._codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_runtime_status_normalizes_invalid_codex_model(
        self,
        build_codex_snapshot,
        build_claude_snapshot,
        normalize_cli_model,
        _find_codex_cli,
        available_cli_models,
        discover_cli_environments,
        _local_model_cards,
        _detect_display_gpu_state,
        _registered_agents,
        _lifecycle_phases,
        _active_agents_count,
    ):
        build_claude_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/claude",
            "selected_environment": {"path": "/tmp/claude", "family": "claude"},
        }
        build_codex_snapshot.return_value = {
            "installed": True,
            "binary": "/tmp/codex",
            "selected_environment": {"path": "/tmp/codex", "family": "codex"},
        }
        discover_cli_environments.return_value = [
            {"path": "/tmp/claude", "label": "claude", "family": "claude"},
            {"path": "/tmp/codex", "label": "codex", "family": "codex"},
        ]
        available_cli_models.return_value = [{"id": "", "label": "Codex default"}]
        normalize_cli_model.return_value = ""

        status = runtime_manager.build_runtime_status(
            settings={
                "ai_backend": "cli",
                "claude_cli_path": "/tmp/codex",
                "claude_cli_model": "gpt-5.4",
            },
            available_models=[],
            ollama_running=False,
            vault_unlocked=False,
            workspace_count=1,
            usage={"calls": 0},
            resource_count=0,
            memory_overview={"total": 0, "layers": {}, "labels": {}},
        )

        self.assertEqual(status["cli_model"], "")
        self.assertEqual(status["active_model"], "Codex default")


class ClaudeCliPacingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cli_pacing._next_cli_start_at_by_key.clear()

    async def test_cli_launches_are_spaced(self):
        first_wait = await cli_pacing.wait_for_cli_slot(0.02)
        started = time.monotonic()
        second_wait = await cli_pacing.wait_for_cli_slot(0.02)
        elapsed = time.monotonic() - started

        self.assertEqual(first_wait, 0.0)
        self.assertGreaterEqual(second_wait, 0.0)
        self.assertGreaterEqual(elapsed, 0.015)

    async def test_rate_limit_extends_cooldown(self):
        await cli_pacing.wait_for_cli_slot(0.0)
        await cli_pacing.extend_cli_cooldown(0.02)

        started = time.monotonic()
        await cli_pacing.wait_for_cli_slot(0.0)
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.015)

    async def test_codex_pacing_is_isolated_from_claude(self):
        await cli_pacing.wait_for_cli_slot(0.03, key="claude")

        started = time.monotonic()
        await cli_pacing.wait_for_cli_slot(0.0, key="codex")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.01)


class ShellAllowlistTests(unittest.TestCase):
    def test_common_bash_commands_are_allowlisted(self):
        allowed = brain._effective_allowed_cmds()

        self.assertIn('bash', allowed)
        self.assertIn('sh', allowed)
        self.assertIn('zsh', allowed)
        self.assertIn('rg', allowed)


class AgentPromptRegressionTests(unittest.TestCase):
    def test_self_improvement_prompt_uses_cwd_instead_of_cd_wrapper(self):
        prompt = agent_prompts._build_react_system("", "Axon", ["shell_cmd", "read_file"])

        self.assertIn('`cwd` to "~/.devbrain"', prompt)
        self.assertIn("Never wrap shell commands with `cd ... && ...`", prompt)
        self.assertNotIn('cd ~/.devbrain &&', prompt)
        self.assertIn("Document Operator Patterns", prompt)
        self.assertIn("Visual Document Patterns", prompt)
        self.assertIn("Treat the request as document design first", prompt)
        self.assertIn("official or public-primary sources", prompt)
        self.assertIn("30-60-90 day execution sequence", prompt)


class SubagentGuardTests(unittest.TestCase):
    def test_nested_spawn_tool_is_removed_from_subagent_runtime(self):
        deps = brain._agent_runtime_deps(exclude_tools={'spawn_subagent'})

        self.assertNotIn('spawn_subagent', deps.tool_registry)
        self.assertIn('shell_cmd', deps.tool_registry)

    def test_spawn_subagent_inherits_parent_runtime_context(self):
        captured = {}

        async def fake_run_agent(task, history, **kwargs):
            captured.update(kwargs)
            yield {"type": "text", "chunk": "done"}

        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set({
            "backend": "cli",
            "workspace_path": "/tmp/workspace",
            "cli_path": "/tmp/codex",
            "cli_model": "",
            "project_name": "Demo",
        })
        try:
            with patch.object(brain, "run_agent", side_effect=fake_run_agent), \
                 patch.object(brain, "_run_async_from_sync", side_effect=lambda coro: asyncio.run(coro)):
                result = brain._tool_spawn_subagent("inspect the repo")
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)

        self.assertIn("done", result)
        self.assertEqual(captured["backend"], "cli")
        self.assertEqual(captured["workspace_path"], "/tmp/workspace")
        self.assertEqual(captured["cli_path"], "/tmp/codex")
        self.assertEqual(captured["project_name"], "Demo")


class MemorySyncRegressionTests(unittest.TestCase):
    def test_sanitize_memory_refs_clears_stale_foreign_keys(self):
        item = {
            "memory_key": "mission:task:99",
            "layer": "mission",
            "title": "Broken task",
            "content": "Task linked to stale records",
            "summary": "Task linked to stale records",
            "source": "mission_task",
            "source_id": "99",
            "workspace_id": 404,
            "mission_id": 505,
            "trust_level": "high",
            "relevance_score": 0.8,
            "meta_json": "{}",
        }

        sanitized = memory_engine._sanitize_memory_refs(
            item,
            valid_workspace_ids={1, 2, 3},
            valid_mission_ids={7, 8, 9},
        )

        self.assertIsNone(sanitized["workspace_id"])
        self.assertIsNone(sanitized["mission_id"])


class RuntimeStateRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_compute_workspace_revision_supports_sqlite_row_results(self):
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row

            conn.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, created_at TEXT, updated_at TEXT)",
            )
            conn.execute(
                "CREATE TABLE prompts (project_id INTEGER, created_at TEXT, updated_at TEXT)",
            )
            conn.execute(
                "CREATE TABLE tasks (project_id INTEGER, created_at TEXT, updated_at TEXT)",
            )
            conn.execute(
                "CREATE TABLE resources (workspace_id INTEGER, created_at TEXT, updated_at TEXT)",
            )
            conn.execute(
                "CREATE TABLE memory_items (workspace_id INTEGER, created_at TEXT, updated_at TEXT)",
            )
            conn.execute(
                "INSERT INTO projects (id, created_at, updated_at) VALUES (1, '2026-04-03T08:00:00Z', '2026-04-03T09:00:00Z')",
            )
            conn.commit()

            class AsyncSqliteCompat:
                def __init__(self, db_conn):
                    self._conn = db_conn

                class _CursorCompat:
                    def __init__(self, row):
                        self._row = row

                    async def fetchone(self):
                        return self._row

                async def execute(self, sql, params=()):
                    row = self._conn.execute(sql, params).fetchone()
                    return self._CursorCompat(row)

            revision = await runtime_state.compute_workspace_revision(AsyncSqliteCompat(conn), 1)

        self.assertEqual(len(revision), 40)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in revision))


class TerminalRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_terminal_cwd_accepts_sqlite_row(self):
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            safe_cwd = str(Path.home() / ".devbrain")
            row = conn.execute("SELECT ? AS cwd, 0 AS workspace_id", (safe_cwd,)).fetchone()

            resolved = await server._resolve_terminal_cwd(None, row)

        self.assertEqual(str(resolved), safe_cwd)

    async def test_terminal_blocks_system_package_manager_installs(self):
        self.assertTrue(server._command_is_blocked("apt install ripgrep"))
        self.assertTrue(server._command_is_blocked("brew install fd"))
        self.assertFalse(server._command_is_blocked("pip install rich"))


class SessionStoreRegressionTests(unittest.TestCase):
    def setUp(self):
        session_store_module._MEMORY_FALLBACK_SESSIONS.clear()

    def test_get_interrupted_skips_stale_paused_sessions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / 'sessions.db')
            stale_updated_at = time.time() - (14 * 3600)
            recent_updated_at = time.time() - (30 * 60)

            with store._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_sessions (
                        session_id, task, messages, iteration, tool_log, status,
                        project_name, backend, created_at, updated_at, metadata
                    ) VALUES (?, ?, '[]', ?, '[]', ?, ?, ?, ?, ?, '{}')
                    """,
                    (
                        'stale-paused',
                        'Old paused task',
                        1,
                        'approval_required',
                        'Axon',
                        'api',
                        stale_updated_at,
                        stale_updated_at,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO agent_sessions (
                        session_id, task, messages, iteration, tool_log, status,
                        project_name, backend, created_at, updated_at, metadata
                    ) VALUES (?, ?, '[]', ?, '[]', ?, ?, ?, ?, ?, '{}')
                    """,
                    (
                        'recent-active',
                        'Recent active task',
                        0,
                        'active',
                        'Axon',
                        'cli',
                        recent_updated_at,
                        recent_updated_at,
                    ),
                )
                conn.commit()

            session = store.get_interrupted()

            self.assertIsNotNone(session)
            self.assertEqual(session.session_id, 'recent-active')

    def test_get_interrupted_prefers_current_workspace_before_newer_foreign_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / 'sessions.db')
            now = time.time()

            store.save(
                session_id='foreign-newer',
                task='Foreign workspace task',
                messages=[],
                iteration=2,
                tool_log=[{'name': 'read_file'}],
                status='interrupted',
                project_name='Other',
                backend='api',
                metadata={'workspace_id': 999, 'workspace_path': '/tmp/other'},
            )
            store.save(
                session_id='local-older',
                task='Current workspace task',
                messages=[],
                iteration=1,
                tool_log=[{'name': 'read_file'}],
                status='approval_required',
                project_name='Axon',
                backend='cli',
                metadata={'workspace_id': 202, 'workspace_path': '/tmp/current'},
            )
            with store._connect() as conn:
                conn.execute("UPDATE agent_sessions SET updated_at=? WHERE session_id=?", (now - 10, 'foreign-newer'))
                conn.execute("UPDATE agent_sessions SET updated_at=? WHERE session_id=?", (now - 120, 'local-older'))
                conn.commit()

            session = store.get_interrupted(workspace_id=202, workspace_path='/tmp/current', project_name='Axon')

            self.assertIsNotNone(session)
            self.assertEqual(session.session_id, 'local-older')

    def test_get_interrupted_strict_workspace_hides_foreign_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore(Path(tmp_dir) / 'sessions.db')
            store.save(
                session_id='foreign-only',
                task='Foreign workspace task',
                messages=[],
                iteration=2,
                tool_log=[{'name': 'read_file'}],
                status='approval_required',
                project_name='dashpro',
                backend='cli',
                metadata={'workspace_id': 2, 'workspace_path': '/tmp/dashpro'},
            )

            session = store.get_interrupted(
                workspace_id=173,
                workspace_path='/tmp/axon',
                project_name='Axon',
                strict_workspace=True,
            )

            self.assertIsNone(session)


class InterruptedSessionEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        session_store_module._MEMORY_FALLBACK_SESSIONS.clear()

    async def test_endpoint_returns_last_assistant_and_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'sessions.db'
            store = SessionStore(db_path)
            store.save(
                session_id='session-1',
                task='Check the workspace',
                messages=[
                    {'role': 'user', 'content': 'Check the workspace'},
                    {'role': 'assistant', 'content': '⚠️ Agent error: Claude CLI hit a rate limit.'},
                ],
                iteration=3,
                tool_log=[{'name': 'read_file'}],
                status='interrupted',
                project_name='Axon',
                backend='cli',
                metadata={'error_message': 'Claude CLI hit a rate limit.'},
            )

            with patch.object(server.devdb, 'DB_PATH', db_path):
                payload = await server.get_interrupted_session()

            self.assertEqual(payload['session']['status'], 'interrupted')
            self.assertIn('rate limit', payload['session']['last_assistant_message'].lower())
            self.assertIn('rate limit', payload['session']['error_message'].lower())
            self.assertEqual(payload['session']['resume_target'], 'session-1')

    async def test_endpoint_with_project_id_does_not_leak_foreign_workspace_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / 'sessions.db'
            store = SessionStore(db_path)
            store.save(
                session_id='foreign-dashpro',
                task='Remove accidental root files',
                messages=[{'role': 'assistant', 'content': 'Approval required before Axon can delete /home/edp/Desktop/dashpro/lib/__tests__/popUpload.test.ts'}],
                iteration=2,
                tool_log=[{'name': 'delete_file'}],
                status='approval_required',
                project_name='dashpro',
                backend='cli',
                metadata={'workspace_id': 2, 'workspace_path': '/home/edp/Desktop/dashpro'},
            )

            @asynccontextmanager
            async def fake_db():
                class _Conn:
                    pass
                yield _Conn()

            with patch.object(server.devdb, 'DB_PATH', db_path), \
                 patch.object(server.devdb, 'get_db', fake_db), \
                 patch.object(server.devdb, 'get_project', return_value={'id': 173, 'name': 'Axon', 'path': '/home/edp/.devbrain'}):
                payload = await server.get_interrupted_session(project_id=173)

            self.assertEqual(payload, {'session': None})


class AgentCliIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_mode_forces_stateless_cli_streams(self):
        captured = []

        async def fake_stream_cli(messages, **kwargs):
            captured.append(kwargs.get('allow_session_persistence'))
            yield 'hello'

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ''

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ''

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=Path(tempfile.gettempdir()) / 'axon-agent-test.db',
        )

        events = []
        async for event in core_agent.run_agent(
            'hello there',
            [],
            deps=deps,
            backend='cli',
            cli_path='/tmp/claude',
            cli_session_persistence=True,
        ):
            events.append(event)

        self.assertTrue(events)
        self.assertEqual(captured, [False])

    async def test_resume_session_without_verified_tools_restarts_saved_task(self):
        db_path = Path(tempfile.gettempdir()) / 'axon-agent-resume.db'
        if db_path.exists():
            db_path.unlink()
        store = SessionStore(db_path)
        store.save(
            session_id='resume-me',
            task='Inspect the repo root',
            messages=[{'role': 'user', 'content': 'Inspect the repo root'}],
            iteration=0,
            tool_log=[],
            status='interrupted',
            project_name='Axon',
            backend='cli',
            metadata={'workspace_id': 202, 'workspace_path': '/tmp/current'},
        )
        captured_messages = []

        async def fake_stream_cli(messages, **kwargs):
            captured_messages.extend(messages)
            yield 'ANSWER: done'

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ''

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ''

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=db_path,
        )

        events = [
            event async for event in core_agent.run_agent(
                'please continue',
                [],
                deps=deps,
                backend='cli',
                cli_path='/tmp/claude',
                workspace_id=202,
                workspace_path='/tmp/current',
                resume_session_id='resume-me',
                resume_reason='resume_banner',
            )
        ]

        text = ''.join(event.get('chunk', '') for event in events if event.get('type') == 'text')
        self.assertIn('restarting that task cleanly', text.lower())
        self.assertTrue(any(msg.get('content') == 'Inspect the repo root' for msg in captured_messages))

    async def test_explicit_continue_without_paused_session_uses_latest_task_hint(self):
        db_path = Path(tempfile.gettempdir()) / 'axon-agent-continue-fallback.db'
        if db_path.exists():
            db_path.unlink()
        captured_messages = []

        async def fake_stream_cli(messages, **kwargs):
            captured_messages.extend(messages)
            yield 'ANSWER: done'

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ''

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ''

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=db_path,
        )

        events = [
            event async for event in core_agent.run_agent(
                'please continue',
                [],
                deps=deps,
                backend='cli',
                cli_path='/tmp/claude',
                workspace_id=202,
                workspace_path='/tmp/current',
                continue_task='Continue working on the Axon website in the current workspace.',
                resume_reason='typed_continue:last_user',
            )
        ]

        text = ''.join(event.get('chunk', '') for event in events if event.get('type') == 'text')
        self.assertIn('latest concrete task', text.lower())
        self.assertTrue(any(
            msg.get('content') == 'Continue working on the Axon website in the current workspace.'
            for msg in captured_messages
        ))

    async def test_agent_cli_rate_limit_falls_back_to_api(self):
        async def fake_stream_cli(messages, **kwargs):
            raise RuntimeError("Claude CLI hit a rate limit.")
            yield ""

        async def fake_stream_api_chat(**kwargs):
            yield "ANSWER: fallback ok"

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=Path(tempfile.gettempdir()) / 'axon-agent-test.db',
        )

        events = []
        async for event in core_agent.run_agent(
            'hello there',
            [],
            deps=deps,
            backend='cli',
            cli_path='/tmp/claude',
            api_key='key',
            api_base_url='https://api.deepseek.com/v1',
            api_provider='deepseek',
            api_model='deepseek-reasoner',
        ):
            events.append(event)

        self.assertTrue(any('switching this' in str(event.get('chunk', '')).lower() and 'deepseek' in str(event.get('chunk', '')).lower() for event in events if event.get('type') in {'thinking', 'text'}))
        self.assertTrue(any(event.get('type') == 'text' and 'fallback ok' in str(event.get('chunk', '')) for event in events))

    async def test_agent_cli_rate_limit_forwards_api_provider_to_fallback_stream(self):
        captured = {}

        async def fake_stream_cli(messages, **kwargs):
            raise RuntimeError("Claude CLI hit a rate limit.")
            yield ""

        async def fake_stream_api_chat(**kwargs):
            captured.update(kwargs)
            yield "ANSWER: anthropic fallback ok"

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=Path(tempfile.gettempdir()) / 'axon-agent-test.db',
        )

        events = []
        async for event in core_agent.run_agent(
            'hello there',
            [],
            deps=deps,
            backend='cli',
            cli_path='/tmp/claude',
            api_key='key',
            api_base_url='https://api.anthropic.com/v1',
            api_provider='anthropic',
            api_model='claude-sonnet-4-5',
        ):
            events.append(event)

        self.assertEqual(captured["api_provider"], "anthropic")
        self.assertTrue(any(event.get('type') == 'text' and 'anthropic fallback ok' in str(event.get('chunk', '')) for event in events))

    async def test_blocked_cd_shell_command_is_repaired_with_cwd(self):
        prompts = []
        model_responses = iter([
            'ACTION: shell_cmd\nARGS: {"cmd": "cd /tmp/work && .venv/bin/python -m py_compile brain.py"}',
            'ACTION: shell_cmd\nARGS: {"cmd": ".venv/bin/python -m py_compile brain.py", "cwd": "/tmp/work"}',
            'ANSWER: verification complete',
        ])

        async def fake_stream_ollama_chat(messages, **kwargs):
            prompts.append(messages[-1]["content"])
            yield next(model_responses)

        async def fake_stream_cli(**kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        def fake_shell_cmd(cmd: str, cwd: str = "", timeout: int = 30) -> str:
            if cmd.startswith("cd "):
                return f"BLOCKED_CMD:cd:{cmd}"
            return f"OK cwd={cwd} cmd={cmd}"

        deps = AgentRuntimeDeps(
            tool_registry={"shell_cmd": fake_shell_cmd},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {'model': 'dummy'},
            ollama_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            api_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            cli_message_with_images=lambda text, images: {'role': 'user', 'content': text},
            find_cli=lambda path: '/tmp/claude',
            ollama_default_model='dummy',
            ollama_agent_model='dummy',
            db_path=Path(tempfile.gettempdir()) / 'axon-agent-test.db',
        )

        events = [
            event async for event in core_agent.run_agent(
                'Verify the project.',
                [],
                deps=deps,
                backend='ollama',
                force_tool_mode=True,
            )
        ]

        self.assertFalse(any(event.get('type') == 'approval_required' for event in events))
        self.assertTrue(any(event.get('type') == 'thinking' and 'use `cwd`' in str(event.get('chunk', '')) for event in events))
        self.assertEqual(
            [event.get('args') for event in events if event.get('type') == 'tool_call'],
            [
                {'cmd': 'cd /tmp/work && .venv/bin/python -m py_compile brain.py'},
                {'cmd': '.venv/bin/python -m py_compile brain.py', 'cwd': '/tmp/work'},
            ],
        )
        self.assertTrue(any(event.get('type') == 'text' and 'verification complete' in str(event.get('chunk', '')) for event in events))
        self.assertIn("do not allow `cd ... && ...` wrappers", prompts[1])
        self.assertIn('"cwd": "/tmp/work"', prompts[1])

    async def test_stream_codex_cli_uses_workspace_write_mode(self):
        captured = {}

        def fake_build(binary, *, prompt, model="", cwd="", sandbox_mode="read-only", approval_mode="on-request"):
            captured["binary"] = binary
            captured["model"] = model
            captured["cwd"] = cwd
            captured["sandbox_mode"] = sandbox_mode
            captured["approval_mode"] = approval_mode
            raise RuntimeError("sentinel")

        with patch.object(brain, "build_codex_exec_command", side_effect=fake_build):
            with self.assertRaises(RuntimeError) as exc:
                async for _ in brain._stream_codex_cli(
                    [{"role": "user", "content": "Reply with OK."}],
                    binary="/tmp/codex",
                    model="gpt-5.4",
                ):
                    pass

        self.assertEqual(str(exc.exception), "sentinel")
        self.assertEqual(captured["sandbox_mode"], "workspace-write")
        self.assertEqual(captured["approval_mode"], "on-request")

    async def test_stream_codex_cli_uses_full_access_runtime_mode(self):
        captured = {}

        def fake_build(binary, *, prompt, model="", cwd="", sandbox_mode="read-only", approval_mode="on-request"):
            captured["binary"] = binary
            captured["model"] = model
            captured["cwd"] = cwd
            captured["sandbox_mode"] = sandbox_mode
            captured["approval_mode"] = approval_mode
            raise RuntimeError("sentinel")

        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set({
            "runtime_permissions_mode": "full_access",
            "autonomy_profile": "workspace_auto",
        })
        try:
            with patch.object(brain, "build_codex_exec_command", side_effect=fake_build):
                with self.assertRaises(RuntimeError) as exc:
                    async for _ in brain._stream_codex_cli(
                        [{"role": "user", "content": "Reply with OK."}],
                        binary="/tmp/codex",
                        model="gpt-5.4",
                    ):
                        pass
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)

        self.assertEqual(str(exc.exception), "sentinel")
        self.assertEqual(captured["sandbox_mode"], "danger-full-access")
        self.assertEqual(captured["approval_mode"], "never")

    async def test_stream_codex_cli_recovers_from_chunk_limit(self):
        captured = {}

        class FakeStdout:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise asyncio.LimitOverrunError(
                    "Separator is found, but chunk is longer than limit",
                    131072,
                )

        class FakeStderr:
            async def read(self):
                return b""

        class FakeProc:
            def __init__(self):
                self.stdout = FakeStdout()
                self.stderr = FakeStderr()
                self.returncode = 0

            def terminate(self):
                self.returncode = -15

            def kill(self):
                self.returncode = -9

            async def wait(self):
                return self.returncode

        async def fake_wait_for_cli_slot(*args, **kwargs):
            return None

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured["limit"] = kwargs.get("limit")
            return FakeProc()

        async def fake_call_codex_exec_prompt(prompt, **kwargs):
            captured["replay_sandbox_mode"] = kwargs.get("sandbox_mode")
            return "Recovered reply", 17

        with patch.object(brain, "wait_for_cli_slot", side_effect=fake_wait_for_cli_slot), \
             patch.object(brain.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec), \
             patch.object(brain, "_call_codex_exec_prompt", side_effect=fake_call_codex_exec_prompt):
            chunks = [
                chunk async for chunk in brain._stream_codex_cli(
                    [{"role": "user", "content": "Reply with OK."}],
                    binary="/tmp/codex",
                    model="gpt-5.4",
                )
            ]

        self.assertEqual("".join(chunks), "Recovered reply")
        self.assertEqual(captured["replay_sandbox_mode"], "workspace-write")
        self.assertEqual(captured["limit"], brain._CLI_SUBPROCESS_STREAM_LIMIT_BYTES)

    async def test_call_codex_exec_prompt_uses_large_subprocess_limit(self):
        captured = {}

        class FakeProc:
            def __init__(self):
                self.returncode = 0

            async def communicate(self):
                payload = "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "item.completed",
                                "item": {"type": "agent_message", "text": "OK"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "usage": {"input_tokens": 1, "output_tokens": 2},
                            }
                        ),
                    ]
                )
                return payload.encode("utf-8"), b""

            def terminate(self):
                self.returncode = -15

            def kill(self):
                self.returncode = -9

            async def wait(self):
                return self.returncode

        async def fake_wait_for_cli_slot(*args, **kwargs):
            return None

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            captured["limit"] = kwargs.get("limit")
            return FakeProc()

        with patch.object(brain, "wait_for_cli_slot", side_effect=fake_wait_for_cli_slot), \
             patch.object(brain.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            text, tokens = await brain._call_codex_exec_prompt(
                "Reply with OK.",
                binary="/tmp/codex",
                model="gpt-5.4",
                sandbox_mode="read-only",
            )

        self.assertEqual(text, "OK")
        self.assertEqual(tokens, 3)
        self.assertEqual(captured["limit"], brain._CLI_SUBPROCESS_STREAM_LIMIT_BYTES)


class BrainAgentWrapperFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cli_pacing._next_cli_start_at_by_key.clear()
        cli_pacing._last_cli_cooldown_message_by_key.clear()
        cli_pacing._last_cli_cooldown_until_by_key.clear()

    async def asyncTearDown(self):
        cli_pacing._next_cli_start_at_by_key.clear()
        cli_pacing._last_cli_cooldown_message_by_key.clear()
        cli_pacing._last_cli_cooldown_until_by_key.clear()

    async def test_wrapper_reroutes_cli_when_cooldown_is_active(self):
        runtime_key = brain._cli_runtime_key("/tmp/claude")
        cli_pacing._last_cli_cooldown_message_by_key[runtime_key] = "Claude CLI hit a rate limit."
        cli_pacing._last_cli_cooldown_until_by_key[runtime_key] = time.time() + 60
        seen = {}

        async def fake_run_agent_core(user_message, history, **kwargs):
            seen["backend"] = kwargs.get("backend")
            yield {"type": "done", "iterations": 0}

        with patch.object(brain, "_resolve_selected_cli_binary", return_value="/tmp/claude"), \
             patch.object(brain, "_find_codex_cli", return_value="/tmp/codex"), \
             patch.object(brain, "_run_agent_core", side_effect=fake_run_agent_core):
            events = [
                event async for event in brain.run_agent(
                    "continue",
                    [],
                    backend="cli",
                    cli_path="/tmp/claude",
                    api_key="key",
                    api_provider="deepseek",
                    api_base_url="https://api.deepseek.com/v1",
                    api_model="deepseek-reasoner",
                )
            ]

        self.assertEqual(seen["backend"], "cli")
        self.assertTrue(any(event.get("type") == "text" and "cooling down after a rate limit" in str(event.get("chunk", "")).lower() for event in events))

    async def test_extracted_core_accepts_external_fetch_policy(self):
        async def fake_stream_cli(messages, **kwargs):
            yield "ANSWER: done"

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: "/tmp/codex",
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-external-fetch.db",
        )

        events = [
            event async for event in core_agent.run_agent(
                "inspect the repo",
                [],
                deps=deps,
                backend="cli",
                cli_path="/tmp/codex",
                cli_model="gpt-5.4",
                workspace_path="/tmp/axon-workspace",
                external_fetch_policy="cache_first",
            )
        ]

        self.assertTrue(any(event.get("type") == "done" for event in events))


class AgentAutonomyRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_mutating_requests_use_direct_file_shortcuts(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: "/tmp/codex",
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        blocked_result = "BLOCKED_EDIT:write:/tmp/AXON_AUTONOMY_PROBE.txt"

        with patch.object(
            core_agent,
            "_direct_agent_action",
            return_value=(
                "write_file",
                {"path": "/tmp/AXON_AUTONOMY_PROBE.txt", "content": "OK"},
                blocked_result,
                blocked_result,
            ),
        ):
            events = [
                event async for event in core_agent.run_agent(
                    "Create a file named AXON_AUTONOMY_PROBE.txt in the workspace root containing exactly OK.",
                    [],
                    deps=deps,
                    backend="cli",
                    cli_path="/tmp/codex",
                    cli_model="gpt-5.4",
                    workspace_path="/tmp/axon-autonomy-workspace",
                )
            ]

        self.assertEqual(
            [event.get("type") for event in events],
            ["tool_call", "tool_result", "approval_required"],
        )
        self.assertEqual(events[0].get("name"), "write_file")
        self.assertEqual(events[1].get("result"), blocked_result)
        self.assertEqual(events[2].get("kind"), "edit")

    def test_direct_action_captures_absolute_tmp_write_and_blocks_it(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={
                "create_file": brain._TOOL_REGISTRY["create_file"],
                "write_file": brain._TOOL_REGISTRY["write_file"],
            },
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: "/tmp/codex",
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-direct-tmp",
            }
        )
        try:
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    result = agent_file_actions._direct_agent_action(
                        "Create the file /tmp/AXON_DIRECT_TMP_PROBE.txt containing exactly DEFAULT_GATE_PROBE, then reply with done.",
                        history=[],
                        project_name="Axon",
                        workspace_path=tmpdir,
                        deps=deps,
                    )
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "create_file")
        self.assertEqual(tool_args["path"], "/tmp/AXON_DIRECT_TMP_PROBE.txt")
        self.assertEqual(tool_args["content"], "DEFAULT_GATE_PROBE")
        self.assertTrue(tool_result.startswith("BLOCKED_EDIT:create:/tmp/AXON_DIRECT_TMP_PROBE.txt"))

    def test_direct_action_prefers_workspace_root_named_file(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        with tempfile.TemporaryDirectory() as tmpdir:
            created: dict[str, str] = {}

            def fake_create_file(path: str, content: str = "") -> str:
                created["path"] = path
                created["content"] = content
                Path(path).write_text(content, encoding="utf-8")
                return "OK"

            deps = AgentRuntimeDeps(
                tool_registry={"create_file": fake_create_file},
                normalize_tool_args=lambda name, args: args,
                stream_cli=fake_stream_cli,
                stream_api_chat=fake_stream_api_chat,
                stream_ollama_chat=fake_stream_ollama_chat,
                ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
                ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
                api_message_with_images=lambda text, images: {"role": "user", "content": text},
                cli_message_with_images=lambda text, images: {"role": "user", "content": text},
                find_cli=lambda path: path,
                ollama_default_model="dummy",
                ollama_agent_model="dummy",
                db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
            )

            result = agent_file_actions._direct_agent_action(
                'Create a file named AXON_AUTONOMY_PROBE.txt in the workspace root containing exactly "OK".',
                history=[{"role": "assistant", "content": "Earlier we inspected /home/edp/.devbrain/server.py"}],
                project_name="axon-online",
                workspace_path=tmpdir,
                deps=deps,
            )

            self.assertIsNotNone(result)
            tool_name, tool_args, tool_result, answer = result
            expected_path = os.path.join(tmpdir, "AXON_AUTONOMY_PROBE.txt")
            self.assertEqual(tool_name, "create_file")
            self.assertEqual(tool_args["path"], expected_path)
            self.assertEqual(created["path"], expected_path)
            self.assertIn("OK", created["content"])
            self.assertEqual(tool_result, "OK")
            self.assertIn(expected_path, answer)

    def test_direct_action_strips_sentence_punctuation_from_single_word_content(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        with tempfile.TemporaryDirectory() as tmpdir:
            created: dict[str, str] = {}

            def fake_create_file(path: str, content: str = "") -> str:
                created["content"] = content
                Path(path).write_text(content, encoding="utf-8")
                return "OK"

            deps = AgentRuntimeDeps(
                tool_registry={"create_file": fake_create_file},
                normalize_tool_args=lambda name, args: args,
                stream_cli=fake_stream_cli,
                stream_api_chat=fake_stream_api_chat,
                stream_ollama_chat=fake_stream_ollama_chat,
                ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
                ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
                api_message_with_images=lambda text, images: {"role": "user", "content": text},
                cli_message_with_images=lambda text, images: {"role": "user", "content": text},
                find_cli=lambda path: path,
                ollama_default_model="dummy",
                ollama_agent_model="dummy",
                db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
            )

            result = agent_file_actions._direct_agent_action(
                "Create a file named AXON_AUTONOMY_PROBE.txt in the workspace root containing exactly OK.",
                history=[],
                project_name="axon-online",
                workspace_path=tmpdir,
                deps=deps,
            )

            self.assertIsNotNone(result)
            self.assertEqual(created["content"], "OK")

    def test_direct_action_fetches_external_url(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={"http_get": lambda url, headers="": "Example Domain"},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        result = agent_file_actions._direct_agent_action(
            "Please take a look at https://example.com for me.",
            history=[],
            project_name="Axon",
            workspace_path="/tmp/axon-autonomy-workspace",
            deps=deps,
        )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, answer = result
        self.assertEqual(tool_name, "http_get")
        self.assertEqual(tool_args["url"], "https://example.com")
        self.assertEqual(tool_result, "Example Domain")
        self.assertIn("Example Domain", answer)

    def test_direct_action_routes_explicit_git_command_to_shell_tool(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={"shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}"},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                'Please run `git commit -m "ship it"`.',
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], 'git commit -m "ship it"')
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git commit -m"))

    def test_direct_action_commit_request_without_message_drafts_message_and_blocks_stage_all(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        def normalize_args(name, args):
            cleaned = dict(args)
            if name == "shell_cmd":
                return {k: v for k, v in cleaned.items() if not str(k).startswith("_")}
            return cleaned

        deps = AgentRuntimeDeps(
            tool_registry={
                "git_status": lambda path: (
                    "Branch: development\n\n"
                    "Status:\n"
                    "M app/screens/parent-payments.tsx\n"
                    " M components/layout/DesktopLayout.tsx\n"
                    "?? tests/unit/navigation/webLayout.test.ts\n"
                ),
                "shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}",
            },
            normalize_tool_args=normalize_args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Please commit everything.",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], "git add -A")
        self.assertEqual(tool_args["_draft_commit_message"], "feat: update payment, navigation, and tests")
        self.assertIn('Commit everything with commit message "feat: update payment, navigation, and tests".', tool_args["_resume_task"])
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git add -A"))
        self.assertEqual(answer, tool_result)

    def test_direct_action_does_not_commit_for_explanatory_question(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={"shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}"},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "How do I commit the repo?",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNone(result)

    def test_direct_action_vague_git_add_and_commit_request_drafts_message_and_blocks_stage_all(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        def normalize_args(name, args):
            cleaned = dict(args)
            if name == "shell_cmd":
                return {k: v for k, v in cleaned.items() if not str(k).startswith("_")}
            return cleaned

        deps = AgentRuntimeDeps(
            tool_registry={
                "git_status": lambda path: (
                    "Branch: development\n\n"
                    "Status:\n"
                    "M app/_layout.tsx\n"
                    " M components/dashboard/parent/MissionControlSection.tsx\n"
                    "?? tests/unit/dashboard/missionControlLayout.test.ts\n"
                ),
                "shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}",
            },
            normalize_tool_args=normalize_args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "git add and commit first then we will debug",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git add -A"))
        self.assertIn('Commit everything with commit message "feat: update missions, navigation, and dashboard".', tool_args["_resume_task"])
        self.assertEqual(answer, tool_result)

    def test_direct_action_commit_request_with_message_blocks_stage_all(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={"shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}"},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                'Commit everything with commit message "Approval smoke".',
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], "git add -A")
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git add -A"))

    def test_direct_action_commit_and_push_request_carries_push_follow_up(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        def normalize_args(name, args):
            cleaned = dict(args)
            if name == "shell_cmd":
                return {k: v for k, v in cleaned.items() if not str(k).startswith("_")}
            return cleaned

        deps = AgentRuntimeDeps(
            tool_registry={
                "git_status": lambda path: (
                    "Branch: main\n\n"
                    "Status:\n"
                    "M app.py\n"
                    "?? tests/test_app.py\n"
                ),
                "shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}",
            },
            normalize_tool_args=normalize_args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Please commit everything and push this branch.",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], "git add -A")
        self.assertIn('Commit everything with commit message "feat: update tests". Then push this branch.', tool_args["_resume_task"])
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git add -A"))
        self.assertEqual(answer, tool_result)

    def test_direct_action_push_request_reports_runtime_network_block_cleanly(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={
                "shell_cmd": lambda cmd, cwd="", timeout=30: (
                    "fatal: unable to access 'https://github.com/devworx8/axon.git/': "
                    "Could not resolve host: github.com"
                ),
            },
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Please push this branch.",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        _tool_name, _tool_args, tool_result, answer = result
        self.assertTrue(tool_result.startswith("ERROR: External network access is unavailable from this Axon runtime right now."))
        self.assertIn("github.com", tool_result)
        self.assertIn("unsandboxed host shell", tool_result)
        self.assertEqual(answer, tool_result)


class AgentResumeRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_task_override_uses_deterministic_direct_action(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "resume-agent.db"
            store = SessionStore(db_path)
            store.save(
                session_id="resume-1",
                task="Please commit everything and push this branch.",
                messages=[{"role": "assistant", "content": "Approval is required for git add -A."}],
                iteration=1,
                tool_log=[{"name": "shell_cmd", "args": {"cmd": "git add -A"}, "result": "BLOCKED_CMD:git:git add -A"}],
                status="approval_required",
                project_name="Axon",
                backend="cli",
                metadata={
                    "resume_task": "Push this branch.",
                    "workspace_path": tmpdir,
                    "workspace_id": 7,
                },
            )

            deps = AgentRuntimeDeps(
                tool_registry={"shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:git:{cmd}"},
                normalize_tool_args=lambda name, args: args,
                stream_cli=fake_stream_cli,
                stream_api_chat=fake_stream_api_chat,
                stream_ollama_chat=fake_stream_ollama_chat,
                ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
                ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
                api_message_with_images=lambda text, images: {"role": "user", "content": text},
                cli_message_with_images=lambda text, images: {"role": "user", "content": text},
                find_cli=lambda path: path,
                ollama_default_model="dummy",
                ollama_agent_model="dummy",
                db_path=db_path,
            )

            events = [
                event async for event in core_agent.run_agent(
                    "please continue",
                    [],
                    deps=deps,
                    backend="cli",
                    cli_path="/tmp/codex",
                    cli_model="gpt-5.4",
                    workspace_path=tmpdir,
                    workspace_id=7,
                    project_name="Axon",
                )
            ]

        self.assertEqual(events[0]["type"], "text")
        self.assertEqual(events[1]["type"], "tool_call")
        self.assertEqual(events[1]["args"]["cmd"], "git push -u origin HEAD")
        self.assertEqual(events[2]["type"], "tool_result")
        self.assertTrue(events[2]["result"].startswith("BLOCKED_CMD:git:git push -u origin HEAD"))
        self.assertEqual(events[3]["type"], "approval_required")
        self.assertEqual(events[3]["action_type"], "git_push")


class GitCommandApprovalGateTests(unittest.TestCase):
    def test_tool_shell_cmd_blocks_mutating_git_but_allows_status(self):
        snapshot = brain.agent_capture_permission_state()
        try:
            with _writable_tempdir() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)

                status_result = brain._TOOL_REGISTRY["shell_cmd"]("git status --short", cwd=tmpdir, timeout=15)
                commit_result = brain._TOOL_REGISTRY["shell_cmd"]('git commit -m "test"', cwd=tmpdir, timeout=15)

            self.assertFalse(status_result.startswith("BLOCKED_CMD:"))
            self.assertTrue(commit_result.startswith('BLOCKED_CMD:git:git commit -m "test"'))
        finally:
            brain.agent_restore_permission_state(snapshot)

    def test_tool_shell_cmd_consumes_workspace_scoped_exact_approval(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-shell-approval",
                "workspace_id": 7,
            }
        )
        try:
            with _writable_tempdir() as tmpdir:
                subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
                Path(tmpdir, "README.md").write_text("workspace scoped approval\n", encoding="utf-8")
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    action = approval_actions.build_command_approval_action(
                        "git add -A",
                        cwd=tmpdir,
                        workspace_id=7,
                        session_id="session-shell-approval",
                    )
                    brain.agent_allow_action(action, scope="once", session_id="session-shell-approval")

                    add_result = brain._TOOL_REGISTRY["shell_cmd"]("git add -A", cwd=tmpdir, timeout=15)
                    status_result = brain._TOOL_REGISTRY["shell_cmd"]("git status --short", cwd=tmpdir, timeout=15)
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)

            self.assertFalse(add_result.startswith("BLOCKED_CMD:"))
            self.assertIn("A  README.md", status_result)
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

    def test_exact_action_approval_is_consumed_once(self):
        snapshot = brain.agent_capture_permission_state()
        try:
            action = approval_actions.build_command_approval_action(
                'git commit -m "test"',
                cwd="/tmp/work",
                session_id="session-1",
            )
            brain.agent_allow_action(action, scope="once", session_id="session-1")

            self.assertTrue(brain._action_is_allowed(action))
            self.assertFalse(brain._action_is_allowed(action))
        finally:
            brain.agent_restore_permission_state(snapshot)

    def test_blocked_tool_event_includes_structured_action_payload(self):
        payload = core_agent._blocked_tool_event(
            "shell_cmd",
            {"cmd": 'git commit -m "ship it"', "cwd": "/tmp/work"},
            'BLOCKED_CMD:git:git commit -m "ship it"',
            workspace_id=7,
            session_id="session-7",
        )

        self.assertEqual(payload["action_type"], "git_commit")
        self.assertEqual(payload["workspace_id"], 7)
        self.assertEqual(
            payload["action_fingerprint"],
            payload["approval_action"]["action_fingerprint"],
        )
        self.assertIn("task", payload["scope_options"])

    def test_git_push_action_cannot_be_persisted(self):
        action = approval_actions.build_command_approval_action(
            "git push origin HEAD",
            cwd="/tmp/work",
            session_id="session-1",
        )

        self.assertFalse(action["persist_allowed"])
        self.assertNotIn("persist", action["scope_options"])

    def test_pr_upsert_action_cannot_be_persisted(self):
        action = approval_actions.build_command_approval_action(
            "gh pr create --title ship --body ready",
            cwd="/tmp/work",
            session_id="session-1",
        )

        self.assertFalse(action["persist_allowed"])
        self.assertNotIn("persist", action["scope_options"])

    def test_outside_workspace_file_action_cannot_be_persisted(self):
        action = approval_actions.build_edit_approval_action(
            "create",
            "/tmp/axon-persist-probe.txt",
            workspace_id=7,
            session_id="session-7",
            workspace_root="/home/edp/.devbrain",
        )

        self.assertFalse(action["persist_allowed"])
        self.assertNotIn("persist", action["scope_options"])


class FileApprovalGateTests(unittest.TestCase):
    def test_workspace_auto_allows_file_action_inside_active_workspace(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-1",
            }
        )
        try:
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    action = approval_actions.build_edit_approval_action(
                        "write",
                        os.path.join(tmpdir, "notes.txt"),
                        session_id="session-1",
                    )
                    self.assertTrue(brain._action_is_allowed(action))
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

    def test_workspace_auto_blocks_file_action_outside_active_workspace(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-2",
            }
        )
        try:
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    action = approval_actions.build_edit_approval_action(
                        "write",
                        "/tmp/axon-default-block.txt",
                        session_id="session-2",
                    )
                    self.assertFalse(brain._action_is_allowed(action))
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

    def test_tool_write_file_blocks_outside_workspace_in_default_mode(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-3",
            }
        )
        target = Path(tempfile.gettempdir()) / f"axon-default-write-{os.getpid()}.txt"
        try:
            if target.exists():
                target.unlink()
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    result = brain._TOOL_REGISTRY["write_file"](str(target), "DEFAULT_BLOCK")
                    self.assertTrue(result.startswith(f"BLOCKED_EDIT:write:{target}"))
                    self.assertFalse(target.exists())
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)
        finally:
            if target.exists():
                target.unlink()
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

    def test_tool_write_file_consumes_workspace_scoped_exact_approval(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-write-approval",
                "workspace_id": 7,
            }
        )
        target = Path(tempfile.gettempdir()) / f"axon-exact-write-{os.getpid()}.txt"
        try:
            if target.exists():
                target.unlink()
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    action = approval_actions.build_edit_approval_action(
                        "write",
                        str(target),
                        workspace_id=7,
                        session_id="session-write-approval",
                        workspace_root=tmpdir,
                    )
                    brain.agent_allow_action(action, scope="once", session_id="session-write-approval")

                    result = brain._TOOL_REGISTRY["write_file"](str(target), "EXACT_APPROVAL_OK")
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)

            self.assertIn("Written", result)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "EXACT_APPROVAL_OK")
        finally:
            if target.exists():
                target.unlink()
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)

    def test_tool_write_file_allows_outside_workspace_in_full_access(self):
        snapshot = brain.agent_capture_permission_state()
        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "runtime_permissions_mode": "full_access",
                "autonomy_profile": "workspace_auto",
                "agent_session_id": "session-4",
            }
        )
        target = Path(tempfile.gettempdir()) / f"axon-full-access-write-{os.getpid()}.txt"
        try:
            if target.exists():
                target.unlink()
            with _writable_tempdir() as tmpdir:
                workspace_token = agent_runtime_state.set_active_workspace_path(tmpdir)
                try:
                    result = brain._TOOL_REGISTRY["write_file"](str(target), "FULL_ACCESS_OK")
                    self.assertIn("Written", result)
                    self.assertTrue(target.exists())
                    self.assertEqual(target.read_text(encoding="utf-8"), "FULL_ACCESS_OK")
                finally:
                    agent_runtime_state.reset_active_workspace_path(workspace_token)
        finally:
            if target.exists():
                target.unlink()
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)
            brain.agent_restore_permission_state(snapshot)


class LegacyApprovalEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_allow_command_endpoint_is_gone(self):
        with self.assertRaises(server.HTTPException) as exc:
            await server.allow_agent_command(server.AllowCommandBody(command="git"))

        self.assertEqual(exc.exception.status_code, 410)

    async def test_allow_edit_endpoint_is_gone(self):
        with self.assertRaises(server.HTTPException) as exc:
            await server.allow_agent_edit(server.AllowEditBody(path="~/demo.txt", scope="file"))

        self.assertEqual(exc.exception.status_code, 410)

    async def test_approval_workspace_root_accepts_sqlite_row(self):
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT 17 AS id, '/tmp/demo' AS path").fetchone()

        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_get_project(_conn, _workspace_id):
            return row

        with patch.object(server.devdb, "get_db", fake_db), \
             patch.object(server.devdb, "get_project", side_effect=fake_get_project):
            result = await server._approval_workspace_root(17)

        self.assertEqual(result, "/tmp/demo")

    async def test_approve_action_rejects_tampered_persist_for_outside_workspace_file(self):
        action = approval_actions.build_edit_approval_action(
            "create",
            "/tmp/axon-persist-endpoint-probe.txt",
            workspace_id=173,
            session_id="session-173",
        )
        tampered = {**action, "persist_allowed": True, "scope_options": ["once", "task", "session", "persist"]}

        async def fake_workspace_root(_workspace_id):
            return "/home/edp/.devbrain"

        with patch.object(server, "_approval_workspace_root", side_effect=fake_workspace_root):
            with self.assertRaises(server.HTTPException) as exc:
                await server.approve_agent_action(
                    server.ApproveActionBody(action=tampered, scope="persist", session_id="session-173")
                )

        self.assertEqual(exc.exception.status_code, 400)


class AgentOutputHardeningTests(unittest.TestCase):
    def test_native_sandbox_git_story_counts_as_hallucinated_execution(self):
        text = (
            "git commit is blocked by the sandbox because .git is mounted read-only in this session. "
            "git commit fails with fatal: Unable to create '/tmp/repo/.git/index.lock': Read-only file system."
        )

        self.assertTrue(agent_output._looks_like_hallucinated_execution(text, []))

    def test_blocked_git_push_receipt_does_not_support_success_claim(self):
        text = (
            "Pushed the active branch from `/home/edp/.devbrain` with `git push -u origin HEAD`.\n\n"
            "Everything up-to-date"
        )
        tool_log = [
            {
                "name": "shell_cmd",
                "args": {"cmd": "git push -u origin HEAD", "cwd": "/home/edp/.devbrain"},
                "result": "BLOCKED_CMD:git:git push -u origin HEAD",
            }
        ]

        self.assertTrue(agent_output._looks_like_hallucinated_execution(text, tool_log))

    def test_successful_git_push_receipt_allows_push_summary(self):
        text = (
            "Pushed the active branch from `/home/edp/.devbrain` with `git push -u origin HEAD`.\n\n"
            "branch 'dev-new' set up to track 'origin/dev-new'.\n"
            "Everything up-to-date"
        )
        tool_log = [
            {
                "name": "shell_cmd",
                "args": {"cmd": "git push -u origin HEAD", "cwd": "/home/edp/.devbrain"},
                "result": "branch 'dev-new' set up to track 'origin/dev-new'.\nEverything up-to-date",
            }
        ]

        self.assertFalse(agent_output._looks_like_hallucinated_execution(text, tool_log))

    def test_combined_git_checkpoint_story_without_receipts_counts_as_hallucinated_execution(self):
        text = (
            "Yes. I applied the UI/UX fix and the runtime hardening. "
            "The changes are committed and pushed on `dev-new` as `cb345be`. "
            "git status is clean and the branch is in sync with origin/dev-new."
        )

        self.assertTrue(agent_output._looks_like_hallucinated_execution(text, []))

    def test_git_clean_sync_claim_requires_matching_receipts(self):
        text = "git status is clean and the branch is in sync with origin/dev-new."
        tool_log = [{"name": "read_file", "args": {"path": "/home/edp/.devbrain/brain.py"}, "result": "ok"}]

        self.assertTrue(agent_output._looks_like_hallucinated_execution(text, tool_log))

    def test_git_clean_sync_claim_allows_real_status_receipt(self):
        text = "git status is clean and the branch is in sync with origin/dev-new."
        tool_log = [
            {
                "name": "shell_cmd",
                "args": {"cmd": "git status --short --branch", "cwd": "/home/edp/.devbrain"},
                "result": "## dev-new...origin/dev-new",
            }
        ]

        self.assertFalse(agent_output._looks_like_hallucinated_execution(text, tool_log))


class GitHubWorkflowRoutingTests(unittest.TestCase):
    def _deps(self):
        async def fake_stream_cli(messages, **kwargs):
            if False:
                yield ""

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        return AgentRuntimeDeps(
            tool_registry={"shell_cmd": lambda cmd, cwd="", timeout=30: f"BLOCKED_CMD:{cmd.split()[0]}:{cmd}"},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: path,
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

    def test_push_request_routes_to_exact_push_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Please push this branch.",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=self._deps(),
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], "git push -u origin HEAD")
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:git:git push -u origin HEAD"))

    def test_pr_request_routes_to_gh_pr_create(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                'Open a PR with title "Axon smoke".',
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=self._deps(),
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertIn("gh pr create", tool_args["cmd"])
        self.assertIn("--title", tool_args["cmd"])
        self.assertTrue(tool_result.startswith("BLOCKED_CMD:gh:gh pr create"))

    def test_workflow_status_request_routes_to_read_only_gh_run_list(self):
        deps = self._deps()
        deps.tool_registry["shell_cmd"] = lambda cmd, cwd="", timeout=30: "completed\tmain\tgreen"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Check the CI workflow status.",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )

        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, answer = result
        self.assertEqual(tool_name, "shell_cmd")
        self.assertEqual(tool_args["cmd"], "gh run list --limit 5")
        self.assertEqual(tool_result, "completed\tmain\tgreen")
        self.assertIn("completed", answer)


class AgentEvidenceSummaryTests(unittest.TestCase):
    def test_checkpoint_summary_without_sections_needs_repair(self):
        text = (
            "Current checkpoint: UI work exists.\n"
            "Verification: npm run build -- --webpack passed."
        )

        self.assertTrue(
            agent_output._needs_evidence_section_repair(
                "pause - review your previous answer and verify it",
                text,
            )
        )

    def test_auto_handoff_without_evidence_sections_needs_repair(self):
        text = (
            "What Changed\n"
            "- Updated the docs route.\n\n"
            "Verification\n"
            "- npm run build -- --webpack passed.\n"
            "- tsc --noEmit passed."
        )

        self.assertTrue(
            agent_output._needs_evidence_section_repair(
                "please continue",
                text,
            )
        )

    def test_checkpoint_summary_with_sections_passes(self):
        text = (
            "Verified In This Run\n"
            "- read_file: app/page.tsx\n\n"
            "Inferred From Repo State\n"
            "- The latest commit suggests landing-page work.\n\n"
            "Not Yet Verified\n"
            "- I have not rerun npm run build in this pass.\n\n"
            "Next Action Not Yet Taken\n"
            "- Continue the next UI change."
        )

        self.assertFalse(
            agent_output._needs_evidence_section_repair(
                "audit the checkpoint",
                text,
            )
        )


class AgentEvidenceRepairLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_agent_repairs_checkpoint_summary_format(self):
        replies = iter(
            [
                "ANSWER: Current checkpoint: route work exists.\nVerification: tsc passed.",
                (
                    "ANSWER: Verified In This Run\n"
                    "- No tool receipts were recorded in this run.\n\n"
                    "Inferred From Repo State\n"
                    "- The current response is only a checkpoint summary.\n\n"
                    "Not Yet Verified\n"
                    "- I did not run tsc in this run.\n\n"
                    "Next Action Not Yet Taken\n"
                    "- I have not continued implementation yet."
                ),
            ]
        )

        async def fake_stream_cli(messages, **kwargs):
            yield next(replies)

        async def fake_stream_api_chat(**kwargs):
            if False:
                yield ""

        async def fake_stream_ollama_chat(**kwargs):
            if False:
                yield ""

        deps = AgentRuntimeDeps(
            tool_registry={},
            normalize_tool_args=lambda name, args: args,
            stream_cli=fake_stream_cli,
            stream_api_chat=fake_stream_api_chat,
            stream_ollama_chat=fake_stream_ollama_chat,
            ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
            ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
            api_message_with_images=lambda text, images: {"role": "user", "content": text},
            cli_message_with_images=lambda text, images: {"role": "user", "content": text},
            find_cli=lambda path: "/tmp/codex",
            ollama_default_model="dummy",
            ollama_agent_model="dummy",
            db_path=Path(tempfile.gettempdir()) / "axon-agent-test.db",
        )

        events = [
            event async for event in core_agent.run_agent(
                "pause - review your previous answer and verify it",
                [],
                deps=deps,
                backend="cli",
                cli_path="/tmp/codex",
                cli_model="gpt-5.4",
                workspace_path="/tmp/axon-autonomy-workspace",
            )
        ]

        text_chunks = [event.get("chunk", "") for event in events if event.get("type") == "text"]
        self.assertEqual(len(text_chunks), 1)
        self.assertIn("Verified In This Run", text_chunks[0])
        self.assertIn("Not Yet Verified", text_chunks[0])


class SubagentRuntimePropagationTests(unittest.TestCase):
    def test_subagent_inherits_parent_runtime(self):
        captured = {}

        async def fake_run_agent(user_message, history, **kwargs):
            captured.update(kwargs)
            yield {"type": "text", "chunk": "subagent ok"}

        token = brain._ACTIVE_AGENT_RUNTIME_CONTEXT.set(
            {
                "backend": "cli",
                "workspace_path": "/tmp/workspace",
                "project_name": "Axon",
                "cli_path": "/tmp/claude",
                "cli_model": "claude-sonnet-4-6",
                "cli_session_persistence": False,
            }
        )
        try:
            with patch.object(brain, "run_agent", side_effect=fake_run_agent):
                result = brain._tool_spawn_subagent("inspect", context="ctx")
        finally:
            brain._ACTIVE_AGENT_RUNTIME_CONTEXT.reset(token)

        self.assertIn("subagent ok", result)
        self.assertEqual(captured["backend"], "cli")
        self.assertEqual(captured["workspace_path"], "/tmp/workspace")
        self.assertEqual(captured["cli_model"], "claude-sonnet-4-6")
        self.assertNotIn("spawn_subagent", captured["tools"])


class TaskSandboxServiceTests(unittest.TestCase):
    def _git(self, cwd: Path, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Axon Tests",
            "GIT_AUTHOR_EMAIL": "axon@example.com",
            "GIT_COMMITTER_NAME": "Axon Tests",
            "GIT_COMMITTER_EMAIL": "axon@example.com",
        }
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout or f"git {' '.join(args)} failed")
        return (result.stdout or "").strip()

    def test_apply_task_sandbox_copies_changes_back_to_source(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            sandbox_root = root / "sandboxes"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")
            sandbox_dir = sandbox_root / "task-1-demo"
            sandbox_root.mkdir(parents=True, exist_ok=True)
            self._git(repo_root, "worktree", "add", "-b", "axon/task-1-demo", str(sandbox_dir), "HEAD")
            (sandbox_dir / "app.txt").write_text("new\n", encoding="utf-8")

            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"task": sandbox_root}, clear=False):
                task_sandbox_service.write_task_sandbox(
                    {
                        "task_id": 1,
                        "task_title": "Demo",
                        "source_path": str(repo_root),
                        "repo_root": str(repo_root),
                        "sandbox_path": str(sandbox_dir),
                        "branch_name": "axon/task-1-demo",
                        "base_branch": "master",
                        "status": "review_ready",
                        "changed_files": ["app.txt"],
                    }
                )
                result = task_sandbox_service.apply_task_sandbox(1, "Demo")

            self.assertTrue(result["applied"])
            self.assertEqual((repo_root / "app.txt").read_text(encoding="utf-8"), "new\n")
            self.assertIn("Applied", result["summary"])

    def test_discard_task_sandbox_removes_worktree(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            repo_root = root / "repo"
            sandbox_root = root / "sandboxes"
            repo_root.mkdir()
            self._git(repo_root, "init")
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            self._git(repo_root, "add", "app.txt")
            self._git(repo_root, "commit", "-m", "init")
            sandbox_dir = sandbox_root / "task-2-demo"
            sandbox_root.mkdir(parents=True, exist_ok=True)
            self._git(repo_root, "worktree", "add", "-b", "axon/task-2-demo", str(sandbox_dir), "HEAD")

            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"task": sandbox_root}, clear=False):
                task_sandbox_service.write_task_sandbox(
                    {
                        "task_id": 2,
                        "task_title": "Demo",
                        "source_path": str(repo_root),
                        "repo_root": str(repo_root),
                        "sandbox_path": str(sandbox_dir),
                        "branch_name": "axon/task-2-demo",
                        "base_branch": "master",
                        "status": "ready",
                        "changed_files": [],
                    }
                )
                result = task_sandbox_service.discard_task_sandbox(2, "Demo")

            self.assertTrue(result["discarded"])
            self.assertFalse(sandbox_dir.exists())


class AutoSessionApiTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_continue_uses_existing_session_workspace_when_project_id_missing(self):
        workspace = {"id": 11, "name": "Demo", "path": "/tmp/demo"}
        session = {"session_id": "auto-11", "workspace_id": 11, "runtime_override": {}, "status": "review_ready"}
        captured = {}

        async def fake_background(workspace_dict, session_meta, **kwargs):
            captured["workspace"] = workspace_dict
            captured["session"] = session_meta
            captured["kwargs"] = kwargs

        async def fake_get_project(_conn, project_id):
            captured["project_id"] = project_id
            return workspace

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_project", side_effect=fake_get_project), \
             patch.object(auto_session_service, "refresh_auto_session", return_value=session), \
             patch.object(auto_session_service, "find_workspace_auto_session", return_value=session), \
             patch.object(server, "_run_auto_session_background", side_effect=fake_background), \
             patch.dict(server._auto_session_runs, {}, clear=True):
            result = await server._queue_auto_session_run(
                server.AutoSessionStartRequest(message="please continue"),
                resume=True,
                session_id="auto-11",
            )
            await asyncio.sleep(0)

        self.assertTrue(result["started"])
        self.assertTrue(result["resume"])
        self.assertEqual(captured["project_id"], 11)
        self.assertEqual(captured["workspace"]["id"], 11)
        self.assertEqual(captured["kwargs"]["resume_message"], "please continue")

    async def test_continue_passes_explicit_resume_instruction_to_runner(self):
        workspace = {"id": 12, "name": "Demo", "path": "/tmp/demo"}
        session = {"session_id": "auto-12", "workspace_id": 12, "runtime_override": {}, "status": "error"}
        captured = {}

        async def fake_background(workspace_dict, session_meta, **kwargs):
            captured["workspace"] = workspace_dict
            captured["session"] = session_meta
            captured["kwargs"] = kwargs

        async def fake_get_project(_conn, project_id):
            return workspace

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_project", side_effect=fake_get_project), \
             patch.object(auto_session_service, "refresh_auto_session", return_value=session), \
             patch.object(auto_session_service, "find_workspace_auto_session", return_value=session), \
             patch.object(server, "_run_auto_session_background", side_effect=fake_background), \
             patch.dict(server._auto_session_runs, {}, clear=True):
            result = await server._queue_auto_session_run(
                server.AutoSessionStartRequest(message="Create AUTO_RESUME.txt and stop for review."),
                resume=True,
                session_id="auto-12",
            )
            await asyncio.sleep(0)

        self.assertTrue(result["started"])
        self.assertEqual(captured["kwargs"]["resume_message"], "Create AUTO_RESUME.txt and stop for review.")

    async def test_auto_session_background_uses_full_access_for_isolated_codex_worktree(self):
        captured = {}

        async def fake_get_all_settings(_conn):
            return {
                "max_agent_iterations": "3",
                "context_compact_enabled": "1",
                "ai_backend": "cli",
                "runtime_permissions_mode": "default",
                "autonomy_profile": "workspace_auto",
            }

        async def fake_rows(*_args, **_kwargs):
            return []

        async def fake_resource_bundle(*_args, **_kwargs):
            return {"context_block": "", "image_paths": [], "vision_model": "", "warnings": []}

        async def fake_memory_bundle(*_args, **_kwargs):
            return {"context_block": ""}

        async def fake_ai_params(*_args, **_kwargs):
            return {"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.4", "cli_session_persistence": False}

        async def fake_auto_route(*args, **kwargs):
            return kwargs.get("ai") or args[1], []

        async def fake_run_agent(*_args, **kwargs):
            captured["runtime_permissions_mode"] = kwargs.get("runtime_permissions_mode")
            captured["autonomy_profile"] = kwargs.get("autonomy_profile")
            yield {"type": "text", "chunk": "looked around"}

        with tempfile.TemporaryDirectory() as tmpdir:
            auto_root = Path(tmpdir) / "auto"
            auto_root.mkdir(parents=True, exist_ok=True)
            workspace_root = Path(tmpdir) / "workspace"
            workspace_root.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=workspace_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Axon Tests"], cwd=workspace_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "axon-tests@example.com"], cwd=workspace_root, check=True, capture_output=True, text=True)
            (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=workspace_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=workspace_root, check=True, capture_output=True, text=True)
            workspace = {"id": 13, "name": "Demo", "path": str(workspace_root)}

            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                session_meta = auto_session_service.ensure_auto_session(
                    "auto-13",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    start_prompt="Inspect the repo",
                    metadata={"status": "ready"},
                )

                with patch.object(server.devdb, "get_db", self._fake_db), \
                     patch.object(server.devdb, "get_all_settings", side_effect=fake_get_all_settings), \
                     patch.object(server.devdb, "get_projects", side_effect=fake_rows), \
                     patch.object(server.devdb, "get_tasks", side_effect=fake_rows), \
                     patch.object(server.devdb, "get_prompts", side_effect=fake_rows), \
                     patch.object(server, "_load_chat_history_rows", side_effect=fake_rows), \
                     patch.object(server, "_resource_bundle", side_effect=fake_resource_bundle), \
                     patch.object(server, "_memory_bundle", side_effect=fake_memory_bundle), \
                     patch.object(server, "_task_sandbox_ai_params", side_effect=fake_ai_params), \
                     patch.object(server, "auto_route_vision_runtime", side_effect=fake_auto_route), \
                     patch.object(server, "_auto_route_image_generation_runtime", side_effect=fake_auto_route), \
                     patch.object(brain, "_build_context_block", return_value=""), \
                     patch.object(brain, "run_agent", side_effect=fake_run_agent), \
                     patch.object(brain, "agent_capture_permission_state", return_value={}), \
                     patch.object(brain, "agent_restore_permission_state"), \
                     patch.object(brain, "agent_allow_edit"), \
                     patch.object(brain, "agent_allow_command"):
                    await server._run_auto_session_background(workspace, session_meta)

        self.assertEqual(captured["autonomy_profile"], "workspace_auto")
        self.assertEqual(captured["runtime_permissions_mode"], "full_access")

    async def test_list_auto_sessions_refreshes_stale_entries(self):
        with patch.object(
            auto_session_service,
            "list_auto_sessions",
            return_value=[
                {
                    "session_id": "auto-17",
                    "status": "running",
                    "workspace_id": 17,
                    "workspace_name": "Demo",
                }
            ],
        ), patch.object(
            auto_session_service,
            "refresh_auto_session",
            return_value={
                "session_id": "auto-17",
                "status": "review_ready",
                "workspace_id": 17,
                "workspace_name": "Demo",
                "changed_files": ["app/page.tsx"],
            },
        ):
            payload = await server.list_auto_sessions()

        self.assertEqual(payload["sessions"][0]["status"], "review_ready")
        self.assertTrue(payload["sessions"][0]["apply_allowed"])

    async def test_list_auto_sessions_degrades_refresh_failures(self):
        with patch.object(
            auto_session_service,
            "list_auto_sessions",
            return_value=[
                {
                    "session_id": "auto-18",
                    "status": "running",
                    "workspace_id": 18,
                    "workspace_name": "Demo",
                }
            ],
        ), patch.object(
            auto_session_service,
            "refresh_auto_session",
            side_effect=RuntimeError("sandbox missing"),
        ):
            payload = await server.list_auto_sessions()

        self.assertEqual(payload["sessions"][0]["status"], "error")
        self.assertIn("sandbox missing", payload["sessions"][0]["last_error"])

    async def test_build_live_snapshot_includes_auto_sessions(self):
        async def fake_get_all_settings(_conn):
            return {"ai_backend": "api", "api_model": "deepseek-reasoner"}

        async def fake_list_terminal_sessions(_conn, limit=6):
            return []

        async def fake_get_activity(_conn, limit=6):
            return []

        with patch.object(server.devdb, "get_db", self._fake_db), \
             patch.object(server.devdb, "get_all_settings", side_effect=fake_get_all_settings), \
             patch.object(server.devdb, "list_terminal_sessions", side_effect=fake_list_terminal_sessions), \
             patch.object(server.devdb, "get_activity", side_effect=fake_get_activity), \
             patch.object(auto_session_service, "list_auto_sessions", return_value=[{
                 "session_id": "auto-12",
                 "workspace_id": 12,
                 "workspace_name": "Demo",
                 "status": "review_ready",
                 "title": "Auto demo",
                 "changed_files": ["app.txt"],
                 "resolved_runtime": {"label": "Codex CLI", "model": "gpt-5.4"},
                 "updated_at": "2026-04-01T10:00:00Z",
             }]), \
             patch.object(server, "_connection_snapshot", return_value={"connected": True}):
            snapshot = await server._build_live_snapshot()

        self.assertEqual(snapshot["auto_sessions"][0]["session_id"], "auto-12")
        self.assertTrue(snapshot["auto_sessions"][0]["apply_allowed"])

    async def test_build_live_snapshot_includes_live_operator_feed(self):
        async def fake_get_all_settings(_conn):
            return {"ai_backend": "api", "api_model": "deepseek-reasoner"}

        async def fake_rows(*_args, **_kwargs):
            return []

        original = dict(server._live_operator_snapshot)
        try:
            server._live_operator_snapshot.update(
                {
                    "active": True,
                    "mode": "auto",
                    "phase": "execute",
                    "title": "Running Auto session",
                    "detail": "Applying a focused patch",
                    "workspace_id": 12,
                    "auto_session_id": "auto-12",
                    "feed": [
                        {
                            "id": "1",
                            "phase": "plan",
                            "title": "Planning inside Auto sandbox",
                            "detail": "Checking the active diff",
                            "at": "2026-04-01T10:00:00Z",
                        }
                    ],
                }
            )
            with patch.object(server.devdb, "get_db", self._fake_db), \
                 patch.object(server.devdb, "get_all_settings", side_effect=fake_get_all_settings), \
                 patch.object(server.devdb, "list_terminal_sessions", side_effect=fake_rows), \
                 patch.object(server.devdb, "get_activity", side_effect=fake_rows), \
                 patch.object(auto_session_service, "list_auto_sessions", return_value=[]), \
                 patch.object(server, "_connection_snapshot", return_value={"connected": True}):
                snapshot = await server._build_live_snapshot()
        finally:
            server._live_operator_snapshot.clear()
            server._live_operator_snapshot.update(original)

        self.assertEqual(snapshot["operator"]["auto_session_id"], "auto-12")
        self.assertEqual(snapshot["operator"]["feed"][0]["title"], "Planning inside Auto sandbox")

    def test_set_live_operator_retains_auto_session_context_on_review_handoff(self):
        original = dict(server._live_operator_snapshot)
        try:
            server._live_operator_snapshot.clear()
            server._live_operator_snapshot.update(
                {
                    "active": True,
                    "mode": "auto",
                    "phase": "execute",
                    "title": "Running Auto session",
                    "detail": "Applying a focused patch",
                    "tool": "",
                    "summary": "",
                    "workspace_id": 12,
                    "auto_session_id": "auto-12",
                    "changed_files_count": 0,
                    "apply_allowed": False,
                    "started_at": "2026-04-01T10:00:00Z",
                    "updated_at": "2026-04-01T10:00:00Z",
                    "feed": [
                        {
                            "id": "1",
                            "phase": "execute",
                            "title": "Running Auto session",
                            "detail": "Applying a focused patch",
                            "at": "2026-04-01T10:00:00Z",
                        }
                    ],
                }
            )

            server._set_live_operator(
                active=False,
                mode="auto",
                phase="verify",
                title="Auto session ready for review",
                detail="Axon finished the sandbox pass and prepared a reviewable handoff.",
                workspace_id=12,
                auto_session_id="auto-12",
                changed_files_count=3,
                apply_allowed=True,
            )
        finally:
            snapshot = dict(server._live_operator_snapshot)
            server._live_operator_snapshot.clear()
            server._live_operator_snapshot.update(original)

        self.assertFalse(snapshot["active"])
        self.assertEqual(snapshot["auto_session_id"], "auto-12")
        self.assertEqual(snapshot["changed_files_count"], 3)
        self.assertTrue(snapshot["apply_allowed"])
        self.assertEqual(snapshot["feed"][-1]["title"], "Auto session ready for review")

    async def test_noop_auto_run_fails_without_reviewable_handoff(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            auto_root = Path(tmp_dir) / "autos"
            repo_root.mkdir()
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Axon Tests",
                "GIT_AUTHOR_EMAIL": "axon@example.com",
                "GIT_COMMITTER_NAME": "Axon Tests",
                "GIT_COMMITTER_EMAIL": "axon@example.com",
            }
            subprocess.run(["git", "-C", str(repo_root), "init"], check=True, env=env, capture_output=True, text=True)
            (repo_root / "app.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo_root), "add", "app.txt"], check=True, env=env, capture_output=True, text=True)
            subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "init"], check=True, env=env, capture_output=True, text=True)
            workspace = {"id": 13, "name": "Demo", "path": str(repo_root)}

            async def fake_get_all_settings(_conn):
                return {"max_agent_iterations": "3", "context_compact_enabled": "1", "ai_backend": "cli"}

            async def fake_rows(*_args, **_kwargs):
                return []

            async def fake_resource_bundle(*_args, **_kwargs):
                return {"context_block": "", "image_paths": [], "vision_model": "", "warnings": []}

            async def fake_memory_bundle(*_args, **_kwargs):
                return {"context_block": ""}

            async def fake_ai_params(*_args, **_kwargs):
                return {"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.4", "cli_session_persistence": False}

            async def fake_auto_route(*args, **kwargs):
                return kwargs.get("ai") or args[1], []

            async def fake_run_agent(*_args, **_kwargs):
                yield {"type": "text", "chunk": "looked around"}

            with patch.dict(sandbox_sessions.SANDBOX_ROOTS, {"auto": auto_root}, clear=False):
                session_meta = auto_session_service.ensure_auto_session(
                    "auto-13",
                    workspace,
                    title="Auto demo",
                    detail="Run autonomously",
                    start_prompt="Inspect the repo",
                    metadata={"status": "ready"},
                )
                with patch.object(server.devdb, "get_db", self._fake_db), \
                     patch.object(server.devdb, "get_all_settings", side_effect=fake_get_all_settings), \
                     patch.object(server.devdb, "get_projects", side_effect=fake_rows), \
                     patch.object(server.devdb, "get_tasks", side_effect=fake_rows), \
                     patch.object(server.devdb, "get_prompts", side_effect=fake_rows), \
                     patch.object(server, "_load_chat_history_rows", side_effect=fake_rows), \
                     patch.object(server, "_resource_bundle", side_effect=fake_resource_bundle), \
                     patch.object(server, "_memory_bundle", side_effect=fake_memory_bundle), \
                     patch.object(server, "_task_sandbox_ai_params", side_effect=fake_ai_params), \
                     patch.object(server, "auto_route_vision_runtime", side_effect=fake_auto_route), \
                     patch.object(server, "_auto_route_image_generation_runtime", side_effect=fake_auto_route), \
                     patch.object(brain, "_build_context_block", return_value=""), \
                     patch.object(brain, "run_agent", side_effect=fake_run_agent), \
                     patch.object(brain, "agent_capture_permission_state", return_value={}), \
                     patch.object(brain, "agent_restore_permission_state"), \
                     patch.object(brain, "agent_allow_edit"), \
                     patch.object(brain, "agent_allow_command"):
                    await server._run_auto_session_background(workspace, session_meta)

                refreshed = auto_session_service.refresh_auto_session("auto-13")

            self.assertEqual(refreshed["status"], "error")
            self.assertIn("did not produce a reviewable handoff", refreshed["last_error"])


if __name__ == "__main__":
    unittest.main()
