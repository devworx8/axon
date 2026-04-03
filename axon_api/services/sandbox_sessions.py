"""Shared file-backed git worktree sandbox helpers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SANDBOX_META = ".axon-sandbox.json"

SANDBOX_ROOTS = {
    "task": Path.home() / ".devbrain" / "task_sandboxes",
    "auto": Path.home() / ".devbrain" / "auto_sessions",
}

SANDBOX_PREFIXES = {
    "task": "task",
    "auto": "auto",
}

IGNORED_SANDBOX_ARTIFACTS = {
    SANDBOX_META,
    ".codex",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str, max_len: int = 40) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return (text or "session")[:max_len].strip("-") or "session"


def sandbox_root(kind: str) -> Path:
    root = SANDBOX_ROOTS.get(str(kind or "").strip().lower())
    if not root:
        raise ValueError(f"Unsupported sandbox session kind: {kind}")
    return root


def sandbox_prefix(kind: str) -> str:
    prefix = SANDBOX_PREFIXES.get(str(kind or "").strip().lower())
    if not prefix:
        raise ValueError(f"Unsupported sandbox session kind: {kind}")
    return prefix


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


def _find_existing_sandbox_dir(kind: str, session_id: str | int) -> Path | None:
    root = sandbox_root(kind)
    if not root.exists():
        return None
    prefix = sandbox_prefix(kind)
    matches = sorted(root.glob(f"{prefix}-{str(session_id).strip()}-*"))
    return matches[0] if matches else None


def sandbox_dir(kind: str, session_id: str | int, title: str = "") -> Path:
    existing = _find_existing_sandbox_dir(kind, session_id)
    if existing:
        return existing
    return sandbox_root(kind) / f"{sandbox_prefix(kind)}-{str(session_id).strip()}-{_slugify(title)}"


def sandbox_meta_path(kind: str, session_id: str | int, title: str = "") -> Path:
    return sandbox_dir(kind, session_id, title) / SANDBOX_META


def read_sandbox_session(kind: str, session_id: str | int, title: str = "") -> dict[str, Any] | None:
    meta_path = sandbox_meta_path(kind, session_id, title)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_sandbox_session(meta: dict[str, Any]) -> dict[str, Any]:
    kind = str(meta.get("session_kind") or "").strip().lower()
    session_id = str(meta.get("session_id") or "").strip()
    if not kind or not session_id:
        raise ValueError("Sandbox session metadata requires session_kind and session_id.")
    title = str(meta.get("title") or "")
    session_dir = Path(meta.get("sandbox_path") or sandbox_dir(kind, session_id, title))
    session_dir.mkdir(parents=True, exist_ok=True)
    meta["sandbox_path"] = str(session_dir)
    meta["updated_at"] = _now_iso()
    meta_path = session_dir / SANDBOX_META
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def _is_ignored_sandbox_artifact(path: str) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    candidate = Path(text)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    if not parts:
        return False
    top = parts[0]
    name = candidate.name
    return top in IGNORED_SANDBOX_ARTIFACTS or name in {SANDBOX_META}


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
        if _is_ignored_sandbox_artifact(path) or _is_ignored_sandbox_artifact(old_path):
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


def _git_state_snapshot(repo: Path) -> dict[str, Any]:
    return {
        "latest_commit": _run_git(["log", "--oneline", "--decorate", "-1"], repo),
        "status_short": _run_git(["status", "--short"], repo),
        "diff_stat": _run_git(["diff", "--stat"], repo),
    }


def _filtered_status_short(status_short: str) -> str:
    kept: list[str] = []
    for raw_line in str(status_short or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        payload = line[3:].strip() if len(line) > 3 else ""
        old_path = ""
        path = payload
        if " -> " in payload:
            old_path, path = [part.strip() for part in payload.split(" -> ", 1)]
        if _is_ignored_sandbox_artifact(path) or _is_ignored_sandbox_artifact(old_path):
            continue
        kept.append(line)
    return "\n".join(kept)


def list_sandbox_sessions(kind: str) -> list[dict[str, Any]]:
    root = sandbox_root(kind)
    prefix = sandbox_prefix(kind)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for meta_path in sorted(root.glob(f"{prefix}-*/{SANDBOX_META}"), reverse=True):
        try:
            rows.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            continue
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows


def ensure_sandbox_session(
    *,
    session_kind: str,
    session_id: str | int,
    title: str,
    source_path: str,
    source_name: str = "",
    source_id: Any = None,
    detail: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = str(session_kind or "").strip().lower()
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("Sandbox session id is required.")
    workspace_path = Path(str(source_path or "")).expanduser().resolve()
    if not source_path:
        raise ValueError("A source workspace path is required before Axon can create a sandbox.")
    if not workspace_path.exists():
        raise ValueError(f"Workspace path does not exist: {workspace_path}")

    repo_root = Path(_run_git(["rev-parse", "--show-toplevel"], workspace_path))
    base_branch = _run_git(["branch", "--show-current"], repo_root) or "HEAD"
    session_dir = sandbox_dir(kind, sid, title)
    existing = read_sandbox_session(kind, sid, title) or {}

    default_branch = f"axon/{sandbox_prefix(kind)}-{_slugify(sid, 12)}-{_slugify(title, 24)}"
    branch_name = str((metadata or {}).get("branch_name") or existing.get("branch_name") or default_branch)

    root = sandbox_root(kind)
    root.mkdir(parents=True, exist_ok=True)
    if not session_dir.exists():
        branch_exists = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            timeout=60,
        ).returncode == 0
        if branch_exists:
            _run_git(["worktree", "add", str(session_dir), branch_name], repo_root)
        else:
            _run_git(["worktree", "add", "-b", branch_name, str(session_dir), "HEAD"], repo_root)

    start_snapshot = existing.get("start_snapshot")
    if not start_snapshot:
        try:
            start_snapshot = _git_state_snapshot(session_dir)
        except Exception:
            start_snapshot = {}

    merged: dict[str, Any] = {
        **existing,
        **(metadata or {}),
        "session_kind": kind,
        "session_id": sid,
        "title": title,
        "detail": detail,
        "source_id": source_id,
        "source_name": source_name or "",
        "source_path": str(workspace_path),
        "repo_root": str(repo_root),
        "sandbox_path": str(session_dir),
        "branch_name": branch_name,
        "base_branch": str((metadata or {}).get("base_branch") or existing.get("base_branch") or base_branch),
        "created_at": existing.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
        "status": (metadata or {}).get("status") or existing.get("status") or "ready",
        "changed_files": list((metadata or {}).get("changed_files") or existing.get("changed_files") or []),
        "diff_stat": str((metadata or {}).get("diff_stat") or existing.get("diff_stat") or ""),
        "latest_commit": str((metadata or {}).get("latest_commit") or existing.get("latest_commit") or ""),
        "report_markdown": str((metadata or {}).get("report_markdown") or existing.get("report_markdown") or ""),
        "final_output": str((metadata or {}).get("final_output") or existing.get("final_output") or ""),
        "last_error": str((metadata or {}).get("last_error") or existing.get("last_error") or ""),
        "last_run_started_at": str((metadata or {}).get("last_run_started_at") or existing.get("last_run_started_at") or ""),
        "last_run_completed_at": str((metadata or {}).get("last_run_completed_at") or existing.get("last_run_completed_at") or ""),
        "applied_at": str((metadata or {}).get("applied_at") or existing.get("applied_at") or ""),
        "applied_summary": str((metadata or {}).get("applied_summary") or existing.get("applied_summary") or ""),
        "mode": str((metadata or {}).get("mode") or existing.get("mode") or ""),
        "runtime_override": dict((metadata or {}).get("runtime_override") or existing.get("runtime_override") or {}),
        "resolved_runtime": dict((metadata or {}).get("resolved_runtime") or existing.get("resolved_runtime") or {}),
        "start_prompt": str((metadata or {}).get("start_prompt") or existing.get("start_prompt") or ""),
        "start_snapshot": start_snapshot,
        "command_receipts": list((metadata or {}).get("command_receipts") or existing.get("command_receipts") or []),
        "verification_receipts": list((metadata or {}).get("verification_receipts") or existing.get("verification_receipts") or []),
        "inferred_notes": list((metadata or {}).get("inferred_notes") or existing.get("inferred_notes") or []),
        "resource_ids": list((metadata or {}).get("resource_ids") or existing.get("resource_ids") or []),
    }
    return write_sandbox_session(merged)


def _receipt_lines(items: list[dict[str, Any]], formatter) -> list[str]:
    lines: list[str] = []
    for item in items[:25]:
        rendered = formatter(item)
        if rendered:
            lines.append(rendered)
    return lines


def _build_auto_report(meta: dict[str, Any], *, status_short: str, diff_stat: str, changed_files: list[str]) -> str:
    title = str(meta.get("title") or f"Auto session {meta.get('session_id')}")
    command_receipts = list(meta.get("command_receipts") or [])
    verification_receipts = list(meta.get("verification_receipts") or [])
    inferred_notes = [str(item).strip() for item in (meta.get("inferred_notes") or []) if str(item).strip()]
    final_output = str(meta.get("final_output") or "").strip()
    last_error = str(meta.get("last_error") or "").strip()

    lines = [
        "# Auto Session Report",
        "",
        f"- Session: `{meta.get('session_id')}`",
        f"- Workspace: {meta.get('source_name') or 'Unknown'}",
        f"- Source path: `{meta.get('source_path')}`",
        f"- Sandbox path: `{meta.get('sandbox_path')}`",
        f"- Branch: `{meta.get('branch_name')}` (base `{meta.get('base_branch')}`)",
        f"- Status: `{meta.get('status')}`",
    ]
    if meta.get("resolved_runtime"):
        runtime = meta["resolved_runtime"]
        runtime_label = str(runtime.get("label") or runtime.get("backend") or "").strip()
        model_label = str(runtime.get("model") or "").strip()
        if runtime_label or model_label:
            lines.append(f"- Runtime: `{runtime_label or 'runtime'}`" + (f" · `{model_label}`" if model_label else ""))
    if meta.get("last_run_started_at"):
        lines.append(f"- Last run started: {meta['last_run_started_at']}")
    if meta.get("last_run_completed_at"):
        lines.append(f"- Last run completed: {meta['last_run_completed_at']}")
    if meta.get("applied_at"):
        lines.append(f"- Applied to source workspace: {meta['applied_at']}")
    if meta.get("latest_commit"):
        lines.append(f"- Latest commit: `{meta['latest_commit']}`")

    lines.extend(["", "## Verified In This Run", ""])
    verified_lines: list[str] = []
    if changed_files:
        verified_lines.append(f"- Working tree changed: {len(changed_files)} file(s) in the sandbox.")
    verified_lines.extend(
        _receipt_lines(
            verification_receipts,
            lambda item: f"- `{item.get('label') or item.get('command') or item.get('tool') or 'check'}`"
            + (f": {str(item.get('summary') or '').strip()}" if str(item.get("summary") or "").strip() else ""),
        )
    )
    if not verified_lines and command_receipts:
        verified_lines.extend(
            _receipt_lines(
                command_receipts,
                lambda item: f"- `{item.get('command') or item.get('label') or item.get('tool') or 'command'}`"
                + (f": {str(item.get('summary') or '').strip()}" if str(item.get("summary") or "").strip() else ""),
            )
        )
    if not verified_lines:
        verified_lines.append("- No explicit verification receipts were recorded in this run.")
    lines.extend(verified_lines)

    lines.extend(["", "## Inferred From Repo State", ""])
    if inferred_notes:
        lines.extend([f"- {note}" for note in inferred_notes[:20]])
    else:
        lines.append("- None recorded automatically.")

    lines.extend(["", "## Not Yet Verified", ""])
    pending_lines: list[str] = []
    if last_error:
        pending_lines.append(f"- {last_error}")
    if not verification_receipts:
        pending_lines.append("- No dedicated verification command receipts were captured yet.")
    if meta.get("status") == "approval_required":
        pending_lines.append("- Axon is blocked pending approval before the next sandbox step.")
    if not pending_lines:
        pending_lines.append("- None.")
    lines.extend(pending_lines)

    lines.extend(["", "## Next Action Not Yet Taken", ""])
    if meta.get("status") == "review_ready":
        lines.append("- Review the sandbox report, then apply or discard the sandbox changes.")
    elif meta.get("status") == "approval_required":
        lines.append("- Continue the Auto session after approval is granted.")
    elif meta.get("status") == "running":
        lines.append("- The Auto session is still running.")
    elif meta.get("status") == "applied":
        lines.append("- Applied. Review the source workspace diff and commit when ready.")
    elif meta.get("status") == "discarded":
        lines.append("- Discarded. Start a new Auto session if more work is needed.")
    elif meta.get("status") == "error":
        lines.append("- Address the blocker and continue the Auto session, or discard it.")
    else:
        lines.append("- Continue the Auto session to produce the next verified change.")

    if final_output:
        lines.extend(
            [
                "",
                "## Axon Summary",
                "",
                "_Operator-authored narrative. Review against the verified receipts above before trusting inferred claims._",
                "",
                final_output,
            ]
        )

    if diff_stat:
        lines.extend(["", "## Diff Stat", "", "```text", diff_stat, "```"])
    if changed_files:
        lines.extend(["", "## Changed Files", ""])
        lines.extend([f"- `{path}`" for path in changed_files[:80]])
    elif status_short.strip():
        lines.extend(["", "## Working Tree", "", "```text", status_short, "```"])
    else:
        lines.extend(["", "## Working Tree", "", "No uncommitted changes in the sandbox right now."])
    return "\n".join(lines).strip() + "\n"


def _build_default_report(meta: dict[str, Any], *, status_short: str, diff_stat: str, changed_files: list[str]) -> str:
    session_id = meta.get("session_id")
    lines = [
        "# Mission Sandbox Report",
        "",
        f"- Session: `{session_id}`",
        f"- Mission: {meta.get('task_title') or meta.get('title') or session_id}",
        f"- Workspace: {meta.get('source_name') or meta.get('project_name') or 'Unknown'}",
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
        lines.extend(["", "## Needs Attention", "", str(meta["last_error"])])
    if meta.get("applied_summary"):
        lines.extend(["", "## Apply Summary", "", str(meta["applied_summary"]).strip()])
    if meta.get("final_output"):
        lines.extend(["", "## Axon Summary", "", str(meta["final_output"]).strip()])
    if diff_stat:
        lines.extend(["", "## Diff Stat", "", "```text", diff_stat, "```"])
    if changed_files:
        lines.extend(["", "## Changed Files", ""])
        lines.extend([f"- `{path}`" for path in changed_files[:50]])
    elif status_short.strip():
        lines.extend(["", "## Working Tree", "", "```text", status_short, "```"])
    else:
        lines.extend(["", "## Working Tree", "", "No uncommitted changes in the sandbox right now."])
    return "\n".join(lines).strip() + "\n"


def refresh_sandbox_session(kind: str, session_id: str | int, title: str = "") -> dict[str, Any] | None:
    meta = read_sandbox_session(kind, session_id, title)
    if not meta:
        return None

    session_dir = Path(meta.get("sandbox_path") or "")
    if not session_dir.exists():
        meta["status"] = "missing"
        meta["last_error"] = f"Sandbox path missing: {session_dir}"
        return write_sandbox_session(meta)

    try:
        status_short = _run_git(["status", "--short"], session_dir)
        visible_status_short = _filtered_status_short(status_short)
        diff_stat = _run_git(["diff", "--stat"], session_dir)
        changed_files = {
            line.strip()
            for line in _run_git(["diff", "--name-only"], session_dir).splitlines()
            if line.strip()
        }
        latest_commit = _run_git(["log", "--oneline", "--decorate", "-1"], session_dir)
    except RuntimeError as exc:
        meta["status"] = "error"
        meta["has_changes"] = False
        meta["changed_files"] = []
        meta["diff_stat"] = ""
        meta["latest_commit"] = ""
        meta["last_error"] = (
            f"Sandbox session is no longer attached to a valid git worktree: {exc}"
        )
        if str(meta.get("mode") or meta.get("session_kind") or "") == "auto":
            meta["report_markdown"] = _build_auto_report(meta, status_short="", diff_stat="", changed_files=[])
        else:
            meta["report_markdown"] = _build_default_report(meta, status_short="", diff_stat="", changed_files=[])
        return write_sandbox_session(meta)

    for line in visible_status_short.splitlines():
        if not line.strip():
            continue
        parsed = line.split(maxsplit=1)[1].strip() if " " in line.strip() else line[3:].strip()
        if parsed:
            changed_files.add(parsed)

    changed_files_list = sorted(path for path in changed_files if not _is_ignored_sandbox_artifact(path))
    meta["changed_files"] = changed_files_list
    meta["diff_stat"] = diff_stat
    meta["latest_commit"] = latest_commit
    meta["has_changes"] = bool(changed_files_list or visible_status_short.strip())

    current_status = str(meta.get("status") or "").strip().lower()
    final_output = str(meta.get("final_output") or "").strip()
    last_error = str(meta.get("last_error") or "").strip()
    verification_receipts = list(meta.get("verification_receipts") or [])
    completed_at = str(meta.get("last_run_completed_at") or meta.get("completed_at") or "").strip()

    if current_status == "completed":
        meta["status"] = "review_ready"
    elif current_status == "running" and completed_at:
        if last_error or final_output.startswith("ERROR:"):
            meta["status"] = "error"
            if not last_error and final_output.startswith("ERROR:"):
                meta["last_error"] = final_output
        elif meta["has_changes"] or verification_receipts or final_output:
            meta["status"] = "review_ready"
        else:
            meta["status"] = "error"
            meta["last_error"] = (
                last_error
                or "Auto session finished without repository changes, verification receipts, "
                "or a concrete blocker. Axon did not produce a reviewable handoff."
            )
    elif current_status in {"applied", "discarded"}:
        pass
    elif current_status not in {"running", "approval_required", "error"}:
        meta["status"] = "review_ready" if meta["has_changes"] else "ready"

    if str(meta.get("mode") or meta.get("session_kind") or "") == "auto":
        meta["report_markdown"] = _build_auto_report(meta, status_short=visible_status_short, diff_stat=diff_stat, changed_files=changed_files_list)
    else:
        meta["report_markdown"] = _build_default_report(meta, status_short=visible_status_short, diff_stat=diff_stat, changed_files=changed_files_list)
    return write_sandbox_session(meta)


def apply_sandbox_session(kind: str, session_id: str | int, title: str = "") -> dict[str, Any]:
    meta = read_sandbox_session(kind, session_id, title)
    if not meta:
        raise ValueError("Sandbox session not created yet.")

    session_dir = Path(str(meta.get("sandbox_path") or "")).expanduser().resolve()
    if not session_dir.exists():
        raise ValueError(f"Sandbox path missing: {session_dir}")

    source_root = Path(str(meta.get("repo_root") or meta.get("source_path") or "")).expanduser().resolve()
    if not source_root.exists():
        raise ValueError(f"Source workspace missing: {source_root}")

    sandbox_entries = _status_records(session_dir)
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

        source_path = session_dir / rel_path
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
    write_sandbox_session(meta)
    refreshed = refresh_sandbox_session(kind, session_id, title) or meta
    return {
        "applied": True,
        "summary": summary,
        "copied": copied,
        "deleted": deleted,
        "renamed": renamed,
        "operations": operations[:50],
        "sandbox": refreshed,
    }


def discard_sandbox_session(kind: str, session_id: str | int, title: str = "") -> dict[str, Any]:
    meta = read_sandbox_session(kind, session_id, title)
    if not meta:
        raise ValueError("Sandbox session not created yet.")

    session_dir = Path(str(meta.get("sandbox_path") or "")).expanduser().resolve()
    repo_root = Path(str(meta.get("repo_root") or meta.get("source_path") or "")).expanduser().resolve()
    branch_name = str(meta.get("branch_name") or "")
    base_branch = str(meta.get("base_branch") or "")

    if session_dir.exists() and repo_root.exists():
        try:
            _run_git(["worktree", "remove", "--force", str(session_dir)], repo_root)
        except Exception:
            shutil.rmtree(session_dir, ignore_errors=True)

    if branch_name and branch_name != base_branch and repo_root.exists():
        subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", branch_name],
            capture_output=True,
            text=True,
            timeout=60,
        )

    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)

    return {
        "discarded": True,
        "sandbox_path": str(session_dir),
        "branch_name": branch_name,
    }
