"""Terminal command policy and runtime helpers extracted from server.py."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


SAFE_TERMINAL_PREFIXES = (
    "pwd",
    "ls",
    "tree",
    "find",
    "rg",
    "cat",
    "head",
    "tail",
    "grep",
    "wc",
    "env",
    "printenv",
    "git status",
    "git branch",
    "git diff",
    "git log",
    "git show",
    "python --version",
    "python3 --version",
    "node -v",
    "npm -v",
)

BLOCKED_TERMINAL_PATTERNS = (
    "rm -rf",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    ":(){",
    "chmod -r 777 /",
    " apt install ",
    " apt-get install ",
    " apk add ",
    " brew install ",
    " dnf install ",
    " pacman -s ",
    " snap install ",
    " yum install ",
    " zypper install ",
)


def terminal_mode_value(raw: str | None, fallback: str = "read_only") -> str:
    value = str(raw or fallback).strip().lower()
    return value if value in {"read_only", "approval_required", "simulation"} else fallback


def command_is_blocked(command: str) -> bool:
    lowered = f" {str(command or '').strip().lower()} "
    return any(pattern in lowered for pattern in BLOCKED_TERMINAL_PATTERNS)


def command_is_read_only(command: str) -> bool:
    lowered = str(command or "").strip().lower()
    if not lowered:
        return False
    return any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in SAFE_TERMINAL_PREFIXES)


def serialize_terminal_session(
    row,
    *,
    running: bool = False,
    recent_events: Optional[list[dict]] = None,
) -> dict:
    item = dict(row)
    item["running"] = bool(running)
    item["recent_events"] = recent_events or []
    return item


def serialize_terminal_event(row) -> dict:
    return dict(row)


async def resolve_terminal_cwd(
    conn,
    session_row,
    requested_cwd: Optional[str] = None,
    *,
    safe_path_fn: Callable[[str], Path],
    db_module: Any,
    home_path: Path,
) -> Path:
    if requested_cwd:
        return safe_path_fn(requested_cwd)
    row = dict(session_row) if session_row is not None else {}
    session_cwd = str(row.get("cwd") or "").strip()
    if session_cwd:
        return safe_path_fn(session_cwd)
    workspace_id = row.get("workspace_id")
    if workspace_id:
        proj = await db_module.get_project(conn, int(workspace_id))
        if proj and proj.get("path"):
            return safe_path_fn(proj["path"])
    return home_path


def terminal_timeout_seconds(settings: dict, requested: Optional[int]) -> int:
    base = settings.get("terminal_command_timeout_seconds") or "25"
    try:
        default = int(str(base).strip())
    except Exception:
        default = 25
    if requested is None:
        return max(5, min(300, default))
    return max(5, min(300, int(requested)))


async def terminal_capture(
    session_id: int,
    process,
    command: str,
    timeout_seconds: int,
    *,
    terminal_processes: dict[int, dict],
    db_module: Any,
    set_live_operator: Callable[..., None],
    time_module,
    asyncio_module,
) -> None:
    timed_out = False
    deadline = time_module.monotonic() + timeout_seconds
    try:
        while True:
            if time_module.monotonic() >= deadline and process.returncode is None:
                timed_out = True
                process.terminate()
                await asyncio_module.sleep(0.5)
                if process.returncode is None:
                    process.kill()
            if process.stdout is None:
                break
            try:
                line = await asyncio_module.wait_for(process.stdout.readline(), timeout=0.8)
            except asyncio_module.TimeoutError:
                if process.returncode is not None:
                    break
                continue
            if not line:
                if process.returncode is not None:
                    break
                continue
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            async with db_module.get_db() as conn:
                await db_module.add_terminal_event(
                    conn,
                    session_id=session_id,
                    event_type="output",
                    content=text[:4000],
                )
            set_live_operator(
                active=True,
                mode="terminal",
                phase="execute",
                title="Streaming terminal output",
                detail=text[:180],
                summary=f"Running: {command}",
                preserve_started=True,
            )

        return_code = await process.wait()
        status = "completed" if return_code == 0 and not timed_out else "failed"
        final_message = "Command completed successfully." if status == "completed" else (
            "Command timed out and was stopped safely." if timed_out else "Command finished with an error."
        )
        async with db_module.get_db() as conn:
            await db_module.update_terminal_session(
                conn,
                session_id,
                status=status,
                pending_command="",
                active_command="",
                pid=0,
            )
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content=final_message,
                exit_code=return_code,
            )
        set_live_operator(
            active=False,
            mode="terminal",
            phase="verify" if status == "completed" else "recover",
            title="Terminal command finished",
            detail=final_message,
            summary=f"{command} · exit {return_code}",
            preserve_started=False,
        )
    except Exception as exc:
        async with db_module.get_db() as conn:
            await db_module.update_terminal_session(
                conn,
                session_id,
                status="failed",
                pending_command="",
                active_command="",
                pid=0,
            )
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="error",
                content=str(exc),
            )
        set_live_operator(
            active=False,
            mode="terminal",
            phase="recover",
            title="Terminal command failed",
            detail=str(exc),
            summary=command,
        )
    finally:
        terminal_processes.pop(session_id, None)


async def start_terminal_command(
    *,
    session_id: int,
    command: str,
    cwd: Path,
    timeout_seconds: int,
    terminal_processes: dict[int, dict],
    db_module: Any,
    set_live_operator: Callable[..., None],
    local_tool_env_module,
    os_environ,
    now_iso: Callable[[], str],
    terminal_capture_fn: Callable[[int, Any, str, int], Awaitable[None]],
    asyncio_module,
) -> dict[str, Any]:
    process = await asyncio_module.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio_module.subprocess.PIPE,
        stderr=asyncio_module.subprocess.STDOUT,
        env=local_tool_env_module.build_tool_env(dict(os_environ)),
    )
    terminal_processes[session_id] = {
        "process": process,
        "command": command,
        "cwd": str(cwd),
        "started_at": now_iso(),
    }
    async with db_module.get_db() as conn:
        await db_module.update_terminal_session(
            conn,
            session_id,
            status="running",
            active_command=command,
            pending_command="",
            cwd=str(cwd),
            pid=process.pid or 0,
        )
        await db_module.add_terminal_event(
            conn,
            session_id=session_id,
            event_type="command",
            content=f"$ {command}",
        )
    set_live_operator(
        active=True,
        mode="terminal",
        phase="execute",
        title="Running terminal command",
        detail=f"{command} · {cwd}",
        summary=f"Running: {command}",
    )
    asyncio_module.create_task(terminal_capture_fn(session_id, process, command, timeout_seconds))
    return {
        "status": "running",
        "command": command,
        "cwd": str(cwd),
        "pid": process.pid or 0,
        "timeout_seconds": timeout_seconds,
    }


async def terminal_execute_request(
    session_id: int,
    body,
    *,
    approved: bool = False,
    db_module: Any,
    terminal_processes: dict[int, dict],
    command_is_blocked_fn: Callable[[str], bool],
    terminal_mode_value_fn: Callable[[str | None, str], str],
    resolve_terminal_cwd_fn: Callable[..., Awaitable[Path]],
    terminal_timeout_seconds_fn: Callable[[dict, Optional[int]], int],
    command_is_read_only_fn: Callable[[str], bool],
    start_terminal_command_fn: Callable[..., Awaitable[dict[str, Any]]],
    http_exception_cls,
) -> dict[str, Any]:
    command = (body.command or "").strip()
    if not command:
        raise http_exception_cls(400, "Command is required")
    if command_is_blocked_fn(command):
        raise http_exception_cls(400, "That command is blocked in Axon terminal mode.")

    async with db_module.get_db() as conn:
        settings = await db_module.get_all_settings(conn)
        session_row = await db_module.get_terminal_session(conn, session_id)
        if not session_row:
            raise http_exception_cls(404, "Terminal session not found")
        if session_row["status"] == "running" and session_id in terminal_processes:
            raise http_exception_cls(409, "A command is already running in this session.")

        mode = terminal_mode_value_fn(body.mode, session_row["mode"] or settings.get("terminal_default_mode", "read_only"))
        cwd = await resolve_terminal_cwd_fn(conn, session_row, body.cwd)
        timeout_seconds = terminal_timeout_seconds_fn(settings, body.timeout_seconds)

        if command_is_blocked_fn(command):
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content=f"Blocked dangerous command: {command}",
            )
            return {
                "status": "blocked",
                "mode": mode,
                "command": command,
                "cwd": str(cwd),
                "message": "This command matches a blocked pattern and cannot be executed.",
            }

        if mode == "simulation":
            await db_module.update_terminal_session(
                conn,
                session_id,
                mode=mode,
                cwd=str(cwd),
                status="idle",
                pending_command="",
            )
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content=f"Simulation only: {command}",
            )
            return {
                "status": "simulation",
                "mode": mode,
                "command": command,
                "cwd": str(cwd),
                "message": "Simulation mode is on. Axon planned the command but did not run it.",
            }

        if mode == "read_only" and not command_is_read_only_fn(command):
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="approval",
                content=f"Read-only mode blocked: {command}",
            )
            return {
                "status": "blocked",
                "mode": mode,
                "command": command,
                "cwd": str(cwd),
                "message": "Read-only mode only allows inspection commands like ls, pwd, rg, cat, and git status.",
            }

        if mode == "approval_required" and not approved:
            await db_module.update_terminal_session(
                conn,
                session_id,
                mode=mode,
                cwd=str(cwd),
                status="pending_approval",
                pending_command=command,
            )
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="approval",
                content=f"Approval requested for: {command}",
            )
            return {
                "status": "approval_required",
                "mode": mode,
                "command": command,
                "cwd": str(cwd),
                "message": "Approval is required before Axon runs this command.",
            }

        await db_module.update_terminal_session(conn, session_id, mode=mode, cwd=str(cwd), status="idle")
    return await start_terminal_command_fn(
        session_id=session_id,
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )
