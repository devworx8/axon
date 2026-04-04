"""Compatibility patches for aiosqlite behavior in this runtime."""

from __future__ import annotations

import asyncio
from functools import partial
import sys

from aiosqlite.core import Connection

_PATCHED = False


async def _await_worker_future(future: asyncio.Future):
    """Poll worker-thread futures so selector wakeups cannot deadlock the loop."""
    while not future.done():
        await asyncio.sleep(0.001)
    return future.result()


def ensure_aiosqlite_compat() -> None:
    """Patch aiosqlite's await path for Python 3.13 selector-loop stalls."""
    global _PATCHED
    if _PATCHED or sys.version_info < (3, 13):
        return

    async def _connect(self):
        if self._connection is None:
            try:
                future = asyncio.get_running_loop().create_future()
                self._tx.put_nowait((future, self._connector))
                self._connection = await _await_worker_future(future)
            except BaseException:
                self._stop_running()
                self._connection = None
                raise
        return self

    async def _execute(self, fn, *args, **kwargs):
        if not self._running or not self._connection:
            raise ValueError("Connection closed")

        function = partial(fn, *args, **kwargs)
        future = asyncio.get_running_loop().create_future()
        self._tx.put_nowait((future, function))
        return await _await_worker_future(future)

    Connection._connect = _connect
    Connection._execute = _execute
    _PATCHED = True
