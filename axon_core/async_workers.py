"""Helpers for sync work inside Axon's agent loop."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


async def run_sync_agent_call(fn, /, *args, **kwargs) -> T:
    """Execute a sync callable from the agent loop.

    The agent already executes tools and local model-profile lookups serially.
    Running these calls inline keeps the repair loop deterministic and avoids
    the thread handoff deadlocks we were seeing under Python 3.13.
    """

    return fn(*args, **kwargs)


__all__ = ["run_sync_agent_call"]
