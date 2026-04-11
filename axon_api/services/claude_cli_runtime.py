from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from glob import glob
from typing import Any, cast

import brain
from axon_api.services import local_tool_env

_CLAUDE_CODE_PACKAGE = "@anthropic-ai/claude-code"
_INSTALL_TIMEOUT_SECONDS = 900
_STATUS_TIMEOUT_SECONDS = 15
_VERSION_TIMEOUT_SECONDS = 10

EnvRecord = dict[str, str]
StatusRecord = dict[str, Any]

_find_cli = cast(Callable[[str], str], getattr(brain, "_find_cli"))
_legacy_discover_cli_environments = cast(
    Callable[[], list[dict[object, object]]],
    getattr(brain, "discover_cli_environments"),
)


def _discover_cli_environments() -> list[EnvRecord]:
    environments = _legacy_discover_cli_environments()
    normalized: list[EnvRecord] = []
    for env in environments:
        item = {str(key): str(value) for key, value in dict(env).items()}
        if item.get("family") not in {"", "claude"}:
            continue
        normalized.append(item)
    return normalized


def _clean_env() -> dict[str, str]:
    env = local_tool_env.build_tool_env({**os.environ, "NO_COLOR": "1"})
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    return env


def _find_npm_binary() -> str:
    found = shutil.which("npm")
    if found:
        return found

    home = os.path.expanduser("~")
    patterns = [
        f"{home}/.nvm/versions/node/*/bin/npm",
        f"{home}/.volta/bin/npm",
        f"{home}/.npm-global/bin/npm",
        f"{home}/.local/bin/npm",
        "/usr/local/bin/npm",
        "/usr/bin/npm",
    ]
    for pattern in patterns:
        for match in sorted(glob(pattern), reverse=True):
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return match
    return ""


def _run_command(parts: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        parts,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_clean_env(),
    )


def _command_preview(parts: list[str]) -> str:
    return shlex.join(parts)


def _npm_install_parts(npm_binary: str, package_name: str) -> list[str]:
    return local_tool_env.npm_install_parts(npm_binary, package_name)


def _selected_environment(binary: str, environments: list[EnvRecord]) -> EnvRecord:
    if not binary:
        return {}
    binary_real = os.path.realpath(binary)
    for env in environments:
        path = str(env.get("path") or "")
        if path and os.path.realpath(path) == binary_real:
            return env
    return {}


def _cli_version(binary: str) -> str:
    if not binary:
        return ""
    try:
        proc = _run_command([binary, "--version"], timeout=_VERSION_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0].strip()


def _auth_status(binary: str) -> StatusRecord:
    if not binary:
        return {
            "logged_in": False,
            "auth_method": "",
            "subscription_type": "",
            "email": "",
            "org_id": "",
            "org_name": "",
            "provider_label": "Not installed",
            "message": "Install Claude CLI to sign in.",
        }

    try:
        proc = _run_command([binary, "auth", "status", "--json"], timeout=_STATUS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {
            "logged_in": False,
            "auth_method": "",
            "subscription_type": "",
            "email": "",
            "org_id": "",
            "org_name": "",
            "provider_label": "Timed out",
            "message": "Timed out while checking Claude CLI auth status.",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "logged_in": False,
            "auth_method": "",
            "subscription_type": "",
            "email": "",
            "org_id": "",
            "org_name": "",
            "provider_label": "Unavailable",
            "message": str(exc),
        }

    raw = (proc.stdout or proc.stderr or "").strip()
    data: dict[str, Any] | None = None
    try:
        candidate = json.loads(raw or "{}")
        if isinstance(candidate, dict):
            data = candidate
    except json.JSONDecodeError:
        data = None

    if data is not None:
        logged_in = bool(data.get("loggedIn"))
        if not logged_in:
            return {
                "logged_in": False,
                "auth_method": "",
                "subscription_type": "",
                "email": "",
                "org_id": "",
                "org_name": "",
                "provider_label": "Not signed in",
                "message": "Claude CLI is installed but not signed in.",
            }
        auth_method = str(data.get("authMethod") or "")
        subscription_type = str(data.get("subscriptionType") or "")
        provider_label = "Claude subscription" if auth_method == "claude.ai" else (
            "Anthropic Console" if auth_method == "console" else (auth_method or "Authenticated")
        )
        message_parts = [provider_label]
        if subscription_type:
            message_parts.append(subscription_type)
        if data.get("email"):
            message_parts.append(str(data.get("email")))
        return {
            "logged_in": True,
            "auth_method": auth_method,
            "subscription_type": subscription_type,
            "email": str(data.get("email") or ""),
            "org_id": str(data.get("orgId") or ""),
            "org_name": str(data.get("orgName") or ""),
            "provider_label": provider_label,
            "message": " · ".join(part for part in message_parts if part),
        }

    if proc.returncode != 0:
        lower = raw.lower()
        if any(token in lower for token in ("not logged", "not authenticated", "sign in", "login")):
            return {
                "logged_in": False,
                "auth_method": "",
                "subscription_type": "",
                "email": "",
                "org_id": "",
                "org_name": "",
                "provider_label": "Not signed in",
                "message": "Claude CLI is installed but not signed in.",
            }
        return {
            "logged_in": False,
            "auth_method": "",
            "subscription_type": "",
            "email": "",
            "org_id": "",
            "org_name": "",
            "provider_label": "Unavailable",
            "message": raw or "Unable to read Claude CLI auth status.",
        }

    return {
        "logged_in": False,
        "auth_method": "",
        "subscription_type": "",
        "email": "",
        "org_id": "",
        "org_name": "",
        "provider_label": "Unknown",
        "message": raw or "Unable to parse Claude CLI auth status.",
    }


def build_cli_runtime_snapshot(cli_path_override: str = "") -> StatusRecord:
    environments = _discover_cli_environments()
    binary = _find_cli(cli_path_override)
    selected_environment = _selected_environment(binary, environments)
    npm_binary = _find_npm_binary()
    version = _cli_version(binary)
    auth = _auth_status(binary)
    login_parts = [binary or "claude", "auth", "login", "--claudeai"]
    logout_parts = [binary or "claude", "auth", "logout"]
    status_parts = [binary or "claude", "auth", "status", "--json"]
    install_parts = _npm_install_parts(npm_binary or "npm", _CLAUDE_CODE_PACKAGE)

    return {
        "installed": bool(binary),
        "binary": binary,
        "binary_name": os.path.basename(binary) if binary else "claude",
        "version": version,
        "package_name": _CLAUDE_CODE_PACKAGE,
        "package_version": version.split(" ")[0] if version else "",
        "install_available": bool(npm_binary),
        "npm_binary": npm_binary,
        "selected_environment": selected_environment,
        "environments": environments,
        "manual_override_path": cli_path_override or "",
        "using_auto_discovery": bool(binary and not cli_path_override),
        "install_scope": "axon_local",
        "install_root": local_tool_env.install_scope_label(),
        "install_command": _command_preview(install_parts),
        "login_command": _command_preview(login_parts),
        "logout_command": _command_preview(logout_parts),
        "status_command": _command_preview(status_parts),
        "auth": auth,
    }


def install_claude_cli(cli_path_override: str = "") -> StatusRecord:
    npm_binary = _find_npm_binary()
    if not npm_binary:
        snapshot = build_cli_runtime_snapshot(cli_path_override)
        return {
            "status": "manual_required",
            "message": "npm is not available in Axon's environment. Install Node/npm first, then run the command below.",
            "command_preview": snapshot["install_command"],
            "cli_runtime": snapshot,
        }

    install_parts = _npm_install_parts(npm_binary, _CLAUDE_CODE_PACKAGE)
    proc = _run_command(install_parts, timeout=_INSTALL_TIMEOUT_SECONDS)
    snapshot = build_cli_runtime_snapshot(cli_path_override)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(output or "Claude CLI install failed.")
    return {
        "status": "completed",
        "message": f"Claude CLI installed into Axon's local toolchain at {snapshot['install_root']}.",
        "command_preview": snapshot["install_command"],
        "cli_runtime": snapshot,
        "output": output,
    }


def prepare_claude_cli_login(cli_path_override: str = "", *, mode: str = "claudeai", email: str = "") -> StatusRecord:
    snapshot = build_cli_runtime_snapshot(cli_path_override)
    if snapshot["auth"].get("logged_in"):
        return {
            "status": "completed",
            "message": "Claude CLI is already signed in.",
            "command_preview": snapshot["status_command"],
            "cli_runtime": snapshot,
        }
    if not snapshot.get("installed"):
        return {
            "status": "manual_required",
            "message": "Install Claude CLI before starting the login flow.",
            "command_preview": snapshot["install_command"],
            "cli_runtime": snapshot,
        }

    login_mode = "console" if str(mode or "").strip().lower() == "console" else "claudeai"
    binary = str(snapshot.get("binary") or "claude")
    parts: list[str] = [binary, "auth", "login", f"--{login_mode}"]
    if email:
        parts += ["--email", email.strip()]
    return {
        "status": "manual_required",
        "message": "Run the Claude CLI login flow locally to finish authentication. The command has been prepared for you.",
        "command_preview": _command_preview(parts),
        "cli_runtime": snapshot,
    }


def logout_claude_cli(cli_path_override: str = "") -> StatusRecord:
    snapshot = build_cli_runtime_snapshot(cli_path_override)
    if not snapshot.get("installed"):
        return {
            "status": "manual_required",
            "message": "Install Claude CLI before signing out.",
            "command_preview": snapshot.get("install_command", ""),
            "cli_runtime": snapshot,
        }
    if not snapshot.get("auth", {}).get("logged_in"):
        return {
            "status": "completed",
            "message": "Claude CLI is already signed out.",
            "command_preview": snapshot.get("status_command", ""),
            "cli_runtime": snapshot,
        }
    binary = str(snapshot.get("binary") or "claude")
    proc = _run_command([binary, "auth", "logout"], timeout=_STATUS_TIMEOUT_SECONDS)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(output or "Claude CLI sign out failed.")
    refreshed = build_cli_runtime_snapshot(cli_path_override)
    return {
        "status": "completed",
        "message": "Claude CLI signed out.",
        "command_preview": refreshed.get("status_command", ""),
        "cli_runtime": refreshed,
        "output": output,
    }
