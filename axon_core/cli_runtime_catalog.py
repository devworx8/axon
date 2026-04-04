from __future__ import annotations

import glob
import os
import shutil

from axon_api.services import local_tool_env


DEFAULT_CLAUDE_CLI_PATHS = [
    str(local_tool_env.axon_binary_path("claude")),
    "/home/edp/.config/Claude/claude-code/2.1.63/claude",
    "/home/edp/.vscode/extensions/anthropic.claude-code-2.1.81-linux-x64/resources/native-binary/claude",
    "/usr/local/bin/claude",
    "/usr/bin/claude",
    "claude",
]

DEFAULT_CODEX_CLI_PATHS = [
    str(local_tool_env.axon_binary_path("codex")),
    "/usr/local/bin/codex",
    "/usr/bin/codex",
    "codex",
]

CLAUDE_CLI_MODEL_OPTIONS = [
    {"id": "", "label": "Claude default", "description": "Use the CLI default model alias."},
    {"id": "sonnet", "label": "Sonnet", "description": "Latest Sonnet alias."},
    {"id": "opus", "label": "Opus", "description": "Latest Opus alias."},
    {"id": "haiku", "label": "Haiku", "description": "Latest Haiku alias."},
    {"id": "claude-sonnet-4-6", "label": "claude-sonnet-4-6", "description": "Pinned Sonnet release."},
    {"id": "claude-opus-4-5", "label": "claude-opus-4-5", "description": "Pinned Opus release."},
    {"id": "claude-haiku-4-5", "label": "claude-haiku-4-5", "description": "Pinned Haiku release."},
]

CODEX_CLI_MODEL_OPTIONS = [
    {
        "id": "",
        "label": "Codex default",
        "description": "Use the Codex CLI default model. ChatGPT-backed Codex currently defaults to GPT-5.1-Codex-Max.",
    },
    {
        "id": "gpt-5.4",
        "label": "gpt-5.4",
        "description": "Verified working with this installed Codex CLI account.",
    },
    {
        "id": "gpt-5.1-codex-max",
        "label": "gpt-5.1-codex-max",
        "description": "Current default long-running Codex model supported by Codex CLI.",
    },
    {
        "id": "gpt-5.1-codex-mini",
        "label": "gpt-5.1-codex-mini",
        "description": "Smaller Codex model currently supported by Codex CLI.",
    },
]


def cli_runtime_family(path: str = "") -> str:
    candidate = os.path.basename(str(path or "")).strip().lower()
    if "codex" in candidate:
        return "codex"
    return "claude"


def runtime_label_for_cli_family(family: str) -> str:
    return "Codex CLI" if family == "codex" else "Claude CLI"


def cli_runtime_key(path: str = "") -> str:
    binary = os.path.realpath(str(path or "").strip()) if path else ""
    family = cli_runtime_family(binary)
    return f"{family}:{binary}" if binary else family


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_named_cli(binary_name: str) -> str:
    home = os.path.expanduser("~")
    axon_path = str(local_tool_env.axon_binary_path(binary_name))
    if binary_name == "codex":
        default_paths = DEFAULT_CODEX_CLI_PATHS
        local_patterns = [
            axon_path,
            f"{home}/.nvm/versions/node/*/bin/codex",
            f"{home}/.volta/bin/codex",
            f"{home}/.npm-global/bin/codex",
            f"{home}/.local/bin/codex",
            f"{home}/bin/codex",
        ]
        extension_patterns: list[str] = []
    else:
        default_paths = DEFAULT_CLAUDE_CLI_PATHS
        local_patterns = [
            axon_path,
            f"{home}/.nvm/versions/node/*/bin/claude",
            f"{home}/.volta/bin/claude",
            f"{home}/.npm-global/bin/claude",
            f"{home}/.local/bin/claude",
            f"{home}/bin/claude",
        ]
        extension_patterns = [
            f"{home}/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
            f"{home}/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude",
        ]

    if _is_executable(axon_path):
        return axon_path

    if binary_name == "claude":
        for pattern in extension_patterns:
            for match in sorted(glob.glob(pattern), reverse=True):
                if _is_executable(match):
                    return match

    for pattern in local_patterns:
        for match in sorted(glob.glob(pattern), reverse=True):
            if _is_executable(match):
                return match

    found = shutil.which(binary_name)
    if found:
        return found

    for path in default_paths:
        if path == binary_name:
            continue
        if _is_executable(path):
            return path
    return ""


def find_codex_cli(override_path: str = "") -> str:
    if override_path and _is_executable(override_path) and cli_runtime_family(override_path) == "codex":
        return override_path
    return find_named_cli("codex")


def find_cli(override_path: str = "") -> str:
    if override_path and _is_executable(override_path) and cli_runtime_family(override_path) == "claude":
        return override_path
    return find_named_cli("claude")


def resolve_selected_cli_binary(override_path: str = "") -> str:
    if override_path and _is_executable(override_path):
        return override_path
    return find_cli()


def available_cli_models(cli_path: str = "") -> list[dict[str, str]]:
    binary = resolve_selected_cli_binary(cli_path)
    options = CODEX_CLI_MODEL_OPTIONS if cli_runtime_family(binary) == "codex" else CLAUDE_CLI_MODEL_OPTIONS
    return [dict(item) for item in options]


def normalize_cli_model(cli_path: str = "", model: str = "") -> str:
    requested = str(model or "").strip()
    if not requested:
        return ""
    binary = resolve_selected_cli_binary(cli_path)
    if cli_runtime_family(binary) != "codex":
        return requested
    supported_ids = {str(item.get("id") or "").strip() for item in CODEX_CLI_MODEL_OPTIONS}
    return requested if requested in supported_ids else ""


def discover_cli_environments() -> list[dict[str, str]]:
    seen: set[str] = set()
    environments: list[dict[str, str]] = []

    def _add(path: str, source: str, family: str) -> None:
        real = os.path.realpath(path)
        if real in seen:
            return
        seen.add(real)
        runtime_name = runtime_label_for_cli_family(family)
        binary_name = "codex" if family == "codex" else "claude"
        if source == "vscode":
            for segment in path.split("/"):
                if segment.startswith("anthropic.claude-code-"):
                    version = (
                        segment.replace("anthropic.claude-code-", "")
                        .split("-linux")[0]
                        .split("-darwin")[0]
                        .split("-win")[0]
                    )
                    label = f"{runtime_name} (VS Code {version})"
                    break
            else:
                label = f"{runtime_name} (VS Code)"
        elif source == "PATH":
            label = f"{binary_name} (PATH)"
        elif source == "axon":
            label = f"{runtime_name} (Axon)"
        elif source == "local":
            if ".nvm/" in path:
                label = f"{binary_name} (nvm)"
            elif ".volta/" in path:
                label = f"{binary_name} (volta)"
            else:
                label = f"{binary_name} (local)"
        else:
            version = ""
            for segment in path.split("/"):
                if segment and segment[0].isdigit() and "." in segment:
                    version = segment
                    break
            label = f"{runtime_name} ({version})" if version else runtime_name
        environments.append(
            {
                "path": path,
                "label": label,
                "source": source,
                "family": family,
                "runtime_id": family,
                "binary_name": binary_name,
            }
        )

    def _discover_family(binary_name: str, family: str) -> None:
        home = os.path.expanduser("~")
        axon_path = str(local_tool_env.axon_binary_path(binary_name))
        default_paths = DEFAULT_CODEX_CLI_PATHS if family == "codex" else DEFAULT_CLAUDE_CLI_PATHS
        local_patterns = [
            axon_path,
            f"{home}/.nvm/versions/node/*/bin/{binary_name}",
            f"{home}/.volta/bin/{binary_name}",
            f"{home}/.npm-global/bin/{binary_name}",
            f"{home}/.local/bin/{binary_name}",
            f"{home}/bin/{binary_name}",
        ]
        extension_patterns: list[str] = []
        if family == "claude":
            extension_patterns = [
                f"{home}/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
                f"{home}/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude",
            ]

        for path in default_paths:
            if path == binary_name:
                continue
            if _is_executable(path):
                _add(path, "default", family)

        found = shutil.which(binary_name)
        if found:
            _add(found, "PATH", family)

        if _is_executable(axon_path):
            _add(axon_path, "axon", family)

        for pattern in local_patterns[1:]:
            for match in sorted(glob.glob(pattern), reverse=True):
                if _is_executable(match):
                    _add(match, "local", family)

        for pattern in extension_patterns:
            for match in sorted(glob.glob(pattern), reverse=True):
                if _is_executable(match):
                    _add(match, "vscode", family)

    _discover_family("claude", "claude")
    _discover_family("codex", "codex")
    return environments
