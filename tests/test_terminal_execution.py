from __future__ import annotations

import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

from axon_api.services import terminal_execution


class TerminalExecutionTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_require_pty_returns_interactive_required(self):
        spawn_called = {"called": False}

        async def fake_dispatch(**kwargs):
            return None

        async def fake_spawn(*args, **kwargs):
            spawn_called["called"] = True
            raise AssertionError("spawn should not be called when require_pty is true")

        db_module = types.SimpleNamespace(
            get_db=self._fake_db,
            update_terminal_session=AsyncMock(),
            add_terminal_event=AsyncMock(),
        )

        result = await terminal_execution.start_terminal_command(
            session_id=12,
            command="git status",
            cwd=Path("/home/edp"),
            timeout_seconds=25,
            require_pty=True,
            dispatch_pty_fn=fake_dispatch,
            pty_sessions={},
            terminal_processes={},
            db_module=db_module,
            set_live_operator=lambda **kwargs: None,
            now_iso=lambda: "2026-04-08T12:00:00Z",
            spawn_subprocess_fn=fake_spawn,
        )

        self.assertEqual(result["status"], "interactive_required")
        self.assertFalse(spawn_called["called"])


if __name__ == "__main__":
    unittest.main()
