from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from axon_api.routes import connectors


class ConnectorStatusRouteTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_vercel_status_lists_active_workspaces_with_inferred_relationships(self):
        project = {"id": 2, "name": "dashpro", "path": "/tmp/dashpro"}
        relationships = [
            {
                "workspace_id": 2,
                "external_system": "vercel",
                "external_id": "prj_123",
                "external_name": "edudash-pro-app",
                "status": "inferred",
            }
        ]
        inbox = {"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}, "top_now": [], "top_waiting_on_me": [], "top_watch": []}

        async def fake_relationships_for_workspace(_db, *, workspace_id: int, external_system: str = "", limit: int = 50):
            self.assertEqual(workspace_id, 2)
            self.assertEqual(limit, 50)
            if external_system and external_system != "vercel":
                return []
            return relationships

        with patch.object(connectors, "get_db", self._fake_db), \
             patch.object(connectors, "get_projects", AsyncMock(return_value=[project])) as get_projects, \
             patch.object(connectors, "get_project", AsyncMock(return_value=project)), \
             patch.object(connectors, "list_workspace_relationships", AsyncMock(return_value=[])) as list_workspace_relationships, \
             patch.object(connectors, "list_workspace_relationships_for_workspace", AsyncMock(side_effect=fake_relationships_for_workspace)), \
             patch.object(connectors, "attention_summary", AsyncMock(return_value=inbox)), \
             patch.object(connectors, "vercel_auth_state", AsyncMock(return_value={"configured": False, "present": False, "locked": False})):
            payload = await connectors.vercel_status()

        get_projects.assert_awaited_once()
        list_workspace_relationships.assert_not_awaited()
        self.assertEqual(len(payload["workspaces"]), 1)
        self.assertEqual(payload["workspaces"][0]["workspace"]["id"], 2)
        self.assertEqual(len(payload["workspaces"][0]["relationships"]), 1)
        self.assertEqual(payload["workspaces"][0]["relationships"][0]["external_system"], "vercel")
        self.assertEqual(payload["workspaces"][0]["relationships"][0]["external_name"], "edudash-pro-app")

    async def test_sentry_status_lists_active_workspaces_with_inferred_relationships(self):
        project = {"id": 4, "name": "console", "path": "/tmp/console"}
        relationships = [
            {
                "workspace_id": 4,
                "external_system": "sentry",
                "external_id": "web",
                "external_name": "web",
                "status": "inferred",
            }
        ]
        inbox = {"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}, "top_now": [], "top_waiting_on_me": [], "top_watch": []}
        unresolved = [{"id": 7, "source": "sentry", "status": "open"}]

        async def fake_relationships_for_workspace(_db, *, workspace_id: int, external_system: str = "", limit: int = 50):
            self.assertEqual(workspace_id, 4)
            self.assertEqual(limit, 50)
            if external_system and external_system != "sentry":
                return []
            return relationships

        with patch.object(connectors, "get_db", self._fake_db), \
             patch.object(connectors, "get_projects", AsyncMock(return_value=[project])) as get_projects, \
             patch.object(connectors, "get_project", AsyncMock(return_value=project)), \
             patch.object(connectors, "list_workspace_relationships", AsyncMock(return_value=[])) as list_workspace_relationships, \
             patch.object(connectors, "list_workspace_relationships_for_workspace", AsyncMock(side_effect=fake_relationships_for_workspace)), \
             patch.object(connectors, "attention_summary", AsyncMock(return_value=inbox)), \
             patch.object(connectors, "list_error_events", AsyncMock(return_value=unresolved)) as list_error_events, \
             patch.object(connectors, "sentry_auth_state", AsyncMock(return_value={"configured": False, "present": False, "org": "", "projects": []})):
            payload = await connectors.sentry_status(limit=10)

        get_projects.assert_awaited_once()
        list_workspace_relationships.assert_not_awaited()
        list_error_events.assert_awaited_once()
        self.assertEqual(payload["unresolved"], unresolved)
        self.assertEqual(len(payload["workspaces"]), 1)
        self.assertEqual(payload["workspaces"][0]["workspace"]["id"], 4)
        self.assertEqual(len(payload["workspaces"][0]["relationships"]), 1)
        self.assertEqual(payload["workspaces"][0]["relationships"][0]["external_system"], "sentry")

    async def test_github_workflow_preview_uses_workspace_row_dict(self):
        project = {"id": 8, "name": "axon", "path": "/tmp/axon"}

        with patch.object(connectors, "get_db", self._fake_db), \
             patch.object(connectors, "get_project", AsyncMock(return_value=project)), \
             patch.object(connectors, "normalize_repo_cwd", return_value="/tmp/axon") as normalize_repo_cwd, \
             patch.object(connectors, "read_workflow_status", return_value=("/tmp/axon", "gh workflow view")) as read_workflow_status:
            payload = await connectors.github_workflow_preview(8, branch="main")

        normalize_repo_cwd.assert_called_once_with("/tmp/axon")
        read_workflow_status.assert_called_once_with(repo_path="/tmp/axon", branch_name="main")
        self.assertEqual(payload["workspace"]["id"], 8)
        self.assertEqual(payload["cwd"], "/tmp/axon")
        self.assertEqual(payload["command"], "gh workflow view")

    async def test_connectors_reconcile_workspace_uses_service(self):
        project = {"id": 202, "name": "axon-online", "path": "/tmp/axon-online"}
        reconcile_payload = {"status": "updated", "changes_applied": 1}

        with patch.object(connectors, "get_db", self._fake_db), \
             patch.object(connectors, "get_project", AsyncMock(return_value=project)), \
             patch.object(connectors, "reconcile_workspace_connectors", AsyncMock(return_value=reconcile_payload)) as reconcile_workspace_connectors:
            payload = await connectors.connectors_reconcile_workspace(
                202,
                body=connectors.WorkspaceConnectorReconcileRequest(
                    persist_inferred=True,
                    allow_repo_writes=False,
                ),
            )

        reconcile_workspace_connectors.assert_awaited_once_with(
            unittest.mock.ANY,
            workspace_id=202,
            persist_inferred=True,
            allow_repo_writes=False,
        )
        self.assertEqual(payload["status"], "updated")
        self.assertEqual(payload["changes_applied"], 1)


if __name__ == "__main__":
    unittest.main()
