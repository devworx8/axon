from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


AUTONOMY_PROFILES = (
    "manual",
    "workspace_auto",
    "branch_auto",
    "pr_auto",
    "merge_auto",
    "deploy_auto",
)

_AUTONOMY_RANK = {name: index for index, name in enumerate(AUTONOMY_PROFILES)}
_DEPLOY_TOKENS = ("deploy", "release", "publish", "promote", "ship-live", "go-live", "rollback", "roll back")
_DESTRUCTIVE_GIT_SUBCOMMANDS = {"reset", "rebase", "merge", "push", "tag", "checkout", "branch", "clean"}
_PROTECTED_BRANCH_TOKENS = {"main", "master", "production", "staging", "release", "develop", "development"}


def normalize_command_preview(command: str) -> str:
    return re.sub(r"\s+", " ", str(command or "").strip())


def resolve_repo_root(path: str = "") -> str:
    raw = os.path.realpath(os.path.expanduser(str(path or "").strip() or "."))
    probe = Path(raw)
    if probe.is_file():
        probe = probe.parent
    while probe != probe.parent:
        if (probe / ".git").exists():
            return str(probe)
        probe = probe.parent
    return raw


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def _git_action_type(command: str) -> str:
    lower = normalize_command_preview(command).lower()
    if lower.startswith("git add"):
        return "git_add"
    if lower.startswith("git commit"):
        return "git_commit"
    if lower.startswith("git push"):
        return "git_push"
    if lower.startswith("git checkout"):
        return "git_checkout"
    if lower.startswith("git branch"):
        return "git_branch"
    if lower.startswith("git merge"):
        return "git_merge"
    if lower.startswith("git rebase"):
        return "git_rebase"
    if lower.startswith("git reset"):
        return "git_reset"
    return "git_command"


def _gh_action_type(command: str) -> str:
    lower = normalize_command_preview(command).lower()
    if lower.startswith("gh pr create") or lower.startswith("gh pr edit"):
        return "gh_pr_upsert"
    if lower.startswith("gh pr"):
        return "gh_pr_command"
    if lower.startswith("gh workflow") or lower.startswith("gh run"):
        return "gh_workflow_command"
    return "gh_command"


def action_type_for_command(command: str) -> str:
    lower = normalize_command_preview(command).lower()
    if lower.startswith("git "):
        return _git_action_type(lower)
    if lower.startswith("gh "):
        return _gh_action_type(lower)
    if any(token in lower for token in _DEPLOY_TOKENS):
        return "deploy_command"
    return "shell_command"


def action_summary_for_command(command: str) -> str:
    normalized = normalize_command_preview(command)
    lower = normalized.lower()
    if lower.startswith("git add"):
        return "Stage changes"
    if lower.startswith("git commit"):
        return "Create commit"
    if lower.startswith("git push"):
        return "Push branch"
    if lower.startswith("gh pr create") or lower.startswith("gh pr edit"):
        return "Create or update pull request"
    if lower.startswith("gh workflow") or lower.startswith("gh run"):
        return "Read workflow status"
    if any(token in lower for token in _DEPLOY_TOKENS):
        return "Deploy release"
    return f"Run `{normalized[:72]}`"


def command_is_destructive(command: str) -> bool:
    lower = normalize_command_preview(command).lower()
    if any(token in lower for token in _DEPLOY_TOKENS):
        return True
    if lower.startswith("rm ") or " rm " in lower:
        return True
    if not lower.startswith(("git ", "gh ")):
        return False
    if lower.startswith("git push") and ("--force" in lower or " -f" in lower):
        return True
    if lower.startswith("git reset") or lower.startswith("git clean"):
        return True
    if lower.startswith("git branch") and any(flag in lower for flag in (" -d", " -D", " --delete", " --move", " --copy")):
        return True
    if lower.startswith("git checkout") and any(token in lower for token in _PROTECTED_BRANCH_TOKENS):
        return True
    if lower.startswith("gh pr merge"):
        return True
    return False


def persist_allowed_for_action(action: dict[str, Any]) -> bool:
    if bool(action.get("destructive")):
        return False
    action_type = str(action.get("action_type") or "").strip().lower()
    if action_type in {
        "git_push",
        "gh_pr_upsert",
        "git_reset",
        "git_rebase",
        "git_merge",
        "git_branch",
        "git_checkout",
        "deploy_command",
    }:
        return False
    return True


def autonomy_profile_allows(action: dict[str, Any], profile: str) -> bool:
    rank = _AUTONOMY_RANK.get(str(profile or "manual").strip().lower(), 0)
    action_type = str(action.get("action_type") or "").strip().lower()
    destructive = bool(action.get("destructive"))
    if destructive:
        if action_type == "deploy_command":
            return rank >= _AUTONOMY_RANK["deploy_auto"]
        return rank >= _AUTONOMY_RANK["merge_auto"]
    if action_type.startswith("file_"):
        return rank >= _AUTONOMY_RANK["workspace_auto"]
    if action_type in {"shell_command"}:
        return rank >= _AUTONOMY_RANK["workspace_auto"]
    if action_type in {"git_add", "git_commit", "git_checkout", "git_branch", "git_command"}:
        return rank >= _AUTONOMY_RANK["branch_auto"]
    if action_type in {"git_push", "gh_pr_upsert"}:
        return rank >= _AUTONOMY_RANK["pr_auto"]
    return False


def build_command_approval_action(
    command: str,
    *,
    cwd: str = "",
    workspace_id: int | None = None,
    session_id: str = "",
    summary: str = "",
) -> dict[str, Any]:
    command_preview = normalize_command_preview(command)
    repo_root = resolve_repo_root(cwd or ".")
    action_type = action_type_for_command(command_preview)
    action_summary = summary or action_summary_for_command(command_preview)
    destructive = command_is_destructive(command_preview)
    payload = {
        "action_type": action_type,
        "workspace_id": workspace_id,
        "repo_root": repo_root,
        "command_preview": command_preview,
        "path": "",
        "operation": "",
    }
    return {
        **payload,
        "action_fingerprint": _hash_payload(payload),
        "summary": action_summary,
        "destructive": destructive,
        "persist_allowed": persist_allowed_for_action({**payload, "destructive": destructive}),
        "scope_options": ["once", "task", "session"]
        + ([] if not persist_allowed_for_action({**payload, "destructive": destructive}) else ["persist"]),
        "session_id": session_id,
        "evidence_source": "deterministic",
    }


def build_edit_approval_action(
    operation: str,
    path: str,
    *,
    workspace_id: int | None = None,
    session_id: str = "",
    summary: str = "",
) -> dict[str, Any]:
    resolved_path = os.path.realpath(os.path.expanduser(path))
    repo_root = resolve_repo_root(resolved_path)
    operation_name = str(operation or "edit").strip().lower()
    payload = {
        "action_type": f"file_{operation_name}",
        "workspace_id": workspace_id,
        "repo_root": repo_root,
        "command_preview": f"{operation_name} {resolved_path}",
        "path": resolved_path,
        "operation": operation_name,
    }
    return {
        **payload,
        "action_fingerprint": _hash_payload(payload),
        "summary": summary or f"{operation_name.title()} {Path(resolved_path).name}",
        "destructive": operation_name in {"delete"},
        "persist_allowed": persist_allowed_for_action({**payload, "destructive": operation_name in {"delete"}}),
        "scope_options": ["once", "task", "session"]
        + ([] if operation_name in {"delete"} else ["persist"]),
        "session_id": session_id,
        "evidence_source": "deterministic",
    }
