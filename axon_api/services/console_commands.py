from __future__ import annotations

import shlex
from typing import Any

from axon_api.services import local_tool_env
from axon_api.services import npm_cli_extensions
from axon_api.services import runtime_login_sessions

CommandRecord = dict[str, Any]
_LOGIN_FAMILY_ALIASES = {
    "claude": "claude",
    "cli": "claude",
    "claude-cli": "claude",
    "claude_code": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "codex-cli": "codex",
    "codex_cli": "codex",
}


def _install_usage() -> str:
    root = local_tool_env.install_scope_label()
    return (
        "Usage: `/install <npm-package|codex|claude> [binary-name]`.\n"
        f"Installs stay inside Axon at `{root}`.\n"
        "Examples: `/install codex`, `/install claude`, `/install @anthropic-ai/claude-code claude`."
    )


def _install_response(result: CommandRecord) -> str:
    lines = [str(result.get("message") or "Install completed.")]
    preview = str(result.get("command_preview") or "").strip()
    extension = dict(result.get("extension") or {})
    binary = str(extension.get("binary") or "").strip()
    if binary:
        lines.append(f"Binary: `{binary}`")
    if preview:
        lines.append(f"Command: `{preview}`")
    return "\n".join(line for line in lines if line)


def _login_usage() -> str:
    return (
        "Usage: `/login <codex|claude>`.\n"
        "Starts Axon's guided local CLI sign-in flow.\n"
        "Examples: `/login codex`, `/login claude`.\n"
        "Run the same command again to refresh an active sign-in session."
    )


def _normalize_login_family(value: str) -> str:
    family = _LOGIN_FAMILY_ALIASES.get(str(value or "").strip().lower(), "")
    if not family:
        raise ValueError("Login target must be `codex` or `claude`.")
    return family


def _login_family_label(family: str) -> str:
    return "Codex CLI" if family == "codex" else "Claude CLI"


def _login_response(session: CommandRecord) -> str:
    family = str(session.get("family") or "").strip().lower()
    family_label = _login_family_label(family)
    status = str(session.get("status") or "").strip().lower()
    message = str(session.get("message") or "").strip()
    browser_url = str(session.get("browser_url") or "").strip()
    user_code = str(session.get("user_code") or "").strip()
    command_preview = str(session.get("command_preview") or "").strip()
    session_id = str(session.get("session_id") or "").strip()

    if status == "authenticated":
        lines = [f"{family_label} is already signed in inside Axon."]
    elif status in {"pending", "browser_opened", "waiting"}:
        lines = [f"{family_label} sign-in is running inside Axon."]
    elif status == "cancelled":
        lines = [f"{family_label} sign-in was cancelled."]
    else:
        lines = [f"{family_label} sign-in status: `{status or 'unknown'}`."]

    if message:
        lines.append(message)
    if browser_url:
        lines.append(f"Open: <{browser_url}>")
    if user_code:
        lines.append(f"Code: `{user_code}`")
    if command_preview:
        lines.append(f"Command: `{command_preview}`")
    if session_id:
        lines.append(f"Session: `{session_id}`")
    if status in {"pending", "browser_opened", "waiting"}:
        lines.append(f"Run `/login {family}` again to refresh this guided sign-in session.")
    return "\n".join(line for line in lines if line)


def _handle_install_command(args: list[str]) -> CommandRecord:
    if not args or len(args) > 2:
        return {
            "command": "install",
            "response": _install_usage(),
            "event_name": "chat_console_install",
            "event_summary": "install usage",
            "data": {"status": "usage"},
        }

    package_name = args[0]
    binary_name = args[1] if len(args) == 2 else ""
    try:
        result = npm_cli_extensions.install_npm_cli_extension(package_name, binary_name)
    except ValueError as exc:
        return {
            "command": "install",
            "response": f"{exc}\n\n{_install_usage()}",
            "event_name": "chat_console_install",
            "event_summary": f"install invalid: {package_name}",
            "data": {"status": "invalid"},
        }
    except RuntimeError as exc:
        return {
            "command": "install",
            "response": f"Install failed: {exc}",
            "event_name": "chat_console_install",
            "event_summary": f"install failed: {package_name}",
            "data": {"status": "failed"},
        }

    extension = dict(result.get("extension") or {})
    package_label = str(extension.get("package_name") or package_name)
    return {
        "command": "install",
        "response": _install_response(result),
        "event_name": "chat_console_install",
        "event_summary": f"install: {package_label}",
        "data": {
            "status": str(result.get("status") or ""),
            "package_name": package_label,
            "binary_name": str(extension.get("binary_name") or ""),
            "binary": str(extension.get("binary") or ""),
            "install_root": str(extension.get("install_root") or local_tool_env.install_scope_label()),
            "install_command": str(result.get("command_preview") or ""),
        },
    }


def _handle_login_command(args: list[str], *, login_overrides: dict[str, str] | None = None) -> CommandRecord:
    if len(args) != 1:
        return {
            "command": "login",
            "response": _login_usage(),
            "event_name": "chat_console_login",
            "event_summary": "login usage",
            "data": {"status": "usage"},
        }

    try:
        family = _normalize_login_family(args[0])
    except ValueError as exc:
        return {
            "command": "login",
            "response": f"{exc}\n\n{_login_usage()}",
            "event_name": "chat_console_login",
            "event_summary": f"login invalid: {args[0]}",
            "data": {"status": "invalid"},
        }

    try:
        override_path = str((login_overrides or {}).get(family) or "").strip()
        session = runtime_login_sessions.start_login_session(family, override_path=override_path)
    except Exception as exc:
        return {
            "command": "login",
            "response": f"Login failed: {exc}",
            "event_name": "chat_console_login",
            "event_summary": f"login failed: {family}",
            "data": {"status": "failed", "family": family},
        }

    return {
        "command": "login",
        "response": _login_response(session),
        "event_name": "chat_console_login",
        "event_summary": f"login: {family}",
        "data": {
            "status": str(session.get("status") or ""),
            "family": family,
            "session_id": str(session.get("session_id") or ""),
            "browser_url": str(session.get("browser_url") or ""),
            "user_code": str(session.get("user_code") or ""),
            "binary": str(session.get("binary") or ""),
            "command_preview": str(session.get("command_preview") or ""),
            "runtime_login_session": dict(session),
        },
    }


def maybe_handle_console_command(message: str, *, login_overrides: dict[str, str] | None = None) -> CommandRecord | None:
    text = str(message or "").strip()
    if not text.startswith("/"):
        return None
    try:
        parts = shlex.split(text)
    except ValueError as exc:
        return {
            "command": "parse_error",
            "response": f"Unable to parse command: {exc}",
            "event_name": "chat_console_command",
            "event_summary": "command parse error",
            "data": {"status": "invalid"},
        }

    if not parts:
        return None

    command_name = parts[0].strip().lower()
    if command_name in {"/install", "/install-cli"}:
        return _handle_install_command(parts[1:])
    if command_name in {"/login", "/login-cli"}:
        return _handle_login_command(parts[1:], login_overrides=login_overrides)
    return None
