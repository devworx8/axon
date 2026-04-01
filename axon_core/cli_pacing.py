from __future__ import annotations

import asyncio
import time


_CLI_START_LOCK = asyncio.Lock()
_next_cli_start_at_by_key: dict[str, float] = {}
_last_cli_cooldown_message_by_key: dict[str, str] = {}
_last_cli_cooldown_until_by_key: dict[str, float] = {}


def _normalize_cli_key(key: str = "claude") -> str:
    return str(key or "claude").strip().lower() or "claude"


async def wait_for_cli_slot(min_interval_seconds: float = 8.0, *, key: str = "claude") -> float:
    """Ensure CLI launches are spaced apart per runtime family.

    Returns the amount of time waited before the caller may start a new CLI
    subprocess. The lock is only held while scheduling the next start time, so
    running commands are not serialized for their full execution duration.
    """
    async with _CLI_START_LOCK:
        runtime_key = _normalize_cli_key(key)
        now = time.monotonic()
        next_start_at = float(_next_cli_start_at_by_key.get(runtime_key, 0.0) or 0.0)
        wait_seconds = max(0.0, next_start_at - now)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        start_at = time.monotonic()
        _next_cli_start_at_by_key[runtime_key] = start_at + max(0.0, float(min_interval_seconds))
        return wait_seconds


async def extend_cli_cooldown(seconds: float, *, key: str = "claude") -> None:
    """Push the next allowed CLI launch into the future after a hard limit hit."""

    async with _CLI_START_LOCK:
        runtime_key = _normalize_cli_key(key)
        current = float(_next_cli_start_at_by_key.get(runtime_key, 0.0) or 0.0)
        _next_cli_start_at_by_key[runtime_key] = max(current, time.monotonic() + max(0.0, float(seconds)))


async def note_cli_cooldown(message: str, seconds: float, *, key: str = "claude") -> None:
    """Record a human-readable cooldown message alongside the cooldown window."""
    runtime_key = _normalize_cli_key(key)

    await extend_cli_cooldown(seconds, key=runtime_key)
    _last_cli_cooldown_message_by_key[runtime_key] = str(message or "").strip()
    _last_cli_cooldown_until_by_key[runtime_key] = max(
        float(_last_cli_cooldown_until_by_key.get(runtime_key, 0.0) or 0.0),
        time.time() + max(0.0, float(seconds)),
    )


def current_cli_cooldown(*, key: str = "claude") -> dict[str, object]:
    runtime_key = _normalize_cli_key(key)
    until = float(_last_cli_cooldown_until_by_key.get(runtime_key, 0.0) or 0.0)
    remaining = max(0.0, until - time.time())
    return {
        "active": remaining > 0,
        "remaining_seconds": int(round(remaining)),
        "until_epoch": until if remaining > 0 else 0.0,
        "message": _last_cli_cooldown_message_by_key.get(runtime_key, "") if remaining > 0 else "",
    }


def cli_cooldown_remaining(*, key: str = "claude") -> float:
    """Return the remaining CLI cooldown in seconds, if any."""
    runtime_key = _normalize_cli_key(key)
    next_start_at = float(_next_cli_start_at_by_key.get(runtime_key, 0.0) or 0.0)
    return max(0.0, next_start_at - time.monotonic())
