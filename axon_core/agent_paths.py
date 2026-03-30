from __future__ import annotations

import os
import re as _re
import sqlite3
from pathlib import Path
from typing import Optional


DEFAULT_DEVBRAIN_DB_PATH = Path.home() / ".devbrain" / "devbrain.db"


def _project_name_pattern(name: str) -> str:
    parts = [part for part in _re.split(r"[^a-z0-9]+", (name or "").lower()) if part]
    if not parts:
        return ""
    return rf"(?<![a-z0-9]){'[\\s/_-]*'.join(_re.escape(part) for part in parts)}(?![a-z0-9])"


def _workspace_root_path(workspace_path: str = "") -> Optional[Path]:
    raw = (workspace_path or "").strip()
    if not raw:
        return None
    try:
        return Path(os.path.expanduser(raw)).resolve()
    except Exception:
        return Path(os.path.realpath(os.path.expanduser(raw)))


def _resolve_user_path(path: str, workspace_path: str = "") -> str:
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return os.path.realpath(expanded)
    base = _workspace_root_path(workspace_path)
    if base:
        return os.path.realpath(str(base / expanded))
    return os.path.realpath(expanded)


def _resolve_project_path_from_text(text: str, db_path: Path = DEFAULT_DEVBRAIN_DB_PATH) -> Optional[str]:
    """Resolve a scanned Axon workspace name mentioned in free text."""
    if not db_path.exists():
        return None

    lower = text.lower()
    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(
                "SELECT name, path FROM projects "
                "WHERE COALESCE(status, 'active') != 'archived' "
                "ORDER BY LENGTH(name) DESC"
            ).fetchall()
    except sqlite3.Error:
        return None

    for name, path in rows:
        pattern = _project_name_pattern(name)
        if pattern and _re.search(pattern, lower):
            return path
    return None


def _extract_path_from_text(
    text: str,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
    workspace_path: str = "",
) -> Optional[str]:
    """Best-effort path extraction for common local-path requests."""
    candidates = _re.findall(r'(~\/[^\s,"\')]+|\/home\/[^\s,"\')]+)', text)
    if candidates:
        return _resolve_user_path(candidates[0].rstrip(".,:;!?`"), workspace_path=workspace_path)

    relative_candidates = _re.findall(
        r'(?<!\w)(\.\.?\/[^\s,"\')]+|[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)+)',
        text,
    )
    if relative_candidates:
        candidate = relative_candidates[0].rstrip(".,:;!?`")
        return _resolve_user_path(candidate, workspace_path=workspace_path)

    lower = text.lower()
    common_paths = [
        ("desktop", "~/Desktop"),
        ("downloads", "~/Downloads"),
        ("documents", "~/Documents"),
        ("pictures", "~/Pictures"),
        ("music", "~/Music"),
        ("videos", "~/Videos"),
        ("home directory", "~"),
        ("home folder", "~"),
        ("home", "~"),
    ]
    for label, path in common_paths:
        if label in lower:
            return path
    return _resolve_project_path_from_text(text, db_path=db_path)


def _recent_repo_path(
    history: list[dict[str, object]] | None = None,
    project_name: Optional[str] = None,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
    workspace_path: str = "",
) -> Optional[str]:
    """Reuse the most recent explicit or workspace-derived path from chat history."""
    if project_name:
        project_path = _resolve_project_path_from_text(project_name, db_path=db_path)
        if project_path:
            return _resolve_user_path(project_path, workspace_path=workspace_path)

    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content, db_path=db_path, workspace_path=workspace_path)
        if path:
            return path
    return None


def _recent_file_path(
    history: list[dict[str, object]] | None = None,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
    workspace_path: str = "",
) -> Optional[str]:
    """Reuse the most recent explicit file path from chat history."""
    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content, db_path=db_path, workspace_path=workspace_path)
        if not path:
            continue
        resolved = _resolve_user_path(path, workspace_path=workspace_path)
        candidate = Path(resolved)
        if candidate.exists() and candidate.is_file():
            return path
        if candidate.suffix:
            return path
    return None
