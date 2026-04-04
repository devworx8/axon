from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from axon_api.services import workspace_relationships


class WorkspaceRelationshipInferenceTests(unittest.TestCase):
    def test_infers_github_vercel_and_sentry_relationships_from_workspace_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_path = Path(tmp_dir)
            (project_path / ".git").mkdir()
            (project_path / ".vercel").mkdir()
            (project_path / ".vercel" / "project.json").write_text(
                '{"projectId":"prj_123","orgId":"team_456","projectName":"edudash-pro-app"}',
                encoding="utf-8",
            )
            (project_path / "sentry.client.config.ts").write_text(
                "export default {};",
                encoding="utf-8",
            )

            def fake_git_output(project_path_arg: Path, *args: str) -> str:
                self.assertEqual(project_path_arg, project_path)
                self.assertEqual(args, ("config", "--get", "remote.origin.url"))
                return "git@github.com:devworx8/axon.git"

            project = {"id": 202, "name": "Axon", "path": str(project_path)}

            original = workspace_relationships._git_output
            workspace_relationships._git_output = fake_git_output
            try:
                relationships = workspace_relationships.infer_workspace_relationships(project)
            finally:
                workspace_relationships._git_output = original

        systems = {item["external_system"] for item in relationships}
        self.assertIn("github", systems)
        self.assertIn("vercel", systems)
        self.assertIn("sentry", systems)

        github = next(item for item in relationships if item["external_system"] == "github")
        self.assertEqual(github["external_id"], "devworx8/axon")
        self.assertEqual(github["external_url"], "https://github.com/devworx8/axon")
        self.assertEqual(github["status"], "inferred")

        vercel = next(item for item in relationships if item["external_system"] == "vercel")
        self.assertEqual(vercel["external_id"], "prj_123")
        self.assertEqual(vercel["external_name"], "edudash-pro-app")
        self.assertIn('"project_name": "edudash-pro-app"', vercel["meta_json"])
        self.assertEqual(vercel["status"], "inferred")


class WorkspaceRelationshipResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_vercel_signal_by_project_name_from_inferred_metadata(self):
        project = {"id": 2, "name": "dashpro", "path": "/tmp/dashpro"}
        relationship = {
            "workspace_id": 2,
            "external_system": "vercel",
            "external_id": "prj_gzH164ClTV08bVPmpmKMn9YRwgn0",
            "external_name": "edudash-pro-app",
            "meta_json": '{"project_id":"prj_gzH164ClTV08bVPmpmKMn9YRwgn0","project_name":"edudash-pro-app","org_id":"team_123"}',
        }

        original_get_projects = workspace_relationships.get_projects
        original_list_bundle = workspace_relationships.list_workspace_relationship_bundle
        workspace_relationships.get_projects = self._fake_get_projects(project)
        workspace_relationships.list_workspace_relationship_bundle = self._fake_list_bundle(relationship)
        try:
            resolved = await workspace_relationships.resolve_workspace_for_connector_signal(
                object(),
                external_system="vercel",
                project_name="edudash-pro-app",
            )
        finally:
            workspace_relationships.get_projects = original_get_projects
            workspace_relationships.list_workspace_relationship_bundle = original_list_bundle

        self.assertEqual(resolved, 2)

    @staticmethod
    def _fake_get_projects(project):
        async def _impl(_db, status="active"):
            return [project] if status == "active" else []

        return _impl

    @staticmethod
    def _fake_list_bundle(relationship):
        async def _impl(_db, **_kwargs):
            return [relationship]

        return _impl

    def test_parse_github_remote_supports_https_and_ssh(self):
        self.assertEqual(
            workspace_relationships._parse_github_remote("git@github.com:devworx8/axon.git"),
            ("devworx8/axon", "axon", "https://github.com/devworx8/axon"),
        )
        self.assertEqual(
            workspace_relationships._parse_github_remote("https://github.com/devworx8/axon.git"),
            ("devworx8/axon", "axon", "https://github.com/devworx8/axon"),
        )


if __name__ == "__main__":
    unittest.main()
