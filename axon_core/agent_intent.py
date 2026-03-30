from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Any

from .agent_paths import DEFAULT_DEVBRAIN_DB_PATH, _extract_path_from_text


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
    workspace_path: str = "",
) -> bool:
    raw = (user_message or "").strip()
    lower = raw.lower()
    if not lower:
        return False

    if _is_casual_conversation(raw) or _is_general_planning_request(raw):
        return False

    if _extract_path_from_text(raw, db_path=db_path, workspace_path=workspace_path):
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
