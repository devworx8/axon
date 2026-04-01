"""Helpers for blocked tool results that the agent can repair automatically."""

from __future__ import annotations

import json
import shlex
from typing import Any, Optional


_REPAIRABLE_SHELL_TOOLS = {"shell_cmd", "shell_bg"}


def _rewrite_cd_wrapper(full_command: str, tool_args: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        parts = shlex.split(full_command)
    except ValueError:
        return None

    if len(parts) < 4 or parts[0] != "cd" or parts[2] != "&&":
        return None

    target_dir = parts[1].strip()
    command_tokens = parts[3:]
    if not target_dir or not command_tokens:
        return None

    rewritten = dict(tool_args)
    rewritten["cmd"] = shlex.join(command_tokens)
    rewritten["cwd"] = target_dir
    return rewritten


def blocked_tool_retry_prompt(tool_name: str, tool_args: dict[str, Any], result: str) -> Optional[str]:
    if (
        tool_name not in _REPAIRABLE_SHELL_TOOLS
        or not isinstance(result, str)
        or not result.startswith("BLOCKED_CMD:")
    ):
        return None

    try:
        _, command_name, full_command = result.split(":", 2)
    except ValueError:
        return None

    if command_name.strip() != "cd":
        return None

    rewritten_args = _rewrite_cd_wrapper(full_command, tool_args)
    if not rewritten_args:
        return None

    return (
        f"Tool result for {tool_name}:\n{result[:4000]}\n\n"
        "That command was blocked because shell tools do not allow `cd ... && ...` wrappers. "
        "Retry the same action now by moving the directory into the tool's `cwd` argument and "
        "keeping only the executable command in `cmd`.\n\n"
        f"Corrected call:\nACTION: {tool_name}\n"
        f"ARGS: {json.dumps(rewritten_args, ensure_ascii=True)}\n\n"
        "Emit exactly one corrected ACTION/ARGS pair now. "
        "Do not ask for approval and do not output ANSWER yet."
    )
