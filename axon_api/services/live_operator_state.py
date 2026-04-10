"""Live operator snapshot state and event helpers."""

from __future__ import annotations

import json
import time as _time
from datetime import UTC, datetime
from typing import Any, Callable, Optional


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


LIVE_OPERATOR_SNAPSHOT: dict[str, Any] = {
    "active": False,
    "mode": "idle",
    "phase": "observe",
    "title": "Standing by",
    "detail": "Axon is ready for the next request.",
    "tool": "",
    "summary": "",
    "workspace_id": None,
    "auto_session_id": "",
    "changed_files_count": 0,
    "apply_allowed": False,
    "started_at": "",
    "updated_at": "",
    "feed": [],
}

def set_live_operator(
    *,
    active: bool,
    mode: str,
    phase: str,
    title: str,
    detail: str = "",
    tool: str = "",
    summary: str = "",
    workspace_id: Optional[int] = None,
    auto_session_id: str = "",
    changed_files_count: int = 0,
    apply_allowed: bool = False,
    preserve_started: bool = False,
    live_operator_snapshot: dict[str, Any] | None = None,
) -> None:
    snapshot = live_operator_snapshot or LIVE_OPERATOR_SNAPSHOT
    started_at = snapshot.get("started_at") if preserve_started else _now_iso()
    if not started_at:
        started_at = _now_iso()
    updated_at = _now_iso()
    tracked_auto_session_id = auto_session_id if auto_session_id else (snapshot.get("auto_session_id") if mode == "auto" else "")
    if active and not preserve_started and str(phase or "").strip().lower() == "observe":
        snapshot["feed"] = []
    snapshot.update(
        {
            "active": active,
            "mode": mode,
            "phase": phase,
            "title": title,
            "detail": detail,
            "tool": tool,
            "summary": summary or snapshot.get("summary", ""),
            "workspace_id": workspace_id,
            "auto_session_id": tracked_auto_session_id or "",
            "changed_files_count": int(changed_files_count or 0) if (active or tracked_auto_session_id) else 0,
            "apply_allowed": bool(apply_allowed) if (active or tracked_auto_session_id) else False,
            "started_at": started_at if active else "",
            "updated_at": updated_at,
        }
    )
    if active or tracked_auto_session_id:
        entry = {
            "id": f"{int(_time.time() * 1000)}-{phase}",
            "phase": phase,
            "title": title,
            "detail": detail,
            "at": updated_at,
        }
        feed = list(snapshot.get("feed") or [])
        last = feed[-1] if feed else None
        last_matches = bool(
            last
            and str(last.get("phase") or "") == str(entry.get("phase") or "")
            and str(last.get("title") or "") == str(entry.get("title") or "")
        )
        if last_matches:
            feed[-1] = {
                **last,
                "id": entry["id"],
                "detail": entry["detail"],
                "at": entry["at"],
            }
            snapshot["feed"] = feed[-12:]
        elif not last or any(str(last.get(key) or "") != str(entry.get(key) or "") for key in ("phase", "title", "detail")):
            feed.append(entry)
            snapshot["feed"] = feed[-12:]
    else:
        snapshot["feed"] = []


def auto_session_live_operator(
    session_meta: dict,
    event: dict,
    *,
    set_live_operator_fn: Callable[..., None] | None = None,
) -> None:
    update = set_live_operator_fn or set_live_operator
    event_type = str(event.get("type") or "")
    workspace_id = session_meta.get("workspace_id")
    session_id = str(session_meta.get("session_id") or "")
    changed_files_count = len(session_meta.get("changed_files") or [])
    if event_type == "tool_call":
        update(
            active=True,
            mode="auto",
            phase="execute",
            title=f"Auto: {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=json.dumps(event.get("args") or {})[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "tool_result":
        update(
            active=True,
            mode="auto",
            phase="verify",
            title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=str(event.get("result") or "")[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "text":
        update(
            active=True,
            mode="auto",
            phase="verify",
            title="Writing Auto handoff",
            detail="Axon is preparing the sandbox review handoff.",
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "thinking":
        update(
            active=True,
            mode="auto",
            phase="plan",
            title="Planning inside Auto sandbox",
            detail=str(event.get("chunk") or "")[:180],
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "approval_required":
        update(
            active=False,
            mode="auto",
            phase="recover",
            title="Auto session awaiting approval",
            detail=str(event.get("message") or "Axon paused for approval inside the sandbox.")[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
            auto_session_id=session_id,
        )
    elif event_type == "error":
        update(
            active=False,
            mode="auto",
            phase="recover",
            title="Auto session needs attention",
            detail=str(event.get("message") or "Axon stopped inside the sandbox.")[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
            auto_session_id=session_id,
        )


def task_sandbox_live_operator(
    task: dict,
    event: dict,
    *,
    set_live_operator_fn: Callable[..., None] | None = None,
) -> None:
    update = set_live_operator_fn or set_live_operator
    event_type = event.get("type")
    workspace_id = task.get("project_id")
    if event_type == "tool_call":
        update(
            active=True,
            mode="agent",
            phase="execute",
            title=f"Sandbox: {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=json.dumps(event.get("args") or {})[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "tool_result":
        update(
            active=True,
            mode="agent",
            phase="verify",
            title=f"Reviewing {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=str(event.get("result") or "")[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "text":
        update(
            active=True,
            mode="agent",
            phase="verify",
            title="Writing sandbox handoff",
            detail="Axon is turning the sandbox run into a reviewable report.",
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "thinking":
        update(
            active=True,
            mode="agent",
            phase="plan",
            title="Planning inside sandbox",
            detail=str(event.get("chunk") or "")[:180],
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "approval_required":
        update(
            active=False,
            mode="agent",
            phase="recover",
            title="Sandbox awaiting approval",
            detail=str(event.get("message") or "Axon paused for approval inside the sandbox.")[:180],
            summary=task.get("title", "")[:120],
            workspace_id=workspace_id,
        )
    elif event_type == "error":
        update(
            active=False,
            mode="agent",
            phase="recover",
            title="Sandbox needs attention",
            detail=str(event.get("message") or "Axon stopped inside the sandbox.")[:180],
            summary=task.get("title", "")[:120],
            workspace_id=workspace_id,
        )
