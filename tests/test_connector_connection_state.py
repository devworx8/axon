from __future__ import annotations

import json
import unittest

from axon_api.services import connector_connection_state


class ConnectorConnectionStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_github_saves_token_and_infers_repo_link(self):
        settings: dict[str, str] = {}
        linked: dict[str, object] = {}

        async def fake_set_setting(_db, key: str, value: str):
            settings[key] = value

        async def fake_get_setting(_db, key: str):
            return settings.get(key, "")

        async def fake_link_workspace_relationship(_db, **kwargs):
            linked.update(kwargs)
            return dict(kwargs)

        result = await connector_connection_state.connect_workspace_connector(
            object(),
            workspace={"id": 7, "name": "Axon", "path": "/tmp/axon"},
            external_system="github",
            token="ghp_1234567890",
            set_setting_fn=fake_set_setting,
            get_setting_fn=fake_get_setting,
            link_workspace_relationship_fn=fake_link_workspace_relationship,
            infer_workspace_relationships_fn=lambda _workspace: [
                {
                    "external_system": "github",
                    "external_id": "devworx8/axon",
                    "external_name": "axon",
                    "external_url": "https://github.com/devworx8/axon",
                }
            ],
        )

        self.assertEqual(settings["github_token"], "ghp_1234567890")
        self.assertEqual(linked["external_id"], "devworx8/axon")
        self.assertEqual(linked["external_url"], "https://github.com/devworx8/axon")
        self.assertEqual(result["saved_settings"]["github_token"], "ghp_...7890")

    async def test_connect_sentry_persists_org_projects_and_primary_relationship(self):
        settings: dict[str, str] = {}
        linked: dict[str, object] = {}

        async def fake_set_setting(_db, key: str, value: str):
            settings[key] = value

        async def fake_get_setting(_db, key: str):
            return settings.get(key, "")

        async def fake_link_workspace_relationship(_db, **kwargs):
            linked.update(kwargs)
            return dict(kwargs)

        result = await connector_connection_state.connect_workspace_connector(
            object(),
            workspace={"id": 9, "name": "Console", "path": "/tmp/console"},
            external_system="sentry",
            token="sntrys_abcdefghijklmnopqrstuvwxyz",
            org_slug="axon",
            project_slugs="web,api",
            set_setting_fn=fake_set_setting,
            get_setting_fn=fake_get_setting,
            link_workspace_relationship_fn=fake_link_workspace_relationship,
            infer_workspace_relationships_fn=lambda _workspace: [],
        )

        self.assertEqual(settings["sentry_api_token"], "sntrys_abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(settings["sentry_org_slug"], "axon")
        self.assertEqual(settings["sentry_project_slugs"], "web,api")
        self.assertEqual(linked["external_id"], "web")
        self.assertEqual(linked["external_name"], "web")
        self.assertIn("project_slugs", linked["meta"])
        self.assertEqual(linked["meta"]["project_slugs"], ["web", "api"])
        self.assertEqual(result["saved_settings"]["sentry_org_slug"], "axon")

    async def test_connect_vercel_saves_token_and_project_metadata(self):
        settings: dict[str, str] = {}
        linked: dict[str, object] = {}

        async def fake_set_setting(_db, key: str, value: str):
            settings[key] = value

        async def fake_get_setting(_db, key: str):
            return settings.get(key, "")

        async def fake_link_workspace_relationship(_db, **kwargs):
            linked.update(kwargs)
            return dict(kwargs)

        result = await connector_connection_state.connect_workspace_connector(
            object(),
            workspace={"id": 11, "name": "axon-online", "path": "/tmp/axon-online"},
            external_system="vercel",
            external_id="prj_123",
            external_name="axon-online",
            token="vercel_secret_token",
            org_slug="team_456",
            set_setting_fn=fake_set_setting,
            get_setting_fn=fake_get_setting,
            link_workspace_relationship_fn=fake_link_workspace_relationship,
            infer_workspace_relationships_fn=lambda _workspace: [],
        )

        self.assertEqual(settings["vercel_api_token"], "vercel_secret_token")
        self.assertEqual(linked["external_id"], "prj_123")
        self.assertEqual(linked["external_name"], "axon-online")
        self.assertEqual(linked["meta"]["project_id"], "prj_123")
        self.assertEqual(linked["meta"]["project_name"], "axon-online")
        self.assertEqual(linked["meta"]["org_id"], "team_456")
        self.assertEqual(result["saved_settings"]["vercel_api_token"], "verc...oken")

    async def test_connect_custom_connector_stores_generic_credentials_json(self):
        settings = {
            "connector_credentials_json": json.dumps(
                {
                    "3:linear:acme": {
                        "external_system": "linear",
                        "external_id": "acme",
                        "updated_at": "2026-04-04T00:00:00Z",
                    }
                },
                sort_keys=True,
            )
        }
        linked: dict[str, object] = {}

        async def fake_set_setting(_db, key: str, value: str):
            settings[key] = value

        async def fake_get_setting(_db, key: str):
            return settings.get(key, "")

        async def fake_link_workspace_relationship(_db, **kwargs):
            linked.update(kwargs)
            return dict(kwargs)

        result = await connector_connection_state.connect_workspace_connector(
            object(),
            workspace={"id": 12, "name": "Axon", "path": "/tmp/axon"},
            external_system="linear",
            external_id="team-axon",
            external_name="Linear",
            token="lin_api_secret",
            url="https://api.linear.app",
            auth={"team": "Axon", "mode": "token"},
            set_setting_fn=fake_set_setting,
            get_setting_fn=fake_get_setting,
            link_workspace_relationship_fn=fake_link_workspace_relationship,
            infer_workspace_relationships_fn=lambda _workspace: [],
        )

        saved = json.loads(settings["connector_credentials_json"])
        self.assertIn("3:linear:acme", saved)
        self.assertIn("12:linear:team-axon", saved)
        self.assertEqual(saved["12:linear:team-axon"]["token"], "lin_api_secret")
        self.assertEqual(saved["12:linear:team-axon"]["auth"]["team"], "Axon")
        self.assertEqual(linked["meta"]["credential_key"], "12:linear:team-axon")
        self.assertEqual(result["saved_settings"]["connector_credentials_json"], "12:linear:team-axon")


if __name__ == "__main__":
    unittest.main()
