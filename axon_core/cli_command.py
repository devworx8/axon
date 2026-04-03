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
    approval_mode: str = "on-request",
) -> list[str]:
    command = [binary, "exec", "--json"]
    if cwd:
        command.extend(["-C", cwd, "--skip-git-repo-check"])
    normalized_sandbox = sandbox_mode or "read-only"
    normalized_approval = str(approval_mode or "").strip().lower()
    if normalized_sandbox == "danger-full-access" and normalized_approval in {"never", "full-access", "bypass"}:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    elif normalized_approval == "on-request" and normalized_sandbox == "workspace-write":
        # Newer Codex CLI builds expose this mode via --full-auto instead of the old -a flag.
        command.append("--full-auto")
    else:
        command.extend(["--sandbox", normalized_sandbox])
    command.append("--ephemeral")
    if model:
        command.extend(["--model", model])
        if "codex-mini" in str(model).strip().lower():
            # Some local Codex configs pin xhigh reasoning effort globally, but
            # codex-mini currently only supports low/medium/high. Override only
            # for the mini fallback model so quick-mode requests stay usable.
            command.extend(["-c", 'model_reasoning_effort="medium"'])
    command.append(prompt)
    return command
