from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from axon_api.services import connector_auth_state


class ConnectorAuthStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_vercel_auth_state_reports_locked_vault_secret(self):
        with patch.object(connector_auth_state, "get_setting", AsyncMock(return_value="")), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(
                 connector_auth_state,
                 "vault_secret_status_by_name",
                 AsyncMock(return_value={"value": "", "present": True, "unlocked": False}),
             ):
            payload = await connector_auth_state.vercel_auth_state(object())

        self.assertFalse(payload["configured"])
        self.assertTrue(payload["present"])
        self.assertTrue(payload["locked"])
        self.assertEqual(payload["source"], "")

    async def test_sentry_auth_state_marks_token_and_org_as_configured(self):
        values = {
            "sentry_api_token": "sntrys-example-token",
            "sentry_org_slug": "edudash-pro",
            "sentry_project_slugs": "web,api",
        }

        async def fake_get_setting(_db, key: str):
            return values.get(key, "")

        with patch.object(connector_auth_state, "get_setting", AsyncMock(side_effect=fake_get_setting)):
            payload = await connector_auth_state.sentry_auth_state(object())

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["org"], "edudash-pro")
        self.assertEqual(payload["projects"], ["web", "api"])
        self.assertEqual(payload["project_count"], 2)


if __name__ == "__main__":
    unittest.main()
