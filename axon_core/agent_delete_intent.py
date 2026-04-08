from __future__ import annotations

import re as _re


_DELETE_NEGATION_RE = _re.compile(
    r"\b(?:do\s+not|don't|dont|never|without|avoid|stop)\b(?:\s+\w+){0,4}\s+\b(?:delete|remove|wipe|trash|rm)\b",
    flags=_re.IGNORECASE,
)
_DELETE_DISCUSSION_RE = _re.compile(
    r"\b(?:why\s+did|did|would|could|can|should)\s+you\s+(?:delete|remove|wipe|trash)\b",
    flags=_re.IGNORECASE,
)
_DELETE_EXPLICIT_RE = (
    _re.compile(r"^\s*(?:please\s+)?(?:delete|remove|wipe|trash)\b", flags=_re.IGNORECASE),
    _re.compile(r"\b(?:please|can you|could you|would you|go ahead and)\s+(?:delete|remove|wipe|trash)\b", flags=_re.IGNORECASE),
    _re.compile(r"\brm\s+[^\s]+", flags=_re.IGNORECASE),
)


def has_explicit_delete_intent(user_message: str) -> bool:
    text = " ".join(str(user_message or "").strip().split())
    if not text:
        return False
    if _DELETE_NEGATION_RE.search(text):
        return False
    if _DELETE_DISCUSSION_RE.search(text):
        return False
    return any(pattern.search(text) for pattern in _DELETE_EXPLICIT_RE)


__all__ = ["has_explicit_delete_intent"]
