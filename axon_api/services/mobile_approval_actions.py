"""Approval normalization helpers for mobile control actions."""

from __future__ import annotations

from typing import Any

from axon_core.approval_actions import build_command_approval_action, build_edit_approval_action
from axon_data import get_project


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


async def approval_workspace_root(db, workspace_id: object) -> str:
    try:
        workspace_int = int(workspace_id)
    except Exception:
        return ""
    if workspace_int <= 0:
        return ""
    project = await get_project(db, workspace_int)
    return str(_row(project).get("path") or "").strip()


async def normalize_approval_action(db, action: dict[str, Any]) -> dict[str, Any]:
    raw = dict(action or {})
    action_type = str(raw.get("action_type") or "").strip().lower()
    workspace_id = raw.get("workspace_id")
    session_id = str(raw.get("session_id") or "").strip()
    workspace_root = await approval_workspace_root(db, workspace_id)
    if action_type.startswith("file_"):
        operation = str(raw.get("operation") or action_type.removeprefix("file_") or "edit").strip().lower()
        path = str(raw.get("path") or "").strip()
        if not path:
            return {}
        return build_edit_approval_action(
            operation,
            path,
            workspace_id=workspace_id,
            session_id=session_id,
            workspace_root=workspace_root,
        )
    command_preview = str(raw.get("command_preview") or raw.get("full_command") or raw.get("command") or "").strip()
    if not command_preview:
        return {}
    return build_command_approval_action(
        command_preview,
        cwd=str(raw.get("repo_root") or ""),
        workspace_id=workspace_id,
        session_id=session_id,
    )
