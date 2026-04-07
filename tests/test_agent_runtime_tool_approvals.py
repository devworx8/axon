from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from axon_core import agent_runtime_tools, approval_actions


def _build_registry(*, tool_path_allowed, action_is_allowed):
    return agent_runtime_tools.build_tool_registry(
        current_agent_runtime_context_fn=lambda: {"workspace_id": 7, "agent_session_id": "agent-7"},
        tool_path_allowed_fn=tool_path_allowed,
        action_is_allowed_fn=action_is_allowed,
        workspace_root_fn=lambda: "/home/edp/.devbrain",
        active_workspace_root_fn=lambda: "/home/edp/.devbrain",
        effective_allowed_cmds_fn=lambda: {"git", "grep"},
        build_command_approval_action=approval_actions.build_command_approval_action,
        build_edit_approval_action=approval_actions.build_edit_approval_action,
        normalize_command_preview=approval_actions.normalize_command_preview,
        db_path=Path("/tmp/axon-runtime-tools.db"),
    )


class AgentRuntimeToolApprovalTests(unittest.TestCase):
    def test_read_file_outside_allowed_directories_emits_exact_approval_block(self):
        captured: list[dict] = []
        registry = _build_registry(
            tool_path_allowed=lambda _path: False,
            action_is_allowed=lambda action: captured.append(dict(action)) or False,
        )

        target = "/home/edp/Documents/demo.pdf"
        result = registry["read_file"](target)

        self.assertEqual(result, f"BLOCKED_EDIT:read:{target}")
        self.assertEqual(captured[0]["action_type"], "file_read")
        self.assertEqual(captured[0]["path"], target)

    def test_read_file_outside_allowed_directories_succeeds_after_exact_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "report.txt"
            target.write_text("mission ready", encoding="utf-8")
            registry = _build_registry(
                tool_path_allowed=lambda _path: False,
                action_is_allowed=lambda _action: True,
            )

            result = registry["read_file"](str(target))

        self.assertIn("mission ready", result)
        self.assertIn(str(target), result)

    def test_delete_file_is_registered_and_respects_edit_approval(self):
        captured: list[dict] = []
        registry = _build_registry(
            tool_path_allowed=lambda _path: False,
            action_is_allowed=lambda action: captured.append(dict(action)) or False,
        )

        target = "/home/edp/Documents/demo.txt"
        result = registry["delete_file"](target)

        self.assertEqual(result, f"BLOCKED_EDIT:delete:{target}")
        self.assertEqual(captured[0]["action_type"], "file_delete")
        self.assertEqual(captured[0]["path"], target)

    def test_edit_file_updates_content_after_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "report.txt"
            target.write_text("mission ready", encoding="utf-8")
            registry = _build_registry(
                tool_path_allowed=lambda _path: False,
                action_is_allowed=lambda _action: True,
            )

            result = registry["edit_file"](str(target), "mission", "system")

            self.assertIn("Edited", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "system ready")


if __name__ == "__main__":
    unittest.main()
