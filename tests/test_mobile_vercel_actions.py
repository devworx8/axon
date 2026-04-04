from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from axon_api.services import mobile_vercel_actions


class MobileVercelTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_vercel_token_falls_back_to_named_vault_secret(self):
        with patch.object(mobile_vercel_actions, "get_setting", AsyncMock(return_value="")), \
             patch.dict(os.environ, {}, clear=True), \
             patch.object(
                 mobile_vercel_actions,
                 "vault_secret_status_by_name",
                 AsyncMock(return_value={"value": "vercel_secret_token", "present": True, "unlocked": True}),
             ) as vault_secret_status_by_name:
            token = await mobile_vercel_actions._vercel_token(object())

        vault_secret_status_by_name.assert_awaited_once_with(
            unittest.mock.ANY,
            secret_names=("AXON_VERCEL_TOKEN",),
        )
        self.assertEqual(token, "vercel_secret_token")

    async def test_vercel_token_prefers_settings_over_vault(self):
        with patch.object(mobile_vercel_actions, "get_setting", AsyncMock(return_value="stored_token")), \
             patch.object(
                 mobile_vercel_actions,
                 "vault_secret_status_by_name",
                 AsyncMock(return_value={"value": "vault_token", "present": True, "unlocked": True}),
             ) as vault_secret_status_by_name:
            token = await mobile_vercel_actions._vercel_token(object())

        vault_secret_status_by_name.assert_not_awaited()
        self.assertEqual(token, "stored_token")

    async def test_prepare_request_reports_locked_vault_secret(self):
        context = {
            "workspace_id": 2,
            "project_id": "prj_123",
            "team_id": "team_123",
        }
        with patch.object(mobile_vercel_actions, "_workspace_vercel_context", AsyncMock(return_value=context)), \
             patch.object(
                 mobile_vercel_actions,
                 "_vercel_token_state",
                 AsyncMock(return_value={"value": "", "source": "", "present": True, "locked": True}),
             ):
            with self.assertRaises(mobile_vercel_actions.MobileVercelActionError) as ctx:
                await mobile_vercel_actions.prepare_vercel_action_request(
                    object(),
                    action_type="vercel.deploy.promote",
                    workspace_id=2,
                    payload={"workspace_id": 2},
                )

        self.assertEqual(ctx.exception.outcome, "vault_locked")
        self.assertIn("vault is currently locked", ctx.exception.summary)


if __name__ == "__main__":
    unittest.main()
