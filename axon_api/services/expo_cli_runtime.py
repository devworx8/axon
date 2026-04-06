"""Expo / EAS CLI resolution, probing, and execution helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExpoControlError(Exception):
    def __init__(
        self,
        summary: str,
        *,
        outcome: str = "blocked",
        result_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.outcome = outcome
        self.result_payload = result_payload or {}


@dataclass(slots=True)
class ExpoCliRuntime:
    available: bool
    source: str
    command: list[str]
    command_preview: str
    summary: str


def _coerce_json(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    for line in reversed([line.strip() for line in raw.splitlines() if line.strip()]):
        if not line.startswith("{") and not line.startswith("["):
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def parse_whoami_profile(stdout: str) -> dict[str, Any]:
    raw = str(stdout or "").strip()
    lines = [line.strip() for line in raw.splitlines()]
    username = lines[0] if lines else ""
    email = ""
    accounts: list[dict[str, str]] = []
    in_accounts = False
    for line in lines[1:]:
        if not line:
            continue
        if line.lower().startswith("accounts:"):
            in_accounts = True
            continue
        if in_accounts and line.startswith("•"):
            item = line.lstrip("•").strip()
            name = item
            role = ""
            if " (Role:" in item and item.endswith(")"):
                name, _, tail = item.partition(" (Role:")
                role = tail[:-1].strip()
            accounts.append({"name": name.strip(), "role": role})
            continue
        if "@" in line and not email:
            email = line
    return {
        "raw": raw,
        "username": username,
        "email": email,
        "accounts": accounts,
        "account_names": [str(item.get("name") or "").strip() for item in accounts if str(item.get("name") or "").strip()],
    }


def whoami_has_project_access(profile: dict[str, Any] | None, *, required_owner: str) -> bool:
    if not profile:
        return True
    owner = str(required_owner or "").strip()
    if not owner:
        return True
    account_names = {str(name or "").strip() for name in profile.get("account_names") or [] if str(name or "").strip()}
    username = str(profile.get("username") or "").strip()
    return owner in account_names or owner == username


def sanitized_command_preview(command: list[str]) -> str:
    return " ".join(command)


def resolve_expo_cli_runtime(project_root: Path) -> ExpoCliRuntime:
    local_name = "eas.cmd" if os.name == "nt" else "eas"
    local_binary = project_root / "node_modules" / ".bin" / local_name
    if local_binary.exists():
        command = [str(local_binary)]
        return ExpoCliRuntime(
            available=True,
            source="project_local",
            command=command,
            command_preview=sanitized_command_preview(command),
            summary="Project-local EAS CLI is available.",
        )

    global_eas = shutil.which("eas")
    if global_eas:
        command = [global_eas]
        return ExpoCliRuntime(
            available=True,
            source="global_path",
            command=command,
            command_preview=sanitized_command_preview(command),
            summary="Global EAS CLI is available on PATH.",
        )

    npx = shutil.which("npx")
    if npx:
        command = [npx, "--yes", "eas-cli"]
        return ExpoCliRuntime(
            available=True,
            source="npx",
            command=command,
            command_preview=sanitized_command_preview(command),
            summary="npx can invoke eas-cli for this project.",
        )

    return ExpoCliRuntime(
        available=False,
        source="missing",
        command=[],
        command_preview="",
        summary="Axon could not find a project-local EAS CLI, a global eas binary, or npx.",
    )


def run_eas_cli(
    *,
    project_root: Path,
    token: str = "",
    command: list[str],
    timeout: int = 600,
    expect_json: bool = True,
) -> dict[str, Any]:
    runtime = resolve_expo_cli_runtime(project_root)
    if not runtime.available:
        raise ExpoControlError(
            runtime.summary,
            outcome="expo_cli_missing",
            result_payload={
                "command_preview": runtime.command_preview,
                "cli_source": runtime.source,
                "project_root": str(project_root),
            },
        )

    full_command = [*runtime.command, *command]
    env = dict(os.environ)
    if token:
        env["EXPO_TOKEN"] = token
    else:
        env.pop("EXPO_TOKEN", None)
    env["CI"] = env.get("CI") or "1"
    try:
        proc = subprocess.run(
            full_command,
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExpoControlError(
            "Expo / EAS CLI is not available in Axon's runtime.",
            outcome="expo_cli_missing",
            result_payload={
                "command_preview": sanitized_command_preview(full_command),
                "cli_source": runtime.source,
                "project_root": str(project_root),
            },
        ) from exc

    stdout = str(proc.stdout or "")
    stderr = str(proc.stderr or "")
    if proc.returncode != 0:
        lower = f"{stdout}\n{stderr}".lower()
        if "not logged in" in lower or "authentication" in lower or "unauthorized" in lower:
            outcome = "expo_auth_failed"
        elif (
            "could not determine executable to run" in lower
            or "command not found" in lower
            or "no such file or directory" in lower
        ):
            outcome = "expo_cli_missing"
        else:
            outcome = "expo_cli_failed"
        raise ExpoControlError(
            "Expo / EAS CLI could not complete the requested action.",
            outcome=outcome,
            result_payload={
                "returncode": proc.returncode,
                "stdout": stdout[-2000:],
                "stderr": stderr[-2000:],
                "command_preview": sanitized_command_preview(full_command),
                "cli_source": runtime.source,
            },
        )

    parsed = _coerce_json(stdout) if expect_json else None
    return {
        "command_preview": sanitized_command_preview(full_command),
        "stdout": stdout[-4000:],
        "stderr": stderr[-2000:],
        "parsed": parsed,
        "cli_source": runtime.source,
    }
