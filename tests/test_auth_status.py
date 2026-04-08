from __future__ import annotations

from contextlib import asynccontextmanager
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

import server


def _request(*, hostname: str = "localhost", client_host: str = "127.0.0.1", headers: dict | None = None):
    return SimpleNamespace(
        url=SimpleNamespace(hostname=hostname),
        client=SimpleNamespace(host=client_host),
        headers=headers or {},
        query_params={},
    )


class ServerAuthStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_status_requires_login_when_pin_exists_on_localhost(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        request = _request()

        with patch.object(server.devdb, "get_db", fake_db), patch.object(
            server.devdb,
            "get_setting",
            AsyncMock(return_value="hashed-pin"),
        ), patch.object(
            server,
            "_valid_session_async",
            AsyncMock(return_value=False),
        ):
            payload = await server.auth_status(request)

        self.assertEqual(
            payload,
            {
                "auth_enabled": True,
                "session_valid": False,
                "dev_bypass": False,
            },
        )

    async def test_auth_status_only_uses_dev_bypass_without_pin(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        request = _request()

        with patch.object(server.devdb, "get_db", fake_db), patch.object(
            server.devdb,
            "get_setting",
            AsyncMock(return_value=""),
        ):
            payload = await server.auth_status(request)

        self.assertEqual(
            payload,
            {
                "auth_enabled": False,
                "session_valid": True,
                "dev_bypass": True,
            },
        )

    async def test_auth_status_accepts_persisted_session_after_reload(self):
        @asynccontextmanager
        async def fake_db():
            yield object()

        request = _request(headers={})

        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_path = Path(tmpdir) / "web_auth_sessions.json"
            with patch.object(server, "AUTH_SESSIONS_FILE", sessions_path), \
                 patch.dict(server._auth_sessions, {}, clear=True), \
                 patch.object(server.devdb, "get_db", fake_db), \
                 patch.object(server.devdb, "get_setting", AsyncMock(return_value="hashed-pin")):
                token = server._create_session()
                server._auth_sessions.clear()
                server._auth_sessions.update(server._load_auth_sessions())
                request.headers["X-Axon-Token"] = token

                payload = await server.auth_status(request)
                self.assertTrue(sessions_path.exists())

        self.assertEqual(
            payload,
            {
                "auth_enabled": True,
                "session_valid": True,
                "dev_bypass": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
