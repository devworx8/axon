from __future__ import annotations


def cli_session_persistence_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_cli_command(
    binary: str,
    *,
    model: str = "",
    stream_json: bool = False,
    allow_session_persistence: bool = False,
) -> list[str]:
    command = [binary]
    if allow_session_persistence:
        command.append("-c")
    command.append("-p")
    if stream_json:
        command.extend([
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ])
    else:
        command.extend(["--output-format", "json"])
    command.extend(["--tools", ""])
    if not allow_session_persistence:
        command.append("--no-session-persistence")
    if model:
        command.extend(["--model", model])
    return command


def build_codex_exec_command(
    binary: str,
    *,
    prompt: str,
    model: str = "",
    cwd: str = "",
    sandbox_mode: str = "read-only",
) -> list[str]:
    command = [binary, "exec", "--json"]
    if cwd:
        command.extend(["-C", cwd, "--skip-git-repo-check"])
    command.extend([
        "--sandbox", sandbox_mode or "read-only",
        "--ephemeral",
    ])
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return command
