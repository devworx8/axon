from __future__ import annotations

import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

from axon_api.services import terminal_pty_runtime


class _FakePty:
    def __init__(self):
        self.writes = []
        self.alive = True

    def isalive(self):
        return self.alive

    def write(self, payload):
        self.writes.append(payload)


class TerminalPtyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    def test_find_attached_pty_session_matches_composite_session_key(self):
        pty = _FakePty()
        key, entry = terminal_pty_runtime.find_attached_pty_session(
            {
                "12-voice": {"pty": pty, "alive": True},
                "13-console": {"pty": _FakePty(), "alive": True},
            },
            12,
        )

        self.assertEqual(key, "12-voice")
        self.assertIs(entry["pty"], pty)

    def test_ingest_pty_output_strips_tracking_markers_and_emits_events(self):
        entry = {"osc_buffer": "", "line_buffer": ""}
        payload = (
            "Preparing build\r\n"
            "\x1b]9999;AXON_CMD_START:17-demo\x07"
            "Streaming logs\r\n"
            "\x1b]9999;AXON_CMD_DONE:17-demo:0\x07"
        )

        visible, lines, events = terminal_pty_runtime.ingest_pty_output(entry, payload)

        self.assertEqual(visible, "Preparing build\r\nStreaming logs\r\n")
        self.assertEqual(lines, ["Preparing build", "Streaming logs"])
        self.assertEqual(
            events,
            [
                {"type": "start", "marker": "17-demo", "exit_code": None},
                {"type": "done", "marker": "17-demo", "exit_code": 0},
            ],
        )

    async def test_dispatch_command_to_attached_pty_tracks_running_command_and_writes_wrapper(self):
        pty = _FakePty()
        pty_sessions = {"9-voice": {"pty": pty, "alive": True, "tracked_commands": {}}}
        terminal_processes = {}
        db_module = types.SimpleNamespace(
            get_db=self._fake_db,
            update_terminal_session=AsyncMock(return_value=None),
            add_terminal_event=AsyncMock(return_value=None),
        )
        live_operator_calls = []

        result = await terminal_pty_runtime.dispatch_command_to_attached_pty(
            session_id=9,
            command="pwd",
            cwd=Path("/tmp/demo"),
            timeout_seconds=30,
            pty_sessions=pty_sessions,
            terminal_processes=terminal_processes,
            db_module=db_module,
            set_live_operator=lambda **payload: live_operator_calls.append(payload),
            now_iso=lambda: "2026-04-08T08:00:00Z",
        )

        self.assertEqual(result["transport"], "pty")
        self.assertEqual(result["status"], "running")
        self.assertEqual(terminal_processes[9]["kind"], "pty")
        self.assertIn(b"stty -echo\n", pty.writes[0])
        self.assertIn(b"pwd", pty.writes[1])
        db_module.update_terminal_session.assert_awaited_once()
        db_module.add_terminal_event.assert_awaited_once()
        self.assertTrue(live_operator_calls)

        terminal_processes[9]["timeout_task"].cancel()


if __name__ == "__main__":
    unittest.main()
