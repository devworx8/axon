from __future__ import annotations

import json
import re as _re


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


_MISSING_SPACE_AFTER_PUNCT = _re.compile(r'([.!?])([A-Za-z])')
_MISSING_SPACE_AFTER_COMMA = _re.compile(r',([A-Za-z])')


def _normalize_thinking_spacing(text: str) -> str:
    """Fix common word-merging artifacts from small LLMs in prose thinking text.
    Only applied to non-indented (non-code) lines to avoid breaking code snippets.
    """
    if not text:
        return text
    out_lines: list[str] = []
    for line in text.splitlines():
        # Skip lines that look like code (indented, or contain common code syntax)
        if line and (line[0] in (" ", "\t") or "`" in line or line.strip().startswith(("$", "#", "//", "/*", "*"))):
            out_lines.append(line)
            continue
        line = _MISSING_SPACE_AFTER_PUNCT.sub(r"\1 \2", line)
        line = _MISSING_SPACE_AFTER_COMMA.sub(r", \1", line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _filter_thinking_chunk(text: str, *, strip: bool = True) -> str:
    """Strip fake structured progress output from thinking tokens, then normalise spacing.

    When *strip* is False the leading/trailing whitespace is preserved so that
    incremental streaming chunks keep the word-boundary spaces that exist in the
    original token stream.
    """
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
    result = "\n".join(kept)
    if strip:
        result = result.strip()
    return _normalize_thinking_spacing(result)


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


def _tool_log_entry_text(entry: dict) -> str:
    parts: list[str] = []
    for key in ("name", "args", "result"):
        value = entry.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            try:
                parts.append(json.dumps(value, sort_keys=True))
            except TypeError:
                parts.append(str(value))
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


def _tool_log_has_name(tool_log: list[dict], names: set[str]) -> bool:
    lowered = {name.lower() for name in names}
    return any(str(entry.get("name", "")).lower() in lowered for entry in tool_log)


def _tool_log_mentions(tool_log: list[dict], keywords: tuple[str, ...]) -> bool:
    lowered = tuple(keyword.lower() for keyword in keywords if keyword)
    return any(any(keyword in _tool_log_entry_text(entry) for keyword in lowered) for entry in tool_log)


def _extract_json_object_after(prefix: str, text: str) -> str | None:
    marker = _re.search(rf"(?m)^\s*{_re.escape(prefix)}\s*:\s*", text)
    if not marker:
        return None
    start = text.find("{", marker.end())
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _fallback_parse_flat_object(raw: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in _re.findall(
        r'"([^"]+)":\s*("(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)',
        raw,
        _re.IGNORECASE,
    ):
        token = value.strip()
        if token.startswith('"') and token.endswith('"'):
            parsed[key] = bytes(token[1:-1], "utf-8").decode("unicode_escape")
        elif token.lower() == "true":
            parsed[key] = True
        elif token.lower() == "false":
            parsed[key] = False
        elif token.lower() == "null":
            parsed[key] = None
        else:
            try:
                parsed[key] = int(token)
            except ValueError:
                try:
                    parsed[key] = float(token)
                except ValueError:
                    parsed[key] = token
    return parsed


def _looks_like_hallucinated_execution(text: str, tool_log: list[dict]) -> bool:
    """Detect when the model narrates command execution without having called tools.

    Catches patterns like writing ```bash blocks with git push, running commands
    in markdown, or claiming success on operations that never ran.
    """
    sample = (text or "").strip().lower()
    if not sample:
        return False

    if tool_log:
        unsupported_claims = 0
        if any(phrase in sample for phrase in (
            "file has been updated",
            "file has been created",
            "file saved successfully",
            "changes applied",
            "i've made the changes",
            "i've updated the file",
            "i've created the file",
            "i've fixed the issue",
            "the fix is in place",
        )) and not _tool_log_has_name(tool_log, {"write_file", "append_file", "create_file", "delete_file", "edit_file"}):
            unsupported_claims += 1

        if any(phrase in sample for phrase in (
            "successfully pushed",
            "successfully committed",
            "successfully merged",
            "all changes committed",
            "pushed to origin",
            "pushed to remote",
            "git push origin",
            "git commit -m",
            "changes committed & pushed",
        )) and not _tool_log_mentions(tool_log, ("git push", "git commit", "git add", "git merge", "pushed", "committed", "merged")):
            unsupported_claims += 1

        if any(phrase in sample for phrase in (
            "repository is clean",
            "git status:",
        )) and not (
            _tool_log_has_name(tool_log, {"git_status"})
            or _tool_log_mentions(tool_log, ("git status", "working tree clean", "nothing to commit"))
        ):
            unsupported_claims += 1

        if any(phrase in sample for phrase in (
            "tests pass",
            "tests passed",
            "all tests passing",
            "build succeeded",
            "build successful",
        )) and not _tool_log_mentions(
            tool_log,
            ("pytest", "test", "tests passed", "build", "compiled", "cargo test", "go test", "npm test", "pnpm test", "yarn test"),
        ):
            unsupported_claims += 1

        if any(phrase in sample for phrase in (
            "server restarted",
            "deployment complete",
            "migration applied",
            "database updated",
            "npm install completed",
            "pip install completed",
            "package installed",
        )) and not _tool_log_mentions(
            tool_log,
            ("restart", "systemctl", "service ", "docker", "deploy", "migration", "database", "npm install", "pip install", "package installed"),
        ):
            unsupported_claims += 1

        return unsupported_claims > 0

    # Phrases that indicate the model is narrating a command it "ran"
    execution_claims = (
        "successfully pushed",
        "successfully committed",
        "successfully merged",
        "changes have been successfully",
        "repository is clean",
        "all changes committed",
        "pushed to origin",
        "pushed to remote",
        "git push origin",
        "git commit -m",
        "git add .",
        "$ command",
        "(no output)",
        "changes committed & pushed",
        "commit messages:",
        "git status:",
        "output:",
        "let me verify the push",
        "let me check the current",
        "let me also check",
        "now let me verify",
        # ── additional hallucination patterns ──
        "file has been updated",
        "file has been created",
        "file saved successfully",
        "changes applied",
        "here is the output",
        "the result is:",
        "running the command",
        "executed successfully",
        "tests pass",
        "tests passed",
        "all tests passing",
        "build succeeded",
        "build successful",
        "deployment complete",
        "server restarted",
        "migration applied",
        "database updated",
        "npm install completed",
        "pip install completed",
        "package installed",
        "i've made the changes",
        "i've updated the file",
        "i've created the file",
        "i've fixed the issue",
        "the fix is in place",
        "here's what i did:",
    )
    hit_count = sum(1 for phrase in execution_claims if phrase in sample)
    return hit_count >= 2


def _guard_unverified_edit_claim(text: str, wrote_files: bool, tool_log: list[dict] | None = None) -> str:
    """Prevent the model from narrating fake self-edits or hallucinated commands."""
    cleaned = _sanitize_agent_text(text)
    # Check for hallucinated command execution (no tools were called at all)
    if _looks_like_hallucinated_execution(cleaned, tool_log or []):
        return ""  # returning empty triggers the retry/correction path
    if wrote_files or not _looks_like_unverified_edit_claim(cleaned):
        return cleaned
    return (
        "I did not verify any real file edits in this run.\n\n"
        "What happened instead: I produced a work-log style answer without a successful "
        "`write_file` tool action behind it.\n\n"
        "To make real changes, I must first inspect the code with tools, then call `write_file`, "
        "and only after that report the exact file path it changed."
    )


def _parse_react_action(text: str) -> tuple[str, dict[str, object]] | None:
    """Parse ACTION/ARGS from ReAct-formatted text. Returns (tool_name, args) or None."""
    action_match = _re.search(r"(?m)^\s*ACTION:\s*(\w+)", text)
    if not action_match:
        return None
    tool_name = action_match.group(1).strip()
    if tool_name == "tool_name":
        return None
    args: dict[str, object] = {}
    args_blob = _extract_json_object_after("ARGS", text)
    if args_blob:
        try:
            args = json.loads(args_blob)
        except json.JSONDecodeError:
            args = _fallback_parse_flat_object(args_blob)
    return tool_name, args
