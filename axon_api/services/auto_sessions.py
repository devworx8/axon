"""File-backed Console Auto session helpers."""

from __future__ import annotations

from typing import Any

from axon_api.services import sandbox_sessions

AUTO_SESSION_ROOT = sandbox_sessions.SANDBOX_ROOTS["auto"]
AUTO_SESSION_META = sandbox_sessions.SANDBOX_META


def auto_session_dir(session_id: str, title: str = ""):
    return sandbox_sessions.sandbox_dir("auto", session_id, title)


def auto_session_meta_path(session_id: str, title: str = ""):
    return sandbox_sessions.sandbox_meta_path("auto", session_id, title)


def read_auto_session(session_id: str, title: str = "") -> dict[str, Any] | None:
    return sandbox_sessions.read_sandbox_session("auto", session_id, title)


def write_auto_session(meta: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(meta)
    cloned["session_kind"] = "auto"
    cloned["session_id"] = str(cloned.get("session_id") or "")
    if not cloned["session_id"]:
        raise ValueError("Auto session metadata requires session_id.")
    cloned.setdefault("title", str(cloned.get("title") or cloned.get("workspace_name") or ""))
    return sandbox_sessions.write_sandbox_session(cloned)


def list_auto_sessions() -> list[dict[str, Any]]:
    return sandbox_sessions.list_sandbox_sessions("auto")


def find_workspace_auto_session(workspace_id: int | None, *, active_only: bool = False) -> dict[str, Any] | None:
    if not workspace_id:
        return None
    rows = [
        row for row in list_auto_sessions()
        if int(row.get("workspace_id") or 0) == int(workspace_id)
    ]
    if active_only:
        rows = [
            row for row in rows
            if str(row.get("status") or "") not in {"applied", "discarded"}
        ]
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows[0] if rows else None


def ensure_auto_session(
    session_id: str,
    workspace: dict[str, Any],
    *,
    title: str,
    detail: str,
    runtime_override: dict[str, Any] | None = None,
    start_prompt: str = "",
    mode: str = "auto",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace_id = workspace.get("id")
    meta = sandbox_sessions.ensure_sandbox_session(
        session_kind="auto",
        session_id=session_id,
        title=title,
        source_path=str(workspace.get("path") or ""),
        source_name=str(workspace.get("name") or ""),
        source_id=workspace_id,
        detail=detail,
        metadata={
            "workspace_id": workspace_id,
            "workspace_name": workspace.get("name") or "",
            "mode": mode,
            "runtime_override": dict(runtime_override or {}),
            "start_prompt": start_prompt,
            "command_receipts": [],
            "verification_receipts": [],
            "inferred_notes": [],
            **(metadata or {}),
        },
    )
    return meta


def refresh_auto_session(session_id: str, title: str = "") -> dict[str, Any] | None:
    return sandbox_sessions.refresh_sandbox_session("auto", session_id, title)


def apply_auto_session(session_id: str, title: str = "") -> dict[str, Any]:
    return sandbox_sessions.apply_sandbox_session("auto", session_id, title)


def discard_auto_session(session_id: str, title: str = "") -> dict[str, Any]:
    return sandbox_sessions.discard_sandbox_session("auto", session_id, title)
