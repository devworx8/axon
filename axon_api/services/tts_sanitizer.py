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

_FENCED_CODE = re.compile(r"```([^\n`]*)\n?([\s\S]*?)```", re.MULTILINE)
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

_SPOKEN_CODE_LABELS = {
    "bash": "shell",
    "js": "JavaScript",
    "jsx": "JSX",
    "py": "Python",
    "sh": "shell",
    "ts": "TypeScript",
    "tsx": "TSX",
    "zsh": "shell",
}
_SPOKEN_COMMANDS = re.compile(
    r"\b(?:git|npm|npx|pnpm|yarn|node|python|python3|pip|pip3|bash|zsh|curl|gh|vercel)\b",
    re.IGNORECASE,
)
_LONG_FLAG = re.compile(r"(^|\s)--([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
_SHORT_FLAG = re.compile(r"(^|\s)-([a-z])\b", re.IGNORECASE)
_UPPER_SNAKE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_DOTTED_FILE_TOKEN = re.compile(r"\b([A-Za-z0-9_-]+)\.(py|js|ts|tsx|jsx|json|md|css|html|sh|yaml|yml|env)\b")
_DOTTED_IDENTIFIER_TOKEN = re.compile(r"\b([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)\b")
_FILE_LABELS = {
    "py": "Python file",
    "js": "JavaScript file",
    "ts": "TypeScript file",
    "tsx": "TSX file",
    "jsx": "JSX file",
    "json": "JSON file",
    "md": "Markdown file",
    "css": "CSS file",
    "html": "HTML file",
    "sh": "shell script",
    "yaml": "YAML file",
    "yml": "YAML file",
    "env": "env file",
}


def _spoken_path(match: re.Match) -> str:
    """Convert /home/edp/Downloads → 'home, edp, Downloads'."""
    raw = match.group(1)
    parts = [p for p in raw.replace("~", "home").split("/") if p]
    if len(parts) <= 1:
        return raw
    return ", ".join(parts)


def _spoken_code_label(raw: str) -> str:
    normalized = str(raw or "").strip().lower()
    return _SPOKEN_CODE_LABELS.get(normalized, normalized)


def _humanize_upper_snake(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("_", " ")).strip()


def _humanize_file_token(stem: str, ext: str) -> str:
    stem_words = re.sub(r"[_-]+", " ", str(stem or "")).strip()
    return f"{stem_words} {_FILE_LABELS.get(str(ext or '').lower(), ext)}".strip()


def _humanize_code(text: str) -> str:
    value = str(text or "").replace("\r", "\n").strip()
    if not value:
        return ""
    value = _SPOKEN_COMMANDS.sub(lambda match: match.group(0).lower(), value)
    value = _UPPER_SNAKE_TOKEN.sub(lambda match: _humanize_upper_snake(match.group(0)), value)
    value = _DOTTED_FILE_TOKEN.sub(lambda match: _humanize_file_token(match.group(1), match.group(2)), value)
    value = _DOTTED_IDENTIFIER_TOKEN.sub(lambda match: f"{match.group(1)} dot {match.group(2)}", value)
    value = _LONG_FLAG.sub(lambda match: f"{match.group(1)}{match.group(2)} flag", value)
    value = _SHORT_FLAG.sub(lambda match: f"{match.group(1)}{match.group(2).lower()} flag", value)
    replacements = (
        (re.compile(r"!=="), " is not exactly equal to "),
        (re.compile(r"==="), " is exactly equal to "),
        (re.compile(r"!="), " is not equal to "),
        (re.compile(r"=="), " is equal to "),
        (re.compile(r"=>"), " returns "),
        (re.compile(r"\+\+"), " increment "),
        (re.compile(r"--"), " decrement "),
        (re.compile(r"<="), " is less than or equal to "),
        (re.compile(r">="), " is greater than or equal to "),
        (re.compile(r"[{}\[\]();,]"), " "),
        (re.compile(r"/"), " slash "),
        (re.compile(r"="), " equals "),
        (re.compile(r":"), " "),
        (re.compile(r"\n+"), ". "),
    )
    for pattern, replacement in replacements:
        value = pattern.sub(replacement, value)
    return re.sub(r"\s+", " ", value).strip()


def _replace_fenced_code(match: re.Match) -> str:
    label = _spoken_code_label(match.group(1))
    spoken = _humanize_code(match.group(2))
    if not spoken:
        return " "
    if label:
        return f" In {label}, {spoken}. "
    return f" {spoken}. "


def _replace_inline_code(match: re.Match) -> str:
    spoken = _humanize_code(match.group(1))
    if not spoken:
        return " "
    return f" {spoken} "


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

    # Code snippets → natural spoken phrasing
    t = _FENCED_CODE.sub(_replace_fenced_code, t)
    t = _INLINE_CODE.sub(_replace_inline_code, t)
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
    # Common command names and flags should sound like speech, not punctuation.
    t = _SPOKEN_COMMANDS.sub(lambda match: match.group(0).lower(), t)
    t = _UPPER_SNAKE_TOKEN.sub(lambda match: _humanize_upper_snake(match.group(0)), t)
    t = _DOTTED_FILE_TOKEN.sub(lambda match: _humanize_file_token(match.group(1), match.group(2)), t)
    t = _DOTTED_IDENTIFIER_TOKEN.sub(lambda match: f"{match.group(1)} dot {match.group(2)}", t)
    t = _LONG_FLAG.sub(lambda match: f"{match.group(1)}{match.group(2)} flag", t)
    t = _SHORT_FLAG.sub(lambda match: f"{match.group(1)}{match.group(2).lower()} flag", t)
    # Collapse whitespace
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()
