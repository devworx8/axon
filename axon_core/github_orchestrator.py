from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


def normalize_repo_cwd(path: str) -> str:
    resolved = os.path.realpath(os.path.expanduser(path or "."))
    probe = Path(resolved)
    if probe.is_file():
        probe = probe.parent
    while probe != probe.parent:
        if (probe / ".git").exists():
            return str(probe)
        probe = probe.parent
    return resolved


def prepare_branch(*, repo_path: str, branch_name: str = "") -> tuple[str, str]:
    cwd = normalize_repo_cwd(repo_path)
    branch = branch_name.strip()
    if branch:
        return cwd, f"git checkout -b {shlex.quote(branch)}"
    return cwd, "git branch --show-current"


def push_branch(*, repo_path: str, remote: str = "origin", branch_name: str = "") -> tuple[str, str]:
    cwd = normalize_repo_cwd(repo_path)
    branch = branch_name.strip() or "HEAD"
    return cwd, f"git push -u {shlex.quote(remote)} {shlex.quote(branch)}"


def upsert_pr(
    *,
    repo_path: str,
    title: str = "",
    body: str = "",
    base: str = "",
) -> tuple[str, str]:
    cwd = normalize_repo_cwd(repo_path)
    parts = ["gh", "pr", "create"]
    if title.strip():
        parts.extend(["--title", title.strip()])
    else:
        parts.append("--fill")
    if body.strip():
        parts.extend(["--body", body.strip()])
    else:
        parts.append("--fill-verbose")
    if base.strip():
        parts.extend(["--base", base.strip()])
    return cwd, " ".join(shlex.quote(part) for part in parts)


def read_workflow_status(*, repo_path: str, branch_name: str = "") -> tuple[str, str]:
    cwd = normalize_repo_cwd(repo_path)
    branch = branch_name.strip()
    if branch:
        return cwd, f"gh run list --branch {shlex.quote(branch)} --limit 5"
    return cwd, "gh run list --limit 5"


def extract_quoted_value(user_message: str, keyword: str) -> str:
    patterns = (
        rf'\b{keyword}\s+["\'`]([^"\']+?)["\'`]',
        rf'\b{keyword}\s*[:=]\s*["\'`]([^"\']+?)["\'`]',
    )
    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""
