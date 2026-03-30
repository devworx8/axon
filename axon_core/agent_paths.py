from __future__ import annotations

import os
import re as _re
import sqlite3
from pathlib import Path
from typing import Optional


DEFAULT_DEVBRAIN_DB_PATH = Path.home() / ".devbrain" / "devbrain.db"


def _match_workspace_candidate(candidate: str, workspace_path: str = "") -> Optional[str]:
    workspace_root = _workspace_root_path(workspace_path)
    if not workspace_root or not workspace_root.exists() or not workspace_root.is_dir():
        return None

    resolved = Path(_resolve_user_path(candidate, workspace_path=workspace_path))
    if resolved.exists():
        return str(resolved)

    # For bare file names like "agent.py", try a unique basename match inside
    # the selected workspace before falling back to project-name heuristics.
    if "/" in candidate or "\\" in candidate or not Path(candidate).suffix:
        return None

    ignored_dirs = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache"}
    matches: list[Path] = []
    try:
        for match in workspace_root.rglob(candidate):
            if match.name != candidate:
                continue
            if any(part in ignored_dirs for part in match.parts):
                continue
            matches.append(match.resolve())
            if len(matches) > 1:
                return None
    except Exception:
        return None

    return str(matches[0]) if matches else None


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

    workspace_root = _workspace_root_path(workspace_path)
    if workspace_root and workspace_root.exists() and workspace_root.is_dir():
        seen: set[str] = set()
        workspace_patterns = (
            r'\b(?:last|tail)\s+\d+\s+lines?\s+(?:of|from)\s+[`"\']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)',
            r'\b(?:read|open|edit|rewrite|overwrite|update|delete|remove|show|tail|cat)\s+'
            r'(?:the\s+)?(?:file\s+)?[`"\']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)',
            r'\b(?:in|inside|within|under|from|at|on|for)\s+[`"\']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)',
            r'\b(?:file|files|folder|folders|directory|directories|path|repo|repository)\s+'
            r'[`"\']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)',
        )
        ignored = {
            "the", "this", "that", "it", "them",
            "file", "files", "folder", "folders",
            "directory", "directories", "path",
            "repo", "repository", "workspace",
            "content", "status", "branch", "commit",
        }
        for pattern in workspace_patterns:
            for match in _re.finditer(pattern, text, flags=_re.IGNORECASE):
                candidate = match.group(1).rstrip(".,:;!?`'\"")
                lower_candidate = candidate.lower()
                if (
                    not candidate
                    or candidate in seen
                    or lower_candidate in ignored
                    or candidate in {".", ".."}
                    or candidate.startswith(("~", "/", "./", "../"))
                ):
                    continue
                seen.add(candidate)
                matched = _match_workspace_candidate(candidate, workspace_path=workspace_path)
                if matched:
                    return matched

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


def _repo_root_path(path: str, workspace_path: str = "") -> Optional[str]:
    """Resolve a repo-friendly working directory for git operations.

    If the path points to a file, use its parent directory. If the path lives
    inside a git repo, return the repo root; otherwise return the nearest
    existing directory.
    """
    raw = (path or "").strip()
    if not raw:
        return None

    candidate = Path(_resolve_user_path(raw, workspace_path=workspace_path))
    if candidate.exists() and candidate.is_file():
        candidate = candidate.parent
    elif not candidate.exists() and candidate.suffix:
        candidate = candidate.parent

    nearest_dir = candidate if candidate.is_dir() else candidate.parent
    probe = nearest_dir
    while probe and probe != probe.parent:
        if (probe / ".git").exists():
            return str(probe)
        probe = probe.parent
    return str(nearest_dir) if str(nearest_dir) else None


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
            return _repo_root_path(project_path, workspace_path=workspace_path) or _resolve_user_path(project_path, workspace_path=workspace_path)

    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content, db_path=db_path, workspace_path=workspace_path)
        if path:
            return _repo_root_path(path, workspace_path=workspace_path) or path
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
