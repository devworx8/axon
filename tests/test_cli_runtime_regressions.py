from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

import brain
import memory_engine
import server
import runtime_manager
import provider_registry
from axon_core import agent as core_agent
from axon_core import agent_file_actions
from axon_core import agent_prompts
from axon_core import cli_pacing
from axon_core.agent_toolspecs import AgentRuntimeDeps
from axon_core.session_store import SessionStore
from axon_api.settings_models import SettingsUpdate
from axon_api.services import claude_cli_runtime
from axon_api.services import codex_cli_runtime
from axon_api.services import task_sandboxes as task_sandbox_service
from axon_core.chat_context import select_history_for_chat
from axon_core import agent_output
from axon_core.vision_runtime import auto_route_vision_runtime


class SettingsPayloadTests(unittest.TestCase):
    def test_settings_update_accepts_cli_model(self):
        payload = SettingsUpdate(claude_cli_model="sonnet", ai_backend="cli")

        self.assertEqual(payload.claude_cli_model, "sonnet")
        self.assertEqual(payload.ai_backend, "cli")

    def test_settings_update_accepts_cli_session_persistence_toggle(self):
        payload = SettingsUpdate(claude_cli_session_persistence_enabled=True, ai_backend="cli")

        self.assertTrue(payload.claude_cli_session_persistence_enabled)
        self.assertEqual(payload.ai_backend, "cli")


class ProviderRegistryTests(unittest.TestCase):
    def test_deepseek_platform_url_normalizes_to_api_base(self):
        settings = {
            "api_provider": "deepseek",
            "deepseek_base_url": "https://platform.deepseek.com/",
            "deepseek_api_model": "deepseek-reasoner",
        }

        cfg = provider_registry.runtime_api_config(settings)

        self.assertEqual(cfg["api_base_url"], "https://api.deepseek.com/v1")


class ServerAiParamsTests(unittest.IsolatedAsyncioTestCase):
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

        async def fail_stream_cli(*args, **kwargs):
            raise AssertionError("CLI should not be launched while cooldown is active")
            yield ""

        async def fake_stream_api_chat(messages, **kwargs):
            self.assertEqual(kwargs["api_model"], "deepseek-reasoner")
            yield "fallback ok"

        with patch.object(brain, "_resolve_selected_cli_binary", return_value="/tmp/claude"), \
             patch.object(brain, "_stream_cli", side_effect=fail_stream_cli), \
             patch.object(brain, "_stream_api_chat", side_effect=fake_stream_api_chat):
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


class ClaudeCliCommandTests(unittest.TestCase):
    def test_find_cli_ignores_codex_override(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            override = Path(tmp_dir) / "codex"
            override.write_text("shim")
            override.chmod(0o755)

            with patch.object(brain, "_find_named_cli", return_value="/tmp/claude"):
                resolved = brain._find_cli(str(override))

        self.assertEqual(resolved, "/tmp/claude")

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
        self.assertIn("gpt-5.1-codex-max", cmd)

    def test_codex_exec_command_accepts_workspace_write_mode(self):
        cmd = brain.build_codex_exec_command(
            "/tmp/codex",
            prompt="Reply with OK",
            model="gpt-5.4",
            cwd="/tmp/work",
            sandbox_mode="workspace-write",
        )

        self.assertIn("--sandbox", cmd)
        self.assertIn("workspace-write", cmd)


class ClaudeCliCooldownGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_cli_falls_back_to_codex_during_cooldown(self):
        async def fake_call_codex(prompt, **kwargs):
            self.assertEqual(kwargs["binary"], "/tmp/codex")
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


class RuntimeStatusCliSelectionTests(unittest.TestCase):
    @patch.object(runtime_manager, "active_agents_count", return_value=1)
    @patch.object(runtime_manager, "lifecycle_phases", return_value=[])
    @patch.object(runtime_manager, "registered_agents", return_value=[])
    @patch.object(runtime_manager.gpu_guard, "detect_display_gpu_state", return_value={"warning": "", "connected_outputs": []})
    @patch.object(runtime_manager, "local_model_cards", return_value=[])
    @patch.object(runtime_manager._brain, "discover_cli_environments")
    @patch.object(runtime_manager._brain, "available_cli_models")
    @patch.object(runtime_manager._claude_cli_runtime, "build_cli_runtime_snapshot")
    @patch.object(runtime_manager._codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_runtime_status_reports_codex_when_selected(
        self,
        build_codex_snapshot,
        build_claude_snapshot,
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
    @patch.object(runtime_manager._brain, "normalize_cli_model")
    @patch.object(runtime_manager._claude_cli_runtime, "build_cli_runtime_snapshot")
    @patch.object(runtime_manager._codex_cli_runtime, "build_codex_runtime_snapshot")
    def test_runtime_status_normalizes_invalid_codex_model(
        self,
        build_codex_snapshot,
        build_claude_snapshot,
        normalize_cli_model,
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


class TerminalRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_terminal_cwd_accepts_sqlite_row(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        safe_cwd = str(Path.home() / ".devbrain")
        row = conn.execute("SELECT ? AS cwd, 0 AS workspace_id", (safe_cwd,)).fetchone()

        resolved = await server._resolve_terminal_cwd(None, row)

        self.assertEqual(str(resolved), safe_cwd)
        conn.close()


class SessionStoreRegressionTests(unittest.TestCase):
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


class InterruptedSessionEndpointTests(unittest.IsolatedAsyncioTestCase):
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

        def fake_build(binary, *, prompt, model="", cwd="", sandbox_mode="read-only"):
            captured["binary"] = binary
            captured["model"] = model
            captured["cwd"] = cwd
            captured["sandbox_mode"] = sandbox_mode
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

        self.assertEqual(seen["backend"], "api")
        self.assertTrue(any(event.get("type") == "text" and "cooling down after a rate limit" in str(event.get("chunk", "")).lower() for event in events))


class AgentAutonomyRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_mutating_requests_skip_direct_file_shortcuts(self):
        async def fake_stream_cli(messages, **kwargs):
            self.assertEqual(kwargs.get("cli_path"), "/tmp/codex")
            self.assertEqual(kwargs.get("model"), "gpt-5.4")
            yield "OK"

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

        with patch.object(core_agent, "_direct_agent_action", side_effect=AssertionError("direct shortcut should be skipped")):
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

        self.assertTrue(any(event.get("type") == "text" and event.get("chunk") == "OK" for event in events))

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

            with patch.object(task_sandbox_service, "TASK_SANDBOX_ROOT", sandbox_root):
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

            with patch.object(task_sandbox_service, "TASK_SANDBOX_ROOT", sandbox_root):
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


if __name__ == "__main__":
    unittest.main()
