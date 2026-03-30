"""Agent orchestration core extracted from brain.py.

This module keeps the ReAct-style agent loop and helper logic isolated from the
runtime/tool implementations that still live in brain.py for compatibility.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional
import re as _re

DEFAULT_DEVBRAIN_DB_PATH = Path.home() / ".devbrain" / "devbrain.db"


@dataclass(frozen=True)
class AgentRuntimeDeps:
    tool_registry: dict[str, Callable[..., str]]
    normalize_tool_args: Callable[[str, dict[str, Any]], dict[str, Any]]
    stream_cli: Callable[..., AsyncGenerator[str, None]]
    stream_api_chat: Callable[..., AsyncGenerator[str, None]]
    stream_ollama_chat: Callable[..., AsyncGenerator[str, None]]
    ollama_execution_profile_sync: Callable[..., dict[str, Any]]
    ollama_message_with_images: Callable[[str, Optional[list[str]]], dict[str, Any]]
    find_cli: Callable[[str], str]
    ollama_default_model: str
    ollama_agent_model: str
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH


AGENT_TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem. Returns file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (absolute or ~-relative)"},
                    "max_kb": {"type": "integer", "description": "Max KB to read (default 32)", "default": 32},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: ~)", "default": "~"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_cmd",
            "description": "Run an allowlisted shell command (git, ls, grep, python3, etc.) and return output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)", "default": "~"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 15)", "default": 15},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git branch, status, and recent commit log for a project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in source code files using grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "~"},
                    "glob": {"type": "string", "description": "File glob patterns (space-separated)", "default": "*.py *.ts *.tsx *.js *.jsx"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append content to an existing file or create it if missing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to append to"},
                    "content": {"type": "string", "description": "Content to append"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with optional content. Fails if the file already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to create"},
                    "content": {"type": "string", "description": "Initial file content", "default": ""},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file safely. Only removes files, not directories.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Make targeted edits to a file using find-and-replace. "
                "This is the PREFERRED tool for modifying code — it makes surgical, "
                "reviewable changes instead of rewriting the entire file. "
                "old_string must match exactly (including whitespace/indentation). "
                "If old_string matches multiple locations, provide more context to make it unique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_string": {"type": "string", "description": "Exact text to find (must be unique in file)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_diff",
            "description": "Show git diff for a file or directory. Use after making edits to review/verify changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path to diff"},
                    "staged": {"type": "boolean", "description": "Show staged changes only", "default": False},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_mission",
            "description": "Create a new mission (task) for tracking. Use this when the user asks to create, add, or queue a mission/task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short mission title (e.g. 'Fix login page bug')"},
                    "detail": {"type": "string", "description": "Detailed description of what needs to be done", "default": ""},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Priority level", "default": "medium"},
                    "project_id": {"type": "integer", "description": "Project ID to link to (optional)"},
                    "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format (optional)"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_mission",
            "description": "Update an existing mission's status or fields. Use this to mark missions as done, in_progress, or to change details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "The mission ID to update"},
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "New status"},
                    "title": {"type": "string", "description": "Updated title"},
                    "detail": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Updated priority"},
                    "due_date": {"type": "string", "description": "Updated due date (YYYY-MM-DD)"},
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_missions",
            "description": "List current missions/tasks, optionally filtered by status or project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "Filter by status (default: all open)"},
                    "project_id": {"type": "integer", "description": "Filter by project ID"},
                },
                "required": [],
            },
        },
    },
]


def _canonical_tool_name(name: str, args: dict[str, Any] | None = None) -> str:
    raw = str(name or "").strip().lower()
    normalized = _re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    alias_map = {
        "append": "append_file",
        "append_file": "append_file",
        "create": "create_file",
        "create_file": "create_file",
        "delete": "delete_file",
        "delete_file": "delete_file",
        "remove": "delete_file",
        "remove_file": "delete_file",
        "rm": "delete_file",
        "read": "read_file",
        "read_file": "read_file",
        "readfile": "read_file",
        "write": "write_file",
        "write_file": "write_file",
        "writefile": "write_file",
        "list": "list_dir",
        "list_dir": "list_dir",
        "listdir": "list_dir",
        "gitstatus": "git_status",
        "git_status": "git_status",
        "search": "search_code",
        "search_code": "search_code",
        "searchcode": "search_code",
        "shell": "shell_cmd",
        "shell_cmd": "shell_cmd",
        "shellcmd": "shell_cmd",
        "edit": "edit_file",
        "edit_file": "edit_file",
        "editfile": "edit_file",
        "replace": "edit_file",
        "patch": "edit_file",
        "diff": "show_diff",
        "show_diff": "show_diff",
        "showdiff": "show_diff",
        "git_diff": "show_diff",
    }
    if normalized == "using" and (args or {}).get("path"):
        return "read_file"
    return alias_map.get(normalized, normalized)


def _execute_tool(name: str, args: dict[str, Any], deps: AgentRuntimeDeps) -> str:
    """Execute a tool by name with the given arguments."""
    canonical_name = _canonical_tool_name(name, args)
    fn = deps.tool_registry.get(canonical_name)
    if not fn:
        return f"ERROR: Unknown tool '{name}'"
    try:
        return fn(**deps.normalize_tool_args(canonical_name, args))
    except TypeError as e:
        return f"ERROR: Bad arguments for {canonical_name}: {e}"
    except Exception as e:
        return f"ERROR: {canonical_name} failed: {e}"


def _project_name_pattern(name: str) -> str:
    parts = [part for part in _re.split(r"[^a-z0-9]+", (name or "").lower()) if part]
    if not parts:
        return ""
    return rf"(?<![a-z0-9]){'[\\s/_-]*'.join(_re.escape(part) for part in parts)}(?![a-z0-9])"


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


def _extract_path_from_text(text: str, db_path: Path = DEFAULT_DEVBRAIN_DB_PATH) -> Optional[str]:
    """Best-effort path extraction for common local-path requests."""
    candidates = _re.findall(r'(~\/[^\s,"\')]+|\/home\/[^\s,"\')]+)', text)
    if candidates:
        return candidates[0].rstrip(".,:;!?`")

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
    history: list[dict[str, Any]] | None = None,
    project_name: Optional[str] = None,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
) -> Optional[str]:
    """Reuse the most recent explicit or workspace-derived path from chat history."""
    if project_name:
        project_path = _resolve_project_path_from_text(project_name, db_path=db_path)
        if project_path:
            return project_path

    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content, db_path=db_path)
        if path:
            return path
    return None


def _recent_file_path(
    history: list[dict[str, Any]] | None = None,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
) -> Optional[str]:
    """Reuse the most recent explicit file path from chat history."""
    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content, db_path=db_path)
        if not path:
            continue
        resolved = os.path.realpath(os.path.expanduser(path))
        candidate = Path(resolved)
        if candidate.exists() and candidate.is_file():
            return path
        if candidate.suffix:
            return path
    return None


def _contains_phrase(text: str, phrase: str) -> bool:
    lower = (text or "").lower()
    token = (phrase or "").lower().strip()
    if not token:
        return False
    return bool(_re.search(rf"(?<![a-z0-9]){_re.escape(token)}(?![a-z0-9])", lower))


def _has_local_operator_markers(text: str, db_path: Path = DEFAULT_DEVBRAIN_DB_PATH) -> bool:
    lower = (text or "").lower()
    return (
        bool(_extract_path_from_text(text or "", db_path=db_path))
        or "action:" in lower
        or "args:" in lower
        or "answer:" in lower
        or any(_contains_phrase(lower, term) for term in (
            "git ", "git status", "branch", "commit", "repo", "repository",
            "workspace", "file", "folder", "directory", "path", "readme",
            ".py", ".ts", ".tsx", ".js", ".jsx", ".md", "package.json",
            "list_dir", "shell_cmd", "read_file", "search_code",
        ))
    )


def _filtered_general_history(
    history: list[dict[str, Any]] | None = None,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in history or []:
        content = str(item.get("content", "") or "")
        if not content.strip():
            continue
        if _has_local_operator_markers(content, db_path=db_path):
            continue
        filtered.append({"role": item.get("role", "user"), "content": content[:500]})
    return filtered[-4:]


def _is_general_planning_request(user_message: str) -> bool:
    lower = (user_message or "").strip().lower()
    if not lower:
        return False

    local_action_terms = (
        "git", "repo", "repository", "branch", "commit", "file", "files", "folder",
        "folders", "directory", "directories", "desktop", "workspace", "scan", "inspect",
        "search code", "read ", "open ", "run ", "execute ", "check ", "look at ",
    )
    if any(_contains_phrase(lower, term) for term in local_action_terms):
        return False
    if _extract_path_from_text(user_message):
        return False

    business_terms = (
        "company profile", "business profile", "enterprise", "company", "business",
        "capability statement", "proposal", "strategy", "go-to-market", "brand profile",
        "executive summary", "corporate profile", "mission statement", "vision statement",
        "service offering", "value proposition", "pitch deck", "brochure", "profile for me",
    )
    writing_terms = (
        "plan", "draft", "write", "create", "prepare", "outline", "summarize",
        "improve", "rewrite", "structure",
    )
    return any(_contains_phrase(lower, term) for term in business_terms) and any(_contains_phrase(lower, term) for term in writing_terms)


def _is_casual_conversation(user_message: str) -> bool:
    """
    Return True if the message is pure casual conversation that should get a
    direct, natural reply — no tools, no ReAct, no project scan.
    """
    raw = (user_message or "").strip()
    lower = raw.lower()
    if not lower or len(lower) > 300:
        return False

    action_signals = (
        "run ", "execute ", "read ", "write ", "scan ", "search ", "find ",
        "list ", "show me ", "check ", "open ", "create file", "git ",
        "fix ", "refactor ", "analyse ", "analyze ", "deploy ", "build ",
        "install ", "debug ", "test ", "review ", "explain the code",
    )
    if any(lower.startswith(s) or f" {s}" in lower for s in action_signals):
        return False

    greetings = (
        "hi", "hello", "hey", "howzit", "yo", "sup", "what's up", "whats up",
        "good morning", "good afternoon", "good evening", "morning", "evening",
    )
    if any(lower == g or lower.startswith(g + " ") or lower.startswith(g + ",") for g in greetings):
        return True

    about_self = (
        "how are you", "how do you feel", "who are you", "what are you",
        "what can you do", "what do you do", "tell me about yourself",
        "are you ready", "you there", "you awake",
    )
    if any(s in lower for s in about_self):
        return True

    words = lower.split()
    if len(words) <= 2 and not any(s in lower for s in ("run", "git", "fix", "file", "scan", "list")):
        return True

    return False


def _requires_local_operator_execution(
    user_message: str,
    db_path: Path = DEFAULT_DEVBRAIN_DB_PATH,
) -> bool:
    raw = (user_message or "").strip()
    lower = raw.lower()
    if not lower:
        return False

    if _is_casual_conversation(raw) or _is_general_planning_request(raw):
        return False

    if _extract_path_from_text(raw, db_path=db_path):
        return True

    direct_phrases = (
        "create a file",
        "create file",
        "edit a file",
        "edit file",
        "write a file",
        "write file",
        "rewrite a file",
        "rewrite file",
        "overwrite a file",
        "overwrite file",
        "update the file",
        "update file",
        "set the file",
        "set file",
        "append the line",
        "append this line",
        "append this text",
        "replace text",
        "replace this text",
        "delete file",
        "remove file",
        "verify it exists",
        "verify the file exists",
        "confirm it exists",
        "show me the absolute path",
        "show the absolute path",
        "show me the last",
        "show the last",
        "read file",
        "open file",
        "scan the workspace",
        "inspect the workspace",
        "inspect the repo",
        "inspect the repository",
        "inspect the codebase",
        "scan the codebase",
        "git status",
        "git branch",
        "list all branches",
        "run command",
        "shell command",
    )
    if any(_contains_phrase(lower, phrase) for phrase in direct_phrases):
        return True

    action_verbs = (
        "create ", "write ", "append ", "replace ", "change ", "edit ", "rewrite ",
        "overwrite ", "update ", "set ", "delete ", "remove ",
        "rm ", "rename ", "move ", "list ", "show ", "inspect ", "scan ", "search ",
        "find ", "read ", "open ", "check ", "verify ", "confirm ", "run ", "execute ",
    )
    local_objects = (
        "file", "files", "folder", "folders", "directory", "directories",
        "repo", "repository", "workspace", "desktop", "path", "readme", "codebase",
        ".py", ".ts", ".tsx", ".js", ".jsx", ".md", "package.json",
        "terminal", "shell", "command",
    )
    return (
        any(lower.startswith(verb) or f" {verb}" in lower for verb in action_verbs)
        and any(_contains_phrase(lower, item) for item in local_objects)
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

    path = _extract_path_from_text(user_message, db_path=deps.db_path)
    lower_has_git = any(term in lower for term in ("git", "branch", "repo", "repository", "status", "commit"))
    lower_has_file_action = any(term in lower for term in (
        "file", "append", "replace", "change", "edit", "rewrite", "overwrite",
        "update", "set", "delete", "remove", "rm", "absolute path", "verify",
        "exists", "content",
    ))
    if not path and lower_has_git:
        path = _recent_repo_path(history, project_name, db_path=deps.db_path)
    if not path and lower_has_file_action:
        path = _recent_file_path(history, db_path=deps.db_path)

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


def _build_react_system(context_block: str, project_name: Optional[str], tool_names: list[str]) -> str:
    """Build ReAct-style system prompt for the agent."""

    axon_ctx = ""
    if project_name and ("axon" in project_name.lower() or "devbrain" in project_name.lower() or "dashpro" in project_name.lower()):
        axon_ctx = """

SELF-IMPROVEMENT MODE — You are working on your own codebase (Axon).
Axon lives at ~/.devbrain/ and you can read, search, and modify your own source code.

Architecture:
  server.py    — FastAPI app (~5800 lines), all API routes, SSE streaming
  brain.py     — AI orchestration, ReAct agent loop, tool execution, model routing
  db.py        — SQLite schema + CRUD (aiosqlite), 20+ tables
  scheduler.py — APScheduler background jobs (scans, digests, webhook queue)
  integrations.py — GitHub CLI, Slack webhooks, generic webhook retry queue
  vault.py     — AES-256-GCM encrypted secrets with TOTP
  memory_engine.py — Memory layer (facts, preferences, project context)
  scanner.py   — Project directory scanner
  model_router.py — Multi-provider model selection
  ui/index.html — SPA (Alpine.js + Tailwind), ~5900 lines
  ui/js/       — chat.js, helpers.js, dashboard.js, settings.js, voice.js
  ui/styles.css — Custom styles for prose, canvas, animations

Key patterns:
  - Routes use: async with devdb.get_db() as conn
  - Agent tools: _TOOL_REGISTRY dict, AGENT_TOOL_DEFS list
  - SSE events: {"type": "text|thinking|tool_call|tool_result|done|error"}
  - DB: aiosqlite with row_factory, init_db() for schema migrations
  - Venv: .venv/bin/python, deps in requirements.txt

When asked to improve Axon, use read_file + search_code to understand the current code,
then write_file to make changes. Test with shell_cmd: "cd ~/.devbrain && .venv/bin/python -c 'import ast; ast.parse(open(\"<file>\").read()); print(\"OK\")'".
After changes, suggest the user restart Axon (axon restart) to apply.
Never claim that a file was modified, patched, backed up, or verified unless you actually used write_file
and received a successful tool result for that exact file path."""

    self_awareness = f"""
## What you are
You are Axon — an agentic AI copilot embedded in a local developer OS at ~/.devbrain/.
Your THINKING blocks and tool calls (Working blocks) render live in the user's browser as you work.
You are NOT limited in streaming. Do NOT tell the user you "can't show real-time output" — you can and do.
You can read and modify your own source code. You are a partner, not a chatbot.
Axon core files: server.py (FastAPI routes), brain.py (agent loop + tools), ui/index.html (SPA), ui/js/ (Alpine.js modules).
"""

    return f"""You are Axon Agent — a NEXT-GEN agentic AI coding assistant that uses tools to act on behalf of developers.

Available tools: {', '.join(tool_names)}

To use a tool, output EXACTLY in this format (no extra text before it):
ACTION: tool_name
ARGS: {{"arg1": "value1"}}

When you have the final answer, output EXACTLY:
ANSWER: your response here

## Coding Workflow — How to Make Real Code Changes

When the user asks you to fix, refactor, add, or change code, follow this multi-step pattern:

1. **UNDERSTAND** — Read the relevant file(s) with `read_file` to understand the current code.
2. **LOCATE** — Use `search_code` if you need to find where something is defined or used.
3. **EDIT** — Use `edit_file` for targeted, surgical changes. This is your PRIMARY editing tool.
   - `old_string` must match EXACTLY (including indentation, whitespace, line breaks).
   - Include enough surrounding context in `old_string` to make it unique.
   - `new_string` is the replacement (can be larger or smaller than old_string).
   - For multi-line edits, include the full block in old_string and new_string.
4. **VERIFY** — Use `show_diff` to review your changes, or `read_file` to confirm the edit landed.
5. **TEST** — If applicable, run tests with `shell_cmd` (e.g., `python3 -c "import ast; ..."` for syntax check).

### Key Rules for `edit_file`:
- ALWAYS read the file FIRST before editing — never guess at file contents.
- Copy the exact text from the file for `old_string` — character-for-character, including indentation.
- If your edit fails with "not found", re-read the file and try again with the exact text.
- For multiple changes to the same file, make them one at a time (each edit_file call).
- Use `write_file` ONLY for creating new files or complete rewrites. For modifications, ALWAYS use `edit_file`.

### Tool Selection:
- `edit_file` — Modify existing code (preferred for all code changes)
- `write_file` — Create new files or complete file rewrites only
- `read_file` — Read file contents before editing
- `search_code` — Find code patterns across files
- `show_diff` — Review changes after editing
- `shell_cmd` — Run commands (git, tests, syntax checks, etc.)
- `git_status` — Check repo state
- `list_dir` — Browse directories

## General Rules:
- ALWAYS use tools when you need real data. Do NOT describe how the user could do it — DO IT.
- If asked to find/search/read ANYTHING on the filesystem — use tools.
- Chain multiple tool calls: read → edit → verify → answer.
- After seeing tool results, either use another tool or give ANSWER.
- Be a partner in ANSWER — direct, warm, technically sharp. Use markdown.
- Never make up file contents, diffs, or command output.
- Never claim you edited a file unless you actually used edit_file/write_file and got a success result.
- All paths must start with ~ or /home/{os.getenv('USER', 'edp')}
{self_awareness}{axon_ctx}
{('Context: ' + context_block[:800]) if context_block else ''}
{('Project: ' + project_name) if project_name else ''}"""


def _sanitize_agent_text(text: str) -> str:
    """Remove leaked internal ReAct instructions before showing text to the user."""
    skip_contains = (
        "To use a tool, output EXACTLY in this format",
        "When you have the final answer, output EXACTLY",
        "EXACTLY in this format (no extra text before it)",
        "ANSWER: your response here",
    )
    skip_exact = {
        "ACTION: tool_name",
        'ARGS: {"arg1": "value1"}',
    }

    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if stripped in skip_exact:
            continue
        if any(marker in stripped for marker in skip_contains):
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


_FAKE_PROGRESS_LINE_RE = _re.compile(
    r'^\s*#\s*(TASK|STATUS|COMMAND|GOAL|PROGRESS|RESULT|VERIFICATION|DURATION)\s*:',
    _re.IGNORECASE,
)
_FAKE_PROGRESS_BAR_RE = _re.compile(r'[█▓░]{3,}.*\d+\s*%')


def _filter_thinking_chunk(text: str) -> str:
    """Strip fake structured progress output from thinking tokens."""
    if not text:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if _FAKE_PROGRESS_LINE_RE.match(line):
            continue
        if _FAKE_PROGRESS_BAR_RE.search(line):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return result


def _looks_like_unverified_edit_claim(text: str) -> bool:
    """Detect model-written "I edited files" reports that were not backed by tools."""
    sample = (text or "").strip()
    if not sample:
        return False
    suspicious_markers = (
        "# TASK:",
        "# STATUS:",
        "# CHANGES:",
        "# METHOD:",
        "# PROGRESS:",
        "Files modified:",
        "Changes made to ",
        "Backup created",
        "Do not restart server",
        "implementation in place",
        "Fix Applied",
        "patch applied",
        "commit when ready",
    )
    return any(marker.lower() in sample.lower() for marker in suspicious_markers)


def _guard_unverified_edit_claim(text: str, wrote_files: bool) -> str:
    """Prevent the model from narrating fake self-edits when no write tool ran."""
    cleaned = _sanitize_agent_text(text)
    if wrote_files or not _looks_like_unverified_edit_claim(cleaned):
        return cleaned
    return (
        "Axon did not verify any real file edits in this run.\n\n"
        "What happened instead: the model produced a work-log style answer without a successful "
        "`write_file` tool action behind it.\n\n"
        "To make real changes, Axon must first inspect the code with tools, then call `write_file`, "
        "and only after that report the exact file path it changed."
    )


def _parse_react_action(text: str) -> tuple[str, dict[str, Any]] | None:
    """Parse ACTION/ARGS from ReAct-formatted text. Returns (tool_name, args) or None."""
    action_match = _re.search(r'ACTION:\s*(\w+)', text)
    args_match = _re.search(r'ARGS:\s*(\{[^}]*\}|\{[\s\S]*?\})', text)
    if not action_match:
        return None
    tool_name = action_match.group(1).strip()
    if tool_name == "tool_name":
        return None
    args: dict[str, Any] = {}
    if args_match:
        try:
            args = json.loads(args_match.group(1))
        except json.JSONDecodeError:
            for kv in _re.findall(r'"(\w+)":\s*"([^"]*)"', args_match.group(1)):
                args[kv[0]] = kv[1]
    return tool_name, args


async def run_agent(
    user_message: str,
    history: list[dict[str, Any]],
    *,
    deps: AgentRuntimeDeps,
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    tools: list[str] | None = None,
    ollama_url: str = "",
    ollama_model: str = "",
    max_iterations: int = 12,
    force_tool_mode: bool = False,
    api_key: str = "",
    api_base_url: str = "",
    api_model: str = "",
    api_provider: str = "",
    cli_path: str = "",
    backend: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Async generator yielding agent events (ReAct-style, streaming-compatible):
      {"type": "text",        "chunk": str}
      {"type": "tool_call",   "name": str, "args": dict}
      {"type": "tool_result", "name": str, "result": str}
      {"type": "done",        "iterations": int}

    Uses ReAct text-based tool calling (reliable across all Ollama models).
    """
    active_tool_names = list(deps.tool_registry.keys()) if tools is None else [
        t for t in tools if t in deps.tool_registry
    ]
    wrote_files = False

    use_api = bool(api_key and api_base_url)
    use_cli = backend == "cli"
    resolved_cli = deps.find_cli(cli_path) if use_cli else ""

    if not force_tool_mode and _is_casual_conversation(user_message):
        casual_system = (
            "You are Axon — a sharp, friendly AI copilot embedded in the user's local developer OS.\n"
            "The user is making casual conversation. Reply naturally and warmly, like a capable colleague.\n"
            "Be brief (2-4 sentences max). Mention what you can help with if relevant, but keep it conversational.\n"
            "Do NOT use tools, do NOT list files, do NOT run commands, do NOT produce reports."
        )
        msgs: list[dict[str, Any]] = [{"role": "system", "content": casual_system}]
        msgs.extend(_filtered_general_history(history, db_path=deps.db_path))
        msgs.append({"role": "user", "content": user_message})
        if use_cli:
            async for chunk in deps.stream_cli(msgs, cli_path=resolved_cli, max_tokens=300):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            async for chunk in deps.stream_api_chat(
                messages=msgs,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=300,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            async for chunk in deps.stream_ollama_chat(
                messages=msgs,
                model=ollama_model or deps.ollama_default_model,
                ollama_url=ollama_url,
                max_tokens=300,
            ):
                yield {"type": "text", "chunk": chunk}
        yield {"type": "done", "iterations": 0}
        return

    if not force_tool_mode and _is_general_planning_request(user_message):
        system = (
            "You are Axon, a calm and practical AI operator.\n"
            "This request is a general planning or writing task, not a local tool task.\n"
            "Do not use tools. Do not inspect files or directories unless the user explicitly asks for local data.\n"
            "Answer directly with a clear structure, a concise draft, and 2-4 helpful next-step options."
        )
        if resource_context:
            system += f"\n\nUse these attached resources when they are relevant:\n{resource_context[:5000]}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(_filtered_general_history(history, db_path=deps.db_path))
        messages.append({"role": "user", "content": user_message})

        if use_cli:
            async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=1200):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            async for chunk in deps.stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=1200,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            execution = await asyncio.to_thread(
                deps.ollama_execution_profile_sync,
                vision_model or ollama_model or deps.ollama_default_model,
                ollama_url,
                streaming=True,
                purpose="chat",
            )
            messages[-1] = deps.ollama_message_with_images(user_message, resource_image_paths)
            if execution.get("note"):
                yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}
            async for chunk in deps.stream_ollama_chat(
                messages=messages,
                model=execution["model"],
                max_tokens=1200,
                ollama_url=ollama_url,
                purpose="chat",
            ):
                yield {"type": "text", "chunk": chunk}
        yield {"type": "done", "iterations": 1}
        return

    direct_action = _direct_agent_action(
        user_message,
        history=history,
        project_name=project_name,
        deps=deps,
    )
    if direct_action:
        tool_name, tool_args, result, answer = direct_action
        yield {"type": "tool_call", "name": tool_name, "args": tool_args}
        yield {"type": "tool_result", "name": tool_name, "result": result[:4000]}
        yield {"type": "text", "chunk": answer}
        yield {"type": "done", "iterations": 1}
        return

    system_context = context_block
    if resource_context:
        system_context = f"{system_context}\n\n{resource_context}" if system_context else resource_context
    system = _build_react_system(system_context, project_name, active_tool_names)

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for h in history[-8:]:
        messages.append({"role": h["role"], "content": h["content"][:1200]})

    if use_cli:
        messages.append({"role": "user", "content": user_message})
        execution = None
    elif use_api:
        messages.append({"role": "user", "content": user_message})
        execution = None
    else:
        execution = await asyncio.to_thread(
            deps.ollama_execution_profile_sync,
            vision_model or ollama_model or deps.ollama_agent_model,
            ollama_url,
            streaming=True,
            purpose="agent",
        )
        messages.append(deps.ollama_message_with_images(user_message, resource_image_paths))

    iteration = 0
    for iteration in range(max_iterations):
        full_text: str = ""
        streamed_up_to = 0
        found_action_live = False
        try:
            async def _token_source() -> AsyncGenerator[str, None]:
                if use_cli:
                    async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=4096):
                        yield chunk
                elif use_api:
                    async for chunk in deps.stream_api_chat(
                        messages=messages,
                        api_key=api_key,
                        api_base_url=api_base_url,
                        api_model=api_model,
                        max_tokens=2400,
                    ):
                        yield chunk
                else:
                    async for chunk in deps.stream_ollama_chat(
                        messages=messages,
                        model=execution["model"] if execution else deps.ollama_agent_model,
                        max_tokens=2400,
                        ollama_url=ollama_url,
                        purpose="agent",
                    ):
                        yield chunk

            if not use_api and not use_cli and iteration == 0 and execution and execution.get("note"):
                yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}

            async for chunk in _token_source():
                full_text += chunk
                if not found_action_live:
                    for marker in ("ACTION:", "ANSWER:"):
                        pos = full_text.find(marker)
                        if pos >= 0:
                            found_action_live = True
                            remaining = _filter_thinking_chunk(_sanitize_agent_text(full_text[streamed_up_to:pos].strip()))
                            if remaining:
                                yield {"type": "thinking", "chunk": remaining}
                            streamed_up_to = pos
                            break
                    if not found_action_live:
                        safe_end = max(streamed_up_to, len(full_text) - 10)
                        new_text = _filter_thinking_chunk(full_text[streamed_up_to:safe_end])
                        if new_text.strip():
                            yield {"type": "thinking", "chunk": new_text}
                            streamed_up_to = safe_end

        except Exception as exc:
            provider_label = api_provider or ("CLI" if use_cli else ("API" if use_api else "Ollama"))
            yield {"type": "text", "chunk": f"\n⚠️ {provider_label} error: {exc}"}
            break

        if not full_text.strip():
            yield {"type": "text", "chunk": "\n⚠️ Empty response from model."}
            break

        action = _parse_react_action(full_text)
        answer_match = _re.search(r'ANSWER:\s*([\s\S]+)', full_text)
        clean_text = _sanitize_agent_text(full_text)

        if action:
            tool_name, tool_args = action
            if not found_action_live:
                think_text = full_text[:full_text.find("ACTION:")].strip()
                think_text = _filter_thinking_chunk(_sanitize_agent_text(think_text))
                if think_text:
                    yield {"type": "thinking", "chunk": think_text}

            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            result = await asyncio.to_thread(_execute_tool, tool_name, tool_args, deps)
            if tool_name in ("write_file", "edit_file") and not str(result).startswith("ERROR:"):
                wrote_files = True
            yield {"type": "tool_result", "name": tool_name, "result": result[:4000]}

            messages.append({"role": "assistant", "content": full_text})
            messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{result[:4000]}\n\nContinue."})

        elif answer_match:
            answer = _guard_unverified_edit_claim(answer_match.group(1).strip(), wrote_files=wrote_files)
            if not answer or answer == "your response here":
                yield {"type": "text", "chunk": "\n⚠️ Axon could not form a clean answer. Please retry the task."}
                break
            yield {"type": "text", "chunk": answer}
            break
        else:
            guarded_text = _guard_unverified_edit_claim(clean_text, wrote_files=wrote_files)
            if guarded_text:
                yield {"type": "text", "chunk": guarded_text}
            else:
                yield {"type": "text", "chunk": "\n⚠️ Axon produced an invalid tool response. Please retry the task."}
            break

    yield {"type": "done", "iterations": iteration + 1}


__all__ = [
    "AGENT_TOOL_DEFS",
    "AgentRuntimeDeps",
    "_build_react_system",
    "_canonical_tool_name",
    "_contains_phrase",
    "_direct_agent_action",
    "_execute_tool",
    "_extract_path_from_text",
    "_filter_thinking_chunk",
    "_filtered_general_history",
    "_format_listing_answer",
    "_guard_unverified_edit_claim",
    "_has_local_operator_markers",
    "_is_casual_conversation",
    "_is_general_planning_request",
    "_requires_local_operator_execution",
    "_looks_like_unverified_edit_claim",
    "_parse_list_dir_entries",
    "_parse_react_action",
    "_project_name_pattern",
    "_recent_repo_path",
    "_resolve_project_path_from_text",
    "_sanitize_agent_text",
    "run_agent",
]
