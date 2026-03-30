from __future__ import annotations

import os
import re as _re
from pathlib import Path
from typing import Any, Optional

from .agent_paths import (
    _extract_path_from_text,
    _recent_file_path,
    _recent_repo_path,
    _resolve_user_path,
    _workspace_root_path,
)
from .agent_toolspecs import AgentRuntimeDeps, _execute_tool


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
    patterns = (
        r"\bcontaining exactly\s*:?\s*(.+?)(?=\s+(?:then|and)\s+(?:verify|show|check|confirm)\b|$)",
        r"\bwith content\s*:?\s*(.+?)(?=\s+(?:then|and)\s+(?:verify|show|check|confirm)\b|$)",
        r"\bcontaining\s*:?\s*(.+?)(?=\s+(?:then|and)\s+(?:verify|show|check|confirm)\b|$)",
        r"\bexactly\s*:?\s*(.+?)(?=\s+(?:then|and)\s+(?:verify|show|check|confirm)\b|$)",
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
        "exists", "content",
    ))
    if not path and lower_has_git:
        path = _recent_repo_path(history, project_name, db_path=deps.db_path, workspace_path=workspace_path)
    if not path and lower_has_file_action:
        path = _recent_file_path(history, db_path=deps.db_path, workspace_path=workspace_path)

    if not path and workspace_path:
        workspace_root = _workspace_root_path(workspace_path)
        path = str(workspace_root) if workspace_root else _resolve_user_path(workspace_path)

    if path:
        path = _resolve_user_path(path, workspace_path=workspace_path)

    if not path:
        return None

    write_phrases = ("write a file", "write file", "save a file")
    create_phrases = ("create a file", "create file", "make a file", "make file")
    overwrite_phrases = (
        "edit a file", "edit file", "rewrite a file", "rewrite file",
        "overwrite a file", "overwrite file", "set the file", "set file",
        "update the file", "update file",
    )
    append_phrases = ("append the line", "append line", "append ")
    replace_phrases = ("replace ", "change ")
    delete_phrases = ("delete file", "remove file", "delete ", "remove ", "rm ")
    wants_append = any(phrase in lower for phrase in append_phrases)
    wants_create = any(phrase in lower for phrase in create_phrases)
    wants_write = any(phrase in lower for phrase in write_phrases)
    wants_overwrite = any(phrase in lower for phrase in overwrite_phrases)
    wants_replace = any(phrase in lower for phrase in replace_phrases)
    wants_delete = any(phrase in lower for phrase in delete_phrases)

    if wants_append:
        content = _extract_append_content(user_message)
        if content:
            if not content.startswith("\n"):
                content = "\n" + content
            tool_name = "append_file"
            tool_args = {"path": path, "content": content}
            tool_result = _execute_tool(tool_name, tool_args, deps)
            if tool_result.startswith("ERROR:"):
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
            if tool_result.startswith("ERROR:"):
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
        if tool_result.startswith("ERROR:"):
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
        if tool_result.startswith("ERROR:"):
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
            if tool_result.startswith("ERROR:"):
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
        tool_name = "shell_cmd"
        tool_args: dict[str, Any] = {"cmd": "git branch --all --no-color", "cwd": path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        branches = [line.rstrip() for line in tool_result.splitlines() if line.strip()]
        visible = "\n".join(f"- {line}" for line in branches[:80]) if branches else "- (no branches found)"
        answer = f"Here are the branches in `{os.path.realpath(os.path.expanduser(path))}`:\n{visible}"
        return tool_name, tool_args, tool_result, answer

    status_phrases = (
        "git status", "report the status", "repo status", "repository status",
        "working tree", "uncommitted changes",
    )
    if any(phrase in lower for phrase in status_phrases):
        tool_name = "git_status"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        return tool_name, tool_args, tool_result, tool_result

    branch_verify_match = _re.search(r'\b(?:verify|confirm|check)\b.*?\b(?:the )?([a-z0-9._/-]+)\s+branch\b', lower)
    current_branch_phrases = ("current branch", "which branch", "what branch", "verify this is the branch")
    if branch_verify_match or any(phrase in lower for phrase in current_branch_phrases):
        tool_name = "shell_cmd"
        tool_args: dict[str, Any] = {"cmd": "git branch --show-current", "cwd": path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args, deps)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        current_branch = tool_result.strip().splitlines()[-1].strip()
        target_branch = branch_verify_match.group(1).strip() if branch_verify_match else ""
        if target_branch:
            if current_branch == target_branch:
                answer = f"Yes — `{os.path.realpath(os.path.expanduser(path))}` is currently on the `{current_branch}` branch."
            else:
                answer = f"No — `{os.path.realpath(os.path.expanduser(path))}` is on `{current_branch}`, not `{target_branch}`."
        else:
            answer = f"`{os.path.realpath(os.path.expanduser(path))}` is currently on the `{current_branch}` branch."
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
