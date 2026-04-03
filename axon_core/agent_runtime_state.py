"""Workspace-scoped runtime state for concurrent agent runs.

This module keeps two pieces of transient state out of the legacy facades:

- the active workspace path used for tool cwd defaulting
- steer messages queued from the UI for a specific session/workspace
"""

from __future__ import annotations

import os
import threading
from contextvars import ContextVar, Token
from typing import Optional

_ACTIVE_WORKSPACE_PATH: ContextVar[str] = ContextVar(
    "axon_active_workspace_path",
    default="",
)

_STEER_LOCK = threading.Lock()
_STEER_QUEUES: dict[str, list[str]] = {}


def set_active_workspace_path(path: str) -> Token:
    return _ACTIVE_WORKSPACE_PATH.set(str(path or "").strip())


def reset_active_workspace_path(token: Token) -> None:
    _ACTIVE_WORKSPACE_PATH.reset(token)


def current_workspace_path() -> str:
    return str(_ACTIVE_WORKSPACE_PATH.get() or "").strip()


def workspace_root(home: str) -> str:
    raw = current_workspace_path()
    if raw:
        resolved = os.path.realpath(os.path.expanduser(raw))
        home_root = os.path.realpath(os.path.expanduser(str(home or "").strip()))
        if resolved.startswith(home_root) and os.path.isdir(resolved):
            return resolved
    return os.path.realpath(os.path.expanduser(str(home or "").strip()))


def active_workspace_root() -> str:
    raw = current_workspace_path()
    if not raw:
        return ""
    resolved = os.path.realpath(os.path.expanduser(raw))
    if os.path.isdir(resolved):
        return resolved
    return ""


def _session_queue_key(session_id: str) -> str:
    return f"session:{str(session_id or '').strip()}"


def _workspace_queue_key(workspace_id: Optional[int | str]) -> str:
    return f"workspace:{str(workspace_id or '').strip()}"


def enqueue_steer_message(message: str, *, session_id: str = "", workspace_id: Optional[int | str] = None) -> int:
    text = str(message or "").strip()
    if not text:
        return 0
    key = ""
    if str(session_id or "").strip():
        key = _session_queue_key(session_id)
    elif str(workspace_id or "").strip():
        key = _workspace_queue_key(workspace_id)
    else:
        key = "global"
    with _STEER_LOCK:
        queue = _STEER_QUEUES.setdefault(key, [])
        queue.append(text)
        return len(queue)


def drain_steer_messages(*, session_id: str = "", workspace_id: Optional[int | str] = None) -> list[str]:
    keys: list[str] = []
    if str(session_id or "").strip():
        keys.append(_session_queue_key(session_id))
    if str(workspace_id or "").strip():
        keys.append(_workspace_queue_key(workspace_id))
    keys.append("global")

    drained: list[str] = []
    with _STEER_LOCK:
        for key in keys:
            queue = _STEER_QUEUES.pop(key, [])
            if queue:
                drained.extend(queue)
    return drained


def queued_steer_count(*, session_id: str = "", workspace_id: Optional[int | str] = None) -> int:
    keys: list[str] = []
    if str(session_id or "").strip():
        keys.append(_session_queue_key(session_id))
    if str(workspace_id or "").strip():
        keys.append(_workspace_queue_key(workspace_id))
    if not keys:
        keys.append("global")
    with _STEER_LOCK:
        return sum(len(_STEER_QUEUES.get(key, [])) for key in keys)
