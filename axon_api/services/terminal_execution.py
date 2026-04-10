from __future__ import annotations

import asyncio
import os
import time as _time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


async def terminal_capture(
    *,
    session_id: int,
    process,
    command: str,
    timeout_seconds: int,
    terminal_processes: dict[int, dict[str, Any]],
    db_module,
    set_live_operator: Callable[..., None],
    now_iso: Callable[[], str],
) -> None:
    info = terminal_processes.get(session_id, {})
    timed_out = False
    deadline = _time.monotonic() + timeout_seconds
    try:
        while True:
            if _time.monotonic() >= deadline and process.returncode is None:
                timed_out = True
                process.terminate()
                await asyncio.sleep(0.5)
                if process.returncode is None:
                    process.kill()
            if process.stdout is None:
                break
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=0.8)
            except asyncio.TimeoutError:
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
    require_pty: bool,
    dispatch_pty_fn: Callable[..., Awaitable[Optional[dict[str, Any]]]],
    pty_sessions: dict[str, Any],
    terminal_processes: dict[int, dict[str, Any]],
    db_module,
    set_live_operator: Callable[..., None],
    now_iso: Callable[[], str],
    spawn_subprocess_fn: Callable[..., Awaitable[Any]] = asyncio.create_subprocess_shell,
) -> dict[str, Any]:
    pty_result = await dispatch_pty_fn(
        session_id=session_id,
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        pty_sessions=pty_sessions,
        terminal_processes=terminal_processes,
        db_module=db_module,
        set_live_operator=set_live_operator,
        now_iso=now_iso,
    )
    if pty_result is not None:
        return pty_result
    if require_pty:
        async with db_module.get_db() as conn:
            await db_module.update_terminal_session(
                conn,
                session_id,
                status="idle",
                pending_command=command,
                active_command="",
                pid=0,
            )
            await db_module.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content="Interactive shell required before running this command.",
            )
        return {
            "status": "interactive_required",
            "command": command,
            "cwd": str(cwd),
            "message": "Open the interactive terminal so Axon can run this command live.",
        }

    process = await spawn_subprocess_fn(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
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
    asyncio.create_task(
        terminal_capture(
            session_id=session_id,
            process=process,
            command=command,
            timeout_seconds=timeout_seconds,
            terminal_processes=terminal_processes,
            db_module=db_module,
            set_live_operator=set_live_operator,
            now_iso=now_iso,
        )
    )
    return {
        "status": "running",
        "command": command,
        "cwd": str(cwd),
        "pid": process.pid or 0,
        "timeout_seconds": timeout_seconds,
    }


def build_terminal_execute_request(
    *,
    db_module,
    terminal_processes: dict[int, dict[str, Any]],
    http_exception_cls,
    resolve_terminal_cwd: Callable[..., Awaitable[Path]],
    terminal_timeout_seconds: Callable[[dict, Optional[int]], int],
    terminal_mode_value: Callable[[Optional[str], str], str],
    command_is_blocked: Callable[[str], bool],
    command_is_read_only: Callable[[str], bool],
    start_terminal_command_fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[[int, Any], Awaitable[dict[str, Any]]]:
    async def _terminal_execute_request(session_id: int, body: Any, *, approved: bool = False):
        command = (body.command or "").strip()
        if not command:
            raise http_exception_cls(400, "Command is required")
        if command_is_blocked(command):
            raise http_exception_cls(400, "That command is blocked in Axon terminal mode.")

        async with db_module.get_db() as conn:
            settings = await db_module.get_all_settings(conn)
            session_row = await db_module.get_terminal_session(conn, session_id)
            if not session_row:
                raise http_exception_cls(404, "Terminal session not found")
            if session_row["status"] == "running" and session_id in terminal_processes:
                raise http_exception_cls(409, "A command is already running in this session.")

            mode = terminal_mode_value(body.mode, session_row["mode"] or settings.get("terminal_default_mode", "read_only"))
            cwd = await resolve_terminal_cwd(conn, session_row, body.cwd)
            timeout_seconds = terminal_timeout_seconds(settings, body.timeout_seconds)

            if mode == "simulation":
                await db_module.update_terminal_session(conn, session_id, mode=mode, cwd=str(cwd), status="idle", pending_command="")
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

            if mode == "read_only" and not command_is_read_only(command):
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
            require_pty=bool(getattr(body, "require_pty", False)),
        )

    return _terminal_execute_request
