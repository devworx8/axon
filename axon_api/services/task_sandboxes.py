"""File-backed task sandbox helpers for isolated mission worktrees."""

from __future__ import annotations

from typing import Any

from axon_api.services import sandbox_sessions

TASK_SANDBOX_ROOT = sandbox_sessions.SANDBOX_ROOTS["task"]
TASK_SANDBOX_META = sandbox_sessions.SANDBOX_META


def task_sandbox_dir(task_id: int, title: str = ""):
    return sandbox_sessions.sandbox_dir("task", task_id, title)


def task_sandbox_meta_path(task_id: int, title: str = ""):
    return sandbox_sessions.sandbox_meta_path("task", task_id, title)


def read_task_sandbox(task_id: int, title: str = "") -> dict[str, Any] | None:
    meta = sandbox_sessions.read_sandbox_session("task", task_id, title)
    if meta and "task_id" not in meta:
        meta["task_id"] = int(task_id)
    return meta


def write_task_sandbox(meta: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(meta)
    cloned["session_kind"] = "task"
    cloned["session_id"] = str(cloned.get("task_id") or cloned.get("session_id") or "")
    if not cloned["session_id"]:
        raise ValueError("Task sandbox metadata requires task_id.")
    cloned.setdefault("title", str(cloned.get("task_title") or ""))
    return sandbox_sessions.write_sandbox_session(cloned)


def list_task_sandboxes() -> list[dict[str, Any]]:
    rows = sandbox_sessions.list_sandbox_sessions("task")
    for row in rows:
        row.setdefault("task_id", int(row.get("session_id") or 0))
    return rows


def ensure_task_sandbox(task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    task_id = int(task["id"])
    title = str(task.get("title") or f"task-{task_id}")
    meta = sandbox_sessions.ensure_sandbox_session(
        session_kind="task",
        session_id=task_id,
        title=title,
        source_path=str(project.get("path") or ""),
        source_name=str(project.get("name") or ""),
        source_id=task.get("project_id"),
        detail=str(task.get("detail") or ""),
        metadata={
            "task_id": task_id,
            "project_id": task.get("project_id"),
            "project_name": project.get("name") or "",
            "task_title": title,
            "task_detail": str(task.get("detail") or ""),
        },
    )
    return meta


def refresh_task_sandbox(task_id: int, title: str = "") -> dict[str, Any] | None:
    meta = sandbox_sessions.refresh_sandbox_session("task", task_id, title)
    if meta and "task_id" not in meta:
        meta["task_id"] = int(task_id)
    return meta


def apply_task_sandbox(task_id: int, title: str = "") -> dict[str, Any]:
    return sandbox_sessions.apply_sandbox_session("task", task_id, title)


def discard_task_sandbox(task_id: int, title: str = "") -> dict[str, Any]:
    return sandbox_sessions.discard_sandbox_session("task", task_id, title)
