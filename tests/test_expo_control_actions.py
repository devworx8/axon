from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import AsyncMock, patch

from axon_api.services import expo_control_actions


class ExpoControlActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_expo_token_state_prefers_owner_specific_env_token(self):
        with patch.dict(
            os.environ,
            {
                "EXPO_TOKEN": "global-token",
                "EXPO_TOKEN__DASH_TS_ORGANIZATION": "owner-token",
            },
            clear=False,
        ), patch.object(expo_control_actions, "get_setting", AsyncMock(return_value="")):
            state = await expo_control_actions.expo_token_state(object(), owner="dash-ts-organization")

        self.assertEqual(state["value"], "owner-token")
        self.assertEqual(state["source"], "env:EXPO_TOKEN__DASH_TS_ORGANIZATION")

    async def test_load_overview_marks_blocked_when_token_missing(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=202,
            workspace_name="Axon",
            workspace_path="/tmp/axon",
            project_root=Path("/tmp/axon/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="expo-project-id",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development", "preview", "production"],
            runtime_version="policy:appVersion",
            update_channel="production",
            channels={"production": "production"},
            git_branch="axon-dev",
        )

        with TemporaryDirectory() as tmpdir:
            with patch.object(expo_control_actions, "PERSISTED_OVERVIEW_CACHE_DIR", Path(tmpdir)), \
                 patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
                 patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"present": False, "locked": False, "source": ""})), \
                 patch.object(
                     expo_control_actions,
                     "_run_eas_cli_async",
                     AsyncMock(side_effect=expo_control_actions.ExpoControlError("no local session", outcome="expo_auth_failed")),
                 ):
                overview = await expo_control_actions.load_expo_overview(object(), workspace_id=202, limit=4, force_refresh=True)

        self.assertEqual(overview["status"], "blocked")
        self.assertIn("EXPO_ACCESS_TOKEN", overview["summary"])
        self.assertEqual(overview["project_count"], 1)
        self.assertEqual(overview["projects"][0]["status"], "token_missing")

    async def test_prepare_request_reports_locked_vault(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=202,
            workspace_name="Axon",
            workspace_path="/tmp/axon",
            project_root=Path("/tmp/axon/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="expo-project-id",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development"],
            runtime_version="policy:appVersion",
            update_channel="production",
            channels={"development": "development"},
            git_branch="axon-dev",
        )

        with patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
             patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "", "present": True, "locked": True, "source": "vault"})):
            with self.assertRaises(expo_control_actions.ExpoControlError) as ctx:
                await expo_control_actions.prepare_expo_action_request(
                    object(),
                    action_type="expo.build.android.dev",
                    workspace_id=202,
                    payload={"workspace_id": 202},
                )

        self.assertEqual(ctx.exception.outcome, "vault_locked")
        self.assertIn("vault is currently locked", ctx.exception.summary)

    async def test_load_overview_marks_account_mismatch_when_token_actor_cannot_access_owner(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=173,
            workspace_name="Axon",
            workspace_path="/home/edp/.devbrain",
            project_root=Path("/home/edp/.devbrain/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="2dcf2ff8-d911-42a8-bcd7-8bc9203ef46c",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development", "preview", "production"],
            runtime_version="policy:appVersion",
            update_channel="production",
            channels={"production": "production"},
            git_branch="axon-dev",
        )

        async def fake_run(*, command, **kwargs):
            if command == ["whoami"]:
                return {
                    "stdout": "dash-t\ndash@example.com\n\nAccounts:\n• dash-t (Role: Owner)\n",
                    "stderr": "",
                    "parsed": None,
                }
            raise AssertionError(f"Unexpected command: {command}")

        with patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
             patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "secret", "present": True, "locked": False, "source": "vault"})), \
             patch.object(expo_control_actions, "_run_eas_cli_async", AsyncMock(side_effect=fake_run)):
            overview = await expo_control_actions.load_expo_overview(object(), workspace_id=173, limit=4, force_refresh=True)

        self.assertEqual(overview["status"], "degraded")
        self.assertEqual(overview["projects"][0]["status"], "expo_account_mismatch")
        self.assertEqual(overview["projects"][0]["account_name"], "dash-t")
        self.assertIn("king-prod", overview["projects"][0]["error"]["summary"])

    async def test_load_overview_preserves_runtime_version_channel_and_active_builds(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=173,
            workspace_name="Axon",
            workspace_path="/home/edp/.devbrain",
            project_root=Path("/home/edp/.devbrain/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="2dcf2ff8-d911-42a8-bcd7-8bc9203ef46c",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development", "preview", "production"],
            runtime_version="policy:appVersion",
            update_channel="development",
            channels={"development": "development", "preview": "preview", "production": "production"},
            git_branch="axon-dev",
        )

        async def fake_run(*, command, **kwargs):
            if command == ["whoami"]:
                return {
                    "stdout": "king-prod\ndash@example.com\n\nAccounts:\n• king-prod (Role: Owner)\n",
                    "stderr": "",
                    "parsed": None,
                }
            if command[:2] == ["build:list", "--limit"]:
                return {
                    "stdout": "",
                    "stderr": "",
                    "parsed": [
                        {
                            "id": "build-1",
                            "appName": "Axon Online",
                            "platform": "android",
                            "status": "IN_PROGRESS",
                            "createdAt": "2026-04-04T12:00:00Z",
                            "updatedAt": "2026-04-04T12:01:00Z",
                            "branch": "dev",
                            "channel": "development",
                            "runtimeVersion": "0.1.0",
                            "profile": "development",
                        }
                    ],
                }
            if command[:2] == ["update:list", "--all"]:
                return {
                    "stdout": "",
                    "stderr": "",
                    "parsed": [],
                }
            raise AssertionError(f"Unexpected command: {command}")

        with patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
             patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "secret", "present": True, "locked": False, "source": "vault"})), \
             patch.object(expo_control_actions, "_run_eas_cli_async", AsyncMock(side_effect=fake_run)):
            overview = await expo_control_actions.load_expo_overview(object(), workspace_id=173, limit=4, force_refresh=True)

        payload = overview["projects"][0]
        self.assertEqual(payload["runtime_version"], "policy:appVersion")
        self.assertEqual(payload["update_channel"], "development")
        self.assertEqual(len(payload["active_builds"]), 1)
        self.assertEqual(overview["active_builds"][0]["id"], "build-1")

    async def test_load_overview_uses_persisted_snapshot_when_vault_relocks(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=173,
            workspace_name="Axon",
            workspace_path="/home/edp/.devbrain",
            project_root=Path("/home/edp/.devbrain/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="2dcf2ff8-d911-42a8-bcd7-8bc9203ef46c",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development", "preview", "production"],
            runtime_version="policy:appVersion",
            update_channel="development",
            channels={"development": "development", "preview": "preview", "production": "production"},
            git_branch="axon-dev",
        )

        async def fake_run(*, command, **kwargs):
            if command == ["whoami"]:
                return {
                    "stdout": "king-prod\ndash@example.com\n\nAccounts:\n• king-prod (Role: Owner)\n",
                    "stderr": "",
                    "parsed": None,
                }
            if command[:2] == ["build:list", "--limit"]:
                return {
                    "stdout": "",
                    "stderr": "",
                    "parsed": [
                        {
                            "id": "build-1",
                            "appName": "Axon Online",
                            "platform": "android",
                            "status": "FINISHED",
                            "createdAt": "2026-04-04T12:00:00Z",
                            "updatedAt": "2026-04-04T12:01:00Z",
                            "branch": "dev",
                            "channel": "development",
                            "runtimeVersion": "0.1.0",
                            "profile": "development",
                        }
                    ],
                }
            if command[:2] == ["update:list", "--all"]:
                return {"stdout": "", "stderr": "", "parsed": []}
            raise AssertionError(f"Unexpected command: {command}")

        with TemporaryDirectory() as tmpdir:
            with patch.object(expo_control_actions, "PERSISTED_OVERVIEW_CACHE_DIR", Path(tmpdir)), \
                 patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
                 patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "secret", "present": True, "locked": False, "source": "vault"})), \
                 patch.object(expo_control_actions, "_run_eas_cli_async", AsyncMock(side_effect=fake_run)):
                first = await expo_control_actions.load_expo_overview(object(), workspace_id=173, limit=4, force_refresh=True)

            with patch.object(expo_control_actions, "PERSISTED_OVERVIEW_CACHE_DIR", Path(tmpdir)), \
                 patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
                 patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "", "present": True, "locked": True, "source": "vault"})), \
                 patch.object(
                     expo_control_actions,
                     "_run_eas_cli_async",
                     AsyncMock(side_effect=expo_control_actions.ExpoControlError("no local session", outcome="expo_auth_failed")),
                 ):
                second = await expo_control_actions.load_expo_overview(object(), workspace_id=173, limit=4, force_refresh=True)

        self.assertEqual(first["build_count"], 1)
        self.assertEqual(second["build_count"], 1)
        self.assertEqual(second["projects"][0]["status"], "ready")
        self.assertEqual(second["status"], "degraded")
        self.assertTrue(second["stale"])
        self.assertEqual(second["stale_reason"], "vault_locked")
        self.assertIn("Showing last successful sync", second["summary"])

    async def test_load_overview_uses_local_cli_session_when_vault_locked(self):
        project = expo_control_actions.ExpoProjectContext(
            workspace_id=173,
            workspace_name="Axon",
            workspace_path="/home/edp/.devbrain",
            project_root=Path("/home/edp/.devbrain/apps/companion-native"),
            app_name="Axon Online",
            owner="king-prod",
            slug="axon-online",
            project_id="2dcf2ff8-d911-42a8-bcd7-8bc9203ef46c",
            android_package="za.org.edudashpro.axononline",
            ios_bundle_identifier="za.org.edudashpro.axononline",
            build_profiles=["development", "preview", "production"],
            runtime_version="policy:appVersion",
            update_channel="development",
            channels={"development": "development", "preview": "preview", "production": "production"},
            git_branch="axon-dev",
        )

        async def fake_run(*, command, token="", **kwargs):
            if command == ["whoami"]:
                return {
                    "stdout": "king-prod\ndash@example.com\n\nAccounts:\n• king-prod (Role: Owner)\n",
                    "stderr": "",
                    "parsed": None,
                }
            if command[:2] == ["build:list", "--limit"]:
                return {
                    "stdout": "",
                    "stderr": "",
                    "parsed": [
                        {
                            "id": "build-1",
                            "appName": "Axon Online",
                            "platform": "android",
                            "status": "FINISHED",
                            "createdAt": "2026-04-04T12:00:00Z",
                            "updatedAt": "2026-04-04T12:01:00Z",
                            "profile": "development",
                        }
                    ],
                }
            if command[:2] == ["update:list", "--all"]:
                return {"stdout": "", "stderr": "", "parsed": []}
            raise AssertionError(f"Unexpected command: {command}")

        with patch.object(expo_control_actions, "discover_expo_projects", AsyncMock(return_value=[project])), \
             patch.object(expo_control_actions, "expo_token_state", AsyncMock(return_value={"value": "", "present": True, "locked": True, "source": "vault"})), \
             patch.object(expo_control_actions, "_run_eas_cli_async", AsyncMock(side_effect=fake_run)):
            overview = await expo_control_actions.load_expo_overview(object(), workspace_id=173, limit=4, force_refresh=True)

        self.assertEqual(overview["status"], "ready")
        self.assertEqual(overview["token"]["source"], "local_cli_session")
        self.assertEqual(overview["projects"][0]["status"], "ready")
        self.assertEqual(overview["build_count"], 1)


if __name__ == "__main__":
    unittest.main()
