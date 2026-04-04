from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from axon_api.routes import mobile_control
from axon_api.services import (
    mobile_action_preflight,
    mobile_control_executor,
    mobile_control_policy,
    mobile_mcp_registry,
    mobile_platform_snapshot,
    mobile_vercel_actions,
)


class MobileControlExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workspace_inspect_returns_workspace_summary(self):
        capability = {
            "action_type": "workspace.inspect",
            "risk_tier": "observe",
            "available": True,
            "meta_json": '{"label":"Inspect workspace"}',
        }
        inspection = {
            "workspace": {"id": 22, "name": "Dashpro"},
            "repo": {"branch": "development", "dirty": True},
            "connector_reconcile": {"status": "blocked", "planned_repairs": []},
            "summary": "Dashpro on development · 3 local change(s)",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 1, "summary": "ok"})), \
             patch.object(mobile_control_executor, "execute_workspace_inspect", AsyncMock(return_value=inspection)):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=4,
                workspace_id=22,
                action_type="workspace.inspect",
                payload={"workspace_id": 22},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["workspace"]["name"], "Dashpro")
        self.assertTrue(result["result"]["repo"]["dirty"])
        self.assertIn("Dashpro", result["result"]["summary"])

    async def test_execute_workspace_connector_reconcile_returns_result(self):
        capability = {
            "action_type": "workspace.connectors.reconcile",
            "risk_tier": "act",
            "available": True,
            "meta_json": '{"label":"Repair connectors"}',
        }
        reconcile_result = {
            "status": "partial",
            "changes_applied": 1,
            "blocked_repairs": 1,
            "summary": "Applied 1 repair(s); blocked 1 unsafe repair(s).",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_control_executor, "execute_workspace_connector_reconcile", AsyncMock(return_value=reconcile_result)), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 2, "summary": "ok"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=4,
                workspace_id=22,
                action_type="workspace.connectors.reconcile",
                payload={"workspace_id": 22},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["status"], "partial")
        self.assertEqual(result["result"]["changes_applied"], 1)

    async def test_execute_destructive_action_creates_challenge(self):
        capability = {
            "action_type": "runtime.permissions.set",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Change permissions"}',
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_control_executor, "create_destructive_challenge", AsyncMock(return_value={"id": 91, "action_type": "runtime.permissions.set"})), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 12, "status": "challenge_required"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=None,
                action_type="runtime.permissions.set",
                payload={"mode": "full_access"},
            )

        self.assertEqual(result["status"], "challenge_required")
        self.assertEqual(result["challenge"]["id"], 91)

    async def test_execute_vercel_promote_blocks_when_vercel_token_missing(self):
        capability = {
            "action_type": "vercel.deploy.promote",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Deploy"}',
        }

        error = mobile_action_preflight.MobileVercelActionError(
            "Vercel deploy actions need a Vercel access token.",
            outcome="missing_vercel_token",
            result_payload={"workspace_id": 2},
        )

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_action_preflight, "prepare_vercel_action_request", AsyncMock(side_effect=error)), \
             patch.object(mobile_action_preflight, "record_action_receipt", AsyncMock(return_value={"id": 14, "status": "blocked"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=2,
                action_type="vercel.deploy.promote",
                payload={"workspace_id": 2},
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["result"]["workspace_id"], 2)

    async def test_execute_vercel_promote_creates_challenge_with_prepared_payload(self):
        capability = {
            "action_type": "vercel.deploy.promote",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Deploy"}',
        }
        prepared = {
            "payload": {"workspace_id": 2, "deployment_id": "dep_123", "deployment_url": "https://preview.example.vercel.app"},
            "title": "Deploy",
            "summary": "Promote https://preview.example.vercel.app to production for dashpro.",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_action_preflight, "prepare_vercel_action_request", AsyncMock(return_value=prepared)), \
             patch.object(mobile_control_executor, "create_destructive_challenge", AsyncMock(return_value={"id": 22, "summary": prepared["summary"]})), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 23, "status": "challenge_required"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=2,
                action_type="vercel.deploy.promote",
                payload={"workspace_id": 2},
            )

        self.assertEqual(result["status"], "challenge_required")
        self.assertEqual(result["challenge"]["id"], 22)
        self.assertEqual(result["receipt"]["status"], "challenge_required")

    async def test_execute_preview_restart_returns_preview_payload(self):
        capability = {
            "action_type": "workspace.preview.restart",
            "risk_tier": "act",
            "available": True,
            "meta_json": '{"label":"Restart preview"}',
        }
        preview_payload = {
            "workspace_id": 22,
            "summary": "Preview running for Dashpro.",
            "preview": {"status": "running", "url": "http://127.0.0.1:3000"},
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_control_executor, "restart_workspace_preview", AsyncMock(return_value=preview_payload)), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 18, "summary": "Preview running"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=4,
                workspace_id=22,
                action_type="workspace.preview.restart",
                payload={"workspace_id": 22},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["preview"]["status"], "running")

    async def test_execute_expo_project_status_returns_project_summary(self):
        capability = {
            "action_type": "expo.project.status",
            "risk_tier": "observe",
            "available": True,
            "meta_json": '{"label":"Expo status"}',
        }
        expo_result = {
            "status": "ready",
            "project_name": "Axon Online",
            "summary": "Axon Online · ready",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_action_preflight, "prepare_expo_action_request", AsyncMock(return_value={"payload": {"workspace_id": 202}, "title": "Expo status", "summary": "Inspect Expo / EAS status for Axon Online."})), \
             patch.object(mobile_control_executor, "execute_expo_status_action", AsyncMock(return_value=expo_result)), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 31, "summary": "Expo ready"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=4,
                workspace_id=202,
                action_type="expo.project.status",
                payload={"workspace_id": 202},
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["project_name"], "Axon Online")

    async def test_execute_expo_publish_creates_challenge(self):
        capability = {
            "action_type": "expo.update.publish",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Publish update"}',
        }
        prepared = {
            "payload": {"workspace_id": 202, "project_root": "/tmp/axon-online", "branch": "production"},
            "title": "Publish update",
            "summary": "Publish an Expo update to production for Axon Online.",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_action_preflight, "prepare_expo_action_request", AsyncMock(return_value=prepared)), \
             patch.object(mobile_control_executor, "create_destructive_challenge", AsyncMock(return_value={"id": 41, "action_type": "expo.update.publish"})), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 42, "status": "challenge_required"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=202,
                action_type="expo.update.publish",
                payload={"workspace_id": 202},
            )

        self.assertEqual(result["status"], "challenge_required")
        self.assertEqual(result["challenge"]["id"], 41)


class MobileControlPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_seeded_control_capability_returns_existing_row_without_reseed(self):
        existing = {
            "action_type": "workspace.inspect",
            "system_name": "workspace",
            "scope": "workspace",
            "risk_tier": "observe",
            "mobile_direct_allowed": 1,
            "destructive": 0,
            "available": 1,
            "description": "Inspect the active workspace and return a concise operational summary.",
            "meta_json": '{"label":"Inspect workspace","quick_action":"inspect"}',
        }

        with patch.object(mobile_control_policy, "get_control_capability", AsyncMock(return_value=existing)), \
             patch.object(mobile_control_policy, "seed_control_capabilities", AsyncMock()) as seed:
            result = await mobile_control_policy.get_seeded_control_capability(object(), "workspace.inspect")

        seed.assert_not_awaited()
        self.assertEqual(result["action_type"], "workspace.inspect")

    async def test_seed_control_capabilities_skips_upserts_when_catalog_already_present(self):
        class _FakeDb:
            def __init__(self):
                self.commit = AsyncMock()

        rows = [
            {
                "action_type": str(capability["action_type"]),
                "system_name": str(capability.get("system_name") or "axon"),
                "scope": str(capability.get("scope") or "global"),
                "risk_tier": str(capability.get("risk_tier") or "observe"),
                "mobile_direct_allowed": 1 if capability.get("mobile_direct_allowed") else 0,
                "destructive": 1 if capability.get("destructive") else 0,
                "available": 1 if capability.get("available", True) else 0,
                "description": str(capability.get("description") or ""),
                "meta_json": mobile_control_policy._json_meta(capability.get("meta") if isinstance(capability.get("meta"), dict) else {}),
            }
            for capability in mobile_control_policy.CONTROL_CAPABILITY_CATALOG
        ]

        fake_db = _FakeDb()
        with patch.object(mobile_control_policy, "list_control_capabilities", AsyncMock(return_value=rows)), \
             patch.object(mobile_control_policy, "upsert_control_capability", AsyncMock()) as upsert:
            result = await mobile_control_policy.seed_control_capabilities(fake_db)

        upsert.assert_not_awaited()
        fake_db.commit.assert_not_awaited()
        self.assertEqual(len(result), len(rows))


class MobileControlRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_mobile_action_execute_maps_value_error_to_bad_request(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace(commit=AsyncMock())

        request = SimpleNamespace()
        body = mobile_control.TypedActionRequest(action_type="workspace.inspect", workspace_id=None, payload={})

        with patch.object(mobile_control, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_control, "get_db", fake_db), \
             patch.object(mobile_control, "execute_typed_action", AsyncMock(side_effect=ValueError("workspace.inspect requires a workspace_id"))):
            with self.assertRaises(HTTPException) as exc:
                await mobile_control.mobile_action_execute(request, body)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("workspace_id", str(exc.exception.detail))

    async def test_mobile_challenge_confirm_maps_value_error_to_bad_request(self):
        @asynccontextmanager
        async def fake_db():
            challenge = {
                "id": 91,
                "device_id": 7,
                "status": "pending",
                "session_id": None,
                "workspace_id": 22,
                "action_type": "runtime.restart",
                "expires_at": "",
            }
            commit = AsyncMock()
            yield SimpleNamespace(commit=commit, challenge=challenge)

        async def fake_get_risk_challenge(_db, _challenge_id):
            return {"id": 91, "device_id": 7, "status": "pending", "session_id": None, "workspace_id": 22, "action_type": "runtime.restart", "expires_at": ""}

        request = SimpleNamespace()

        with patch.object(mobile_control, "require_companion_context", AsyncMock(return_value=("", {}, {"id": 7}))), \
             patch.object(mobile_control, "get_db", fake_db), \
             patch.object(mobile_control, "get_risk_challenge", AsyncMock(side_effect=fake_get_risk_challenge)), \
             patch.object(mobile_control, "confirm_destructive_action", AsyncMock(side_effect=ValueError("Unsupported destructive action"))):
            with self.assertRaises(HTTPException) as exc:
                await mobile_control.mobile_challenge_confirm(request, 91)

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Unsupported", str(exc.exception.detail))

    async def test_confirmed_runtime_restart_executes_without_new_challenge(self):
        capability = {
            "action_type": "runtime.restart",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Restart runtime"}',
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_control_executor, "log_runtime_restart_requested", AsyncMock()), \
             patch.object(mobile_control_executor, "queue_runtime_restart", return_value={"accepted": True, "summary": "Restart queued"}), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 21, "summary": "Restart queued"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=None,
                action_type="runtime.restart",
                payload={},
                confirmed=True,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["accepted"])

    async def test_confirmed_vercel_rollback_executes_without_new_challenge(self):
        capability = {
            "action_type": "vercel.deploy.rollback",
            "risk_tier": "destructive",
            "available": True,
            "meta_json": '{"label":"Rollback"}',
        }
        prepared = {
            "payload": {"workspace_id": 2, "deployment_id": "dep_prev", "deployment_url": "https://old.example.vercel.app"},
            "title": "Rollback",
            "summary": "Roll production back to https://old.example.vercel.app for dashpro.",
        }

        with patch.object(mobile_control_executor, "get_seeded_control_capability", AsyncMock(return_value=capability)), \
             patch.object(mobile_action_preflight, "prepare_vercel_action_request", AsyncMock(return_value=prepared)), \
             patch.object(mobile_control_executor, "execute_vercel_rollback", AsyncMock(return_value={"summary": "Rolled back"})), \
             patch.object(mobile_control_executor, "record_action_receipt", AsyncMock(return_value={"id": 28, "summary": "Rolled back"})):
            result = await mobile_control_executor.execute_typed_action(
                object(),
                device_id=7,
                session_id=None,
                workspace_id=2,
                action_type="vercel.deploy.rollback",
                payload={"workspace_id": 2},
                confirmed=True,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["summary"], "Rolled back")


class MobileVercelActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_vercel_token_uses_exact_named_vault_secret(self):
        with patch.object(mobile_vercel_actions, "get_setting", AsyncMock(return_value="")), \
             patch.dict(mobile_vercel_actions.os.environ, {}, clear=True), \
             patch.object(
                 mobile_vercel_actions,
                 "vault_secret_status_by_name",
                 AsyncMock(return_value={"value": "vault-token-123", "present": True, "unlocked": True}),
             ) as vault_secret_status_by_name:
            token = await mobile_vercel_actions._vercel_token(object())

        vault_secret_status_by_name.assert_awaited_once_with(
            unittest.mock.ANY,
            secret_names=("AXON_VERCEL_TOKEN",),
        )
        self.assertEqual(token, "vault-token-123")

    async def test_vercel_token_prefers_setting_before_vault(self):
        with patch.object(mobile_vercel_actions, "get_setting", AsyncMock(return_value="setting-token-xyz")), \
             patch.object(
                 mobile_vercel_actions,
                 "vault_secret_status_by_name",
                 AsyncMock(return_value={"value": "vault-token-123", "present": True, "unlocked": True}),
             ) as vault_secret_status_by_name:
            token = await mobile_vercel_actions._vercel_token(object())

        vault_secret_status_by_name.assert_not_awaited()
        self.assertEqual(token, "setting-token-xyz")


class MissionSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_platform_snapshot_marks_urgent_with_pending_challenge(self):
        live_snapshot = {
            "at": "2026-04-04T00:00:00Z",
            "focus": {"workspace_id": 17, "workspace": {"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"}},
            "operator": {"active": False},
        }
        summary = {"counts": {"now": 0, "waiting_on_me": 1, "watch": 0}}
        inbox = {"now": [], "waiting_on_me": [], "watch": []}

        with patch.object(mobile_platform_snapshot, "seed_control_capabilities", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_companion_live_snapshot", AsyncMock(return_value=live_snapshot)), \
             patch.object(mobile_platform_snapshot, "build_mobile_axon_snapshot", AsyncMock(return_value={"status": "idle"})), \
             patch.object(mobile_platform_snapshot, "attention_summary", AsyncMock(return_value=summary)), \
             patch.object(mobile_platform_snapshot, "query_attention_inbox", AsyncMock(return_value=inbox)), \
             patch.object(mobile_platform_snapshot, "load_expo_overview", AsyncMock(return_value={"project_count": 0, "build_count": 0, "projects": []})), \
             patch.object(mobile_platform_snapshot, "get_trust_snapshot", AsyncMock(return_value={"effective_max_risk_tier": "act"})), \
             patch.object(mobile_platform_snapshot, "list_companion_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_risk_challenges", AsyncMock(return_value=[{"id": 4, "title": "Confirm rollback"}])), \
             patch.object(mobile_platform_snapshot, "list_action_receipts", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_servers", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "get_project", AsyncMock(return_value={"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"})), \
             patch.object(mobile_platform_snapshot, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_companion_voice_turns", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_workspace_cards", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_system_strip", AsyncMock(return_value=[])):
            snapshot = await mobile_platform_snapshot.build_platform_snapshot(
                object(),
                device_id=8,
                workspace_id=17,
            )

        self.assertEqual(snapshot["posture"], "urgent")
        self.assertEqual(snapshot["focus"]["workspace"]["name"], "Dashpro")
        self.assertEqual(snapshot["next_required_action"]["title"], "Confirm rollback")

    async def test_build_platform_snapshot_includes_preview_state(self):
        live_snapshot = {
            "at": "2026-04-04T00:00:00Z",
            "focus": {"workspace_id": 17, "workspace": {"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"}},
            "operator": {"active": False},
        }
        summary = {"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}}
        inbox = {"now": [], "waiting_on_me": [], "watch": []}
        preview = {"status": "running", "url": "http://127.0.0.1:3000", "healthy": True}

        with patch.object(mobile_platform_snapshot, "seed_control_capabilities", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_companion_live_snapshot", AsyncMock(return_value=live_snapshot)), \
             patch.object(mobile_platform_snapshot, "build_mobile_axon_snapshot", AsyncMock(return_value={"status": "idle"})), \
             patch.object(mobile_platform_snapshot, "attention_summary", AsyncMock(return_value=summary)), \
             patch.object(mobile_platform_snapshot, "query_attention_inbox", AsyncMock(return_value=inbox)), \
             patch.object(mobile_platform_snapshot, "load_expo_overview", AsyncMock(return_value={"project_count": 1, "build_count": 2, "projects": [{"workspace_id": 17, "project_name": "Axon Online", "status": "ready"}]})), \
             patch.object(mobile_platform_snapshot, "get_trust_snapshot", AsyncMock(return_value={"effective_max_risk_tier": "act"})), \
             patch.object(mobile_platform_snapshot, "list_companion_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_risk_challenges", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_action_receipts", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_servers", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "get_project", AsyncMock(return_value={"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"})), \
             patch.object(mobile_platform_snapshot, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_companion_voice_turns", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_workspace_cards", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_system_strip", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot.live_preview_service, "get_preview_session", return_value=preview):
            snapshot = await mobile_platform_snapshot.build_platform_snapshot(
                object(),
                device_id=8,
                workspace_id=17,
            )

        self.assertEqual(snapshot["focus"]["preview"]["status"], "running")
        self.assertEqual(snapshot["focus"]["preview"]["url"], "http://127.0.0.1:3000")
        self.assertEqual(snapshot["expo"]["project_count"], 1)

    async def test_build_platform_snapshot_scopes_expo_to_focused_workspace(self):
        live_snapshot = {
            "at": "2026-04-04T00:00:00Z",
            "focus": {"workspace_id": 17, "workspace": {"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"}},
            "operator": {"active": False},
        }
        summary = {"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}}
        inbox = {"now": [], "waiting_on_me": [], "watch": []}
        expo_overview = {
            "project_count": 1,
            "build_count": 2,
            "projects": [{"workspace_id": 17, "project_name": "Dashpro Mobile", "status": "ready"}],
        }

        with patch.object(mobile_platform_snapshot, "seed_control_capabilities", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_companion_live_snapshot", AsyncMock(return_value=live_snapshot)), \
             patch.object(mobile_platform_snapshot, "build_mobile_axon_snapshot", AsyncMock(return_value={"status": "idle"})), \
             patch.object(mobile_platform_snapshot, "attention_summary", AsyncMock(return_value=summary)), \
             patch.object(mobile_platform_snapshot, "query_attention_inbox", AsyncMock(return_value=inbox)), \
             patch.object(mobile_platform_snapshot, "load_expo_overview", AsyncMock(return_value=expo_overview)) as load_expo_overview, \
             patch.object(mobile_platform_snapshot, "get_trust_snapshot", AsyncMock(return_value={"effective_max_risk_tier": "act"})), \
             patch.object(mobile_platform_snapshot, "list_companion_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_risk_challenges", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_action_receipts", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_servers", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_mcp_sessions", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "get_project", AsyncMock(return_value={"id": 17, "name": "Dashpro", "path": "/tmp/dashpro"})), \
             patch.object(mobile_platform_snapshot, "list_workspace_relationships_for_workspace", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "list_companion_voice_turns", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_workspace_cards", AsyncMock(return_value=[])), \
             patch.object(mobile_platform_snapshot, "build_system_strip", AsyncMock(return_value=[])):
            snapshot = await mobile_platform_snapshot.build_platform_snapshot(
                object(),
                device_id=8,
                workspace_id=17,
            )

        load_expo_overview.assert_awaited_once()
        self.assertEqual(load_expo_overview.await_args.kwargs["workspace_id"], 17)
        self.assertEqual(snapshot["focus"]["expo"]["project_name"], "Dashpro Mobile")


class MobileMcpRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoke_builtin_mission_snapshot_returns_snapshot(self):
        snapshot = {"posture": "healthy", "focus": {"workspace": {"name": "Axon"}}}

        with patch.object(mobile_mcp_registry, "build_platform_snapshot", AsyncMock(return_value=snapshot)):
            result = await mobile_mcp_registry.invoke_builtin_mcp_capability(
                object(),
                device_id=3,
                workspace_id=9,
                capability_key="axon-core:mission.snapshot",
                arguments={"session_id": 2},
            )

        self.assertEqual(result["capability_key"], "axon-core:mission.snapshot")
        self.assertEqual(result["result"]["focus"]["workspace"]["name"], "Axon")


if __name__ == "__main__":
    unittest.main()
