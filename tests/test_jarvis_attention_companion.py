from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from axon_api.services import companion_runtime, connector_attention, sentry_bridge


class ConnectorAttentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_vercel_attention_creates_review_item_for_inferred_link(self):
        fake_db = object()
        project = {"id": 17, "name": "Vercel Demo", "path": "/tmp/vercel-demo"}
        relationships = [
            {
                "workspace_id": 17,
                "external_system": "vercel",
                "external_id": "prj_123",
                "status": "inferred",
                "source": "inferred",
                "meta_json": '{"project_id":"prj_123","org_id":"team_456"}',
            }
        ]
        ingested = {"id": 91, "item_type": "vercel_link_review", "workspace_id": 17}

        with patch.object(connector_attention, "get_project", AsyncMock(return_value=project)), \
             patch.object(connector_attention, "list_workspace_relationships_for_workspace", AsyncMock(return_value=relationships)), \
             patch.object(connector_attention, "ingest_attention_signal", AsyncMock(return_value=ingested)) as ingest_mock:
            items = await connector_attention.sync_vercel_attention(fake_db, workspace_id=17)

        self.assertEqual(items, [ingested])
        ingest_mock.assert_awaited_once()
        kwargs = ingest_mock.await_args.kwargs
        self.assertEqual(kwargs["item_type"], "vercel_link_review")
        self.assertEqual(kwargs["workspace_id"], 17)


class SentryBridgeAttentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_ingests_attention_with_resolved_workspace(self):
        payload = {
            "action": "created",
            "data": {
                "issue": {
                    "id": "issue-1",
                    "title": "Crash in checkout flow",
                    "level": "error",
                    "culprit": "checkout.tsx",
                    "permalink": "https://sentry.example/issues/1",
                    "project": {"slug": "sentrydemo"},
                }
            },
        }

        @asynccontextmanager
        async def fake_db():
            yield object()

        with patch.object(sentry_bridge, "get_db", fake_db), \
             patch.object(sentry_bridge, "resolve_workspace_for_connector_signal", AsyncMock(return_value=44)), \
             patch.object(sentry_bridge, "ingest_error_event", AsyncMock(return_value=5)), \
             patch.object(sentry_bridge, "ingest_attention_signal", AsyncMock(return_value={"id": 12, "workspace_id": 44})) as ingest_mock:
            result = await sentry_bridge.handle_sentry_webhook(payload)

        self.assertEqual(result["status"], "ingested")
        ingest_mock.assert_awaited_once()
        kwargs = ingest_mock.await_args.kwargs
        self.assertEqual(kwargs["workspace_id"], 44)
        self.assertEqual(kwargs["item_type"], "sentry_issue")


class CompanionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_voice_turn_creates_reply_and_updates_session(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain"}
        user_turn = {"id": 100, "role": "user", "content": "What needs attention?"}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Voice reply ready."}
        refreshed_session = dict(session) | {"summary": "Voice reply ready."}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 1, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])) as record_mock, \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "chat", AsyncMock(return_value={"content": "Voice reply ready.", "tokens": 42})) as chat_mock:
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="What needs attention?",
                transcript="What needs attention?",
            )

        self.assertEqual(result["response_text"], "Voice reply ready.")
        self.assertEqual(result["tokens_used"], 42)
        self.assertEqual(result["session"]["id"], 7)
        chat_mock.assert_awaited_once()
        self.assertEqual(record_mock.await_count, 2)


if __name__ == "__main__":
    unittest.main()
