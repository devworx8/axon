from __future__ import annotations

import os
import shlex
import re as _re
from pathlib import Path
from typing import Any, Optional

from .agent_paths import (
    _extract_path_from_text,
    _recent_file_path,
    _recent_repo_path,
    _repo_root_path,
    _resolve_user_path,
    _workspace_root_path,
)
from .agent_commit_intents import (
    commit_scope_is_all_changes as _commit_scope_is_all_changes,
    commit_scope_is_stage_all_request as _commit_scope_is_stage_all_request,
    extract_commit_message as _extract_commit_message,
    extract_push_remote as _extract_push_remote,
    looks_like_commit_request as _looks_like_commit_request,
    looks_like_push_request as _looks_like_push_request,
)
from .agent_delete_intent import has_explicit_delete_intent
from .github_orchestrator import (
    extract_quoted_value,
    push_branch,
    read_workflow_status,
    upsert_pr,
)
from .agent_toolspecs import AgentRuntimeDeps, _execute_tool


def _tool_result_needs_attention(result: str) -> bool:
    return isinstance(result, str) and (
        result.startswith("ERROR:")
        or result.startswith("BLOCKED_EDIT:")
        or result.startswith("BLOCKED_CMD:")
    )


def _looks_like_external_network_error(result: str) -> bool:
    lower = str(result or "").strip().lower()
    if not lower:
        return False
    return any(token in lower for token in (
        "could not resolve host",
        "temporary failure in name resolution",
        "name or service not known",
        "could not resolve proxy",
        "network is unreachable",
        "failed to connect to",
        "connection timed out",
        "failed to connect",
        "couldn't connect to server",
    ))


def _extract_failed_host(result: str) -> str:
    text = str(result or "")
    match = _re.search(r"could not resolve host:\s*([A-Za-z0-9._-]+)", text, flags=_re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = _re.search(r"failed to connect to\s+([A-Za-z0-9._-]+)", text, flags=_re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _normalize_shell_error(result: str, *, command: str = "", cwd: str = "") -> str:
    if not isinstance(result, str):
        return result
    if result.startswith(("ERROR:", "BLOCKED_CMD:", "BLOCKED_EDIT:")):
        return result
    if not _looks_like_external_network_error(result):
        return result
    host = _extract_failed_host(result)
    command_preview = " ".join(str(command or "").split()) or "shell command"
    resolved_cwd = os.path.realpath(os.path.expanduser(str(cwd or ".").strip() or "."))
    host_line = f"- Host: `{host}`\n" if host else ""
    return (
        "ERROR: External network access is unavailable from this Axon runtime right now.\n\n"
        f"- Command: `{command_preview}`\n"
        f"- Repo: `{resolved_cwd}`\n"
        f"{host_line}"
        "- Next step: retry from an unsandboxed host shell or run Axon with host-network access enabled.\n\n"
        f"Original error:\n{result.strip()}"
    )


def _parse_list_dir_entries(result: str) -> list[tuple[str, str]]:
    """Parse list_dir output into (kind, name) pairs."""
    entries: list[tuple[str, str]] = []
    for line in result.splitlines():
        if line.startswith("DIR "):
            entries.append(("dir", line[4:].strip()))
        elif line.startswith("FILE "):
            entries.append(("file", line[5:].strip()))
    return entries


def _format_listing_answer(path: str, names: list[str], label: str) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    if not names:
        return f"I checked `{resolved}` and there are no visible {label} there."
    visible = names[:40]
    bullets = "\n".join(f"- {name}" for name in visible)
    more = ""
    if len(names) > len(visible):
        more = f"\n- ...and {len(names) - len(visible)} more"
    return f"Here are the {label} in `{resolved}`:\n{bullets}{more}"


def _extract_requested_content(user_message: str) -> Optional[str]:
    """Best-effort content extraction for create/write requests."""
    stop_clause = r"(?=\s+(?:then|and)\s+(?:verify|show|check|confirm|reply|respond|return|say)\b|$)"
    patterns = (
        rf"\bcontaining exactly\s*:?\s*(.+?){stop_clause}",
        rf"\bwith content\s*:?\s*(.+?){stop_clause}",
        rf"\bcontaining\s*:?\s*(.+?){stop_clause}",
        rf"\bexactly\s*:?\s*(.+?){stop_clause}",
        r"\b(?:write|put|save)\s+(?:the\s+)?(?:single\s+)?word\s+(.+?)\s+\b(?:to|into|in)\b",
        r"\bwrite\s+(.+?)\s+\b(?:to|into)\b",
        r"\bput\s+(.+?)\s+\b(?:into|in)\b",
        r"\bsave\s+(.+?)\s+\b(?:to|into|in)\b",
        rf"\breplace the contents of\b.+?\bwith\s*:?\s*(.+?){stop_clause}",
    )
    for pattern in patterns:
        match = _re.search(pattern, user_message, flags=_re.IGNORECASE | _re.DOTALL)
        if match:
            return _normalize_inline_content(match.group(1).strip())
    return None


def _extract_append_content(user_message: str) -> Optional[str]:
    """Extract the line/text to append from simple natural-language requests."""
    patterns = (
        r"\bappend the line\s+(.+?)(?=\s+\b(?:to|into|onto)\b|$)",
        r"\bappend\s+(.+?)(?=\s+\b(?:to|into|onto)\b|$)",
    )
    for pattern in patterns:
        match = _re.search(pattern, user_message, flags=_re.IGNORECASE | _re.DOTALL)
        if match:
            content = match.group(1).strip()
            if (
                len(content) >= 2
                and content[0] == content[-1]
                and content[0] in {'"', "'", "`"}
            ):
                content = content[1:-1]
            return content
    return None


def _strip_wrapping_quotes(text: str) -> str:
    value = (text or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _normalize_inline_content(text: str) -> str:
    value = _strip_wrapping_quotes(text)
    if _re.fullmatch(r"[A-Za-z0-9_-]+[.,;:!?]", value):
        return value[:-1]
    return value


def _extract_http_url(user_message: str) -> Optional[str]:
    match = _re.search(r"https?://[^\s<>()]+", user_message or "", flags=_re.IGNORECASE)
    if not match:
        return None
    return match.group(0).rstrip(".,);!?]}>\"'")


def _looks_like_url_fetch_request(user_message: str, url: str) -> bool:
    raw = str(user_message or "").strip()
    if not raw:
        return False
    bare = raw.strip().strip("`'\"")
    if bare == url or bare == f"<{url}>":
        return True
    lower = raw.lower()
    fetch_phrases = (
        "look at",
        "take a look",
        "open this",
        "open the link",
        "fetch",
        "read this",
        "read the page",
        "review this",
        "inspect this",
        "visit",
        "analyze this",
        "analyse this",
        "summarize this",
        "check this link",
        "check this url",
    )
    return any(phrase in lower for phrase in fetch_phrases)


def _extract_explicit_shell_command(user_message: str) -> Optional[str]:
    raw = " ".join(str(user_message or "").strip().split())
    if not raw:
        return None

    normalized = _re.sub(
        r"^(?:please\s+)?(?:can you|could you|would you)\s+",
        "",
        raw,
        flags=_re.IGNORECASE,
    )
    normalized = _re.sub(r"^(?:please|axon)[,:]?\s+", "", normalized, flags=_re.IGNORECASE)

    backtick_match = _re.search(r"`((?:git|gh)\b[^`]+)`", normalized, flags=_re.IGNORECASE)
    if backtick_match:
        return backtick_match.group(1).strip().rstrip(".,;:!?")

    prefixed_request = False
    candidate = normalized
    for prefix in (
        "please run ",
        "run ",
        "please execute ",
        "execute ",
        "check ",
        "show ",
    ):
        if normalized.lower().startswith(prefix):
            candidate = normalized[len(prefix):].strip()
            prefixed_request = True
            break

    if not _re.match(r"^(?:git|gh)\b", candidate, flags=_re.IGNORECASE):
        return None
    if not prefixed_request:
        conversational_sequence = _re.search(
            r"\b(?:and|then)\b.+\b(?:we|debug|fix|review|continue|start|commit|push|deploy)\b",
            candidate,
            flags=_re.IGNORECASE,
        )
        if conversational_sequence:
            return None
    return candidate.rstrip(".,;:!?")


def _looks_like_pr_request(user_message: str) -> bool:
    lower = (user_message or "").lower()
    return any(phrase in lower for phrase in (
        "open a pr",
        "open pr",
        "open a pull request",
        "create a pr",
        "create pr",
        "create a pull request",
        "update the pr",
        "update pr",
    ))


def _looks_like_workflow_status_request(user_message: str) -> bool:
    lower = (user_message or "").lower()
    return any(phrase in lower for phrase in (
        "workflow status",
        "check ci",
        "check the ci",
        "check github actions",
        "github actions status",
        "workflow runs",
        "pipeline status",
    ))


def _mentions_workspace_root(user_message: str) -> bool:
    lower = (user_message or "").lower()
    root_phrases = (
        "workspace root",
        "project root",
        "repo root",
        "repository root",
        "root of the workspace",
        "root of the project",
        "root of the repo",
        "root of the repository",
    )
    return any(phrase in lower for phrase in root_phrases)


def _extract_named_file_hint(user_message: str) -> Optional[str]:
    patterns = (
        r"\b(?:file|document)\s+(?:named|called)\s+[`\"']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)",
        r"\b(?:named|called)\s+[`\"']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)",
        r"\b(?:create|write|edit|rewrite|overwrite|update|delete|remove)\s+"
        r"(?:a\s+)?(?:file\s+)?[`\"']?([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)",
    )
    for pattern in patterns:
        match = _re.search(pattern, user_message, flags=_re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip().rstrip(".,:;!?`'\"")
        if not candidate or candidate.lower() in {"workspace", "project", "repo", "repository"}:
            continue
        if "/" in candidate or "." in Path(candidate).name:
            return candidate
    return None


def _git_status_changed_entries(status_text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    in_status = False
    for raw_line in (status_text or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Status:":
            in_status = True
            continue
        if stripped == "Recent commits:":
            break
        if not in_status:
            continue
        if stripped in {"Working tree clean.", "nothing to commit, working tree clean"}:
            return []
        if len(line) >= 2 and line[0] in {"M", "A", "D", "R", "C", "?", "U", " "} and line[1] in {"M", "A", "D", "R", "C", "?", "U", " "}:
            code = line[:2].strip() or line[:2]
            path = line[2:].strip()
            if path:
                entries.append((code, path))
    return entries


def _draft_commit_message_from_git_status(status_text: str) -> str:
    entries = _git_status_changed_entries(status_text)
    if not entries:
        return "chore: checkpoint current changes"

    paths = [path for _code, path in entries]
    lower_paths = [path.lower() for path in paths]

    topical_labels = (
        ("payment", ("payment", "invoice", "billing", "pop")),
        ("missions", ("mission",)),
        ("navigation", ("navigation", "tabbar", "layout", "weblayout")),
        ("dashboard", ("dashboard",)),
        ("tests", ("test", "__tests__")),
    )
    picked_topics: list[str] = []
    for label, needles in topical_labels:
        if any(any(needle in path for needle in needles) for path in lower_paths):
            picked_topics.append(label)
        if len(picked_topics) >= 3:
            break

    untracked_count = sum(1 for code, _path in entries if "?" in code)
    if picked_topics:
        summary = ", ".join(picked_topics[:2]) if len(picked_topics) <= 2 else f"{picked_topics[0]}, {picked_topics[1]}, and {picked_topics[2]}"
        prefix = "feat" if untracked_count else "chore"
        return f"{prefix}: update {summary}"

    first_names = [Path(path).stem.replace("-", " ").replace("_", " ") for path in paths[:2]]
    detail = " and ".join(name for name in first_names if name).strip()
    if detail:
        return f"chore: update {detail}"
    return "chore: checkpoint current changes"


def _is_mutating_file_request(user_message: str) -> bool:
    lower = (user_message or "").lower()
    mutate_phrases = (
        "create a file",
        "create the file",
        "create file",
        "make a file",
        "make the file",
        "make file",
        "write a file",
        "write the file",
        "write file",
        "save the file",
        "save a file",
        "save ",
        "put ",
        "edit a file",
        "edit file",
        "rewrite a file",
        "rewrite file",
        "overwrite a file",
        "overwrite file",
        "update the file",
        "update file",
        "replace the contents of",
        "append the line",
        "append line",
        "append ",
        "replace ",
        "change ",
        "delete file",
        "remove file",
        "rm ",
    )
    return any(phrase in lower for phrase in mutate_phrases)


def _extract_replace_strings(user_message: str) -> tuple[Optional[str], Optional[str]]:
    """Extract old/new text from simple replace requests."""
    patterns = (
        r"\breplace\s+(.+?)\s+with\s+(.+?)(?=\s+\b(?:in|inside|within)\b|$)",
        r"\bchange\s+(.+?)\s+to\s+(.+?)(?=\s+\b(?:in|inside|within)\b|$)",
    )
    for pattern in patterns:
        match = _re.search(pattern, user_message, flags=_re.IGNORECASE | _re.DOTALL)
        if match:
            old_string = _strip_wrapping_quotes(match.group(1))
            new_string = _strip_wrapping_quotes(match.group(2))
            if old_string and new_string:
                return old_string, new_string
    return None, None


def _requested_tail_line_count(user_message: str) -> int:
    match = _re.search(r"\b(?:last|tail)\s+(\d+)\s+lines?\b", user_message, flags=_re.IGNORECASE)
    if not match:
        return 0
    try:
        return max(1, min(50, int(match.group(1))))
    except Exception:
        return 0


def _wants_diff(user_message: str) -> bool:
    lower = (user_message or "").lower()
    return "show diff" in lower or "show me the diff" in lower or "diff" in lower


def _format_file_write_answer(
    *,
    action: str,
    path: str,
    content: str,
    user_message: str,
) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    exists = os.path.exists(resolved)
    pieces = [
        f"{action} `{resolved}`."
    ]
    if "verify" in user_message.lower() or "exists" in user_message.lower() or "confirm" in user_message.lower():
        pieces.append("Verified: the file exists." if exists else "Verification failed: the file does not exist.")
    if "absolute path" in user_message.lower():
        pieces.append(f"Absolute path: `{resolved}`")

    tail_count = _requested_tail_line_count(user_message)
    if tail_count:
        lines = content.splitlines()
        tail = lines[-tail_count:] if lines else [content]
        rendered = "\n".join(tail).strip("\n")
        pieces.append(f"Last {tail_count} lines:\n```\n{rendered}\n```")
    elif "show me the content" in user_message.lower() or "show the content" in user_message.lower():
        pieces.append(f"Content:\n```\n{content}\n```")

    return "\n\n".join(pieces)


def _format_file_read_answer(*, path: str, content: str, user_message: str) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    pieces = [f"Here is `{resolved}`:"]

    tail_count = _requested_tail_line_count(user_message)
    if tail_count:
        lines = content.splitlines()
        tail = lines[-tail_count:] if lines else [content]
        rendered = "\n".join(tail).strip("\n")
        pieces.append(f"Last {tail_count} lines:\n```\n{rendered}\n```")
    else:
        rendered = content.strip("\n")
        if len(rendered) > 12000:
            rendered = rendered[:12000].rstrip() + "\n... (truncated)"
        pieces.append(f"```\n{rendered}\n```")

    if "absolute path" in user_message.lower():
        pieces.append(f"Absolute path: `{resolved}`")

    return "\n\n".join(pieces)


def _format_file_edit_answer(
    *,
    action: str,
    path: str,
    content: str,
    user_message: str,
    diff_text: str = "",
) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    pieces = [f"{action} `{resolved}`."]

    if _wants_diff(user_message) and diff_text and not diff_text.startswith("No diff found"):
        pieces.append(f"Diff:\n```diff\n{diff_text}\n```")

    tail_count = _requested_tail_line_count(user_message)
    if tail_count:
        lines = content.splitlines()
        tail = lines[-tail_count:] if lines else [content]
        rendered = "\n".join(tail).strip("\n")
        pieces.append(f"Last {tail_count} lines:\n```\n{rendered}\n```")
    elif "show me the content" in user_message.lower() or "show the content" in user_message.lower():
        pieces.append(f"Content:\n```\n{content}\n```")

    if "absolute path" in user_message.lower():
        pieces.append(f"Absolute path: `{resolved}`")

    return "\n\n".join(pieces)


def _format_file_delete_answer(*, path: str, user_message: str) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    exists = os.path.exists(resolved)
    pieces = [f"Deleted `{resolved}`."]
    if "verify" in user_message.lower() or "exists" in user_message.lower() or "confirm" in user_message.lower():
        pieces.append("Verified: the file no longer exists." if not exists else "Verification failed: the file still exists.")
    if "absolute path" in user_message.lower():
        pieces.append(f"Absolute path: `{resolved}`")
    return "\n\n".join(pieces)


def _direct_agent_action(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    project_name: Optional[str] = None,
    workspace_path: str = "",
    *,
    deps: AgentRuntimeDeps,
) -> tuple[str, dict[str, Any], str, str] | None:
    """
    Handle obvious local actions deterministically so the agent behaves like a copilot
    even when the model does not emit a tool call.
    Returns (tool_name, args, tool_result, final_answer) or None.
    """
    lower = user_message.lower()
    tail_count = _requested_tail_line_count(user_message)
    explicit_url = _extract_http_url(user_message)
    explicit_command = _extract_explicit_shell_command(user_message)

    if explicit_url and _looks_like_url_fetch_request(user_message, explicit_url):
        tool_name = "http_get"
        tool_args = {"url": explicit_url}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        rendered = tool_result.strip()
        if len(rendered) > 8000:
            rendered = rendered[:8000].rstrip() + "\n... (truncated)"
        answer = f"I fetched `{explicit_url}`:\n\n```\n{rendered}\n```"
        return tool_name, tool_args, tool_result, answer

    power_phrases = (
        "reboot", "restart the system", "restart my system", "restart the machine",
        "restart my machine", "restart the computer", "restart my computer",
        "shutdown", "shut down", "power off", "poweroff", "turn off the computer",
        "turn off the machine", "halt the system",
    )
    if any(phrase in lower for phrase in power_phrases):
        answer = (
            "I can't reboot or power off this system directly from chat.\n\n"
            "- Full power actions stay blocked in agent mode by design.\n"
            "- Open `Settings -> System Actions` for the guided restart and reboot flow.\n"
            "- From there, Axon can restart safe local services or prepare the exact OS command for you to run manually."
        )
        return "shell_cmd", {"cmd": "echo blocked-power-action"}, "BLOCKED: power action not allowed", answer

    path = _extract_path_from_text(user_message, db_path=deps.db_path, workspace_path=workspace_path)
    lower_has_git = any(term in lower for term in ("git", "branch", "repo", "repository", "status", "commit"))
    lower_has_file_action = any(term in lower for term in (
        "file", "append", "replace", "change", "edit", "rewrite", "overwrite",
        "update", "set", "delete", "remove", "rm", "absolute path", "verify",
        "exists", "content", "read file", "open file", "show me the file",
        "show the file", "show me the content", "show the content", "tail ",
    )) or tail_count > 0 or lower.startswith("read ") or lower.startswith("open ")
    if not path and lower_has_git:
        path = _recent_repo_path(history, project_name, db_path=deps.db_path, workspace_path=workspace_path)
    if not path and lower_has_file_action:
        path = _recent_file_path(history, db_path=deps.db_path, workspace_path=workspace_path)

    if not path and workspace_path:
        workspace_root = _workspace_root_path(workspace_path)
        path = str(workspace_root) if workspace_root else _resolve_user_path(workspace_path)

    if path:
        path = _resolve_user_path(path, workspace_path=workspace_path)
    shell_targets_repo = bool(explicit_command and explicit_command.lower().startswith(("git ", "gh ")))
    repo_path = _repo_root_path(path, workspace_path=workspace_path) if path and (lower_has_git or shell_targets_repo) else None

    if not path:
        return None

    if explicit_command:
        shell_cwd = repo_path or path
        tool_name = "shell_cmd"
        tool_args: dict[str, Any] = {"cmd": explicit_command, "cwd": shell_cwd, "timeout": 30}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        tool_result = _normalize_shell_error(tool_result, command=explicit_command, cwd=shell_cwd)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        resolved_cwd = os.path.realpath(os.path.expanduser(shell_cwd))
        rendered = tool_result.strip()
        if len(rendered) > 8000:
            rendered = rendered[:8000].rstrip() + "\n... (truncated)"
        answer = f"Ran `{explicit_command}` in `{resolved_cwd}`.\n\n```\n{rendered}\n```"
        return tool_name, tool_args, tool_result, answer

    if _looks_like_commit_request(user_message):
        repo_target = repo_path or path
        wants_push_after_commit = _looks_like_push_request(user_message)
        push_follow_up = ""
        if wants_push_after_commit:
            push_remote = _extract_push_remote(user_message)
            push_follow_up = f" Then push this branch to {push_remote}." if push_remote != "origin" else " Then push this branch."
        commit_message = _extract_commit_message(user_message)
        auto_generated_message = False
        if not commit_message:
            tool_name = "git_status"
            tool_args = {"path": repo_target}
            tool_result = _execute_tool(tool_name, tool_args, deps)
            if _tool_result_needs_attention(tool_result):
                return tool_name, tool_args, tool_result, tool_result
            changed_entries = _git_status_changed_entries(tool_result)
            if not changed_entries:
                resolved_repo = os.path.realpath(os.path.expanduser(repo_target))
                answer = f"`{resolved_repo}` has no tracked or untracked changes to commit."
                return tool_name, tool_args, tool_result, answer
            commit_message = _draft_commit_message_from_git_status(tool_result)
            auto_generated_message = True

        if _commit_scope_is_all_changes(user_message):
            staged_cmd = "git add -A"
            tool_name = "shell_cmd"
            tool_args = {"cmd": staged_cmd, "cwd": repo_target, "timeout": 30}
            if auto_generated_message and commit_message:
                tool_args["_resume_task"] = f'Commit everything with commit message "{commit_message}".{push_follow_up}'
                tool_args["_draft_commit_message"] = commit_message
            tool_result = _execute_tool(tool_name, tool_args, deps)
            tool_result = _normalize_shell_error(tool_result, command=staged_cmd, cwd=repo_target)
            if _tool_result_needs_attention(tool_result):
                return tool_name, tool_args, tool_result, tool_result
            resolved_repo = os.path.realpath(os.path.expanduser(repo_target))
            drafted = f"I drafted commit message `{commit_message}` and " if auto_generated_message else ""
            answer = f"{drafted}staged the full worktree in `{resolved_repo}` and I’m ready to create the commit next."
            return tool_name, tool_args, tool_result, answer

        commit_cmd = f"git commit -m {shlex.quote(commit_message)}"
        tool_name = "shell_cmd"
        tool_args = {"cmd": commit_cmd, "cwd": repo_target, "timeout": 30}
        if commit_message:
            if wants_push_after_commit:
                push_remote = _extract_push_remote(user_message)
                tool_args["_resume_task"] = f"Push this branch to {push_remote}." if push_remote != "origin" else "Push this branch."
            elif auto_generated_message:
                tool_args["_resume_task"] = f'Run {commit_cmd}.'
        if auto_generated_message and commit_message:
            tool_args["_draft_commit_message"] = commit_message
        tool_result = _execute_tool(tool_name, tool_args, deps)
        tool_result = _normalize_shell_error(tool_result, command=commit_cmd, cwd=repo_target)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        resolved_repo = os.path.realpath(os.path.expanduser(repo_target))
        prefix = f"I drafted commit message `{commit_message}` and then " if auto_generated_message else ""
        answer = f"{prefix}ran `{commit_cmd}` in `{resolved_repo}`.\n\n```\n{tool_result}\n```"
        return tool_name, tool_args, tool_result, answer

    if _looks_like_push_request(user_message):
        repo_target = repo_path or path
        remote = _extract_push_remote(user_message)
        shell_cwd, push_cmd = push_branch(repo_path=repo_target, remote=remote)
        tool_name = "shell_cmd"
        tool_args = {"cmd": push_cmd, "cwd": shell_cwd, "timeout": 45}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        tool_result = _normalize_shell_error(tool_result, command=push_cmd, cwd=shell_cwd)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        answer = f"Pushed the active branch from `{os.path.realpath(os.path.expanduser(shell_cwd))}` with `{push_cmd}`.\n\n```\n{tool_result}\n```"
        return tool_name, tool_args, tool_result, answer

    if _looks_like_pr_request(user_message):
        repo_target = repo_path or path
        title = extract_quoted_value(user_message, "title")
        body = extract_quoted_value(user_message, "body")
        base = extract_quoted_value(user_message, "base")
        shell_cwd, pr_cmd = upsert_pr(repo_path=repo_target, title=title, body=body, base=base)
        tool_name = "shell_cmd"
        tool_args = {"cmd": pr_cmd, "cwd": shell_cwd, "timeout": 60}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        tool_result = _normalize_shell_error(tool_result, command=pr_cmd, cwd=shell_cwd)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        answer = f"Opened or updated a PR from `{os.path.realpath(os.path.expanduser(shell_cwd))}`.\n\n```\n{tool_result}\n```"
        return tool_name, tool_args, tool_result, answer

    if _looks_like_workflow_status_request(user_message):
        repo_target = repo_path or path
        shell_cwd, workflow_cmd = read_workflow_status(repo_path=repo_target)
        tool_name = "shell_cmd"
        tool_args = {"cmd": workflow_cmd, "cwd": shell_cwd, "timeout": 30}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        tool_result = _normalize_shell_error(tool_result, command=workflow_cmd, cwd=shell_cwd)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        answer = f"Recent workflow runs for `{os.path.realpath(os.path.expanduser(shell_cwd))}`:\n\n```\n{tool_result}\n```"
        return tool_name, tool_args, tool_result, answer

    if any(token in lower for token in ("deploy", "rollback", "roll back", "go live", "ship to production")):
        answer = (
            "Direct production deploys are intentionally disabled in Axon's unattended path.\n\n"
            "- Safe flow: edit -> test -> commit -> push branch -> open or update PR.\n"
            "- Production rollout should happen through protected CI/CD after merge."
        )
        return "shell_cmd", {"cmd": "echo blocked-direct-deploy"}, "BLOCKED: direct deploys disabled", answer

    write_phrases = ("write a file", "write the file", "write file", "save a file", "save the file", "save ", "put ")
    create_phrases = ("create a file", "create the file", "create file", "make a file", "make the file", "make file")
    overwrite_phrases = (
        "edit a file", "edit file", "rewrite a file", "rewrite file",
        "overwrite a file", "overwrite file", "set the file", "set file",
        "update the file", "update file", "replace the contents of",
    )
    append_phrases = ("append the line", "append line", "append ")
    replace_phrases = ("replace ", "change ")
    wants_append = any(phrase in lower for phrase in append_phrases)
    wants_create = any(phrase in lower for phrase in create_phrases)
    wants_write = any(phrase in lower for phrase in write_phrases)
    wants_overwrite = any(phrase in lower for phrase in overwrite_phrases)
    wants_replace = any(phrase in lower for phrase in replace_phrases)
    wants_delete = has_explicit_delete_intent(user_message)
    workspace_root_requested = _mentions_workspace_root(user_message)
    filename_hint = _extract_named_file_hint(user_message)

    if workspace_path and filename_hint and workspace_root_requested:
        path = _resolve_user_path(filename_hint, workspace_path=workspace_path)
    elif workspace_path and filename_hint and not path and _is_mutating_file_request(user_message):
        path = _resolve_user_path(filename_hint, workspace_path=workspace_path)
    elif workspace_path and workspace_root_requested and (not path or Path(str(path)).name == ".devbrain"):
        workspace_root = _workspace_root_path(workspace_path)
        if workspace_root:
            path = str(workspace_root)

    if wants_append:
        content = _extract_append_content(user_message)
        if content:
            if not content.startswith("\n"):
                content = "\n" + content
            tool_name = "append_file"
            tool_args = {"path": path, "content": content}
            tool_result = _execute_tool(tool_name, tool_args, deps)
            if _tool_result_needs_attention(tool_result):
                return tool_name, tool_args, tool_result, tool_result
            resolved = os.path.realpath(os.path.expanduser(path))
            try:
                verified = Path(resolved).read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return tool_name, tool_args, tool_result, f"Appended to `{resolved}`, but I could not verify the file content: {exc}"
            answer = _format_file_write_answer(
                action="Appended to",
                path=path,
                content=verified,
                user_message=user_message,
            )
            return tool_name, tool_args, tool_result, answer

    if wants_replace:
        old_string, new_string = _extract_replace_strings(user_message)
        if old_string and new_string:
            tool_name = "edit_file"
            tool_args = {
                "path": path,
                "old_string": old_string,
                "new_string": new_string,
            }
            tool_result = _execute_tool(tool_name, tool_args, deps)
            if _tool_result_needs_attention(tool_result):
                return tool_name, tool_args, tool_result, tool_result
            resolved = os.path.realpath(os.path.expanduser(path))
            try:
                verified = Path(resolved).read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return tool_name, tool_args, tool_result, f"Edited `{resolved}`, but I could not verify the file content: {exc}"
            diff_text = _execute_tool("show_diff", {"path": path}, deps)
            answer = _format_file_edit_answer(
                action="Edited",
                path=path,
                content=verified,
                user_message=user_message,
                diff_text=diff_text,
            )
            return tool_name, tool_args, tool_result, answer

    if wants_delete and not any((wants_append, wants_create, wants_write, wants_replace)):
        tool_name = "delete_file"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        answer = _format_file_delete_answer(path=path, user_message=user_message)
        return tool_name, tool_args, tool_result, answer

    if wants_overwrite and not any((wants_append, wants_replace, wants_delete)):
        content = _extract_requested_content(user_message)
        resolved = os.path.realpath(os.path.expanduser(path))
        if content is None:
            error = (
                f"ERROR: I couldn't determine the new file content for `{resolved}`. "
                "Use phrasing like `edit file ... containing exactly: ...`."
            )
            return "write_file", {"path": path}, error, error
        if not Path(resolved).exists():
            error = f"ERROR: File not found: {resolved}"
            return "write_file", {"path": path, "content": content}, error, error
        tool_name = "write_file"
        tool_args = {"path": path, "content": content}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if _tool_result_needs_attention(tool_result):
            return tool_name, tool_args, tool_result, tool_result
        try:
            verified = Path(resolved).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return tool_name, tool_args, tool_result, f"Updated `{resolved}`, but I could not verify the file content: {exc}"
        answer = _format_file_write_answer(
            action="Updated",
            path=path,
            content=verified,
            user_message=user_message,
        )
        return tool_name, tool_args, tool_result, answer

    if wants_create or wants_write:
        content = _extract_requested_content(user_message)
        if content is not None:
            tool_name = "create_file" if wants_create else "write_file"
            tool_args = {"path": path, "content": content}
            tool_result = _execute_tool(tool_name, tool_args, deps)
            if tool_result.startswith("ERROR: File already exists:") and wants_create:
                tool_name = "write_file"
                tool_args = {"path": path, "content": content}
                tool_result = _execute_tool(tool_name, tool_args, deps)
            if _tool_result_needs_attention(tool_result):
                return tool_name, tool_args, tool_result, tool_result
            resolved = os.path.realpath(os.path.expanduser(path))
            try:
                verified = Path(resolved).read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return tool_name, tool_args, tool_result, f"Wrote `{resolved}`, but I could not verify the file content: {exc}"
            answer = _format_file_write_answer(
                action="Created" if wants_create else "Wrote",
                path=path,
                content=verified,
                user_message=user_message,
            )
            return tool_name, tool_args, tool_result, answer

    branch_list_phrases = (
        "list all branches", "list branches", "show all branches", "show branches",
        "what branches", "which branches",
    )
    if any(phrase in lower for phrase in branch_list_phrases):
        git_path = repo_path or path
        tool_name = "shell_cmd"
        tool_args: dict[str, Any] = {"cmd": "git branch --all --no-color", "cwd": git_path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        branches = [line.rstrip() for line in tool_result.splitlines() if line.strip()]
        visible = "\n".join(f"- {line}" for line in branches[:80]) if branches else "- (no branches found)"
        answer = f"Here are the branches in `{os.path.realpath(os.path.expanduser(git_path))}`:\n{visible}"
        return tool_name, tool_args, tool_result, answer

    status_phrases = (
        "git status", "report the status", "repo status", "repository status",
        "working tree", "uncommitted changes",
    )
    if any(phrase in lower for phrase in status_phrases):
        tool_name = "git_status"
        tool_args = {"path": repo_path or path}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        return tool_name, tool_args, tool_result, tool_result

    branch_verify_match = _re.search(r'\b(?:verify|confirm|check)\b.*?\b(?:the )?([a-z0-9._/-]+)\s+branch\b', lower)
    current_branch_phrases = ("current branch", "which branch", "what branch", "verify this is the branch")
    if branch_verify_match or any(phrase in lower for phrase in current_branch_phrases):
        git_path = repo_path or path
        tool_name = "shell_cmd"
        tool_args: dict[str, Any] = {"cmd": "git branch --show-current", "cwd": git_path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        current_branch = tool_result.strip().splitlines()[-1].strip()
        target_branch = branch_verify_match.group(1).strip() if branch_verify_match else ""
        if target_branch:
            if current_branch == target_branch:
                answer = f"Yes — `{os.path.realpath(os.path.expanduser(git_path))}` is currently on the `{current_branch}` branch."
            else:
                answer = f"No — `{os.path.realpath(os.path.expanduser(git_path))}` is on `{current_branch}`, not `{target_branch}`."
        else:
            answer = f"`{os.path.realpath(os.path.expanduser(git_path))}` is currently on the `{current_branch}` branch."
        return tool_name, tool_args, tool_result, answer

    read_phrases = (
        "read file", "open file", "show me the file", "show the file",
        "show me the content", "show the content", "tail ",
    )
    wants_read = any(phrase in lower for phrase in read_phrases) or tail_count > 0 or lower.startswith("read ")
    if wants_read and (Path(path).is_file() or bool(Path(path).suffix)):
        tool_name = "read_file"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        answer = _format_file_read_answer(path=path, content=tool_result, user_message=user_message)
        return tool_name, tool_args, tool_result, answer

    listing_phrases = (
        "list", "show", "what's in", "what is in", "contents of", "items in", "items on",
        "folders in", "folders on", "directories in", "directories on", "files in", "files on",
        "inside",
    )
    if any(phrase in lower for phrase in listing_phrases):
        tool_name = "list_dir"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result

        parsed = _parse_list_dir_entries(tool_result)
        wants_all = any(phrase in lower for phrase in ("contents", "inside", "what's in", "what is in", "items"))
        wants_dirs = any(word in lower for word in ("folder", "folders", "directory", "directories")) and not wants_all
        wants_files = ("file" in lower or "files" in lower) and not wants_dirs and not wants_all

        if wants_all:
            names = [name for _, name in parsed]
            label = "items"
        elif wants_dirs:
            names = [name for kind, name in parsed if kind == "dir"]
            label = "folders"
        elif wants_files:
            names = [name for kind, name in parsed if kind == "file"]
            label = "files"
        else:
            names = [name for _, name in parsed]
            label = "items"

        answer = _format_listing_answer(path, names, label)
        return tool_name, tool_args, tool_result, answer

    return None
