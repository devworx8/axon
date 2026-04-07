from __future__ import annotations

import sys
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import WebSocketDisconnect

from axon_api.routes.terminal_routes import TerminalRouteHandlers


class _FakeWebSocket:
    def __init__(self):
        self.query_params = {}
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = (code, reason)

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_text(self):
        raise WebSocketDisconnect()


class _FakePty:
    def __init__(self):
        self.exitstatus = 0

    def isalive(self):
        return False

    def terminate(self, force=False):
        self.force = force

    def write(self, payload):
        self.payload = payload


class TerminalRouteTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_pty_websocket_uses_terminal_session_cwd_for_composite_session_keys(self):
        spawn_calls = {}

        class FakePtyProcess:
            @staticmethod
            def spawn(argv, dimensions=None, env=None, cwd=None):
                spawn_calls["argv"] = argv
                spawn_calls["dimensions"] = dimensions
                spawn_calls["cwd"] = cwd
                return _FakePty()

        fake_module = types.ModuleType("ptyprocess")
        fake_module.PtyProcess = FakePtyProcess

        db_module = types.SimpleNamespace(
            get_db=self._fake_db,
            get_setting=AsyncMock(return_value=None),
            get_terminal_session=AsyncMock(return_value={
                "id": 12,
                "workspace_id": 7,
                "cwd": "/tmp/legacy-shell",
            }),
        )

        handlers = TerminalRouteHandlers(
            db_module=db_module,
            terminal_processes={},
            pty_sessions={},
            resolve_terminal_cwd=AsyncMock(return_value=Path("/tmp/voice-shell")),
            terminal_mode_value=lambda raw, fallback="read_only": raw or fallback,
            terminal_execute_request=AsyncMock(),
            serialize_terminal_session=lambda *args, **kwargs: {},
            serialize_terminal_event=lambda row: row,
            set_live_operator=lambda **kwargs: None,
            valid_session=lambda token: True,
            local_tool_scope_label=lambda: str(Path.home()),
        )

        websocket = _FakeWebSocket()
        with unittest.mock.patch.dict(sys.modules, {"ptyprocess": fake_module}):
            await handlers.pty_websocket(websocket, "12-voice")

        self.assertTrue(websocket.accepted)
        self.assertEqual(spawn_calls["cwd"], "/tmp/voice-shell")
        db_module.get_terminal_session.assert_awaited_once()
        handlers._resolve_terminal_cwd.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
