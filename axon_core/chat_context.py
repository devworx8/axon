from __future__ import annotations

import re
from typing import Optional


_IMAGE_INSPECTION_RE = re.compile(
    r"\b(what do you see|what's in|what is in|describe|identify|analy[sz]e|read|ocr|summari[sz]e|look at)\b"
)
_IMAGE_REFERENT_RE = re.compile(
    r"\b(image|photo|picture|screenshot|logo|diagram|attachment|attached|uploaded)\b"
)
_IMAGE_COMPARISON_RE = re.compile(
    r"\b(compare|difference|different|previous|earlier|before|again|same as|other image|last image)\b"
)


def _history_limit_for_backend(backend: str) -> int:
    runtime = (backend or "api").strip().lower()
    if runtime == "ollama":
        return 6
    if runtime == "cli":
        return 10
    return 20


def _is_image_focused_question(user_message: str) -> bool:
    text = str(user_message or "").strip().lower()
    if not text:
        return False
    if _IMAGE_COMPARISON_RE.search(text):
        return False
    if _IMAGE_INSPECTION_RE.search(text):
        return True
    return _IMAGE_REFERENT_RE.search(text) is not None and any(
        marker in text for marker in ("what", "describe", "identify", "read", "analyse", "analyze")
    )


def select_history_for_chat(
    user_message: str,
    history: list[dict],
    *,
    backend: str,
    max_turns: Optional[int] = None,
    resource_image_paths: Optional[list[str]] = None,
) -> list[dict]:
    if not history:
        return []
    if resource_image_paths and _is_image_focused_question(user_message):
        return []
    limit = _history_limit_for_backend(backend)
    if max_turns is not None:
        limit = max(1, int(max_turns))
    return history[-limit:]
