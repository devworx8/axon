from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from axon_api.services import connector_reconcile


class ConnectorReconcileServiceTests(unittest.IsolatedAsyncioTestCase):
    def _git(self, repo_path: Path, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _init_repo(self, repo_path: Path) -> None:
        self._git(repo_path, "init")
        self._git(repo_path, "config", "user.email", "axon-tests@example.com")
        self._git(repo_path, "config", "user.name", "Axon Tests")
        (repo_path / "README.md").write_text("init\n", encoding="utf-8")
        (repo_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        self._git(repo_path, "add", "README.md")
        self._git(repo_path, "add", ".gitignore")
        self._git(repo_path, "commit", "-m", "init")

    async def test_inspect_workspace_connectors_reports_dirty_repo_and_persistable_relationships(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = Path(tmp_dir)
            self._init_repo(repo_path)
            self._git(repo_path, "remote", "add", "origin", "https://github.com/devworx8/dashpro.git")
            (repo_path / ".gitignore").write_text("node_modules/\n.dist/\n", encoding="utf-8")

            inspection = await connector_reconcile.inspect_workspace_connectors(
                object(),
                workspace_id=22,
                get_project_fn=AsyncMock(return_value={"id": 22, "name": "Dashpro", "path": str(repo_path)}),
                list_workspace_relationships_for_workspace_fn=AsyncMock(return_value=[]),
            )

        self.assertTrue(inspection["repo"]["dirty"])
        self.assertEqual(inspection["repo"]["remote_origin_url"], "https://github.com/devworx8/dashpro.git")
        self.assertEqual(inspection["repo"]["status_entries"][0]["path"], ".gitignore")
        self.assertTrue(
            any(
                item["kind"] == "relationship_upsert" and item["external_system"] == "github"
                for item in inspection["planned_repairs"]
            )
        )
        self.assertIn("local change", inspection["summary"])

    async def test_reconcile_workspace_connectors_blocks_repo_writes_when_repo_is_dirty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = Path(tmp_dir)
            self._init_repo(repo_path)
            (repo_path / "README.md").write_text("dirty\n", encoding="utf-8")
            project = {"id": 202, "name": "axon-online", "path": str(repo_path)}
            inferred_relationships = [
                {
                    "workspace_id": 202,
                    "external_system": "github",
                    "external_id": "devworx8/axon-online",
                    "relationship_type": "primary",
                    "external_name": "axon-online",
                    "external_url": "https://github.com/devworx8/axon-online",
                    "status": "inferred",
                    "meta_json": '{"remote_url":"https://github.com/devworx8/axon-online.git"}',
                },
                {
                    "workspace_id": 202,
                    "external_system": "vercel",
                    "external_id": "prj_123",
                    "relationship_type": "primary",
                    "external_name": "axon-online",
                    "external_url": "",
                    "status": "inferred",
                    "meta_json": '{"project_id":"prj_123","org_id":"team_456","project_name":"axon-online"}',
                },
            ]

            async def fake_link(_db, **kwargs):
                return {"id": 1, **kwargs}

            link_workspace_relationship_fn = AsyncMock(side_effect=fake_link)
            result = await connector_reconcile.reconcile_workspace_connectors(
                object(),
                workspace_id=202,
                allow_repo_writes=True,
                get_project_fn=AsyncMock(return_value=project),
                list_workspace_relationships_for_workspace_fn=AsyncMock(return_value=[]),
                link_workspace_relationship_fn=link_workspace_relationship_fn,
                infer_workspace_relationships_fn=lambda _project: list(inferred_relationships),
            )

            self.assertFalse((repo_path / ".vercel" / "project.json").exists())

        self.assertEqual(link_workspace_relationship_fn.await_count, 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["changes_applied"], 2)
        self.assertEqual(result["blocked_repairs"], 1)
        self.assertTrue(
            any(receipt["outcome"] == "blocked_dirty_repo" for receipt in result["receipts"])
        )

    async def test_reconcile_workspace_connectors_writes_vercel_project_file_for_clean_repo(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = Path(tmp_dir)
            self._init_repo(repo_path)
            project = {"id": 8, "name": "axon-online", "path": str(repo_path)}
            relationships = [
                {
                    "workspace_id": 8,
                    "external_system": "vercel",
                    "external_id": "prj_789",
                    "relationship_type": "primary",
                    "external_name": "axon-online",
                    "external_url": "",
                    "status": "active",
                    "meta_json": '{"project_id":"prj_789","org_id":"team_789","project_name":"axon-online"}',
                    "source": "persisted",
                }
            ]

            result = await connector_reconcile.reconcile_workspace_connectors(
                object(),
                workspace_id=8,
                persist_inferred=False,
                allow_repo_writes=True,
                get_project_fn=AsyncMock(return_value=project),
                list_workspace_relationships_for_workspace_fn=AsyncMock(return_value=relationships),
                link_workspace_relationship_fn=AsyncMock(),
                infer_workspace_relationships_fn=lambda _project: [],
            )

            project_file = repo_path / ".vercel" / "project.json"
            self.assertTrue(project_file.exists())
            payload = json.loads(project_file.read_text(encoding="utf-8"))

        self.assertEqual(payload["projectId"], "prj_789")
        self.assertEqual(payload["orgId"], "team_789")
        self.assertEqual(payload["projectName"], "axon-online")
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["changes_applied"], 1)
        self.assertTrue(result["repo"]["dirty"])


if __name__ == "__main__":
    unittest.main()
