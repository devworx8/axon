"""Helpers for routing terminal commands through an attached PTY shell."""
from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


AXON_OSC_PREFIX = "\x1b]9999;AXON_"
AXON_OSC_SUFFIX = "\x07"
_AXON_OSC_RE = re.compile(r"\x1b]9999;AXON_(CMD_START|CMD_DONE):([^:\x07]+)(?::(-?\d+))?\x07")


def session_numeric_id(session_key: Any) -> int:
    match = re.match(r"^(\d+)", str(session_key or ""))
    return int(match.group(1)) if match else 0


def find_attached_pty_session(pty_sessions: dict[Any, Any], session_id: int):
    for key, entry in list((pty_sessions or {}).items()):
        if session_numeric_id(key) != int(session_id or 0):
            continue
        pty_proc = entry.get("pty") or entry.get("proc")
        if not pty_proc:
            continue
        try:
            alive = bool(entry.get("alive")) and bool(pty_proc.isalive())
        except Exception:
            alive = False
        if alive:
            return key, entry
    return None, None


def build_pty_command_payload(command: str, cwd: Path, marker: str) -> str:
    start = f"\\033]9999;AXON_CMD_START:{marker}\\007"
    done = f"\\033]9999;AXON_CMD_DONE:{marker}:"
    run_segment = f"cd {shlex.quote(str(cwd))} >/dev/null 2>&1 && {{ {command}; }}"
    return (
        f"printf '{start}'; "
        f"{run_segment}; "
        "__axon_exit=$?; "
        f"printf '{done}'\"$__axon_exit\"'\\007'; "
        "stty echo\n"
    )


def _write_pty(pty_proc: Any, payload: str) -> None:
    pty_proc.write(payload.encode("utf-8", errors="ignore"))


def ingest_pty_output(entry: dict[str, Any], text: str):
    source = f"{entry.get('osc_buffer', '')}{text}"
    visible_parts: list[str] = []
    events: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(source):
        match = _AXON_OSC_RE.search(source, cursor)
        if not match:
            tail = source[cursor:]
            partial_start = tail.find(AXON_OSC_PREFIX)
            if partial_start >= 0:
                visible_parts.append(tail[:partial_start])
                entry["osc_buffer"] = tail[partial_start:]
            else:
                visible_parts.append(tail)
                entry["osc_buffer"] = ""
            break

        visible_parts.append(source[cursor:match.start()])
        kind, marker, exit_code = match.groups()
        events.append(
            {
                "type": "done" if kind == "CMD_DONE" else "start",
                "marker": marker,
                "exit_code": int(exit_code) if exit_code is not None else None,
            }
        )
        cursor = match.end()
    else:
        entry["osc_buffer"] = ""

    visible_text = "".join(visible_parts)
    buffered = f"{entry.get('line_buffer', '')}{visible_text}"
    lines: list[str] = []
    while "\n" in buffered:
        raw_line, buffered = buffered.split("\n", 1)
        line = raw_line.rstrip("\r")
        if line.strip():
            lines.append(line)
    entry["line_buffer"] = buffered
    return visible_text, lines, events


async def append_tracked_pty_output(
    session_id: int,
    line: str,
    *,
    terminal_processes: dict[int, dict],
    db_module: Any,
    set_live_operator,
):
    active = terminal_processes.get(session_id)
    if not active or active.get("kind") != "pty":
        return
    text = str(line or "").strip()
    if not text:
        return
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
        summary=f"Running: {active.get('command', '')}",
        preserve_started=True,
    )


async def finalize_tracked_pty_command(
    session_id: int,
    *,
    terminal_processes: dict[int, dict],
    pty_sessions: dict[Any, Any],
    db_module: Any,
    set_live_operator,
    exit_code: Optional[int] = None,
    timed_out: bool = False,
    stopped: bool = False,
):
    active = terminal_processes.get(session_id)
    if not active or active.get("kind") != "pty":
        return False

    timeout_task = active.get("timeout_task")
    if timeout_task:
        timeout_task.cancel()

    marker = str(active.get("marker") or "").strip()
    entry_key = active.get("pty_entry_key")
    if entry_key in pty_sessions:
        pty_sessions[entry_key].get("tracked_commands", {}).pop(marker, None)

    command = str(active.get("command") or "").strip()
    if stopped:
        status = "stopped"
        message = "Command stopped by the user."
        phase = "recover"
        title = "Terminal command stopped"
        summary = command
    elif timed_out:
        status = "failed"
        message = "Command timed out and was stopped safely."
        phase = "recover"
        title = "Terminal command finished"
        summary = f"{command} · timeout"
    else:
        status = "completed" if exit_code == 0 else "failed"
        message = "Command completed successfully." if status == "completed" else "Command finished with an error."
        phase = "verify" if status == "completed" else "recover"
        title = "Terminal command finished"
        summary = f"{command} · exit {exit_code}"

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
            content=message,
            exit_code=exit_code,
        )

    set_live_operator(
        active=False,
        mode="terminal",
        phase=phase,
        title=title,
        detail=message,
        summary=summary,
        preserve_started=False,
    )
    terminal_processes.pop(session_id, None)
    return True


async def dispatch_command_to_attached_pty(
    *,
    session_id: int,
    command: str,
    cwd: Path,
    timeout_seconds: int,
    pty_sessions: dict[Any, Any],
    terminal_processes: dict[int, dict],
    db_module: Any,
    set_live_operator,
    now_iso,
    asyncio_module=asyncio,
):
    entry_key, entry = find_attached_pty_session(pty_sessions, session_id)
    if not entry:
        return None
    pty_proc = entry.get("pty") or entry.get("proc")
    if not pty_proc:
        return None

    marker = f"{session_id}-{uuid4().hex[:10]}"
    entry.setdefault("tracked_commands", {})[marker] = {"command": command, "session_id": session_id}
    terminal_processes[session_id] = {
        "kind": "pty",
        "command": command,
        "cwd": str(cwd),
        "started_at": now_iso(),
        "marker": marker,
        "pty_entry_key": entry_key,
    }

    async with db_module.get_db() as conn:
        await db_module.update_terminal_session(
            conn,
            session_id,
            status="running",
            active_command=command,
            pending_command="",
            cwd=str(cwd),
            pid=0,
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

    try:
        _write_pty(pty_proc, "stty -echo\n")
        await asyncio_module.sleep(0.05)
        _write_pty(pty_proc, build_pty_command_payload(command, cwd, marker))
    except Exception:
        entry.get("tracked_commands", {}).pop(marker, None)
        terminal_processes.pop(session_id, None)
        raise

    async def _timeout_guard():
        await asyncio_module.sleep(timeout_seconds)
        active = terminal_processes.get(session_id)
        if not active or active.get("marker") != marker or active.get("kind") != "pty":
            return
        try:
            _write_pty(pty_proc, "\x03")
            await asyncio_module.sleep(0.05)
            _write_pty(pty_proc, "stty echo\n")
        except Exception:
            pass
        await finalize_tracked_pty_command(
            session_id,
            terminal_processes=terminal_processes,
            pty_sessions=pty_sessions,
            db_module=db_module,
            set_live_operator=set_live_operator,
            exit_code=124,
            timed_out=True,
        )

    terminal_processes[session_id]["timeout_task"] = asyncio_module.create_task(_timeout_guard())
    return {
        "status": "running",
        "command": command,
        "cwd": str(cwd),
        "pid": 0,
        "timeout_seconds": timeout_seconds,
        "transport": "pty",
    }


async def interrupt_tracked_pty_command(
    session_id: int,
    *,
    terminal_processes: dict[int, dict],
    pty_sessions: dict[Any, Any],
    db_module: Any,
    set_live_operator,
    asyncio_module=asyncio,
):
    active = terminal_processes.get(session_id)
    if not active or active.get("kind") != "pty":
        return False

    entry_key = active.get("pty_entry_key")
    entry = pty_sessions.get(entry_key)
    pty_proc = (entry or {}).get("pty") or (entry or {}).get("proc")
    if pty_proc:
        try:
            _write_pty(pty_proc, "\x03")
            await asyncio_module.sleep(0.05)
            _write_pty(pty_proc, "stty echo\n")
        except Exception:
            pass

    return await finalize_tracked_pty_command(
        session_id,
        terminal_processes=terminal_processes,
        pty_sessions=pty_sessions,
        db_module=db_module,
        set_live_operator=set_live_operator,
        exit_code=130,
        stopped=True,
    )
