from __future__ import annotations

import re
from typing import Optional


_DIRECTIVE_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+|i\s+need\s+you\s+to\s+|i\s+want\s+you\s+to\s+)?",
    re.IGNORECASE,
)

_INFORMATIONAL_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"how\s+do\s+i|"
    r"how\s+to|"
    r"show\s+me\s+how|"
    r"tell\s+me\s+how|"
    r"explain\s+how|"
    r"can\s+you\s+explain|"
    r"could\s+you\s+explain|"
    r"what(?:'s|\s+is)\s+the\s+(?:way|command)\s+to|"
    r"what\s+do\s+i\s+run\s+to"
    r")\b",
    re.IGNORECASE,
)

_COMMIT_DIRECTIVE_PHRASES = (
    "git commit",
    "commit and push",
    "commit the repo",
    "commit this repo",
    "commit repo",
    "git add and commit",
    "add and commit",
    "stage and commit",
    "stage the changes and commit",
    "stage everything and commit",
    "commit everything",
    "commit all changes",
    "commit the changes",
    "commit these changes",
    "commit the current changes",
    "commit the worktree",
    "commit the current worktree",
    "create a local commit",
    "make a local commit",
    "create a git commit",
    "make a git commit",
)


def _strip_wrapping_quotes(text: str) -> str:
    value = str(text or "").strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        value = value[1:-1].strip()
    return value


def looks_like_commit_request(user_message: str) -> bool:
    normalized = " ".join(str(user_message or "").strip().split())
    if not normalized:
        return False
    if _INFORMATIONAL_PREFIX_RE.search(normalized):
        return False
    candidate = _DIRECTIVE_PREFIX_RE.sub("", normalized, count=1).lower()
    return any(candidate.startswith(phrase) for phrase in _COMMIT_DIRECTIVE_PHRASES)


def looks_like_push_request(user_message: str) -> bool:
    lower = (user_message or "").lower()
    return any(phrase in lower for phrase in (
        "git push",
        "commit and push",
        "push this branch",
        "push the branch",
        "push branch",
        "push my changes",
        "push the changes",
        "publish the branch",
    ))


def extract_push_remote(user_message: str) -> str:
    remote = "origin"
    remote_match = re.search(r"\bto\s+([A-Za-z0-9._/-]+)\b", user_message or "", flags=re.IGNORECASE)
    if not remote_match:
        return remote
    candidate_remote = remote_match.group(1).strip()
    if candidate_remote and candidate_remote.lower() not in {"branch", "pr", "pull", "request"}:
        return candidate_remote
    return remote


def commit_scope_is_stage_all_request(user_message: str) -> bool:
    lower = (user_message or "").lower()
    scope_phrases = (
        "commit the repo",
        "commit this repo",
        "commit repo",
        "git add and commit",
        "add and commit",
        "stage and commit",
        "stage the changes and commit",
        "stage everything and commit",
        "stage all changes and commit",
    )
    return any(phrase in lower for phrase in scope_phrases)


def commit_scope_is_all_changes(user_message: str) -> bool:
    lower = (user_message or "").lower()
    scope_phrases = (
        "everything",
        "all changes",
        "full worktree",
        "whole worktree",
        "entire worktree",
        "full repo",
        "entire repo",
        "commit the repo",
        "commit this repo",
        "commit repo",
    )
    return any(phrase in lower for phrase in scope_phrases) or commit_scope_is_stage_all_request(user_message)


def extract_commit_message(user_message: str) -> Optional[str]:
    patterns = (
        r'\b(?:with|using)\s+(?:the\s+)?commit message\s+["\'`]([^"\']+?)["\'`]',
        r'\bcommit message\s*[:=]?\s*["\'`]([^"\']+?)["\'`]',
        r'\bmessage\s*[:=]?\s*["\'`]([^"\']+?)["\'`]',
        r'\bas\s+["\'`]([^"\']+?)["\'`]',
        r'\bcalled\s+["\'`]([^"\']+?)["\'`]',
        r'\bnamed\s+["\'`]([^"\']+?)["\'`]',
    )
    for pattern in patterns:
        match = re.search(pattern, user_message, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _strip_wrapping_quotes(match.group(1).strip())
    return None
