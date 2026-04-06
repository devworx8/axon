from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from axon_api.routes import companion as companion_routes
from axon_api.services import auth_runtime_state, companion_live, companion_runtime, companion_voice_runtime, connector_attention, sentry_bridge


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
    async def test_process_voice_turn_uses_fast_path_for_workspace_question(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain", "git_branch": "main"}
        user_turn = {"id": 100, "role": "user", "content": "What is the workspace path?"}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Path: /home/edp/.devbrain"}
        refreshed_session = dict(session) | {"summary": "Path: /home/edp/.devbrain"}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])) as record_mock, \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "chat", AsyncMock()) as chat_mock:
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="What is the workspace path?",
                transcript="What is the workspace path?",
            )

        self.assertIn("/home/edp/.devbrain", result["response_text"])
        self.assertEqual(result["tokens_used"], 0)
        self.assertEqual(result["voice_mode"], "")
        self.assertEqual(result["live"]["focus"]["workspace"]["path"], "/home/edp/.devbrain")
        chat_mock.assert_not_awaited()
        self.assertEqual(record_mock.await_count, 2)

    async def test_process_voice_turn_uses_fast_path_for_day_plan_prompt(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain", "git_branch": "main"}
        user_turn = {"id": 100, "role": "user", "content": "How should I structure today's work?"}
        assistant_turn = {"id": 101, "role": "assistant", "content": "No urgent inbox items are flagged right now."}
        refreshed_session = dict(session) | {"summary": "No urgent inbox items are flagged right now."}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])) as record_mock, \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "chat", AsyncMock()) as chat_mock:
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="How should I structure today's work?",
                transcript="How should I structure today's work?",
            )

        self.assertIn("Focus workspace: Axon", result["response_text"])
        self.assertIn("No urgent inbox items are flagged right now.", result["response_text"])
        self.assertEqual(result["tokens_used"], 0)
        chat_mock.assert_not_awaited()
        self.assertEqual(record_mock.await_count, 2)

    async def test_process_voice_turn_upgrades_to_agent_for_local_operator_request(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain"}
        user_turn = {"id": 100, "role": "user", "content": "List the top-level files"}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Top-level files: README.md"}
        refreshed_session = dict(session) | {"summary": "Top-level files: README.md", "agent_session_id": "agent-123"}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)) as touch_mock, \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])), \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "_requires_local_operator_execution", return_value=True), \
             patch.object(companion_runtime.companion_agent_bridge, "run_companion_agent_turn", AsyncMock(return_value={
                 "response_text": "Top-level files: README.md",
                 "tokens_used": 0,
                 "backend": "agent",
                 "approval_required": {"message": "Approval required.", "approval_action": {"session_id": "agent-123"}},
                 "agent_session_id": "agent-123",
                 "tool_events": [{"type": "tool_call"}],
             })) as agent_mock:
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="List the top-level files",
                transcript="List the top-level files",
            )

        self.assertEqual(result["backend"], "agent")
        self.assertEqual(result["approval_required"]["message"], "Approval required.")
        agent_mock.assert_awaited_once()
        touch_kwargs = touch_mock.await_args.kwargs
        self.assertEqual(touch_kwargs["status"], "awaiting_approval")
        self.assertEqual(touch_kwargs["agent_session_id"], "agent-123")

    async def test_process_voice_turn_creates_reply_and_updates_session(self):
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
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])) as record_mock, \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_voice_runtime, "resolve_companion_voice_model_candidates", AsyncMock(return_value=[{"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.1-codex-mini"}])), \
             patch.object(companion_voice_runtime, "resolve_companion_voice_model_kwargs", AsyncMock(return_value={"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.1-codex-mini"})), \
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
        self.assertEqual(result["tokens_used"], 42)
        self.assertEqual(result["session"]["id"], 7)
        self.assertEqual(result["live"]["focus"]["workspace"]["name"], "Axon")
        chat_mock.assert_awaited_once()
        self.assertEqual(record_mock.await_count, 2)

    async def test_process_voice_turn_times_out_to_local_fallback(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain", "git_branch": "main"}
        user_turn = {"id": 100, "role": "user", "content": "Explain the dashboard refactor approach."}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Fallback reply"}
        refreshed_session = dict(session) | {"summary": "Fallback reply"}

        async def slow_chat(**_kwargs):
            await asyncio.sleep(0.05)
            return {"content": "Too slow", "tokens": 99}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 1, "waiting_on_me": 2, "watch": 3}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])), \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "_requires_local_operator_execution", return_value=False), \
             patch.object(companion_voice_runtime, "resolve_companion_voice_model_candidates", AsyncMock(return_value=[{"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.1-codex-mini"}])), \
             patch.object(companion_voice_runtime, "resolve_companion_voice_model_kwargs", AsyncMock(return_value={"backend": "cli", "cli_path": "/tmp/codex", "cli_model": "gpt-5.1-codex-mini"})), \
             patch.object(companion_voice_runtime, "companion_voice_timeout_seconds", return_value=0.01), \
             patch.object(companion_voice_runtime.brain, "chat", AsyncMock(side_effect=slow_chat)):
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="Explain the dashboard refactor approach.",
                transcript="Explain the dashboard refactor approach.",
            )

        self.assertEqual(result["backend"], "local_timeout")
        self.assertEqual(result["tokens_used"], 0)
        self.assertIn("quick-response budget", result["response_text"])

    async def test_process_voice_turn_fails_over_to_next_runtime_candidate(self):
        fake_db = object()
        session = {"id": 7, "workspace_id": 202, "session_key": "companion:1:202:", "summary": ""}
        project = {"id": 202, "name": "Axon", "path": "/home/edp/.devbrain"}
        user_turn = {"id": 100, "role": "user", "content": "Explain the dashboard refactor approach."}
        assistant_turn = {"id": 101, "role": "assistant", "content": "Use the open issues list and start with the most urgent task."}
        refreshed_session = dict(session) | {"summary": assistant_turn["content"]}

        async def voice_chat(**kwargs):
            if kwargs.get("api_provider") == "anthropic":
                raise RuntimeError("Anthropic credits exhausted")
            return {"content": "Use the open issues list and start with the most urgent task.", "tokens": 21}

        with patch.object(companion_runtime, "get_project", AsyncMock(return_value=project)), \
             patch.object(companion_runtime, "get_all_settings", AsyncMock(return_value={"ai_backend": "cli", "cli_runtime_path": "/tmp/codex", "cli_runtime_model": "gpt-5.4"})), \
             patch.object(companion_runtime, "get_companion_session", AsyncMock(return_value=refreshed_session)), \
             patch.object(companion_runtime, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(companion_runtime, "attention_summary", AsyncMock(return_value={"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}})), \
             patch.object(companion_runtime.companion_sessions_service, "ensure_companion_session", AsyncMock(return_value=session)), \
             patch.object(companion_runtime.companion_sessions_service, "touch_companion_session", AsyncMock(return_value=True)), \
             patch.object(companion_runtime.companion_voice_service, "record_companion_voice_turn", AsyncMock(side_effect=[user_turn, assistant_turn])), \
             patch.object(companion_runtime.companion_voice_service, "list_recent_companion_voice_turns", AsyncMock(return_value=[user_turn])), \
             patch.object(companion_runtime.brain, "_requires_local_operator_execution", return_value=False), \
             patch.object(companion_voice_runtime, "resolve_companion_voice_model_candidates", AsyncMock(return_value=[
                 {"backend": "api", "api_provider": "anthropic", "api_key": "a", "api_base_url": "https://api.anthropic.com/v1", "api_model": "claude-haiku-4-5"},
                 {"backend": "api", "api_provider": "deepseek", "api_key": "d", "api_base_url": "https://api.deepseek.com/v1", "api_model": "deepseek-chat"},
             ])), \
             patch.object(companion_voice_runtime.brain, "chat", AsyncMock(side_effect=voice_chat)):
            result = await companion_runtime.process_companion_voice_turn(
                fake_db,
                device_id=1,
                workspace_id=202,
                content="Explain the dashboard refactor approach.",
                transcript="Explain the dashboard refactor approach.",
            )

        self.assertEqual(result["backend"], "api")
        self.assertEqual(result["tokens_used"], 21)
        self.assertEqual(result["response_text"], "Use the open issues list and start with the most urgent task.")


class CompanionLiveSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_live_snapshot_includes_operator_and_focus_workspace(self):
        snapshot = {
            "active": True,
            "mode": "agent",
            "phase": "execute",
            "title": "Running tests",
            "detail": "Axon is checking the repo.",
            "workspace_id": 9,
            "updated_at": "2026-04-04T00:00:00Z",
            "feed": [{"id": "1"}],
        }
        with patch.dict(companion_live.LIVE_OPERATOR_SNAPSHOT, snapshot, clear=True), \
             patch.object(companion_live, "get_project", AsyncMock(return_value={"id": 9, "name": "Dashpro", "path": "/tmp/dashpro", "git_branch": "development"})), \
             patch.object(companion_live, "get_companion_session", AsyncMock(return_value={"id": 4, "workspace_id": 9})), \
             patch.object(companion_live, "get_companion_presence", AsyncMock(return_value={"device_id": 7, "workspace_id": 9})):
            result = await companion_live.build_companion_live_snapshot(object(), device_id=7, session_id=4)

        self.assertTrue(result["operator"]["active"])
        self.assertEqual(result["operator"]["workspace_name"], "Dashpro")
        self.assertEqual(result["focus"]["workspace"]["path"], "/tmp/dashpro")


class AuthRuntimeStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_middleware_allows_options_preflight(self):
        request = SimpleNamespace(method="OPTIONS", url=SimpleNamespace(path="/api/attention/summary"))
        called = False

        async def call_next(_request):
            nonlocal called
            called = True
            return {"ok": True}

        response = await auth_runtime_state.auth_middleware(
            request,
            call_next,
            dev_local_auth_bypass_active_fn=lambda _request: False,
            db_module=SimpleNamespace(get_db=None),
            extract_session_token_fn=lambda _request: "",
            valid_session_async_fn=AsyncMock(return_value=False),
            json_response_cls=lambda body, status_code=200: {"body": body, "status_code": status_code},
        )

        self.assertTrue(called)
        self.assertEqual(response, {"ok": True})

    async def test_auth_middleware_accepts_companion_bearer_for_safe_mobile_paths(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_get_setting(_conn, key):
            self.assertEqual(key, "auth_pin_hash")
            return "enabled"

        request = SimpleNamespace(
            method="GET",
            url=SimpleNamespace(path="/api/attention/summary"),
            headers={"Authorization": "Bearer companion-token"},
            query_params={},
        )

        async def call_next(_request):
            return {"ok": True}

        response = await auth_runtime_state.auth_middleware(
            request,
            call_next,
            dev_local_auth_bypass_active_fn=lambda _request: False,
            db_module=SimpleNamespace(get_db=fake_db, get_setting=fake_get_setting),
            extract_session_token_fn=lambda _request: "",
            valid_session_async_fn=AsyncMock(return_value=True),
            json_response_cls=lambda body, status_code=200: {"body": body, "status_code": status_code},
        )

        self.assertEqual(response, {"ok": True})


class CompanionRouteScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_companion_devices_only_returns_authenticated_device(self):
        request = SimpleNamespace()
        device_row = {"id": 7, "name": "Phone A", "device_key": "phone-a"}

        with patch.object(companion_routes, "_require_companion_context", AsyncMock(return_value=("", {}, device_row))):
            result = await companion_routes.companion_devices(request)

        self.assertEqual(result["devices"], [device_row])

    async def test_companion_session_detail_blocks_other_device_session(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        request = SimpleNamespace()
        device_row = {"id": 7}
        session_row = {"id": 11, "device_id": 99, "session_key": "other"}

        with patch.object(companion_routes, "_require_companion_context", AsyncMock(return_value=("", {}, device_row))), \
             patch.object(companion_routes, "get_db", fake_db), \
             patch.object(companion_routes, "get_companion_session", AsyncMock(return_value=session_row)):
            with self.assertRaises(HTTPException) as exc:
                await companion_routes.companion_session_detail(11, request)

        self.assertEqual(exc.exception.status_code, 403)

    async def test_auth_middleware_accepts_companion_bearer_for_mobile_control_path(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_get_setting(_conn, key):
            self.assertEqual(key, "auth_pin_hash")
            return "enabled"

        request = SimpleNamespace(
            method="GET",
            url=SimpleNamespace(path="/api/mobile/actions/capabilities"),
            headers={"Authorization": "Bearer companion-token"},
            query_params={},
        )

        async def call_next(_request):
            return {"ok": True}

        response = await auth_runtime_state.auth_middleware(
            request,
            call_next,
            dev_local_auth_bypass_active_fn=lambda _request: False,
            db_module=SimpleNamespace(get_db=fake_db, get_setting=fake_get_setting),
            extract_session_token_fn=lambda _request: "",
            valid_session_async_fn=AsyncMock(return_value=True),
            json_response_cls=lambda body, status_code=200: {"body": body, "status_code": status_code},
        )

        self.assertEqual(response, {"ok": True})

    async def test_auth_middleware_accepts_companion_bearer_for_mcp_path(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        async def fake_get_setting(_conn, key):
            self.assertEqual(key, "auth_pin_hash")
            return "enabled"

        request = SimpleNamespace(
            method="GET",
            url=SimpleNamespace(path="/api/mcp/servers"),
            headers={"Authorization": "Bearer companion-token"},
            query_params={},
        )

        async def call_next(_request):
            return {"ok": True}

        response = await auth_runtime_state.auth_middleware(
            request,
            call_next,
            dev_local_auth_bypass_active_fn=lambda _request: False,
            db_module=SimpleNamespace(get_db=fake_db, get_setting=fake_get_setting),
            extract_session_token_fn=lambda _request: "",
            valid_session_async_fn=AsyncMock(return_value=True),
            json_response_cls=lambda body, status_code=200: {"body": body, "status_code": status_code},
        )

        self.assertEqual(response, {"ok": True})


if __name__ == "__main__":
    unittest.main()
