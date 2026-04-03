from __future__ import annotations

import os
import re
import shutil
from glob import glob
from typing import Any

from axon_api.services import claude_cli_runtime as _shared
from axon_api.services import local_tool_env

StatusRecord = dict[str, Any]

_PACKAGE_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_BINARY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PACKAGE_ALIASES = {
    "claude": ("@anthropic-ai/claude-code", "claude"),
    "claude-code": ("@anthropic-ai/claude-code", "claude"),
    "@anthropic-ai/claude-code": ("@anthropic-ai/claude-code", "claude"),
    "codex": ("@openai/codex", "codex"),
    "@openai/codex": ("@openai/codex", "codex"),
}


def _default_binary_name(package_name: str) -> str:
    return str(package_name or "").strip().rsplit("/", 1)[-1]


def _resolve_package_request(package_name: str, binary_name: str = "") -> tuple[str, str]:
    requested_package = str(package_name or "").strip()
    alias = _PACKAGE_ALIASES.get(requested_package.lower())
    normalized_package = alias[0] if alias else normalize_package_name(requested_package)
    default_binary = alias[1] if alias else _default_binary_name(normalized_package)
    normalized_binary = normalize_binary_name(binary_name or default_binary, package_name=normalized_package)
    return normalized_package, normalized_binary


def normalize_package_name(value: str) -> str:
    package_name = str(value or "").strip()
    if not package_name or not _PACKAGE_RE.fullmatch(package_name):
        raise ValueError("Package name must be a valid npm package name.")
    return package_name


def normalize_binary_name(value: str, *, package_name: str = "") -> str:
    binary_name = str(value or "").strip() or _default_binary_name(package_name)
    if not binary_name or not _BINARY_RE.fullmatch(binary_name):
        raise ValueError("Binary name must contain only letters, numbers, dots, dashes, or underscores.")
    return binary_name


def _candidate_patterns(binary_name: str) -> list[str]:
    home = os.path.expanduser("~")
    return [
        str(local_tool_env.axon_binary_path(binary_name)),
        f"{home}/.nvm/versions/node/*/bin/{binary_name}",
        f"{home}/.volta/bin/{binary_name}",
        f"{home}/.npm-global/bin/{binary_name}",
        f"{home}/.local/bin/{binary_name}",
        f"{home}/bin/{binary_name}",
        f"/usr/local/bin/{binary_name}",
        f"/usr/bin/{binary_name}",
    ]


def _find_installed_binary(binary_name: str) -> str:
    found = shutil.which(binary_name)
    if found:
        return found
    for pattern in _candidate_patterns(binary_name):
        for match in sorted(glob(pattern), reverse=True):
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return match
    return ""


def _binary_version(binary: str) -> str:
    if not binary:
        return ""
    try:
        proc = _shared._run_command([binary, "--version"], timeout=_shared._VERSION_TIMEOUT_SECONDS)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0].strip()


def build_extension_snapshot(package_name: str, binary_name: str = "") -> StatusRecord:
    normalized_package, normalized_binary = _resolve_package_request(package_name, binary_name)
    npm_binary = _shared._find_npm_binary()
    binary = _find_installed_binary(normalized_binary)
    install_parts = _shared._npm_install_parts(npm_binary or "npm", normalized_package)
    return {
        "package_name": normalized_package,
        "binary_name": normalized_binary,
        "binary": binary,
        "installed": bool(binary),
        "version": _binary_version(binary),
        "install_available": bool(npm_binary),
        "npm_binary": npm_binary,
        "install_scope": "axon_local",
        "install_root": local_tool_env.install_scope_label(),
        "install_command": _shared._command_preview(install_parts),
    }


def install_npm_cli_extension(package_name: str, binary_name: str = "") -> StatusRecord:
    snapshot = build_extension_snapshot(package_name, binary_name)
    npm_binary = str(snapshot.get("npm_binary") or "")
    if not npm_binary:
        return {
            "status": "manual_required",
            "message": "npm is not available in Axon's environment. Install Node/npm first, then run the command below.",
            "command_preview": snapshot["install_command"],
            "extension": snapshot,
        }

    proc = _shared._run_command(
        _shared._npm_install_parts(npm_binary, str(snapshot["package_name"])),
        timeout=_shared._INSTALL_TIMEOUT_SECONDS,
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(output or f"npm install failed for {snapshot['package_name']}.")

    refreshed = build_extension_snapshot(str(snapshot["package_name"]), str(snapshot["binary_name"]))
    message = (
        f"{refreshed['package_name']} installed into Axon's local toolchain at {refreshed['install_root']}. "
        f"Binary detected at {refreshed['binary']}."
        if refreshed.get("installed")
        else (
            f"{refreshed['package_name']} installed into Axon's local toolchain at {refreshed['install_root']}, "
            f"but Axon could not detect `{refreshed['binary_name']}` yet."
        )
    )
    return {
        "status": "completed",
        "message": message,
        "command_preview": refreshed["install_command"],
        "extension": refreshed,
        "output": output,
    }
