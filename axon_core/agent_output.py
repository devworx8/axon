from __future__ import annotations

import json
import re as _re

_EVIDENCE_SECTION_HEADINGS = (
    "Verified In This Run",
    "Inferred From Repo State",
    "Not Yet Verified",
    "Next Action Not Yet Taken",
)


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


_MISSING_SPACE_AFTER_PUNCT  = _re.compile(r'([.!?])([A-Za-z])')
_MISSING_SPACE_AFTER_COMMA  = _re.compile(r',([A-Za-z])')
_MISSING_SPACE_AFTER_COLON  = _re.compile(r':([A-Za-z])(?![/\\])')   # skip :// URLs
_MISSING_SPACE_AFTER_SEMI   = _re.compile(r';([A-Za-z])')


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
        line = _MISSING_SPACE_AFTER_COLON.sub(r": \1", line)
        line = _MISSING_SPACE_AFTER_SEMI.sub(r"; \1", line)
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


def _has_required_evidence_sections(text: str) -> bool:
    sample = (text or "").lower()
    return all(heading.lower() in sample for heading in _EVIDENCE_SECTION_HEADINGS)


def _looks_like_checkpoint_or_audit_summary(user_message: str, text: str) -> bool:
    request_text = (user_message or "").lower()
    answer_text = (text or "").lower()
    request_markers = (
        "review your previous answer",
        "unsupported assumptions",
        "invented details",
        "confidence rating",
        "current checkpoint",
        "repo state",
        "what changed",
        "reconstruct",
        "audit",
        "checkpoint",
        "verify the claims",
        "verify the last response",
    )
    answer_markers = (
        "what changed",
        "current checkpoint",
        "rewritten answer",
        "unsupported or too strong",
        "unsupported assumptions",
        "repo state",
        "i'm reconstructing",
    )
    structured_handoff = (
        ("what changed" in answer_text and "verification" in answer_text)
        or ("verified in this run" in answer_text and "not yet verified" in answer_text)
        or ("verification" in answer_text and "next action" in answer_text)
    )
    return (
        any(marker in request_text for marker in request_markers)
        or any(marker in answer_text for marker in answer_markers)
        or structured_handoff
    )


def _needs_evidence_section_repair(user_message: str, text: str) -> bool:
    sample = (text or "").strip()
    if not sample:
        return False
    if _has_required_evidence_sections(sample):
        return False
    return _looks_like_checkpoint_or_audit_summary(user_message, sample)


def _tool_receipt_summary(tool_log: list[dict]) -> str:
    if not tool_log:
        return "- No tool receipts were recorded in this run."

    lines: list[str] = []
    for entry in tool_log[-8:]:
        name = str(entry.get("name", "") or "tool")
        args = entry.get("args") or {}
        result = str(entry.get("result", "") or "").replace("\n", " ").strip()
        result_preview = result[:120] + ("…" if len(result) > 120 else "")
        if isinstance(args, dict):
            if name == "shell_cmd":
                detail = str(args.get("cmd", "")).strip()
            elif name in {"read_file", "write_file", "edit_file", "append_file", "create_file", "delete_file"}:
                detail = str(args.get("path", "")).strip()
            elif name == "search_code":
                detail = str(args.get("pattern", "")).strip()
            elif name == "show_diff":
                detail = str(args.get("path", "") or args.get("cwd", "")).strip()
            else:
                detail = json.dumps(args, sort_keys=True)[:120]
        else:
            detail = str(args)[:120]
        detail = detail or "(no args)"
        lines.append(f"- {name}: {detail} -> {result_preview or '(no result preview)'}")
    return "\n".join(lines)


def _build_evidence_repair_prompt(user_message: str, tool_log: list[dict]) -> str:
    return (
        "STOP. This is a checkpoint/audit/verification summary and it must separate evidence levels.\n\n"
        "Re-answer using EXACTLY these headings:\n"
        "Verified In This Run\n"
        "Inferred From Repo State\n"
        "Not Yet Verified\n"
        "Next Action Not Yet Taken\n\n"
        "Rules:\n"
        "- Only put a claim under 'Verified In This Run' if this run's tool results support it.\n"
        "- Put interpretations, likely direction, and commit/file-shape guesses under 'Inferred From Repo State'.\n"
        "- Put unresolved checks, missing reruns, and environment-sensitive claims under 'Not Yet Verified'.\n"
        "- If you did not actually continue implementation yet, say so under 'Next Action Not Yet Taken'.\n"
        "- No chain-of-thought, no 'I'm reconstructing...' narration, no blended checkpoint story.\n\n"
        f"Original user request:\n{(user_message or '').strip()[:600] or '(none)'}\n\n"
        "Recent tool receipts from this run:\n"
        f"{_tool_receipt_summary(tool_log)}\n\n"
        "Now emit only:\n"
        "ANSWER: ..."
    )


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
            try:
                parsed[key] = json.loads(token)
            except Exception:
                parsed[key] = token[1:-1].replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
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
            ".git/index.lock",
            "read-only file system",
            "git metadata is not writable",
            "blocked by the sandbox",
            "this session cannot write git metadata",
        )) and not _tool_log_mentions(
            tool_log,
            ("blocked_cmd:git", "git commit", "git add", "git push", "read-only file system", ".git/index.lock"),
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
        ".git/index.lock",
        "read-only file system",
        "git metadata is not writable",
        "blocked by the sandbox",
        "this session cannot write git metadata",
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


def _sanitize_json_string_literals(raw: str) -> str:
    """Fix unescaped control characters inside JSON string values.

    Models (especially DeepSeek) often emit JSON with literal newlines, tabs,
    and carriage returns inside string values, which breaks json.loads().
    Walk the string and escape any control characters that appear while we are
    inside a JSON string literal.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in raw:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            # Escape control characters that are illegal in JSON strings
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def _extract_write_args_structural(after_action: str) -> dict[str, object]:
    """Last-resort extraction for write_file/edit_file when JSON parsing completely fails.

    Looks for known key patterns like "path": "...", then extracts the content
    value by finding the last string value in the JSON blob (typically the longest
    multi-line value is the file content).
    """
    args: dict[str, object] = {}
    # Extract path — look for "path": "..." or path: "..."
    path_match = _re.search(r'["\']?path["\']?\s*:\s*"([^"]+)"', after_action)
    if not path_match:
        path_match = _re.search(r'["\']?(?:file|target)["\']?\s*:\s*"([^"]+)"', after_action)
    if path_match:
        args["path"] = path_match.group(1)

    # For edit_file, extract old_string
    old_match = _re.search(r'["\']?old_string["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', after_action, _re.DOTALL)
    if old_match:
        args["old_string"] = old_match.group(1).replace("\\n", "\n").replace("\\t", "\t")

    # For edit_file, extract new_string
    new_match = _re.search(r'["\']?new_string["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', after_action, _re.DOTALL)
    if new_match:
        args["new_string"] = new_match.group(1).replace("\\n", "\n").replace("\\t", "\t")

    # Extract content — look for "content": "..." or content between triple backticks
    content_match = _re.search(r'["\']?content["\']?\s*:\s*"((?:[^"\\]|\\.)*)"', after_action, _re.DOTALL)
    if content_match:
        args["content"] = content_match.group(1).replace("\\n", "\n").replace("\\t", "\t")
    elif "content" not in args:
        # Try code block: content: ```...```
        code_match = _re.search(r'["\']?content["\']?\s*:\s*```\w*\n([\s\S]*?)```', after_action)
        if code_match:
            args["content"] = code_match.group(1)

    return args

def _parse_react_action(text: str) -> tuple[str, dict[str, object]] | None:
    """Parse ACTION/ARGS from ReAct-formatted text. Returns (tool_name, args) or None."""
    action_match = _re.search(r"(?m)^\s*ACTION:\s*(\w+)", text)
    if not action_match:
        return None
    tool_name = action_match.group(1).strip()
    if tool_name == "tool_name":
        return None
    args: dict[str, object] = {}

    # Primary: ARGS: { ... } on its own line
    args_blob = _extract_json_object_after("ARGS", text)
    if args_blob:
        try:
            args = json.loads(args_blob)
        except json.JSONDecodeError:
            # Try sanitizing unescaped newlines/tabs inside JSON strings
            sanitized = _sanitize_json_string_literals(args_blob)
            try:
                args = json.loads(sanitized)
            except json.JSONDecodeError:
                args = _fallback_parse_flat_object(args_blob)

    # Fallback 1: any JSON object after the ACTION line (some models skip the ARGS: label)
    if not args:
        after_action = text[action_match.end():]
        brace = after_action.find("{")
        if brace >= 0:
            candidate = _extract_json_object_after_pos(after_action, brace)
            if candidate:
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and parsed:
                        args = parsed
                except json.JSONDecodeError:
                    sanitized = _sanitize_json_string_literals(candidate)
                    try:
                        parsed = json.loads(sanitized)
                        if isinstance(parsed, dict) and parsed:
                            args = parsed
                    except json.JSONDecodeError:
                        fb = _fallback_parse_flat_object(candidate)
                        if fb:
                            args = fb

    # Fallback 2: ```json code block anywhere after ACTION
    if not args:
        code_match = _re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", text[action_match.end():])
        if code_match:
            try:
                parsed = json.loads(code_match.group(1))
                if isinstance(parsed, dict) and parsed:
                    args = parsed
            except json.JSONDecodeError:
                sanitized = _sanitize_json_string_literals(code_match.group(1))
                try:
                    parsed = json.loads(sanitized)
                    if isinstance(parsed, dict) and parsed:
                        args = parsed
                except json.JSONDecodeError:
                    pass

    # Fallback 3 — structural extraction for write_file / edit_file with multi-line content
    if not args and tool_name in ("write_file", "write", "edit_file", "edit", "append_file"):
        args = _extract_write_args_structural(text[action_match.end():])

    return tool_name, args


def _extract_json_object_after_pos(text: str, start: int) -> str | None:
    """Extract balanced JSON object starting at position `start`."""
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
