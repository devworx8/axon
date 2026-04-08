from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from axon_core import agent_file_actions
from axon_core.agent_delete_intent import has_explicit_delete_intent
from axon_core.agent_toolspecs import AgentRuntimeDeps


async def _fake_stream(*_args, **_kwargs):
    if False:
        yield ""


def _deps(tool_registry: dict):
    return AgentRuntimeDeps(
        tool_registry=tool_registry,
        normalize_tool_args=lambda _name, args: args,
        stream_cli=_fake_stream,
        stream_api_chat=_fake_stream,
        stream_ollama_chat=_fake_stream,
        ollama_execution_profile_sync=lambda *args, **kwargs: {"model": "dummy"},
        ollama_message_with_images=lambda text, images: {"role": "user", "content": text},
        api_message_with_images=lambda text, images: {"role": "user", "content": text},
        cli_message_with_images=lambda text, images: {"role": "user", "content": text},
        find_cli=lambda path: path,
        ollama_default_model="dummy",
        ollama_agent_model="dummy",
        db_path=Path(tempfile.gettempdir()) / "axon-agent-delete-intent.db",
    )


class AgentDeleteIntentTests(unittest.TestCase):
    def test_has_explicit_delete_intent_for_positive_request(self):
        self.assertTrue(has_explicit_delete_intent("Please delete /tmp/demo.txt"))

    def test_has_explicit_delete_intent_ignores_negation(self):
        self.assertFalse(has_explicit_delete_intent("Do not delete the file - print it"))

    def test_has_explicit_delete_intent_ignores_questions(self):
        self.assertFalse(has_explicit_delete_intent("Why did you delete that file?"))

    def test_direct_action_does_not_route_negated_delete_to_delete_tool(self):
        deps = _deps({"delete_file": lambda path: f"Deleted {path}"})
        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent_file_actions._direct_agent_action(
                "Do not delete the file - print it",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )
        self.assertIsNone(result)

    def test_direct_action_routes_explicit_delete_request(self):
        deps = _deps({"delete_file": lambda path: f"Deleted {path}"})
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "demo.txt")
            result = agent_file_actions._direct_agent_action(
                f"Please delete {target}",
                history=[],
                project_name="Axon",
                workspace_path=tmpdir,
                deps=deps,
            )
        self.assertIsNotNone(result)
        tool_name, tool_args, tool_result, _answer = result
        self.assertEqual(tool_name, "delete_file")
        self.assertEqual(tool_args["path"], target)
        self.assertEqual(tool_result, f"Deleted {target}")


if __name__ == "__main__":
    unittest.main()
