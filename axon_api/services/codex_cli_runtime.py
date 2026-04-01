from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, cast

import brain
from axon_api.services import claude_cli_runtime as _shared

_CODEX_PACKAGE = "@openai/codex"

EnvRecord = dict[str, str]
StatusRecord = dict[str, Any]

_find_codex_cli = cast(Callable[[str], str], getattr(brain, "_find_codex_cli"))
_legacy_discover_cli_environments = cast(
    Callable[[], list[dict[object, object]]],
    getattr(brain, "discover_cli_environments"),
)


def _discover_codex_environments() -> list[EnvRecord]:
    environments = _legacy_discover_cli_environments()
    normalized: list[EnvRecord] = []
    for env in environments:
        item = {str(key): str(value) for key, value in dict(env).items()}
        if item.get("family") != "codex":
            continue
        normalized.append(item)
    return normalized


def _selected_environment(binary: str, environments: list[EnvRecord]) -> EnvRecord:
    if not binary:
        return {}
    binary_real = os.path.realpath(binary)
    for env in environments:
        path = str(env.get("path") or "")
        if path and os.path.realpath(path) == binary_real:
            return env
    return {}


def _codex_version(binary: str) -> str:
    if not binary:
        return ""
    try:
        proc = _shared._run_command([binary, "--version"], timeout=_shared._VERSION_TIMEOUT_SECONDS)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0].strip()


def _auth_status(binary: str) -> StatusRecord:
    if not binary:
        return {
            "logged_in": False,
            "auth_method": "",
            "provider_label": "Not installed",
            "message": "Install Codex CLI to sign in.",
        }

    try:
        proc = _shared._run_command([binary, "login", "status"], timeout=_shared._STATUS_TIMEOUT_SECONDS)
    except Exception as exc:
        return {
            "logged_in": False,
            "auth_method": "",
            "provider_label": "Unavailable",
            "message": str(exc),
        }

    raw = (proc.stdout or proc.stderr or "").strip()
    lower = raw.lower()
    if proc.returncode != 0:
        if any(token in lower for token in ("not logged", "logged out", "login required")):
            return {
                "logged_in": False,
                "auth_method": "",
                "provider_label": "Not signed in",
                "message": raw or "Codex CLI is installed but not signed in.",
            }
        return {
            "logged_in": False,
            "auth_method": "",
            "provider_label": "Unavailable",
            "message": raw or "Unable to read Codex CLI login status.",
        }

    logged_in = "logged in" in lower
    provider_label = "ChatGPT" if "chatgpt" in lower else ("API key" if "api key" in lower else ("Authenticated" if logged_in else "Unknown"))
    return {
        "logged_in": logged_in,
        "auth_method": "chatgpt" if "chatgpt" in lower else ("api_key" if "api key" in lower else ""),
        "provider_label": provider_label,
        "message": raw or provider_label,
    }


def build_codex_runtime_snapshot(codex_path_override: str = "") -> StatusRecord:
    environments = _discover_codex_environments()
    binary = _find_codex_cli(codex_path_override)
    selected_environment = _selected_environment(binary, environments)
    npm_binary = _shared._find_npm_binary()
    version = _codex_version(binary)
    auth = _auth_status(binary)
    install_parts = [npm_binary or "npm", "install", "-g", _CODEX_PACKAGE]
    login_parts = [binary or "codex", "login"]
    status_parts = [binary or "codex", "login", "status"]

    return {
        "installed": bool(binary),
        "binary": binary,
        "binary_name": os.path.basename(binary) if binary else "codex",
        "version": version,
        "package_name": _CODEX_PACKAGE,
        "package_version": version.split(" ")[-1] if version else "",
        "install_available": bool(npm_binary),
        "npm_binary": npm_binary,
        "selected_environment": selected_environment,
        "environments": environments,
        "manual_override_path": codex_path_override or "",
        "using_auto_discovery": bool(binary and not codex_path_override),
        "install_command": _shared._command_preview(install_parts),
        "login_command": _shared._command_preview(login_parts),
        "status_command": _shared._command_preview(status_parts),
        "auth": auth,
    }


def install_codex_cli(codex_path_override: str = "") -> StatusRecord:
    npm_binary = _shared._find_npm_binary()
    if not npm_binary:
        snapshot = build_codex_runtime_snapshot(codex_path_override)
        return {
            "status": "manual_required",
            "message": "npm is not available in Axon's environment. Install Node/npm first, then run the command below.",
            "command_preview": snapshot["install_command"],
            "cli_runtime": snapshot,
        }

    proc = _shared._run_command([npm_binary, "install", "-g", _CODEX_PACKAGE], timeout=_shared._INSTALL_TIMEOUT_SECONDS)
    snapshot = build_codex_runtime_snapshot(codex_path_override)
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(output or "Codex CLI install failed.")
    return {
        "status": "completed",
        "message": "Codex CLI installed and ready for discovery.",
        "command_preview": snapshot["install_command"],
        "cli_runtime": snapshot,
        "output": output,
    }


def prepare_codex_cli_login(codex_path_override: str = "") -> StatusRecord:
    snapshot = build_codex_runtime_snapshot(codex_path_override)
    if snapshot["auth"].get("logged_in"):
        return {
            "status": "completed",
            "message": "Codex CLI is already signed in.",
            "command_preview": snapshot["status_command"],
            "cli_runtime": snapshot,
        }
    if not snapshot.get("installed"):
        return {
            "status": "manual_required",
            "message": "Install Codex CLI before starting the login flow.",
            "command_preview": snapshot["install_command"],
            "cli_runtime": snapshot,
        }

    binary = str(snapshot.get("binary") or "codex")
    parts = [binary, "login"]
    return {
        "status": "manual_required",
        "message": "Run the Codex CLI login flow locally to finish authentication. The command has been prepared for you.",
        "command_preview": _shared._command_preview(parts),
        "cli_runtime": snapshot,
    }
