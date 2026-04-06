from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from axon_api.routes import companion as companion_routes


class CompanionStatusRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_companion_status_preserves_latest_presence_meta_json(self):
        @asynccontextmanager
        async def fake_db():
            yield SimpleNamespace()

        latest_meta = '{"axon_mode":{"armed":true,"wake_phrase":"Axon","voice_identity":"en-ZA-LeahNeural"}}'

        with patch.object(companion_routes, "companion_auth_context", AsyncMock(return_value=("", None, None))), \
             patch.object(companion_routes, "get_db", fake_db), \
             patch.object(companion_routes, "get_setting", AsyncMock(return_value="pin-hash")), \
             patch.object(companion_routes, "list_companion_devices", AsyncMock(return_value=[{"id": 29, "name": "Axon phone", "platform": "expo", "status": "paired"}])), \
             patch.object(companion_routes, "list_companion_sessions", AsyncMock(return_value=[])), \
             patch.object(
                 companion_routes,
                 "list_companion_presence",
                 AsyncMock(return_value=[{
                     "device_id": 29,
                     "presence_state": "online",
                     "voice_state": "live",
                     "app_state": "foreground",
                     "active_route": "/voice",
                     "workspace_id": 2,
                     "session_id": None,
                     "last_seen_at": "2026-04-04 16:44:53",
                     "updated_at": "2026-04-04 16:44:53",
                     "meta_json": latest_meta,
                 }]),
             ):
            payload = await companion_routes.companion_status(SimpleNamespace())

        self.assertEqual(payload["latest_presence"]["device_name"], "Axon phone")
        self.assertEqual(payload["latest_presence"]["meta_json"], latest_meta)


if __name__ == "__main__":
    unittest.main()
