"""File-backed task sandbox helpers for isolated mission worktrees."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TASK_SANDBOX_ROOT = Path.home() / ".devbrain" / "task_sandboxes"
TASK_SANDBOX_META = ".axon-sandbox.json"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return (text or "mission")[:max_len].strip("-") or "mission"


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Git command failed").strip()
        raise RuntimeError(message)
    return (result.stdout or "").strip()


def _find_existing_sandbox_dir(task_id: int) -> Path | None:
    if not TASK_SANDBOX_ROOT.exists():
        return None
    matches = sorted(TASK_SANDBOX_ROOT.glob(f"task-{int(task_id)}-*"))
    return matches[0] if matches else None


def task_sandbox_dir(task_id: int, title: str = "") -> Path:
    existing = _find_existing_sandbox_dir(task_id)
    if existing:
        return existing
    return TASK_SANDBOX_ROOT / f"task-{int(task_id)}-{_slugify(title)}"


def task_sandbox_meta_path(task_id: int, title: str = "") -> Path:
    return task_sandbox_dir(task_id, title) / TASK_SANDBOX_META


def read_task_sandbox(task_id: int, title: str = "") -> dict[str, Any] | None:
    meta_path = task_sandbox_meta_path(task_id, title)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_task_sandbox(meta: dict[str, Any]) -> dict[str, Any]:
    task_id = int(meta["task_id"])
    title = str(meta.get("task_title") or "")
    sandbox_dir = Path(meta.get("sandbox_path") or task_sandbox_dir(task_id, title))
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    meta["sandbox_path"] = str(sandbox_dir)
    meta["updated_at"] = _now_iso()
    meta_path = sandbox_dir / TASK_SANDBOX_META
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def _status_records(repo: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Git status failed").strip()
        raise RuntimeError(message)

    entries: list[dict[str, str]] = []
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        code = line[:2]
        payload = line[3:].strip() if len(line) > 3 else ""
        old_path = ""
        path = payload
        if " -> " in payload:
            old_path, path = [part.strip() for part in payload.split(" -> ", 1)]
        if Path(path).name == TASK_SANDBOX_META or Path(old_path).name == TASK_SANDBOX_META:
            continue
        entries.append({"code": code, "path": path, "old_path": old_path})
    return entries


def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists() and not target.is_dir():
            target.unlink()
        shutil.copytree(source, target, dirs_exist_ok=True)
        return
    if target.exists() and target.is_dir():
        shutil.rmtree(target)
    shutil.copy2(source, target)


def _delete_path(target: Path) -> None:
    if not target.exists():
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def list_task_sandboxes() -> list[dict[str, Any]]:
    if not TASK_SANDBOX_ROOT.exists():
        return []
    sandboxes: list[dict[str, Any]] = []
    for meta_path in sorted(TASK_SANDBOX_ROOT.glob(f"task-*/{TASK_SANDBOX_META}"), reverse=True):
        try:
            sandboxes.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            continue
    sandboxes.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return sandboxes


def ensure_task_sandbox(task: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    task_id = int(task["id"])
    title = str(task.get("title") or f"task-{task_id}")
    project_path = str(project.get("path") or "").strip()
    if not project_path:
        raise ValueError("This mission needs a workspace before Axon can create a sandbox.")

    workspace_path = Path(project_path).expanduser().resolve()
    if not workspace_path.exists():
        raise ValueError(f"Workspace path does not exist: {workspace_path}")

    repo_root = Path(_run_git(["rev-parse", "--show-toplevel"], workspace_path))
    base_branch = _run_git(["branch", "--show-current"], repo_root) or "HEAD"

    sandbox_dir = task_sandbox_dir(task_id, title)
    existing = read_task_sandbox(task_id, title) or {}
    branch_name = str(existing.get("branch_name") or f"axon/task-{task_id}-{_slugify(title, 24)}")

    TASK_SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    if not sandbox_dir.exists():
        branch_exists = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            timeout=60,
        ).returncode == 0
        if branch_exists:
            _run_git(["worktree", "add", str(sandbox_dir), branch_name], repo_root)
        else:
            _run_git(["worktree", "add", "-b", branch_name, str(sandbox_dir), "HEAD"], repo_root)

    meta = {
        **existing,
        "task_id": task_id,
        "project_id": task.get("project_id"),
        "project_name": project.get("name") or "",
        "task_title": title,
        "task_detail": str(task.get("detail") or ""),
        "source_path": str(workspace_path),
        "repo_root": str(repo_root),
        "sandbox_path": str(sandbox_dir),
        "branch_name": branch_name,
        "base_branch": base_branch,
        "created_at": existing.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
        "status": existing.get("status") or "ready",
        "changed_files": existing.get("changed_files") or [],
        "diff_stat": existing.get("diff_stat") or "",
        "latest_commit": existing.get("latest_commit") or "",
        "report_markdown": existing.get("report_markdown") or "",
        "final_output": existing.get("final_output") or "",
        "last_error": existing.get("last_error") or "",
        "last_run_started_at": existing.get("last_run_started_at") or "",
        "last_run_completed_at": existing.get("last_run_completed_at") or "",
        "applied_at": existing.get("applied_at") or "",
        "applied_summary": existing.get("applied_summary") or "",
    }
    return write_task_sandbox(meta)


def refresh_task_sandbox(task_id: int, title: str = "") -> dict[str, Any] | None:
    meta = read_task_sandbox(task_id, title)
    if not meta:
        return None

    sandbox_dir = Path(meta.get("sandbox_path") or "")
    if not sandbox_dir.exists():
        meta["status"] = "missing"
        meta["last_error"] = f"Sandbox path missing: {sandbox_dir}"
        return write_task_sandbox(meta)

    status_short = _run_git(["status", "--short"], sandbox_dir)
    diff_stat = _run_git(["diff", "--stat"], sandbox_dir)
    changed_files = {
        line.strip()
        for line in _run_git(["diff", "--name-only"], sandbox_dir).splitlines()
        if line.strip()
    }
    for line in status_short.splitlines():
        if not line.strip():
            continue
        parsed = line.split(maxsplit=1)[1].strip() if " " in line.strip() else line[3:].strip()
        if parsed:
            changed_files.add(parsed)
    latest_commit = _run_git(["log", "--oneline", "--decorate", "-1"], sandbox_dir)

    changed_files_list = sorted(
        path for path in changed_files if Path(path).name != TASK_SANDBOX_META
    )
    meta["changed_files"] = changed_files_list
    meta["diff_stat"] = diff_stat
    meta["latest_commit"] = latest_commit
    meta["has_changes"] = bool(changed_files_list or status_short.strip())

    if meta.get("status") == "completed":
        meta["status"] = "review_ready"
    elif meta.get("status") in {"applied"}:
        pass
    elif meta.get("status") not in {"running", "approval_required", "error"}:
        meta["status"] = "review_ready" if meta["has_changes"] else "ready"

    lines = [
        "# Mission Sandbox Report",
        "",
        f"- Mission: {meta.get('task_title') or f'Task {task_id}'}",
        f"- Workspace: {meta.get('project_name') or 'Unknown'}",
        f"- Source path: `{meta.get('source_path')}`",
        f"- Sandbox path: `{meta.get('sandbox_path')}`",
        f"- Branch: `{meta.get('branch_name')}` (base `{meta.get('base_branch')}`)",
        f"- Status: `{meta.get('status')}`",
        "",
    ]
    if meta.get("last_run_started_at"):
        lines.append(f"- Last run started: {meta['last_run_started_at']}")
    if meta.get("last_run_completed_at"):
        lines.append(f"- Last run completed: {meta['last_run_completed_at']}")
    if meta.get("applied_at"):
        lines.append(f"- Applied to source workspace: {meta['applied_at']}")
    if meta.get("latest_commit"):
        lines.append(f"- Latest commit: `{meta['latest_commit']}`")
    if meta.get("last_error"):
        lines.extend(["", "## Needs Attention", "", meta["last_error"]])
    if meta.get("applied_summary"):
        lines.extend(["", "## Apply Summary", "", str(meta["applied_summary"]).strip()])
    if meta.get("final_output"):
        lines.extend(["", "## Axon Summary", "", str(meta["final_output"]).strip()])
    if diff_stat:
        lines.extend(["", "## Diff Stat", "", "```text", diff_stat, "```"])
    if changed_files_list:
        lines.extend(["", "## Changed Files", ""])
        lines.extend([f"- `{path}`" for path in changed_files_list[:50]])
    elif status_short.strip():
        lines.extend(["", "## Working Tree", "", "```text", status_short, "```"])
    else:
        lines.extend(["", "## Working Tree", "", "No uncommitted changes in the sandbox right now."])

    meta["report_markdown"] = "\n".join(lines).strip() + "\n"
    return write_task_sandbox(meta)


def apply_task_sandbox(task_id: int, title: str = "") -> dict[str, Any]:
    meta = read_task_sandbox(task_id, title)
    if not meta:
        raise ValueError("Sandbox not created yet for this mission.")

    sandbox_dir = Path(str(meta.get("sandbox_path") or "")).expanduser().resolve()
    if not sandbox_dir.exists():
        raise ValueError(f"Sandbox path missing: {sandbox_dir}")

    source_root = Path(str(meta.get("repo_root") or meta.get("source_path") or "")).expanduser().resolve()
    if not source_root.exists():
        raise ValueError(f"Source workspace missing: {source_root}")

    sandbox_entries = _status_records(sandbox_dir)
    if not sandbox_entries:
        raise ValueError("Sandbox has no pending file changes to apply.")

    source_dirty_paths = {
        candidate
        for item in _status_records(source_root)
        for candidate in (item.get("path", ""), item.get("old_path", ""))
        if candidate
    }
    incoming_paths = {
        candidate
        for item in sandbox_entries
        for candidate in (item.get("path", ""), item.get("old_path", ""))
        if candidate
    }
    conflicts = sorted(source_dirty_paths & incoming_paths)
    if conflicts:
        raise RuntimeError(
            "Source workspace has overlapping uncommitted changes: "
            + ", ".join(conflicts[:8])
            + ("..." if len(conflicts) > 8 else "")
        )

    copied = 0
    deleted = 0
    renamed = 0
    operations: list[str] = []

    for entry in sandbox_entries:
        rel_path = str(entry.get("path") or "").strip()
        old_path = str(entry.get("old_path") or "").strip()
        code = str(entry.get("code") or "")
        if not rel_path:
            continue

        source_path = sandbox_dir / rel_path
        target_path = source_root / rel_path
        delete_only = "D" in code and not source_path.exists()

        if delete_only:
            _delete_path(target_path)
            deleted += 1
            operations.append(f"delete {rel_path}")
            continue

        if not source_path.exists():
            raise RuntimeError(f"Sandbox file missing while applying changes: {rel_path}")

        _copy_path(source_path, target_path)
        copied += 1
        operations.append(f"copy {rel_path}")

        if old_path and old_path != rel_path:
            _delete_path(source_root / old_path)
            renamed += 1
            operations.append(f"rename {old_path} -> {rel_path}")

    summary = f"Applied {copied} file(s) to the source workspace"
    if deleted:
        summary += f", removed {deleted}"
    if renamed:
        summary += f", renamed {renamed}"
    summary += "."

    meta["status"] = "applied"
    meta["last_error"] = ""
    meta["applied_at"] = _now_iso()
    meta["applied_summary"] = summary
    write_task_sandbox(meta)
    refreshed = refresh_task_sandbox(task_id, title) or meta
    return {
        "applied": True,
        "summary": summary,
        "copied": copied,
        "deleted": deleted,
        "renamed": renamed,
        "operations": operations[:50],
        "sandbox": refreshed,
    }


def discard_task_sandbox(task_id: int, title: str = "") -> dict[str, Any]:
    meta = read_task_sandbox(task_id, title)
    if not meta:
        raise ValueError("Sandbox not created yet for this mission.")

    sandbox_dir = Path(str(meta.get("sandbox_path") or "")).expanduser().resolve()
    repo_root = Path(str(meta.get("repo_root") or meta.get("source_path") or "")).expanduser().resolve()
    branch_name = str(meta.get("branch_name") or "")
    base_branch = str(meta.get("base_branch") or "")

    if sandbox_dir.exists() and repo_root.exists():
        try:
            _run_git(["worktree", "remove", "--force", str(sandbox_dir)], repo_root)
        except Exception:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    if branch_name and branch_name != base_branch and repo_root.exists():
        subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", branch_name],
            capture_output=True,
            text=True,
            timeout=60,
        )

    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir, ignore_errors=True)

    return {
        "discarded": True,
        "sandbox_path": str(sandbox_dir),
        "branch_name": branch_name,
    }
