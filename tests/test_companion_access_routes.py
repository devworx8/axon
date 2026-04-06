from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import server
from axon_api.routes import companion_access
from axon_api.routes.companion_models import CompanionPairRequest, CompanionRefreshRequest, CompanionRestoreRequest


class CompanionAccessRouteTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_companion_pair_returns_restore_token(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        body = CompanionPairRequest(device_key="phone-1", name="Phone")

        with patch.object(companion_access, "get_db", self._fake_db), \
             patch.object(companion_access, "get_setting", AsyncMock(return_value="")), \
             patch.object(
                 companion_access.companion_auth_service,
                 "register_companion_device",
                 AsyncMock(return_value={"id": 7, "name": "Phone", "device_key": "phone-1"}),
             ) as register_device, \
             patch.object(
                 companion_access.companion_auth_service,
                 "issue_companion_auth_session",
                 AsyncMock(return_value={
                     "auth_session": {"id": 11, "device_id": 7},
                     "access_token": "access-1",
                     "refresh_token": "refresh-1",
                     "expires_at": "2026-04-07T00:00:00Z",
                 }),
             ) as issue_session, \
             patch.object(
                 companion_access.companion_auth_service,
                 "issue_companion_device_restore_token",
                 AsyncMock(return_value="restore-1"),
             ) as issue_restore, \
             patch.object(companion_access, "touch_companion_device", AsyncMock()) as touch_device, \
             patch.object(
                 companion_access,
                 "get_companion_device",
                 AsyncMock(return_value={"id": 7, "name": "Phone", "device_key": "phone-1"}),
             ):
            payload = await companion_access.companion_pair(body, request)

        register_device.assert_awaited_once()
        issue_session.assert_awaited_once()
        issue_restore.assert_awaited_once()
        touch_device.assert_awaited_once()
        self.assertEqual(payload["device"]["id"], 7)
        self.assertEqual(payload["restore_token"], "restore-1")
        self.assertEqual(payload["auth_session"]["device_id"], 7)

    async def test_companion_refresh_returns_rotated_restore_token(self):
        body = CompanionRefreshRequest(refresh_token="refresh-1")

        with patch.object(companion_access, "get_db", self._fake_db), \
             patch.object(
                 companion_access.companion_auth_service,
                 "refresh_companion_auth_session",
                 AsyncMock(return_value={
                     "auth_session": {"id": 15, "device_id": 9},
                     "access_token": "access-2",
                     "refresh_token": "refresh-2",
                     "expires_at": "2026-04-08T00:00:00Z",
                 }),
             ) as refresh_session, \
             patch.object(
                 companion_access.companion_auth_service,
                 "issue_companion_device_restore_token",
                 AsyncMock(return_value="restore-2"),
             ) as issue_restore, \
             patch.object(companion_access, "touch_companion_device", AsyncMock()) as touch_device, \
             patch.object(
                 companion_access,
                 "get_companion_device",
                 AsyncMock(return_value={"id": 9, "name": "Field phone", "device_key": "phone-9"}),
             ):
            payload = await companion_access.companion_refresh(body)

        refresh_session.assert_awaited_once()
        issue_restore.assert_awaited_once()
        touch_device.assert_awaited_once_with(unittest.mock.ANY, 9)
        self.assertEqual(payload["restore_token"], "restore-2")
        self.assertEqual(payload["device"]["device_key"], "phone-9")

    async def test_companion_restore_rejects_invalid_saved_trust(self):
        body = CompanionRestoreRequest(device_key="phone-1", restore_token="bad-token")

        with patch.object(companion_access, "get_db", self._fake_db), \
             patch.object(
                 companion_access.companion_auth_service,
                 "restore_companion_auth_session",
                 AsyncMock(return_value=None),
             ):
            with self.assertRaises(HTTPException) as ctx:
                await companion_access.companion_restore(body)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Pair this device again", str(ctx.exception.detail))


class CompanionAccessRegistrationTests(unittest.TestCase):
    def test_server_app_registers_companion_restore_route(self):
        paths = {route.path for route in server.app.routes}
        self.assertIn("/api/companion/auth/restore", paths)


if __name__ == "__main__":
    unittest.main()
