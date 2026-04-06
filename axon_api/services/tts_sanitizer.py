"""
Axon — TTS Text Sanitizer

Central utility for cleaning text before speech synthesis.
Strips markdown, normalizes paths, collapses formatting artifacts.
Used by all TTS paths: desktop /api/tts, mobile /api/mobile/axon/speak,
and mobile device-local Speech.speak() (via cleanForSpeech export).
"""

from __future__ import annotations

import re

# ── Markdown stripping ──────────────────────────────────────

_FENCED_CODE = re.compile(r"```[^\n`]*\n?[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_HEADINGS = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD_DOUBLE = re.compile(r"\*\*([^*]+)\*\*")
_BOLD_UNDER = re.compile(r"__([^_]+)__")
_ITALIC_STAR = re.compile(r"\*([^*]+)\*")
_ITALIC_UNDER = re.compile(r"_([^_]+)_")
_STRIKETHROUGH = re.compile(r"~~([^~]+)~~")
_MD_LINKS = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_IMAGES = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_UNORDERED_LIST = re.compile(r"^[-*+]\s+", re.MULTILINE)
_ORDERED_LIST = re.compile(r"^\d+\.\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^>\s*", re.MULTILINE)
_HORIZ_RULE = re.compile(r"^---+$", re.MULTILINE)
_TABLE_PIPES = re.compile(r"[|]")
_TABLE_SEPARATOR = re.compile(r"^[-|: ]+$", re.MULTILINE)
_BACKSLASH = re.compile(r"\\([^\\])")
_HTML_TAGS = re.compile(r"<[^>]+>")

# ── Path normalization ──────────────────────────────────────

_FILE_PATH = re.compile(
    r"(?<!\w)([/~](?:[a-zA-Z0-9._-]+/)+[a-zA-Z0-9._-]+)",
)


def _spoken_path(match: re.Match) -> str:
    """Convert /home/edp/Downloads → 'home, edp, Downloads'."""
    raw = match.group(1)
    parts = [p for p in raw.replace("~", "home").split("/") if p]
    if len(parts) <= 1:
        return raw
    return ", ".join(parts)


# ── Emoji cleanup ───────────────────────────────────────────

_EMOJI_PREFIX = re.compile(
    r"[\U0001f4c1\U0001f4c2\U0001f4ce\U0001f4cb\U0001f50d\u2705\u274c\u26a0\u2139"
    r"\U0001f6a8\U0001f4a1\U0001f4e6\U0001f527\U0001f3af\U0001f4dd\U0001f9e0"
    r"\U0001f916\U0001f4ac\U0001f4e2\U0001f389\U0001f525\U0001f680\u2728]+\s*"
)


# ── Main sanitizer ──────────────────────────────────────────

def clean_for_speech(text: str) -> str:
    """Strip markdown, paths, and formatting artifacts for natural TTS."""
    if not text:
        return ""
    t = str(text)

    # Remove code blocks entirely (spoken code sounds terrible)
    t = _FENCED_CODE.sub(" ", t)
    # Inline code → just the content
    t = _INLINE_CODE.sub(r"\1", t)
    # Images → alt text
    t = _MD_IMAGES.sub(r"\1", t)
    # Links → label only
    t = _MD_LINKS.sub(r"\1", t)
    # HTML tags
    t = _HTML_TAGS.sub("", t)
    # Headings
    t = _HEADINGS.sub("", t)
    # Bold / italic / strikethrough
    t = _BOLD_DOUBLE.sub(r"\1", t)
    t = _BOLD_UNDER.sub(r"\1", t)
    t = _ITALIC_STAR.sub(r"\1", t)
    t = _ITALIC_UNDER.sub(r"\1", t)
    t = _STRIKETHROUGH.sub(r"\1", t)
    # Lists → natural flow
    t = _UNORDERED_LIST.sub("", t)
    t = _ORDERED_LIST.sub("", t)
    # Blockquotes
    t = _BLOCKQUOTE.sub("", t)
    # Horizontal rules
    t = _HORIZ_RULE.sub("", t)
    # Table artifacts
    t = _TABLE_SEPARATOR.sub("", t)
    t = _TABLE_PIPES.sub(" ", t)
    # Backslash escapes
    t = _BACKSLASH.sub(r"\1", t)
    # Emoji prefixes (they sound weird in TTS)
    t = _EMOJI_PREFIX.sub("", t)
    # File paths → spoken form
    t = _FILE_PATH.sub(_spoken_path, t)
    # Collapse whitespace
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()
