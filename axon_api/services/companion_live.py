"""Live Axon state helpers for the mobile companion."""

from __future__ import annotations

import json
from typing import Any

from axon_api.services.live_operator_state import LIVE_OPERATOR_SNAPSHOT, set_live_operator
from axon_data import get_companion_presence, get_companion_session, get_project

_UNSET = object()


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _project_payload(project: dict[str, Any] | None) -> dict[str, Any]:
    project = dict(project or {})
    if not project:
        return {}
    return {
        "id": project.get("id"),
        "name": str(project.get("name") or "").strip(),
        "path": str(project.get("path") or "").strip(),
        "git_branch": str(project.get("git_branch") or "").strip(),
    }


def _operator_payload(snapshot: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(snapshot or {})
    payload["workspace_name"] = str((project or {}).get("name") or payload.get("workspace_name") or "").strip()
    payload["workspace_path"] = str((project or {}).get("path") or payload.get("workspace_path") or "").strip()
    payload["feed"] = list(payload.get("feed") or [])
    return payload


async def build_companion_live_snapshot(
    db,
    *,
    device_id: int | None = None,
    session_id: int | None = None,
    workspace_id: int | None = None,
    session_row: Any = _UNSET,
    presence_row: Any = _UNSET,
    operator_project_row: Any = _UNSET,
    focus_project_row: Any = _UNSET,
) -> dict[str, Any]:
    session = _row(session_row) if session_row is not _UNSET else (_row(await get_companion_session(db, int(session_id))) if session_id else {})
    presence = _row(presence_row) if presence_row is not _UNSET else (_row(await get_companion_presence(db, int(device_id))) if device_id else {})
    operator = dict(LIVE_OPERATOR_SNAPSHOT)
    focus_workspace_id = (
        int(workspace_id)
        if workspace_id is not None
        else int(session.get("workspace_id") or presence.get("workspace_id") or operator.get("workspace_id") or 0) or None
    )
    operator_workspace_id = int(operator.get("workspace_id") or 0) or focus_workspace_id
    project = (
        _row(operator_project_row)
        if operator_project_row is not _UNSET
        else (_row(await get_project(db, operator_workspace_id)) if operator_workspace_id else {})
    )
    focus_project = _row(focus_project_row) if focus_project_row is not _UNSET else project
    if not focus_project and focus_workspace_id and focus_workspace_id != operator_workspace_id:
        focus_project = _row(await get_project(db, focus_workspace_id))
    return {
        "at": str(operator.get("updated_at") or ""),
        "operator": _operator_payload(operator, project),
        "focus": {
            "workspace_id": focus_workspace_id,
            "workspace": _project_payload(focus_project),
            "session_id": session.get("id"),
        },
        "session": session,
        "presence": presence,
    }


def apply_companion_agent_event(
    event: dict[str, Any],
    *,
    project: dict[str, Any] | None = None,
    user_message: str = "",
    agent_session_id: str = "",
) -> None:
    event_type = str(event.get("type") or "").strip().lower()
    workspace_id = int((project or {}).get("id") or 0) or None
    summary = str(user_message or "").strip()[:120]

    if event_type == "thinking":
        set_live_operator(
            active=True,
            mode="agent",
            phase="plan",
            title="Thinking through the live voice task",
            detail=str(event.get("chunk") or "Axon is reasoning through the voice request.")[:180],
            workspace_id=workspace_id,
            auto_session_id=agent_session_id,
            preserve_started=True,
        )
        return
    if event_type == "tool_call":
        set_live_operator(
            active=True,
            mode="agent",
            phase="execute",
            title=f"Running {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=json.dumps(event.get("args") or {})[:180],
            tool=str(event.get("name") or ""),
            workspace_id=workspace_id,
            auto_session_id=agent_session_id,
            preserve_started=True,
        )
        return
    if event_type == "tool_result":
        set_live_operator(
            active=True,
            mode="agent",
            phase="verify",
            title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=str(event.get("result") or "Axon is reviewing the tool output.")[:180],
            tool=str(event.get("name") or ""),
            workspace_id=workspace_id,
            auto_session_id=agent_session_id,
            preserve_started=True,
        )
        return
    if event_type == "approval_required":
        set_live_operator(
            active=False,
            mode="agent",
            phase="recover",
            title="Awaiting approval from Axon Online",
            detail=str(event.get("message") or "Axon paused until you approve the blocked step.")[:180],
            summary=summary,
            workspace_id=workspace_id,
            auto_session_id=agent_session_id,
        )
        return
    if event_type == "error":
        set_live_operator(
            active=False,
            mode="agent",
            phase="recover",
            title="Live voice task needs attention",
            detail=str(event.get("message") or "Axon hit an error and stopped safely.")[:180],
            summary=summary,
            workspace_id=workspace_id,
            auto_session_id=agent_session_id,
        )
