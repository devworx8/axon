"""Local workspace repository inspection helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _row(project: Any) -> dict[str, Any]:
    return dict(project) if project else {}


def _run_git(repo_path: Path, *args: str) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.rstrip("\n"), proc.stderr.rstrip("\n")


def _parse_status_entries(raw_status: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw_line in str(raw_status or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        code = line[:2]
        payload = line[3:].strip() if len(line) > 3 else ""
        old_path = ""
        path = payload
        if " -> " in payload:
            old_path, path = [part.strip() for part in payload.split(" -> ", 1)]
        entries.append({"code": code, "path": path, "old_path": old_path})
    return entries


def inspect_workspace_repo(project: Any) -> dict[str, Any]:
    project_dict = _row(project)
    raw_path = str(project_dict.get("path") or "").strip()
    if not raw_path:
        return {
            "path": "",
            "exists": False,
            "is_git_repo": False,
            "dirty": False,
            "status_entries": [],
            "dirty_count": 0,
            "tracked_change_count": 0,
            "untracked_count": 0,
            "worktree_write_safe": False,
            "summary": "Workspace path is missing.",
        }

    repo_path = Path(raw_path).expanduser().resolve()
    if not repo_path.exists():
        return {
            "path": str(repo_path),
            "exists": False,
            "is_git_repo": False,
            "dirty": False,
            "status_entries": [],
            "dirty_count": 0,
            "tracked_change_count": 0,
            "untracked_count": 0,
            "worktree_write_safe": False,
            "summary": "Workspace path is missing on disk.",
        }

    repo_state: dict[str, Any] = {
        "path": str(repo_path),
        "exists": True,
        "is_git_repo": False,
        "branch": "",
        "remote_origin_url": "",
        "dirty": False,
        "status_entries": [],
        "dirty_count": 0,
        "tracked_change_count": 0,
        "untracked_count": 0,
        "worktree_write_safe": False,
        "summary": "",
    }

    returncode, stdout, stderr = _run_git(repo_path, "rev-parse", "--is-inside-work-tree")
    if returncode != 0 or stdout.lower() != "true":
        repo_state["git_error"] = stderr or stdout or "Not a git worktree."
        repo_state["summary"] = "Workspace path exists but is not a git repo."
        return repo_state

    repo_state["is_git_repo"] = True

    _branch_rc, branch_stdout, _branch_stderr = _run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    repo_state["branch"] = branch_stdout or str(project_dict.get("git_branch") or "").strip()

    _remote_rc, remote_stdout, _remote_stderr = _run_git(repo_path, "config", "--get", "remote.origin.url")
    repo_state["remote_origin_url"] = remote_stdout

    status_rc, status_stdout, status_stderr = _run_git(repo_path, "status", "--porcelain")
    if status_rc != 0:
        repo_state["git_error"] = status_stderr or status_stdout or "git status failed"
        repo_state["summary"] = "Git repo found, but Axon could not read worktree status."
        return repo_state

    entries = _parse_status_entries(status_stdout)
    untracked_count = sum(1 for entry in entries if "?" in str(entry.get("code") or ""))
    tracked_change_count = max(0, len(entries) - untracked_count)
    dirty = bool(entries)

    repo_state.update(
        {
            "dirty": dirty,
            "status_entries": entries,
            "dirty_count": len(entries),
            "tracked_change_count": tracked_change_count,
            "untracked_count": untracked_count,
            "worktree_write_safe": not dirty,
        }
    )
    repo_state["summary"] = (
        f"Git repo on {repo_state['branch'] or 'detached HEAD'} with {len(entries)} local change(s)."
        if dirty
        else f"Git repo on {repo_state['branch'] or 'detached HEAD'} with a clean worktree."
    )
    return repo_state
