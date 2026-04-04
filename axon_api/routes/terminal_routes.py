"""Terminal session routes extracted from server.py."""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel


class TerminalSessionCreate(BaseModel):
    title: Optional[str] = None
    workspace_id: Optional[int] = None
    mode: Optional[str] = "read_only"
    cwd: Optional[str] = None


class TerminalCommandBody(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout_seconds: Optional[int] = None
    mode: Optional[str] = None
    approved: Optional[bool] = False


class TerminalRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        terminal_processes: dict[int, Any],
        pty_sessions: dict[Any, Any],
        resolve_terminal_cwd: Callable[..., Awaitable[Path]],
        terminal_mode_value: Callable[[str | None, str], str],
        terminal_execute_request: Callable[..., Awaitable[dict[str, Any]]],
        serialize_terminal_session: Callable[..., dict[str, Any]],
        serialize_terminal_event: Callable[..., dict[str, Any]],
        set_live_operator: Callable[..., None],
        valid_session: Callable[[str], bool],
        local_tool_scope_label: Callable[[], str],
    ) -> None:
        self._db = db_module
        self._terminal_processes = terminal_processes
        self._pty_sessions = pty_sessions
        self._resolve_terminal_cwd = resolve_terminal_cwd
        self._terminal_mode_value = terminal_mode_value
        self._terminal_execute_request = terminal_execute_request
        self._serialize_terminal_session = serialize_terminal_session
        self._serialize_terminal_event = serialize_terminal_event
        self._set_live_operator = set_live_operator
        self._valid_session = valid_session
        self._local_tool_scope_label = local_tool_scope_label

    async def list_terminal_sessions(self, workspace_id: Optional[int] = None, limit: int = 20):
        async with self._db.get_db() as conn:
            rows = await self._db.list_terminal_sessions(conn, workspace_id=workspace_id, limit=limit)
        return [self._serialize_terminal_session(row, running=row["id"] in self._terminal_processes) for row in rows]

    async def create_terminal_session(self, body: TerminalSessionCreate):
        from datetime import datetime

        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            mode = self._terminal_mode_value(body.mode, settings.get("terminal_default_mode", "read_only"))
            cwd = str(await self._resolve_terminal_cwd(conn, {"cwd": body.cwd or "", "workspace_id": body.workspace_id}))
            title = (body.title or "").strip() or f"Terminal {datetime.now().strftime('%H:%M')}"
            session_id = await self._db.create_terminal_session(
                conn,
                title=title,
                workspace_id=body.workspace_id,
                mode=mode,
                cwd=cwd,
            )
            session = await self._db.get_terminal_session(conn, session_id)
            await self._db.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content=f"Session ready in {cwd}. Installs stay inside Axon at {self._local_tool_scope_label()}.",
            )
        return self._serialize_terminal_session(session, running=False)

    async def get_terminal_session(self, session_id: int, limit: int = 160):
        async with self._db.get_db() as conn:
            row = await self._db.get_terminal_session(conn, session_id)
            if not row:
                raise HTTPException(404, "Terminal session not found")
            events = await self._db.list_terminal_events(conn, session_id, limit=limit)
        return self._serialize_terminal_session(
            row,
            running=session_id in self._terminal_processes,
            recent_events=[self._serialize_terminal_event(event) for event in events],
        )

    async def patch_terminal_session(self, session_id: int, request: Request):
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "Title is required")
        async with self._db.get_db() as conn:
            row = await self._db.get_terminal_session(conn, session_id)
            if not row:
                raise HTTPException(404, "Terminal session not found")
            await self._db.update_terminal_session(conn, session_id, title=title)
        return {"ok": True, "title": title}

    async def terminal_execute(self, session_id: int, body: TerminalCommandBody):
        return await self._terminal_execute_request(session_id, body, approved=bool(body.approved))

    async def terminal_approve(self, session_id: int, body: TerminalCommandBody):
        return await self._terminal_execute_request(session_id, body, approved=True)

    async def terminal_stop(self, session_id: int):
        entry = self._terminal_processes.get(session_id)
        if not entry:
            async with self._db.get_db() as conn:
                row = await self._db.get_terminal_session(conn, session_id)
                if not row:
                    raise HTTPException(404, "Terminal session not found")
            return {"status": "idle", "message": "No running command to stop."}

        process = entry.get("process")
        if process and process.returncode is None:
            process.terminate()
            await asyncio.sleep(0.5)
            if process.returncode is None:
                process.kill()
        async with self._db.get_db() as conn:
            await self._db.update_terminal_session(conn, session_id, status="stopped", active_command="", pending_command="", pid=0)
            await self._db.add_terminal_event(conn, session_id=session_id, event_type="status", content="Command stopped by the user.")
        self._set_live_operator(
            active=False,
            mode="terminal",
            phase="recover",
            title="Terminal command stopped",
            detail="Axon stopped the running command safely.",
            summary=str(entry.get("command") or ""),
        )
        return {"status": "stopped", "message": "Command stopped."}

    async def close_terminal_session(self, session_id: int):
        pty_key = str(session_id)
        pty_info = self._pty_sessions.get(pty_key) or self._pty_sessions.get(session_id)
        if pty_info:
            try:
                pty_info["alive"] = False
                pty_proc = pty_info.get("pty") or pty_info.get("proc")
                if pty_proc and pty_proc.isalive():
                    pty_proc.terminate(force=True)
            except Exception:
                pass
            task = pty_info.get("task")
            if task:
                task.cancel()
            self._pty_sessions.pop(pty_key, None)
            self._pty_sessions.pop(session_id, None)

        entry = self._terminal_processes.pop(session_id, None)
        if entry:
            process = entry.get("process")
            if process and process.returncode is None:
                try:
                    process.terminate()
                except Exception:
                    pass
        async with self._db.get_db() as conn:
            row = await self._db.get_terminal_session(conn, session_id)
            if not row:
                raise HTTPException(404, "Terminal session not found")
            await self._db.update_terminal_session(conn, session_id, status="closed", active_command="", pending_command="")
        return {"status": "closed", "message": "Session closed."}

    async def pty_websocket(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        async with self._db.get_db() as conn:
            pin_hash = await self._db.get_setting(conn, "auth_pin_hash")
        if pin_hash:
            token = websocket.query_params.get("token", "")
            if not token or not self._valid_session(token):
                await websocket.send_json({"type": "error", "message": "Authentication required"})
                await websocket.close()
                return

        try:
            from ptyprocess import PtyProcess
        except ImportError:
            await websocket.send_json({"type": "error", "message": "ptyprocess not installed on server"})
            await websocket.close()
            return

        cols, rows = 220, 50
        shell = os.environ.get("SHELL", "/bin/bash")
        shell_name = Path(shell).name
        shell_argv = [shell]
        if shell_name in {"bash", "zsh"}:
            shell_argv.extend(["-i", "-l"])
        elif shell_name == "fish":
            shell_argv.append("-i")
        else:
            shell_argv.append("--login")
        home = str(Path.home())

        pty_proc = PtyProcess.spawn(
            shell_argv,
            dimensions=(rows, cols),
            env={**os.environ, "TERM": "xterm-256color"},
            cwd=home,
        )

        entry = {"pty": pty_proc, "ws": websocket, "alive": True}
        self._pty_sessions[session_id] = entry

        def write_input(raw: Any):
            if raw is None:
                return
            if isinstance(raw, str):
                payload = raw.encode("utf-8", errors="ignore")
            elif isinstance(raw, (bytes, bytearray)):
                payload = bytes(raw)
            else:
                payload = str(raw).encode("utf-8", errors="ignore")
            if payload:
                pty_proc.write(payload)

        async def read_pty():
            loop = asyncio.get_event_loop()
            try:
                while entry["alive"] and pty_proc.isalive():
                    try:
                        data = await loop.run_in_executor(None, pty_proc.read, 4096)
                        if data:
                            await websocket.send_json(
                                {"type": "data", "data": base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()}
                            )
                    except EOFError:
                        break
                    except Exception:
                        break
            finally:
                exit_code = pty_proc.exitstatus if not pty_proc.isalive() else None
                try:
                    await websocket.send_json({"type": "exit", "code": exit_code})
                except Exception:
                    pass

        read_task = asyncio.create_task(read_pty())
        entry["task"] = read_task

        try:
            while True:
                msg = await websocket.receive_text()
                if not pty_proc.isalive():
                    break
                try:
                    parsed = json.loads(msg)
                    if parsed.get("type") == "resize":
                        pty_proc.setwinsize(int(parsed.get("rows", rows)), int(parsed.get("cols", cols)))
                    elif parsed.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif parsed.get("type") == "input":
                        write_input(parsed.get("data", ""))
                except json.JSONDecodeError:
                    write_input(msg)
                except ValueError:
                    continue
                except Exception as exc:
                    try:
                        await websocket.send_json({"type": "error", "message": f"PTY input failed: {exc}"})
                    except Exception:
                        pass
                    if not pty_proc.isalive():
                        break
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            entry["alive"] = False
            read_task.cancel()
            try:
                pty_proc.terminate(force=True)
            except Exception:
                pass
            self._pty_sessions.pop(session_id, None)


def build_terminal_router(
    *,
    db_module: Any,
    terminal_processes: dict[int, Any],
    pty_sessions: dict[Any, Any],
    resolve_terminal_cwd: Callable[..., Awaitable[Path]],
    terminal_mode_value: Callable[[str | None, str], str],
    terminal_execute_request: Callable[..., Awaitable[dict[str, Any]]],
    serialize_terminal_session: Callable[..., dict[str, Any]],
    serialize_terminal_event: Callable[..., dict[str, Any]],
    set_live_operator: Callable[..., None],
    valid_session: Callable[[str], bool],
    local_tool_scope_label: Callable[[], str],
):
    handlers = TerminalRouteHandlers(
        db_module=db_module,
        terminal_processes=terminal_processes,
        pty_sessions=pty_sessions,
        resolve_terminal_cwd=resolve_terminal_cwd,
        terminal_mode_value=terminal_mode_value,
        terminal_execute_request=terminal_execute_request,
        serialize_terminal_session=serialize_terminal_session,
        serialize_terminal_event=serialize_terminal_event,
        set_live_operator=set_live_operator,
        valid_session=valid_session,
        local_tool_scope_label=local_tool_scope_label,
    )
    router = APIRouter()
    router.add_api_route("/api/terminal/sessions", handlers.list_terminal_sessions, methods=["GET"])
    router.add_api_route("/api/terminal/sessions", handlers.create_terminal_session, methods=["POST"])
    router.add_api_route("/api/terminal/sessions/{session_id}", handlers.get_terminal_session, methods=["GET"])
    router.add_api_route("/api/terminal/sessions/{session_id}", handlers.patch_terminal_session, methods=["PATCH"])
    router.add_api_route("/api/terminal/sessions/{session_id}/execute", handlers.terminal_execute, methods=["POST"])
    router.add_api_route("/api/terminal/sessions/{session_id}/approve", handlers.terminal_approve, methods=["POST"])
    router.add_api_route("/api/terminal/sessions/{session_id}/stop", handlers.terminal_stop, methods=["POST"])
    router.add_api_route("/api/terminal/sessions/{session_id}", handlers.close_terminal_session, methods=["DELETE"])
    router.add_api_websocket_route("/ws/pty/{session_id}", handlers.pty_websocket)
    return router, handlers
