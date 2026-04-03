from __future__ import annotations

import os
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from axon_api.services import console_commands
from axon_api.services import local_tool_env
from axon_api.services import npm_cli_extensions


class AxonLocalToolEnvTests(unittest.TestCase):
    def test_build_tool_env_scopes_common_installers_to_axon(self):
        env = local_tool_env.build_tool_env({"PATH": "/usr/bin"})
        path_parts = env["PATH"].split(os.pathsep)

        self.assertEqual(env["AXON_TOOL_ROOT"], str(local_tool_env.axon_tool_root()))
        self.assertEqual(env["NPM_CONFIG_PREFIX"], str(local_tool_env.npm_prefix_dir()))
        self.assertEqual(env["PYTHONUSERBASE"], str(local_tool_env.python_user_base_dir()))
        self.assertEqual(env["GOBIN"], str(local_tool_env.go_bin_dir()))
        self.assertEqual(path_parts[0], str(local_tool_env.npm_bin_dir()))
        self.assertIn(str(local_tool_env.python_bin_dir()), path_parts)


class NpmCliExtensionsTests(unittest.TestCase):
    def test_build_extension_snapshot_derives_binary_name_from_package(self):
        with patch.object(npm_cli_extensions._shared, "_find_npm_binary", return_value="/usr/bin/npm"), \
             patch.object(npm_cli_extensions, "_find_installed_binary", return_value="/tmp/bin/codex"), \
             patch.object(npm_cli_extensions, "_binary_version", return_value="codex 1.2.3"):
            snapshot = npm_cli_extensions.build_extension_snapshot("@openai/codex")

        self.assertEqual(snapshot["package_name"], "@openai/codex")
        self.assertEqual(snapshot["binary_name"], "codex")
        self.assertEqual(snapshot["binary"], "/tmp/bin/codex")
        self.assertTrue(snapshot["installed"])

    def test_build_extension_snapshot_maps_known_claude_alias(self):
        with patch.object(npm_cli_extensions._shared, "_find_npm_binary", return_value="/usr/bin/npm"), \
             patch.object(npm_cli_extensions, "_find_installed_binary", return_value="/tmp/bin/claude"), \
             patch.object(npm_cli_extensions, "_binary_version", return_value="1.0.0"):
            snapshot = npm_cli_extensions.build_extension_snapshot("claude")

        self.assertEqual(snapshot["package_name"], "@anthropic-ai/claude-code")
        self.assertEqual(snapshot["binary_name"], "claude")
        self.assertIn("--prefix", snapshot["install_command"])
        self.assertIn(str(local_tool_env.npm_prefix_dir()), snapshot["install_command"])

    def test_install_npm_cli_extension_returns_manual_required_when_npm_missing(self):
        with patch.object(npm_cli_extensions._shared, "_find_npm_binary", return_value=""), \
             patch.object(npm_cli_extensions, "_find_installed_binary", return_value=""):
            result = npm_cli_extensions.install_npm_cli_extension("@openai/codex")

        self.assertEqual(result["status"], "manual_required")
        self.assertIn("npm", result["message"].lower())
        self.assertIn("@openai/codex", result["command_preview"])

    def test_install_npm_cli_extension_runs_install_and_refreshes_detection(self):
        with patch.object(npm_cli_extensions._shared, "_find_npm_binary", return_value="/usr/bin/npm"), \
             patch.object(
                 npm_cli_extensions._shared,
                 "_run_command",
                 return_value=CompletedProcess(["/usr/bin/npm", "install"], 0, "installed", ""),
             ) as run_command, \
             patch.object(npm_cli_extensions, "_find_installed_binary", side_effect=["", "/tmp/bin/example"]), \
             patch.object(npm_cli_extensions, "_binary_version", return_value="example 1.0.0"):
            result = npm_cli_extensions.install_npm_cli_extension("example-cli", "example")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["extension"]["binary"], "/tmp/bin/example")
        self.assertEqual(result["extension"]["version"], "example 1.0.0")
        install_parts = run_command.call_args.args[0]
        self.assertIn("--prefix", install_parts)
        self.assertIn(str(local_tool_env.npm_prefix_dir()), install_parts)

    def test_install_npm_cli_extension_rejects_invalid_package_name(self):
        with self.assertRaises(ValueError):
            npm_cli_extensions.install_npm_cli_extension("not valid!", "tool")


class ConsoleCommandTests(unittest.TestCase):
    def test_install_command_returns_usage_when_missing_package(self):
        result = console_commands.maybe_handle_console_command("/install")

        self.assertIsNotNone(result)
        self.assertEqual(result["command"], "install")
        self.assertIn("Usage:", result["response"])

    def test_install_command_supports_install_cli_alias(self):
        with patch.object(
            console_commands.npm_cli_extensions,
            "install_npm_cli_extension",
            return_value={
                "status": "completed",
                "message": "Installed.",
                "command_preview": "npm install --global --prefix /tmp/axon/tools/npm @openai/codex",
                "extension": {
                    "package_name": "@openai/codex",
                    "binary_name": "codex",
                    "binary": "/tmp/axon/tools/npm/bin/codex",
                    "install_root": "/tmp/axon/tools",
                },
            },
        ) as install_extension:
            result = console_commands.maybe_handle_console_command("/install-cli codex")

        self.assertIsNotNone(result)
        self.assertEqual(result["command"], "install")
        self.assertEqual(result["data"]["package_name"], "@openai/codex")
        self.assertIn("Binary:", result["response"])
        install_extension.assert_called_once_with("codex", "")
