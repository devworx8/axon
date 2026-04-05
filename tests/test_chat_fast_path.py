from __future__ import annotations

import unittest

from axon_api.services import chat_context_state


class ChatFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_task_question_still_uses_workspace_snapshot(self):
        payload = await chat_context_state.maybe_local_fast_chat_response(
            object(),
            lambda value: value,
            object(),
            user_message="What open tasks do I have right now?",
            project_id=7,
            settings={"external_fetch_policy": "cache_first"},
            snapshot_bundle={
                "data": {
                    "tasks": [
                        {"title": "Repair deploy lane", "status": "open"},
                        {"title": "Review approvals", "status": "in_progress"},
                    ]
                }
            },
            memory_bundle_payload={"items": []},
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["evidence_source"], "workspace_snapshot")
        self.assertIn("Repair deploy lane", payload["content"])

    async def test_capability_question_with_tasks_gets_orchestration_fast_answer(self):
        payload = await chat_context_state.maybe_local_fast_chat_response(
            object(),
            lambda value: value,
            object(),
            user_message="Can you connect to GPTs and use them for other tasks and monitor them while they do those tasks?",
            project_id=7,
            settings={
                "external_fetch_policy": "cache_first",
                "openai_gpts_enabled": "1",
                "gemini_gems_enabled": "0",
                "cloud_agents_enabled": "1",
            },
            snapshot_bundle={
                "data": {
                    "tasks": [
                        {"title": "Repair deploy lane", "status": "open"},
                    ]
                }
            },
            memory_bundle_payload={"items": []},
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["evidence_source"], "capabilities")
        self.assertIn("Partly.", payload["content"])
        self.assertIn("OpenAI GPT routing", payload["content"])
        self.assertIn("worker heartbeats", payload["content"])


if __name__ == "__main__":
    unittest.main()
