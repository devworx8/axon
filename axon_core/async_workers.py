"""Helpers for sync work inside Axon's agent loop."""

from __future__ import annotations

import inspect
from typing import TypeVar

T = TypeVar("T")


async def run_sync_agent_call(fn, /, *args, **kwargs) -> T:
    """Execute a sync or async callable from the agent loop.

    Sync functions are called inline (deterministic, avoids thread deadlocks).
    If the function returns an awaitable (coroutine), it is transparently
    awaited — this supports async browser tools alongside sync file/shell tools.
    """

    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = ["run_sync_agent_call"]
