"""
Axon — Main FastAPI Server
Start with: python3 ~/.devbrain/server.py
Access at:  http://localhost:7734
"""

import asyncio
import sys
import os
import platform as _platform
import shlex as _shlex
import subprocess
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uvicorn
import json as _json

# Add devbrain dir to path
sys.path.insert(0, str(Path.home() / ".devbrain"))

import db as devdb
import brain
import vault as devvault
import scanner
import scheduler as sched_module
import integrations as integ
import runtime_manager
import gpu_guard
import provider_registry

PORT = 7734
DEVBRAIN_DIR = Path.home() / ".devbrain"
UI_DIR = Path.home() / ".devbrain" / "ui"
START_SH = DEVBRAIN_DIR / "start.sh"
STOP_SH = DEVBRAIN_DIR / "stop.sh"
OLLAMA_SH = DEVBRAIN_DIR / "ollama-start.sh"
PIDFILE = DEVBRAIN_DIR / ".pid"
DEVBRAIN_LOG = DEVBRAIN_DIR / "devbrain.log"

SYSTEM_ACTION_CONFIRMATIONS = {
    "restart_devbrain": "RESTART AXON",
    "restart_ollama": "RESTART OLLAMA",
    "reboot_machine": "REBOOT MACHINE",
}


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await devdb.init_db()
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        scan_hours = int(settings.get("scan_interval_hours", 6))
        digest_hour = int(settings.get("morning_digest_hour", 8))

    scheduler = sched_module.setup_scheduler(
        scan_interval_hours=scan_hours,
        digest_hour=digest_hour,
    )
    scheduler.start()
    print(f"[Axon] Server started on http://localhost:{PORT}")
    print(f"[Axon] Scheduler running — scan every {scan_hours}h, digest at {digest_hour}:00")

    # Run initial scan on startup
    asyncio.create_task(sched_module.trigger_scan_now())

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    print("[Axon] Server stopped.")


app = FastAPI(
    title="Axon",
    version="1.0.0",
    description="Local AI Operator",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth — PIN-based session authentication ─────────────────────────────────

import hashlib
import secrets as _secrets
from datetime import datetime, timedelta

# In-memory session store: { token_str: expiry_datetime }
_auth_sessions: dict[str, datetime] = {}
_AUTH_SESSION_HOURS = 72  # sessions last 3 days


def _extract_session_token(request: Request) -> str:
    return (
        request.headers.get("X-Axon-Token")
        or request.headers.get("X-DevBrain-Token")
        or request.headers.get("X-Session-Token")
        or request.query_params.get("token")
        or ""
    )


def _hash_pin(pin: str) -> str:
    """SHA-256 hash a PIN with a fixed app salt."""
    return hashlib.sha256(f"devbrain-pin-{pin}".encode()).hexdigest()

def _create_session() -> str:
    """Create a new session token, store it, and return it."""
    token = _secrets.token_hex(32)
    _auth_sessions[token] = datetime.utcnow() + timedelta(hours=_AUTH_SESSION_HOURS)
    # Prune expired sessions
    now = datetime.utcnow()
    expired = [k for k, v in _auth_sessions.items() if v < now]
    for k in expired:
        del _auth_sessions[k]
    return token

def _valid_session(token: str) -> bool:
    """Check if a session token is valid and not expired."""
    exp = _auth_sessions.get(token)
    if not exp:
        return False
    if datetime.utcnow() > exp:
        del _auth_sessions[token]
        return False
    return True

# Paths that don't require auth
_AUTH_EXEMPT = {"/", "/sw.js", "/manifest.json", "/manual", "/manual.html",
                "/api/health", "/api/tunnel/status", "/api/tunnel/start", "/api/tunnel/stop"}
_AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/icons/")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protect API routes with session token when a PIN is set."""
    path = request.url.path

    # Always allow auth endpoints, static assets, and the UI itself
    if path in _AUTH_EXEMPT or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return await call_next(request)

    # Check if auth is enabled (PIN is set)
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")

    # No PIN set = auth disabled, allow everything
    if not pin_hash:
        return await call_next(request)

    # PIN is set — require valid session token
    token = _extract_session_token(request)
    if not token or not _valid_session(token):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    return await call_next(request)


class PinSetup(BaseModel):
    pin: str  # 4-6 digit PIN

class PinLogin(BaseModel):
    pin: str

@app.get("/api/auth/status")
async def auth_status(request: Request):
    """Check if auth is enabled and if current session is valid."""
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    token = _extract_session_token(request)
    return {
        "auth_enabled": bool(pin_hash),
        "session_valid": (not pin_hash) or bool(token and _valid_session(token)),
    }

@app.post("/api/auth/setup")
async def auth_setup(body: PinSetup):
    """Set up a PIN for the first time (or change it)."""
    pin = body.pin.strip()
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        raise HTTPException(400, "PIN must be 4-6 digits")
    async with devdb.get_db() as conn:
        await devdb.set_setting(conn, "auth_pin_hash", _hash_pin(pin))
    token = _create_session()
    return {"status": "ok", "token": token}

@app.post("/api/auth/login")
async def auth_login(body: PinLogin):
    """Verify PIN and return a session token."""
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    if not pin_hash:
        raise HTTPException(400, "No PIN set — use /api/auth/setup first")
    if _hash_pin(body.pin.strip()) != pin_hash:
        raise HTTPException(401, "Wrong PIN")
    token = _create_session()
    return {"status": "ok", "token": token}

@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    """Invalidate current session."""
    token = _extract_session_token(request)
    if token and token in _auth_sessions:
        del _auth_sessions[token]
    return {"status": "ok"}

@app.post("/api/auth/remove")
async def auth_remove(body: PinLogin):
    """Remove PIN protection (requires current PIN)."""
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    if not pin_hash:
        return {"status": "ok", "message": "No PIN was set"}
    if _hash_pin(body.pin.strip()) != pin_hash:
        raise HTTPException(401, "Wrong PIN")
    async with devdb.get_db() as conn:
        await devdb.set_setting(conn, "auth_pin_hash", "")
    # Clear all sessions
    _auth_sessions.clear()
    return {"status": "ok"}


# ─── Serve UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    ui_file = UI_DIR / "index.html"
    if not ui_file.exists():
        return HTMLResponse("<h1>Axon UI not found</h1><p>Run install.sh again.</p>", status_code=404)
    return HTMLResponse(
        ui_file.read_text(),
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/manual", response_class=HTMLResponse)
@app.get("/manual.html", response_class=HTMLResponse)
async def serve_manual():
    manual_file = UI_DIR / "manual.html"
    if not manual_file.exists():
        return HTMLResponse("<h1>Manual not found</h1>", status_code=404)
    return HTMLResponse(manual_file.read_text())


# ─── Projects ────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects(status: Optional[str] = None):
    async with devdb.get_db() as conn:
        rows = await devdb.get_projects(conn, status=status)
        return [dict(r) for r in rows]


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_project(conn, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        return dict(row)


class ProjectUpdate(BaseModel):
    note: Optional[str] = None
    status: Optional[str] = None


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: int, body: ProjectUpdate):
    async with devdb.get_db() as conn:
        if body.note is not None:
            await devdb.update_project_note(conn, project_id, body.note)
        if body.status is not None:
            await devdb.update_project_status(conn, project_id, body.status)
        row = await devdb.get_project(conn, project_id)
        return dict(row)


@app.post("/api/projects/{project_id}/analyse")
async def analyse_project(project_id: int):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = _ai_params(settings)

        project = dict(await devdb.get_project(conn, project_id))
        if not project:
            raise HTTPException(404, "Project not found")

        tasks = [dict(r) for r in await devdb.get_tasks(conn, project_id=project_id)]
        prompts = [dict(r) for r in await devdb.get_prompts(conn, project_id=project_id)]

        analysis = await brain.analyse_project(project, tasks, prompts, **ai)
        await devdb.log_event(conn, "analysis", f"Analysed {project['name']}", project_id=project_id)
        return {"analysis": analysis}


@app.post("/api/projects/{project_id}/suggest-tasks")
async def suggest_project_tasks(project_id: int):
    """Generate SMART task suggestions for a specific project."""
    async with devdb.get_db() as conn:
        project = await devdb.get_project(conn, project_id)
        if not project:
            raise HTTPException(404, "Project not found")
        settings = await devdb.get_all_settings(conn)
        ai = _ai_params(settings)
        open_tasks = [dict(r) for r in await devdb.get_tasks(conn, project_id=project_id, status="open")]
        try:
            suggestions = await brain.suggest_tasks_for_project(dict(project), open_tasks, **ai)
        except Exception as e:
            raise HTTPException(500, f"Suggestion failed: {e}")
        return {"suggestions": suggestions, "project_name": project["name"]}


# ─── Scan ────────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def run_scan():
    """Trigger an immediate project scan."""
    asyncio.create_task(sched_module.trigger_scan_now())
    return {"status": "scan started"}


# ─── Prompts ─────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    project_id: Optional[int] = None
    title: str
    content: str
    tags: str = ""


@app.get("/api/prompts")
async def list_prompts(project_id: Optional[int] = None):
    async with devdb.get_db() as conn:
        rows = await devdb.get_prompts(conn, project_id=project_id)
        return [dict(r) for r in rows]


@app.post("/api/prompts")
async def create_prompt(body: PromptCreate):
    async with devdb.get_db() as conn:
        prompt_id = await devdb.save_prompt(
            conn, body.project_id, body.title, body.content, body.tags
        )
        await devdb.log_event(
            conn, "prompt_saved", f"Saved prompt: {body.title}",
            project_id=body.project_id
        )
        return {"id": prompt_id, "title": body.title}


@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: int):
    async with devdb.get_db() as conn:
        await devdb.delete_prompt(conn, prompt_id)
        return {"deleted": True}


class PromptUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    project_id: Optional[int] = None


@app.patch("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: int, body: PromptUpdate):
    async with devdb.get_db() as conn:
        fields = {k: v for k, v in body.dict().items() if v is not None}
        if not fields:
            raise HTTPException(400, "Nothing to update")
        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [prompt_id]
        await conn.execute(
            f"UPDATE prompts SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
            values
        )
        await conn.commit()
        cur = await conn.execute("SELECT * FROM prompts WHERE id = ?", (prompt_id,))
        row = await cur.fetchone()
        return dict(row)


@app.post("/api/prompts/{prompt_id}/pin")
async def toggle_pin(prompt_id: int):
    async with devdb.get_db() as conn:
        await conn.execute(
            "UPDATE prompts SET pinned = CASE WHEN pinned = 1 THEN 0 ELSE 1 END, "
            "updated_at = datetime('now') WHERE id = ?",
            (prompt_id,)
        )
        await conn.commit()
        cur = await conn.execute("SELECT pinned FROM prompts WHERE id = ?", (prompt_id,))
        row = await cur.fetchone()
        return {"pinned": bool(row["pinned"])}


class EnhanceRequest(BaseModel):
    content: str
    project_context: Optional[str] = None


@app.post("/api/prompts/enhance")
async def enhance_prompt(body: EnhanceRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = _ai_params(settings)
        enhanced = await brain.enhance_prompt(body.content, body.project_context, **ai)
        return {"enhanced": enhanced}


# ─── Tasks ───────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    project_id: Optional[int] = None
    title: str
    detail: str = ""
    priority: str = "medium"
    due_date: Optional[str] = None


@app.get("/api/tasks")
async def list_tasks(project_id: Optional[int] = None, status: Optional[str] = "open"):
    async with devdb.get_db() as conn:
        rows = await devdb.get_tasks(conn, project_id=project_id, status=status)
        return [dict(r) for r in rows]


@app.post("/api/tasks")
async def create_task(body: TaskCreate):
    async with devdb.get_db() as conn:
        task_id = await devdb.add_task(
            conn, body.project_id, body.title, body.detail,
            body.priority, body.due_date
        )
        await devdb.log_event(
            conn, "task_added", f"Task added: {body.title}",
            project_id=body.project_id
        )
        return {"id": task_id, "title": body.title}


class TaskUpdate(BaseModel):
    status: str


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, body: TaskUpdate):
    async with devdb.get_db() as conn:
        await devdb.update_task_status(conn, task_id, body.status)
        return {"updated": True}


@app.post("/api/tasks/suggest")
async def suggest_tasks():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = _ai_params(settings)
        projects = [dict(r) for r in await devdb.get_projects(conn)]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        suggestions = await brain.suggest_tasks(
            projects, tasks, **ai
        )
        return {"suggestions": suggestions}


# ─── AI backend helper ────────────────────────────────────────────────────────

def _ai_params(settings: dict) -> dict:
    """Extract AI backend params from settings dict."""
    backend = settings.get("ai_backend", "ollama")
    api_runtime = provider_registry.runtime_api_config(settings)
    api_key = api_runtime.get("api_key", "")
    cli_path = settings.get("claude_cli_path", "")
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    if backend == "api" and not api_key:
        provider_label = api_runtime.get("provider_label", "External API")
        raise HTTPException(400, f"{provider_label} key not set. Go to Settings → Runtime.")
    if backend == "cli" and not cli_path and not brain._find_cli():
        raise HTTPException(400, "CLI agent not found. Set the path in Settings.")
    return {
        "api_key": api_key,
        "api_provider": api_runtime.get("provider_id", "anthropic"),
        "api_base_url": api_runtime.get("api_base_url", ""),
        "api_model": api_runtime.get("api_model", ""),
        "backend": backend, "cli_path": cli_path,
        "ollama_url": ollama_url, "ollama_model": ollama_model,
    }


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    model: Optional[str] = None


@app.post("/api/chat")
async def chat(body: ChatMessage):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = _ai_params(settings)
        if body.model:
            ai["ollama_model"] = body.model

        # Build rich context
        projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
        context_block = brain._build_context_block(projects, tasks, prompts_list)

        # Load history
        history_rows = await devdb.get_chat_history(conn, project_id=body.project_id)
        history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

        # Get project name if scoped
        project_name = None
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]

        # Call AI with timeout handling
        try:
            import asyncio as _aio
            result = await _aio.wait_for(
                brain.chat(body.message, history, context_block, project_name, **ai),
                timeout=90.0,
            )
        except (_aio.TimeoutError, TimeoutError, RuntimeError) as exc:
            raise HTTPException(504, f"AI backend timed out — try a shorter message or check Ollama. ({exc})")

        # Persist messages
        await devdb.save_message(conn, "user", body.message, project_id=body.project_id)
        await devdb.save_message(
            conn, "assistant", result["content"],
            project_id=body.project_id, tokens=result["tokens"]
        )
        await devdb.log_event(conn, "chat", body.message[:100], project_id=body.project_id)

        return {"response": result["content"], "tokens": result["tokens"]}


@app.get("/api/chat/history")
async def get_chat_history(project_id: Optional[int] = None, limit: int = 30):
    async with devdb.get_db() as conn:
        rows = await devdb.get_chat_history(conn, project_id=project_id, limit=limit)
        return [{"role": r["role"], "content": r["content"],
                 "created_at": r["created_at"], "tokens_used": r["tokens_used"]} for r in rows]


@app.delete("/api/chat/history")
async def clear_history(project_id: Optional[int] = None):
    async with devdb.get_db() as conn:
        await devdb.clear_chat_history(conn, project_id=project_id)
        return {"cleared": True}


# ─── Streaming chat (Ollama SSE) ──────────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(body: ChatMessage, request: Request):
    """SSE streaming chat — Ollama only; falls back to buffered for API/CLI."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        backend = settings.get("ai_backend", "ollama")
        if body.model:
            settings["ollama_model"] = body.model

        # Load context + history
        projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
        context_block = brain._build_context_block(projects, tasks, prompts_list)
        history_rows = await devdb.get_chat_history(conn, project_id=body.project_id)
        history = [{"role": r["role"], "content": r["content"]} for r in history_rows]
        project_name = None
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]

    if backend != "ollama":
        # Fall back to non-streaming for API/CLI — emit single SSE event
        try:
            ai = _ai_params(settings)
            result = await brain.chat(body.message, history, context_block,
                                       project_name, **ai)
            async def _buffered():
                yield {"data": _json.dumps({"chunk": result["content"]})}
                yield {"data": _json.dumps({"done": True, "tokens": result["tokens"]})}
            return EventSourceResponse(_buffered())
        except Exception as exc:
            async def _err():
                yield {"data": _json.dumps({"error": str(exc)})}
            return EventSourceResponse(_err())

    # Ollama: true streaming
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    full_content: list[str] = []

    async def generate():
        try:
            async for chunk in brain.stream_chat(
                body.message, history, context_block, project_name,
                ollama_url=ollama_url, ollama_model=ollama_model,
            ):
                full_content.append(chunk)
                if await request.is_disconnected():
                    return
                yield {"data": _json.dumps({"chunk": chunk})}
            # Persist after stream completes
            async with devdb.get_db() as conn:
                await devdb.save_message(conn, "user", body.message,
                                          project_id=body.project_id)
                await devdb.save_message(conn, "assistant", "".join(full_content),
                                          project_id=body.project_id, tokens=0)
                await devdb.log_event(conn, "chat", body.message[:100],
                                       project_id=body.project_id)
            yield {"data": _json.dumps({"done": True, "tokens": 0})}
        except Exception as exc:
            yield {"data": _json.dumps({"error": str(exc)})}

    return EventSourceResponse(generate())


# ─── Agent endpoint ───────────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    tools: Optional[list[str]] = None    # None = all tools
    model: Optional[str] = None


@app.post("/api/agent")
async def agent_endpoint(body: AgentRequest, request: Request):
    """SSE streaming agent with tool-calling (Ollama only)."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        backend = settings.get("ai_backend", "ollama")
        if backend != "ollama":
            raise HTTPException(400, "Agent mode requires the Ollama backend. Switch in Settings.")

        projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
        context_block = brain._build_context_block(projects, tasks, prompts_list)
        history_rows = await devdb.get_chat_history(conn, project_id=body.project_id)
        history = [{"role": r["role"], "content": r["content"]} for r in history_rows]
        project_name = None
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]

    ollama_url = settings.get("ollama_url", "")
    ollama_model = body.model or settings.get("ollama_model", "")
    collected_text: list[str] = []

    async def generate():
        try:
            async for event in brain.run_agent(
                body.message, history, context_block, project_name,
                tools=body.tools,
                ollama_url=ollama_url, ollama_model=ollama_model,
            ):
                if event.get("type") == "text":
                    collected_text.append(event["chunk"])
                if await request.is_disconnected():
                    return
                yield {"data": _json.dumps(event)}

            # Persist final answer
            final_text = "".join(collected_text)
            if final_text:
                async with devdb.get_db() as conn:
                    await devdb.save_message(conn, "user", body.message,
                                              project_id=body.project_id)
                    await devdb.save_message(conn, "assistant", final_text,
                                              project_id=body.project_id, tokens=0)
                    await devdb.log_event(conn, "agent", body.message[:100],
                                           project_id=body.project_id)
        except Exception as exc:
            yield {"data": _json.dumps({"type": "error", "message": str(exc)})}

    return EventSourceResponse(generate())


# ─── Digest ───────────────────────────────────────────────────────────────────

@app.post("/api/digest")
async def run_digest():
    asyncio.create_task(sched_module.trigger_digest_now())
    return {"status": "digest started"}


@app.get("/api/digest/latest")
async def get_latest_digest():
    async with devdb.get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM activity_log WHERE event_type = 'digest' ORDER BY created_at DESC LIMIT 1"
        )
        row = await cur.fetchone()
        if not row:
            return {"digest": None}
        return {"digest": dict(row)["summary"], "created_at": dict(row)["created_at"]}


# ─── Activity ────────────────────────────────────────────────────────────────

@app.get("/api/activity")
async def get_activity(limit: int = 30):
    async with devdb.get_db() as conn:
        rows = await devdb.get_activity(conn, limit=limit)
        return [dict(r) for r in rows]


# ─── Settings ────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    async with devdb.get_db() as conn:
        s = await devdb.get_all_settings(conn)
        s["ai_backend"] = s.get("ai_backend") or "ollama"
        s["api_provider"] = provider_registry.selected_api_provider_id(s)
        for key in (
            "cloud_agents_enabled",
            "openai_gpts_enabled",
            "gemini_gems_enabled",
            "generic_api_enabled",
        ):
            s[key] = str(s.get(key, "")).strip().lower() in {"1", "true", "yes", "on"}
        for key_name in (
            "anthropic_api_key",
            "openai_api_key",
            "gemini_api_key",
            "generic_api_key",
        ):
            raw = s.get(key_name, "")
            s[f"{key_name}_set"] = bool(raw)
            s[key_name] = provider_registry.mask_secret(raw) if raw else ""
        s["api_key_set"] = s.get("anthropic_api_key_set", False)
        if s.get("github_token"):
            token = s["github_token"]
            s["github_token"] = token[:4] + "..." + token[-4:] if len(token) > 10 else "set"
            s["github_token_set"] = True
        else:
            s["github_token_set"] = False
        return s


class SettingsUpdate(BaseModel):
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    anthropic_api_model: Optional[str] = None
    scan_interval_hours: Optional[str] = None
    morning_digest_hour: Optional[str] = None
    projects_root: Optional[str] = None
    notify_desktop: Optional[str] = None
    ai_backend: Optional[str] = None
    api_provider: Optional[str] = None
    claude_cli_path: Optional[str] = None
    ollama_url: Optional[str] = None
    ollama_model: Optional[str] = None
    code_model: Optional[str] = None
    general_model: Optional[str] = None
    reasoning_model: Optional[str] = None
    embeddings_model: Optional[str] = None
    vision_model: Optional[str] = None
    cloud_agents_enabled: Optional[bool] = None
    openai_gpts_enabled: Optional[bool] = None
    gemini_gems_enabled: Optional[bool] = None
    generic_api_enabled: Optional[bool] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_api_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    gemini_api_model: Optional[str] = None
    generic_api_key: Optional[str] = None
    generic_api_url: Optional[str] = None
    generic_api_model: Optional[str] = None
    github_token: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    webhook_urls: Optional[str] = None
    webhook_secret: Optional[str] = None
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = None
    azure_voice: Optional[str] = None


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    async with devdb.get_db() as conn:
        data = body.model_dump(exclude_none=True)
        for key, value in data.items():
            if isinstance(value, bool):
                await devdb.set_setting(conn, key, "1" if value else "0")
            else:
                await devdb.set_setting(conn, key, str(value))

        # Restart scheduler with new settings if timing changed
        if "scan_interval_hours" in data or "morning_digest_hour" in data:
            settings = await devdb.get_all_settings(conn)
            scan_h = int(settings.get("scan_interval_hours", 6))
            digest_h = int(settings.get("morning_digest_hour", 8))
            scheduler = sched_module.get_scheduler()
            if scheduler.running:
                sched_module.setup_scheduler(scan_h, digest_h)

        return {"updated": list(data.keys())}


class CloudProviderTestRequest(BaseModel):
    provider_id: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


@app.get("/api/cloud/providers")
async def list_cloud_providers():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    return {
        "selected": provider_registry.runtime_api_config(settings),
        "providers": provider_registry.api_provider_cards(settings),
        "adapters": provider_registry.cloud_adapter_cards(settings),
    }


@app.post("/api/cloud/providers/test")
async def test_cloud_provider(body: CloudProviderTestRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    return await provider_registry.test_provider_connection(
        body.provider_id,
        settings,
        overrides={
            "api_key": body.api_key,
            "base_url": body.base_url,
            "model": body.model,
        },
    )


# ─── Vault ────────────────────────────────────────────────────────────────────

class VaultSetupRequest(BaseModel):
    master_password: str


class VaultUnlockRequest(BaseModel):
    master_password: str
    totp_code: str


class VaultSecretCreate(BaseModel):
    name: str
    category: str = "general"
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""


class VaultSecretUpdate(BaseModel):
    name: str
    category: str = "general"
    username: str = ""
    password: str = ""
    url: str = ""
    notes: str = ""


@app.get("/api/vault/status")
async def vault_status():
    """Return vault setup state and lock state."""
    async with devdb.get_db() as conn:
        is_setup = await devvault.vault_is_setup(conn)
    return {
        "is_setup": is_setup,
        "is_unlocked": devvault.VaultSession.is_unlocked(),
    }


@app.post("/api/vault/setup")
async def vault_setup(body: VaultSetupRequest):
    """Initialise the vault for the first time. Returns TOTP QR code."""
    async with devdb.get_db() as conn:
        already = await devvault.vault_is_setup(conn)
        if already:
            raise HTTPException(400, "Vault is already set up. Reset not supported via API.")
        result = await devvault.setup_vault(conn, body.master_password)
    return result  # {"totp_secret": str, "qr_data_uri": str}


@app.post("/api/vault/unlock")
async def vault_unlock(body: VaultUnlockRequest):
    """Unlock the vault with master password + TOTP code."""
    async with devdb.get_db() as conn:
        ok, err = await devvault.unlock_vault(conn, body.master_password, body.totp_code)
    if not ok:
        raise HTTPException(401, err)
    return {"unlocked": True}


@app.post("/api/vault/lock")
async def vault_lock():
    """Lock the vault (clears in-memory key)."""
    devvault.VaultSession.lock()
    return {"locked": True}


@app.get("/api/vault/secrets")
async def list_vault_secrets():
    """List all secrets (metadata only — no passwords)."""
    if not devvault.VaultSession.is_unlocked():
        raise HTTPException(403, "Vault is locked")
    async with devdb.get_db() as conn:
        secrets = await devvault.vault_list_secrets(conn)
    return secrets


@app.get("/api/vault/secrets/{secret_id}")
async def get_vault_secret(secret_id: int):
    """Return a fully decrypted secret."""
    key = devvault.VaultSession.get_key()
    if not key:
        raise HTTPException(403, "Vault is locked")
    async with devdb.get_db() as conn:
        secret = await devvault.vault_get_secret(conn, secret_id, key)
    if not secret:
        raise HTTPException(404, "Secret not found")
    return secret


@app.post("/api/vault/secrets")
async def create_vault_secret(body: VaultSecretCreate):
    """Encrypt and store a new secret."""
    key = devvault.VaultSession.get_key()
    if not key:
        raise HTTPException(403, "Vault is locked")
    async with devdb.get_db() as conn:
        secret_id = await devvault.vault_add_secret(
            conn, key, body.name, body.category,
            body.username, body.password, body.url, body.notes
        )
        await devdb.log_event(conn, "vault", f"Secret added: {body.name}")
    return {"id": secret_id, "name": body.name}


@app.put("/api/vault/secrets/{secret_id}")
async def update_vault_secret(secret_id: int, body: VaultSecretUpdate):
    """Re-encrypt and update a secret."""
    key = devvault.VaultSession.get_key()
    if not key:
        raise HTTPException(403, "Vault is locked")
    async with devdb.get_db() as conn:
        await devvault.vault_update_secret(
            conn, key, secret_id,
            body.name, body.category, body.username,
            body.password, body.url, body.notes
        )
        await devdb.log_event(conn, "vault", f"Secret updated: {body.name}")
    return {"updated": True}


@app.delete("/api/vault/secrets/{secret_id}")
async def delete_vault_secret(secret_id: int):
    """Delete a secret from the vault."""
    if not devvault.VaultSession.is_unlocked():
        raise HTTPException(403, "Vault is locked")
    async with devdb.get_db() as conn:
        await devvault.vault_delete_secret(conn, secret_id)
    return {"deleted": True}


# ─── Usage metrics ────────────────────────────────────────────────────────────

@app.get("/api/usage")
async def get_usage():
    """Return session-level AI usage stats."""
    return brain.get_session_usage()


@app.post("/api/usage/reset")
async def reset_usage():
    brain.reset_session_usage()
    return {"reset": True}


@app.get("/api/runtime/status")
async def runtime_status():
    """Return the Axon runtime snapshot used by the dashboard and settings."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        projects = await devdb.get_projects(conn, status="active")

    available_models = await brain.ollama_list_models(settings.get("ollama_url", ""))
    ollama_service = _ollama_service_status()
    return runtime_manager.build_runtime_status(
        settings=settings,
        available_models=available_models,
        ollama_running=bool(ollama_service.get("running")),
        vault_unlocked=devvault.VaultSession.is_unlocked(),
        workspace_count=len(projects),
        usage=brain.get_session_usage(),
    )


# ─── Mobile info ──────────────────────────────────────────────────────────────

@app.get("/api/mobile/info")
async def mobile_info():
    """Return local IP, Tailscale IP + QR code for mobile access."""
    import socket, io, base64

    # LAN IP (default route)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    # Tailscale IP (100.x.x.x range on tailscale0/utun interface)
    tailscale_ip = ""
    try:
        for iface_ip in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface_ip[4][0]
            if ip.startswith("100.") and not ip.startswith("100.127."):
                tailscale_ip = ip
                break
        if not tailscale_ip:
            # Try via ip command
            import subprocess
            out = subprocess.check_output(
                ["ip", "-4", "addr", "show", "tailscale0"],
                stderr=subprocess.DEVNULL, timeout=3
            ).decode()
            import re
            m = re.search(r"inet\s+(100\.\d+\.\d+\.\d+)", out)
            if m:
                tailscale_ip = m.group(1)
    except Exception:
        pass

    # Cloudflared tunnel URL (HTTPS — required for PWA install)
    cloudflared_url = ""
    try:
        import re as _re
        cf_log = Path.home() / ".devbrain" / "cloudflared.log"
        if cf_log.exists():
            text = cf_log.read_text()
            m = _re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
            if m:
                cloudflared_url = m.group(0)
    except Exception:
        pass

    # Prefer cloudflared (HTTPS) > Tailscale > LAN for QR code
    if cloudflared_url:
        qr_url = cloudflared_url
    elif tailscale_ip:
        qr_url = f"http://{tailscale_ip}:{PORT}"
    else:
        qr_url = f"http://{local_ip}:{PORT}"

    qr_data_uri = ""
    try:
        import qrcode
        qr = qrcode.QRCode(version=1,
                            error_correction=qrcode.constants.ERROR_CORRECT_L,
                            box_size=6, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass

    return {
        "local_url": f"http://{local_ip}:{PORT}",
        "local_ip": local_ip,
        "tailscale_ip": tailscale_ip,
        "tailscale_url": f"http://{tailscale_ip}:{PORT}" if tailscale_ip else "",
        "cloudflared_url": cloudflared_url,
        "qr_url": qr_url,
        "port": PORT,
        "qr_data_uri": qr_data_uri,
    }


# ─── Tunnel management ────────────────────────────────────────────────────────

import subprocess as _subprocess
import re as _re

TUNNEL_LOG = Path.home() / ".devbrain" / "cloudflared.log"
TUNNEL_PID = Path.home() / ".devbrain" / ".tunnel.pid"
TUNNEL_BIN = Path.home() / ".devbrain" / "cloudflared"
TUNNEL_SH  = Path.home() / ".devbrain" / "tunnel.sh"


def _read_tunnel_url() -> str:
    try:
        if TUNNEL_LOG.exists():
            m = _re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", TUNNEL_LOG.read_text())
            return m.group(0) if m else ""
    except Exception:
        pass
    return ""


def _tunnel_running() -> bool:
    try:
        if TUNNEL_PID.exists():
            pid = int(TUNNEL_PID.read_text().strip())
            _subprocess.check_output(["kill", "-0", str(pid)], stderr=_subprocess.DEVNULL)
            return True
    except Exception:
        pass
    return False


@app.get("/api/tunnel/status")
async def tunnel_status():
    running = _tunnel_running()
    url = _read_tunnel_url() if running else ""
    return {"running": running, "url": url}


@app.post("/api/tunnel/start")
async def tunnel_start():
    if _tunnel_running():
        return {"running": True, "url": _read_tunnel_url(), "msg": "Already running"}
    if not TUNNEL_BIN.exists():
        raise HTTPException(400, "cloudflared binary not found")
    # Clear old log
    TUNNEL_LOG.write_text("")
    proc = _subprocess.Popen(
        [str(TUNNEL_BIN), "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
        stdout=open(str(TUNNEL_LOG), "a"),
        stderr=_subprocess.STDOUT,
    )
    TUNNEL_PID.write_text(str(proc.pid))
    # Wait up to 12s for URL
    import asyncio as _aio
    for _ in range(24):
        await _aio.sleep(0.5)
        url = _read_tunnel_url()
        if url:
            return {"running": True, "url": url, "msg": "Tunnel started"}
    return {"running": True, "url": "", "msg": "Started — URL not yet ready"}


@app.post("/api/tunnel/stop")
async def tunnel_stop():
    if TUNNEL_PID.exists():
        try:
            pid = int(TUNNEL_PID.read_text().strip())
            _subprocess.run(["kill", str(pid)], check=False)
        except Exception:
            pass
        TUNNEL_PID.unlink(missing_ok=True)
    TUNNEL_LOG.write_text("")
    return {"running": False, "url": "", "msg": "Tunnel stopped"}


# ─── GitHub integration ───────────────────────────────────────────────────────

# ─── Azure TTS proxy ─────────────────────────────────────────────────────────

from fastapi.responses import Response as FastAPIResponse


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-ZA-LeahNeural"   # South African English


@app.post("/api/tts")
async def azure_tts(body: TTSRequest):
    """Proxy text-to-speech via Azure Cognitive Services."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    key = settings.get("azure_speech_key", "")
    region = settings.get("azure_speech_region", "eastus")
    if not key:
        raise HTTPException(400, "Azure Speech key not set in Settings")

    # Get access token
    token_url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    ssml = f"""<speak version='1.0' xml:lang='en-ZA'>
        <voice name='{body.voice}'>{body.text[:500]}</voice>
    </speak>"""
    tts_url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, headers={"Ocp-Apim-Subscription-Key": key}) as r:
                if r.status != 200:
                    raise HTTPException(400, "Azure auth failed")
                token = await r.text()
            async with session.post(
                tts_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                },
                data=ssml.encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status != 200:
                    raise HTTPException(502, "Azure TTS failed")
                audio = await r.read()
        return FastAPIResponse(content=audio, media_type="audio/mpeg")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"TTS error: {e}")


@app.get("/api/tts/voices")
async def list_tts_voices():
    """Return curated list of great Azure neural voices."""
    return {"voices": [
        {"id": "en-ZA-LeahNeural",   "name": "Leah (SA English)",    "lang": "en-ZA", "gender": "Female"},
        {"id": "en-ZA-LukeNeural",   "name": "Luke (SA English)",    "lang": "en-ZA", "gender": "Male"},
        {"id": "en-GB-SoniaNeural",  "name": "Sonia (British)",      "lang": "en-GB", "gender": "Female"},
        {"id": "en-GB-RyanNeural",   "name": "Ryan (British)",       "lang": "en-GB", "gender": "Male"},
        {"id": "en-US-AriaNeural",   "name": "Aria (US)",            "lang": "en-US", "gender": "Female"},
        {"id": "en-US-DavisNeural",  "name": "Davis (US)",           "lang": "en-US", "gender": "Male"},
        {"id": "af-ZA-AdriNeural",   "name": "Adri (Afrikaans)",     "lang": "af-ZA", "gender": "Female"},
        {"id": "af-ZA-WillemNeural", "name": "Willem (Afrikaans)",   "lang": "af-ZA", "gender": "Male"},
    ]}


@app.get("/api/github/status")
async def github_status():
    """Check if gh CLI is available and authenticated."""
    available = integ.is_gh_available()
    return {"available": available}


@app.get("/api/projects/{project_id}/github")
async def project_github(project_id: int):
    """Fetch GitHub data (PRs, issues, CI) for a project."""
    async with devdb.get_db() as conn:
        row = await devdb.get_project(conn, project_id)
        settings = await devdb.get_all_settings(conn)
    if not row:
        raise HTTPException(404, "Project not found")
    token = settings.get("github_token", "")
    data = await integ.github_full_status(row["path"], token)
    return data


# ─── Slack integration ────────────────────────────────────────────────────────

class SlackTestRequest(BaseModel):
    webhook_url: str


@app.post("/api/slack/test")
async def test_slack(body: SlackTestRequest):
    """Send a test message to a Slack webhook URL."""
    ok = await integ.slack_send(
        body.webhook_url,
        "✅ Axon connected to Slack successfully. Morning Briefs will appear here."
    )
    if not ok:
        raise HTTPException(400, "Slack webhook failed. Check your URL.")
    return {"sent": True}


# ─── Generic webhooks ─────────────────────────────────────────────────────────

class WebhookTestRequest(BaseModel):
    url: str
    secret: str = ""


@app.post("/api/webhooks/test")
async def test_webhook(body: WebhookTestRequest):
    """Fire a test event to a webhook URL."""
    ok = await integ.fire_webhook(
        body.url, "devbrain.test",
        {"message": "Axon webhook test", "timestamp": "now"},
        body.secret
    )
    if not ok:
        raise HTTPException(400, "Webhook failed. Check your URL.")
    return {"sent": True}


# ─── File browser ─────────────────────────────────────────────────────────────
# Sandboxed to home — lets you browse, read, write desktop files from phone

_HOME = Path.home()


def _safe_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs).expanduser()
    if not p.is_absolute():
        p = _HOME / p
    p = p.resolve()
    if not str(p).startswith(str(_HOME)):
        raise HTTPException(403, "Access outside home directory is not allowed.")
    return p


@app.get("/api/files/browse")
async def files_browse(path: str = "~"):
    p = _safe_path(path)
    if not p.exists():
        raise HTTPException(404, "Path not found")
    if not p.is_dir():
        raise HTTPException(400, "Path is not a directory — use /read")
    items = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name.startswith(".") and entry.name not in (".env", ".envrc"):
                continue  # skip dotfiles except common config ones
            s = entry.stat()
            items.append({
                "name": entry.name,
                "path": str(entry),
                "rel": str(entry.relative_to(_HOME)),
                "is_dir": entry.is_dir(),
                "size": s.st_size,
                "modified": s.st_mtime,
                "ext": entry.suffix.lower() if entry.is_file() else "",
            })
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {
        "path": str(p),
        "rel": str(p.relative_to(_HOME)),
        "parent": str(p.parent.relative_to(_HOME)) if p != _HOME else None,
        "items": items,
    }


@app.get("/api/files/read")
async def files_read(path: str):
    p = _safe_path(path)
    if not p.exists():
        raise HTTPException(404, "File not found")
    if p.is_dir():
        raise HTTPException(400, "Path is a directory — use /browse")
    size = p.stat().st_size
    if size > 512 * 1024:
        raise HTTPException(413, f"File too large ({size // 1024}KB > 512KB limit)")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {"path": str(p), "rel": str(p.relative_to(_HOME)), "content": content, "size": size, "ext": p.suffix.lower()}


class FileWriteBody(BaseModel):
    path: str
    content: str


@app.post("/api/files/write")
async def files_write(body: FileWriteBody):
    p = _safe_path(body.path)
    if p.is_dir():
        raise HTTPException(400, "Path is a directory")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(body.content, encoding="utf-8")
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {"path": str(p), "rel": str(p.relative_to(_HOME)), "size": len(body.content.encode()), "written": True}


# ─── Ollama endpoints ─────────────────────────────────────────────────────────

@app.get("/api/ollama/status")
async def ollama_status():
    """Check if Ollama is running and return available models."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    url = settings.get("ollama_url", "")
    status = await brain.ollama_status(ollama_url=url)
    return status


@app.get("/api/ollama/models")
async def ollama_models():
    """List locally available Ollama models with sizes."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    base_url = (settings.get("ollama_url", "") or brain.OLLAMA_BASE_URL).rstrip("/")
    try:
        import httpx as _hx
        async with _hx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [
            {
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "modified": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
                "parameter_size": m.get("details", {}).get("parameter_size", ""),
                "quantization": m.get("details", {}).get("quantization_level", ""),
            }
            for m in data.get("models", [])
        ]
        return {"models": models, "running": True}
    except Exception as exc:
        return {"models": [], "running": False, "error": str(exc)}


# Recommended local models for Axon — curated for GTX 1060 6GB (6GB VRAM)
RECOMMENDED_MODELS = [
    {"name": "qwen2.5-coder:7b",   "desc": "Best coding model — 7B, 4.7GB",  "category": "code",    "size_gb": 4.7},
    {"name": "qwen2.5-coder:1.5b", "desc": "Ultra-fast code suggestions",     "category": "code",    "size_gb": 1.0},
    {"name": "llama3.2:3b",        "desc": "Fast general-purpose chat",        "category": "general", "size_gb": 2.0},
    {"name": "deepseek-r1:7b",     "desc": "Strong reasoning + code (7B)",     "category": "reason",  "size_gb": 4.7},
    {"name": "nomic-embed-text",   "desc": "Embeddings for semantic search",   "category": "embed",   "size_gb": 0.3},
    {"name": "phi4-mini",          "desc": "Microsoft Phi-4 Mini — 3.8B",      "category": "general", "size_gb": 2.5},
]


@app.get("/api/ollama/recommended")
async def ollama_recommended():
    """Return recommended models with local availability status."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    base_url = (settings.get("ollama_url", "") or brain.OLLAMA_BASE_URL).rstrip("/")
    try:
        import httpx as _hx
        async with _hx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            resp.raise_for_status()
            installed = {m["name"] for m in resp.json().get("models", [])}
    except Exception:
        installed = set()

    gpu_profile = gpu_guard.detect_display_gpu_state()
    result = []
    for m in RECOMMENDED_MODELS:
        safety = gpu_guard.ollama_model_safety(m["name"], gpu_profile)
        result.append(
            {
                **m,
                "installed": m["name"] in installed,
                "risky": safety.get("risky", False),
                "risk_severity": safety.get("severity", "none"),
                "warning": safety.get("warning", ""),
            }
        )
    return {"models": result, "gpu_guard": gpu_profile}


class OllamaPullRequest(BaseModel):
    model: str


@app.post("/api/ollama/pull")
async def ollama_pull(body: OllamaPullRequest, request: Request):
    """Pull an Ollama model with SSE progress streaming."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    base_url = (settings.get("ollama_url", "") or brain.OLLAMA_BASE_URL).rstrip("/")

    async def generate():
        try:
            import httpx as _hx
            async with _hx.AsyncClient(timeout=3600) as client:
                async with client.stream(
                    "POST", f"{base_url}/api/pull",
                    json={"name": body.model},
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if await request.is_disconnected():
                            return
                        try:
                            data = _json.loads(line)
                            yield {"data": _json.dumps(data)}
                        except _json.JSONDecodeError:
                            pass
        except Exception as exc:
            yield {"data": _json.dumps({"error": str(exc), "status": "error"})}

    return EventSourceResponse(generate())


@app.delete("/api/ollama/models/{model_name:path}")
async def ollama_delete_model(model_name: str):
    """Delete a local Ollama model."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    base_url = (settings.get("ollama_url", "") or brain.OLLAMA_BASE_URL).rstrip("/")
    try:
        import httpx as _hx
        async with _hx.AsyncClient(timeout=30) as client:
            resp = await client.request("DELETE", f"{base_url}/api/delete",
                                         json={"name": model_name})
            resp.raise_for_status()
        return {"deleted": model_name}
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ─── System actions ───────────────────────────────────────────────────────────

class SystemActionExecute(BaseModel):
    action: str
    confirmation_text: str = ""
    acknowledge: bool = False


def _command_preview(cmd: list[str]) -> str:
    return " ".join(_shlex.quote(part) for part in cmd)


def _run_capture(cmd: list[str], timeout: int = 20) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        output = "\n".join(part for part in (stdout, stderr) if part).strip()
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output": output,
        }
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "output": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        output = "\n".join(part for part in (stdout, stderr) if part).strip() or "Command timed out"
        return {
            "ok": False,
            "returncode": 124,
            "stdout": stdout,
            "stderr": stderr,
            "output": output,
        }


def _read_pidfile() -> Optional[int]:
    try:
        value = PIDFILE.read_text(encoding="utf-8").strip()
        return int(value) if value.isdigit() else None
    except Exception:
        return None


def _ollama_service_status() -> dict:
    if not OLLAMA_SH.exists():
        return {
            "running": False,
            "mode": "unavailable",
            "detail": "Ollama launcher not found",
            "command_preview": "",
            "output": "",
        }

    result = _run_capture([str(OLLAMA_SH), "status"], timeout=15)
    output = result["output"]
    lower = output.lower()
    mode = "unknown"
    running = False
    detail = output or "No status output"

    if lower.startswith("systemd: active"):
        mode = "systemd"
        running = True
    elif lower.startswith("manual: running"):
        mode = "manual"
        running = True
    elif lower.startswith("running (external process)"):
        mode = "external"
        running = True
    elif "stopped" in lower:
        mode = "stopped"
        running = False
    elif result["ok"] and output:
        mode = "running"
        running = True

    return {
        "running": running,
        "mode": mode,
        "detail": detail,
        "command_preview": _command_preview([str(OLLAMA_SH), "restart"]),
        "output": output,
    }


def _reboot_plan(os_name: str) -> dict:
    if os_name == "Linux":
        return {
            "supported": True,
            "execution_mode": "manual",
            "command_preview": "sudo systemctl reboot",
            "note": "Requires root privileges and immediately disconnects every client.",
        }
    if os_name == "Darwin":
        return {
            "supported": True,
            "execution_mode": "manual",
            "command_preview": "sudo shutdown -r now",
            "note": "Requires an administrator password and immediately disconnects every client.",
        }
    if os_name == "Windows":
        return {
            "supported": True,
            "execution_mode": "manual",
            "command_preview": "shutdown /r /t 0",
            "note": "Requires an elevated shell on most Windows setups and immediately disconnects every client.",
        }
    return {
        "supported": False,
        "execution_mode": "unsupported",
        "command_preview": "",
        "note": f"System reboot is not configured for {os_name}.",
    }


def _restart_devbrain_plan(os_name: str) -> dict:
    server_py = DEVBRAIN_DIR / "server.py"
    if server_py.exists():
        preview = (
            f"kill {os.getpid()} && "
            f"cd {_shlex.quote(str(DEVBRAIN_DIR))} && "
            f"setsid python3 {_shlex.quote(str(server_py))} >> {_shlex.quote(str(DEVBRAIN_LOG))} 2>&1 < /dev/null &"
        )
        return {
            "supported": True,
            "execution_mode": "automatic",
            "command_preview": preview,
            "note": "Safe user-level restart. Existing Axon tabs reconnect after a short interruption.",
        }

    if os_name == "Windows":
        preview = "python %USERPROFILE%\\.devbrain\\server.py"
    else:
        preview = "python3 ~/.devbrain/server.py"
    return {
        "supported": False,
        "execution_mode": "manual",
        "command_preview": preview,
        "note": "Axon launcher files were not found on this machine.",
    }


def _restart_ollama_plan(os_name: str, service: dict) -> dict:
    if os_name == "Linux":
        if service.get("mode") == "systemd":
            return {
                "supported": True,
                "execution_mode": "manual",
                "command_preview": "sudo systemctl restart ollama",
                "note": "Ollama is managed by systemd, so Axon prepares the exact command but does not run sudo automatically.",
            }
        if OLLAMA_SH.exists():
            return {
                "supported": True,
                "execution_mode": "automatic",
                "command_preview": _command_preview([str(OLLAMA_SH), "restart"]),
                "note": "Restarts only the model runtime. Active chats and agents may fail while Ollama comes back.",
            }
        return {
            "supported": False,
            "execution_mode": "unsupported",
            "command_preview": "ollama serve",
            "note": "Ollama launcher script is missing.",
        }

    if os_name == "Darwin":
        return {
            "supported": True,
            "execution_mode": "manual",
            "command_preview": "pkill -f 'ollama serve' && ollama serve",
            "note": "macOS restart is manual because launch methods vary between installations.",
        }
    if os_name == "Windows":
        return {
            "supported": True,
            "execution_mode": "manual",
            "command_preview": "taskkill /IM ollama.exe /F && ollama serve",
            "note": "Windows restart is manual because service setup varies between installations.",
        }
    return {
        "supported": False,
        "execution_mode": "unsupported",
        "command_preview": "",
        "note": f"Ollama restart is not configured for {os_name}.",
    }


def _system_action_specs(os_name: str, ollama_service: dict) -> list[dict]:
    restart_devbrain = _restart_devbrain_plan(os_name)
    restart_ollama = _restart_ollama_plan(os_name, ollama_service)
    reboot_machine = _reboot_plan(os_name)

    return [
        {
            "id": "restart_devbrain",
            "title": "Restart Axon",
            "description": "Restart the local Axon server without touching the rest of the machine.",
            "impact": "Open Axon tabs disconnect briefly, then reconnect when the server is back.",
            "level": "warning",
            "supported": restart_devbrain["supported"],
            "execution_mode": restart_devbrain["execution_mode"],
            "confirmation_text": SYSTEM_ACTION_CONFIRMATIONS["restart_devbrain"],
            "command_preview": restart_devbrain["command_preview"],
            "note": restart_devbrain["note"],
        },
        {
            "id": "restart_ollama",
            "title": "Restart Ollama",
            "description": "Restart the local Ollama runtime separately from Axon.",
            "impact": "Current model pulls, chat streams, and agent runs may fail until Ollama is healthy again.",
            "level": "warning",
            "supported": restart_ollama["supported"],
            "execution_mode": restart_ollama["execution_mode"],
            "confirmation_text": SYSTEM_ACTION_CONFIRMATIONS["restart_ollama"],
            "command_preview": restart_ollama["command_preview"],
            "note": restart_ollama["note"],
        },
        {
            "id": "reboot_machine",
            "title": "Reboot Machine",
            "description": "Prepare a full OS reboot with the exact command for this operating system.",
            "impact": "Every app, model, shell, and remote/mobile client will disconnect immediately.",
            "level": "danger",
            "supported": reboot_machine["supported"],
            "execution_mode": reboot_machine["execution_mode"],
            "confirmation_text": SYSTEM_ACTION_CONFIRMATIONS["reboot_machine"],
            "command_preview": reboot_machine["command_preview"],
            "note": reboot_machine["note"],
        },
    ]


def _queue_devbrain_restart() -> None:
    cmd = (
        f"sleep 1; "
        f"kill {os.getpid()} >/dev/null 2>&1 || true; "
        f"sleep 1; "
        f"cd {_shlex.quote(str(DEVBRAIN_DIR))} && "
        f"setsid python3 {_shlex.quote(str(DEVBRAIN_DIR / 'server.py'))} >> {_shlex.quote(str(DEVBRAIN_LOG))} 2>&1 < /dev/null & "
        f"echo $! > {_shlex.quote(str(PIDFILE))}"
    )
    with open(os.devnull, "wb") as devnull:
        subprocess.Popen(
            ["/usr/bin/env", "bash", "-lc", cmd],
            cwd=str(DEVBRAIN_DIR),
            start_new_session=True,
            stdout=devnull,
            stderr=devnull,
        )


@app.get("/api/system/actions")
async def system_actions():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)

    os_name = _platform.system() or "Unknown"
    ollama_service = _ollama_service_status()
    actions = _system_action_specs(os_name, ollama_service)

    return {
        "host": {
            "os": os_name,
            "release": _platform.release(),
            "hostname": _platform.node() or "localhost",
            "python": _platform.python_version(),
        },
        "services": {
            "axon": {
                "running": True,
                "pid": _read_pidfile() or os.getpid(),
                "port": PORT,
                "url": f"http://localhost:{PORT}",
                "mode": "local-server",
            },
            "devbrain": {
                "running": True,
                "pid": _read_pidfile() or os.getpid(),
                "port": PORT,
                "url": f"http://localhost:{PORT}",
                "mode": "local-server",
            },
            "ollama": {
                **ollama_service,
                "url": (settings.get("ollama_url", "") or brain.OLLAMA_BASE_URL),
            },
        },
        "actions": actions,
    }


@app.post("/api/system/actions/execute")
async def system_action_execute(body: SystemActionExecute, background_tasks: BackgroundTasks):
    action_id = body.action.strip()
    if action_id not in SYSTEM_ACTION_CONFIRMATIONS:
        raise HTTPException(404, "Unknown system action")
    if not body.acknowledge:
        raise HTTPException(400, "Please acknowledge the impact before continuing.")

    expected = SYSTEM_ACTION_CONFIRMATIONS[action_id]
    if body.confirmation_text.strip().upper() != expected:
        raise HTTPException(400, f"Type '{expected}' to confirm this action.")

    os_name = _platform.system() or "Unknown"
    ollama_service = _ollama_service_status()
    actions = {item["id"]: item for item in _system_action_specs(os_name, ollama_service)}
    action = actions[action_id]

    if not action.get("supported"):
        raise HTTPException(400, action.get("note") or "This action is not supported on this machine.")

    if action_id == "restart_devbrain":
        background_tasks.add_task(_queue_devbrain_restart)
        async with devdb.get_db() as conn:
            await devdb.log_event(conn, "maintenance", "Restart Axon requested")
        return {
            "status": "accepted",
            "action": action_id,
            "message": "Axon restart queued. The page should reconnect in a moment.",
            "command_preview": action["command_preview"],
            "execution_mode": action["execution_mode"],
            "reconnect_after_ms": 4500,
        }

    if action_id == "restart_ollama":
        if action["execution_mode"] != "automatic":
            async with devdb.get_db() as conn:
                await devdb.log_event(conn, "maintenance", "Restart Ollama manual command prepared")
            return {
                "status": "manual_required",
                "action": action_id,
                "message": action["note"],
                "command_preview": action["command_preview"],
                "execution_mode": action["execution_mode"],
            }

        result = _run_capture([str(OLLAMA_SH), "restart"], timeout=90)
        async with devdb.get_db() as conn:
            await devdb.log_event(conn, "maintenance", "Restart Ollama requested")
        if not result["ok"]:
            raise HTTPException(500, result["output"] or "Failed to restart Ollama")
        return {
            "status": "completed",
            "action": action_id,
            "message": result["output"] or "Ollama restart requested.",
            "command_preview": action["command_preview"],
            "execution_mode": action["execution_mode"],
            "output": result["output"],
        }

    if action_id == "reboot_machine":
        async with devdb.get_db() as conn:
            await devdb.log_event(conn, "maintenance", "Reboot command prepared")
        return {
            "status": "manual_required",
            "action": action_id,
            "message": action["note"],
            "command_preview": action["command_preview"],
            "execution_mode": action["execution_mode"],
        }

    raise HTTPException(400, "Unsupported system action")


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "port": PORT}


# ─── PWA — manifest + service worker ─────────────────────────────────────────

import time as _startup_time
_SW_CACHE_VERSION = f"axon-{int(_startup_time.time())}"

@app.get("/manifest.json")
async def pwa_manifest():
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "id": "/",
        "name": "Axon",
        "short_name": "Axon",
        "description": "Local AI Operator — console, workspaces, missions, secure vault",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#020617",
        "theme_color": "#0f172a",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ],
        "categories": ["productivity", "developer-tools"],
        "shortcuts": [
            {"name": "Console", "url": "/", "description": "Open Axon Console"},
            {"name": "Missions", "url": "/", "description": "Review active missions"},
        ]
    })


@app.get("/icons/{filename}")
async def serve_icon(filename: str):
    """Serve PWA icon PNG files."""
    from fastapi.responses import FileResponse
    icon_path = UI_DIR / "icons" / filename
    if not icon_path.exists() or not filename.endswith(".png"):
        raise HTTPException(404, "Icon not found")
    return FileResponse(str(icon_path), media_type="image/png")


@app.get("/sw.js")
async def service_worker():
    """Service worker — PWA install support.
    Strategy:
      - HTML pages (/): network-first (always fresh, fallback to cache if offline)
      - API calls (/api/*): network-only (never cache live data)
      - Static assets (icons, manifest): cache-first (immutable)
    Cache version is set once at server startup — stable until restart.
    """
    from fastapi.responses import Response as FastAPIResponse
    cache_version = _SW_CACHE_VERSION
    sw_code = f"""
const CACHE = '{cache_version}';
const STATIC = ['/icons/icon-192.png', '/icons/icon-512.png', '/manifest.json'];

self.addEventListener('install', e => {{
  // Pre-cache only truly static assets (icons never change)
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
}});

self.addEventListener('activate', e => {{
  // Delete ALL old caches (previous versions)
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => clients.claim())
  );
}});

self.addEventListener('fetch', e => {{
  const url = new URL(e.request.url);

  // API calls: network-only, never cache
  if (url.pathname.startsWith('/api/')) {{
    e.respondWith(fetch(e.request));
    return;
  }}

  // Static assets (icons): cache-first
  if (url.pathname.startsWith('/icons/')) {{
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request))
    );
    return;
  }}

  // HTML pages: network-first, fall back to cache only if offline
  e.respondWith(
    fetch(e.request)
      .then(res => {{
        // Update cache with fresh response
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      }})
      .catch(() => caches.match(e.request))
  );
}});
"""
    return FastAPIResponse(content=sw_code, media_type="application/javascript",
                           headers={
                               "Service-Worker-Allowed": "/",
                               "Cache-Control": "no-store",  # SW itself must never be cached
                           })


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",   # bind all interfaces — enables Tailscale + LAN access
        port=PORT,
        reload=False,
        log_level="warning",
    )
