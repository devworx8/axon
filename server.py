"""
Axon — Main FastAPI Server
Start with: python3 ~/.devbrain/server.py
Access at:  http://localhost:7734
"""

import asyncio
import importlib.util
import io
import sys
import os
import platform as _platform
import shlex as _shlex
import shutil
import sqlite3 as _sqlite3
import subprocess
import tempfile
import time as _time
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib import error as _urlerror, request as _urlrequest

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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
import resource_bank
import memory_engine
from model_router import resolve_model_for_role

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
)

_live_operator_snapshot = {
    "active": False,
    "mode": "idle",
    "phase": "observe",
    "title": "Standing by",
    "detail": "Axon is ready for the next request.",
    "tool": "",
    "summary": "",
    "workspace_id": None,
    "started_at": "",
    "updated_at": "",
}
_terminal_processes: dict[int, dict] = {}
# PTY WebSocket sessions: session_id → {pty, ws_set, task}
_pty_sessions: dict[str, dict] = {}
_domain_probe_cache = {
    "url": "",
    "active": False,
    "status": "planned",
    "detail": "",
    "checked_at": 0.0,
}
_browser_action_state = {
    "session": {
        "connected": False,
        "url": "",
        "title": "",
        "last_seen_at": "",
        "mode": "approval_required",
    },
    "proposals": [],
    "history": [],
    "next_id": 1,
}
_local_voice_state = {
    "speaking": False,
    "last_engine": "",
    "last_error": "",
    "updated_at": "",
}
_whisper_model_cache: dict[str, object] = {}
_piper_voice_cache: dict[str, object] = {}


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _probe_public_origin(public_base_url: str, enabled: bool) -> dict:
    if not enabled or not public_base_url:
        return {
            "active": False,
            "status": "planned",
            "detail": "Stable domain is not enabled yet.",
        }
    now = _time.time()
    if (
        _domain_probe_cache.get("url") == public_base_url
        and now - float(_domain_probe_cache.get("checked_at") or 0) < 60
    ):
        return {
            "active": bool(_domain_probe_cache.get("active")),
            "status": str(_domain_probe_cache.get("status") or "configured"),
            "detail": str(_domain_probe_cache.get("detail") or ""),
        }
    probe_url = f"{public_base_url.rstrip('/')}/api/health"
    active = False
    status = "configured"
    detail = "Stable domain is configured, but Axon has not answered on /api/health yet."
    try:
        req = _urlrequest.Request(probe_url, headers={"Accept": "application/json"})
        with _urlrequest.urlopen(req, timeout=3) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = _json.loads(raw)
            active = payload.get("status") == "ok"
            status = "active" if active else "configured"
            detail = "Stable domain reaches Axon successfully." if active else "Stable domain responded, but Axon health was not OK."
    except _urlerror.HTTPError as exc:
        detail = f"Stable domain responded with HTTP {exc.code}. It is not pointing at Axon yet."
    except Exception as exc:
        detail = f"Stable domain is configured, but Axon could not confirm it yet: {exc}"
    _domain_probe_cache.update(
        {
            "url": public_base_url,
            "active": active,
            "status": status,
            "detail": detail,
            "checked_at": now,
        }
    )
    return {"active": active, "status": status, "detail": detail}


def _set_live_operator(
    *,
    active: bool,
    mode: str,
    phase: str,
    title: str,
    detail: str = "",
    tool: str = "",
    summary: str = "",
    workspace_id: Optional[int] = None,
    preserve_started: bool = False,
):
    started_at = _live_operator_snapshot.get("started_at") if preserve_started else _now_iso()
    if not started_at:
        started_at = _now_iso()
    _live_operator_snapshot.update(
        {
            "active": active,
            "mode": mode,
            "phase": phase,
            "title": title,
            "detail": detail,
            "tool": tool,
            "summary": summary or _live_operator_snapshot.get("summary", ""),
            "workspace_id": workspace_id,
            "started_at": started_at if active else "",
            "updated_at": _now_iso(),
        }
    )


def _connection_snapshot() -> dict:
    config = _connection_config()
    probe = _probe_public_origin(config["public_base_url"], config["stable_domain_enabled"])
    tunnel_url = _read_tunnel_url(config)
    domain_active = bool(probe["active"])
    if domain_active:
        state = "domain_active"
        label = "Domain Active"
    elif tunnel_url:
        state = "tunnel_active"
        label = "Tunnel Active"
    else:
        state = "local_only"
        label = "Local Only"
    return {
        "connected": True,
        "state": state,
        "label": label,
        "local_only": not bool(tunnel_url) and not domain_active,
        "tunnel_active": bool(tunnel_url),
        "tunnel_url": tunnel_url,
        "domain_active": domain_active,
        "stable_domain": config["stable_domain"],
        "stable_domain_url": config["public_base_url"],
        "stable_domain_enabled": config["stable_domain_enabled"],
        "stable_domain_status": probe["status"],
        "stable_domain_detail": probe["detail"],
        "tunnel_mode": config.get("tunnel_mode", "trycloudflare"),
        "named_tunnel_ready": config.get("named_tunnel_ready", False),
    }


def _serialize_browser_action_state() -> dict:
    proposals = sorted(
        _browser_action_state["proposals"],
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
    history = sorted(
        _browser_action_state["history"],
        key=lambda item: item.get("updated_at", item.get("created_at", "")),
        reverse=True,
    )
    return {
        "session": dict(_browser_action_state["session"]),
        "pending_count": sum(1 for item in proposals if item.get("status") == "pending"),
        "proposals": [dict(item) for item in proposals[:20]],
        "history": [dict(item) for item in history[:20]],
        "approval_mode": _browser_action_state["session"].get("mode", "approval_required"),
    }


def _next_browser_action_id() -> int:
    current = int(_browser_action_state.get("next_id") or 1)
    _browser_action_state["next_id"] = current + 1
    return current


def _python_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _resolve_ffmpeg_path() -> str:
    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path
    if _python_module_available("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg

            bundled_path = str(imageio_ffmpeg.get_ffmpeg_exe() or "").strip()
            if bundled_path and Path(bundled_path).exists():
                return bundled_path
        except Exception:
            return ""
    return ""


def _piper_python_available() -> bool:
    return _python_module_available("piper.voice")


def _local_voice_paths(settings: Optional[dict] = None) -> dict:
    settings = settings or _read_settings_sync()
    return {
        "piper_model_path": str(settings.get("local_tts_model_path") or os.environ.get("AXON_PIPER_MODEL_PATH") or "").strip(),
        "piper_config_path": str(settings.get("local_tts_config_path") or os.environ.get("AXON_PIPER_CONFIG_PATH") or "").strip(),
        "stt_model": str(settings.get("local_stt_model") or os.environ.get("AXON_WHISPER_MODEL") or "base").strip() or "base",
        "language": str(settings.get("local_stt_language") or os.environ.get("AXON_WHISPER_LANGUAGE") or "en").strip() or "en",
    }


def _local_voice_status(settings: Optional[dict] = None) -> dict:
    settings = settings or _read_settings_sync()
    paths = _local_voice_paths(settings)
    ffmpeg_path = _resolve_ffmpeg_path()
    piper_path = shutil.which("piper") or ""
    piper_python_available = _piper_python_available()
    faster_whisper_available = _python_module_available("faster_whisper")
    whisper_available = _python_module_available("whisper")
    piper_model_ready = bool(paths["piper_model_path"] and Path(paths["piper_model_path"]).exists())
    piper_config_ready = bool(not paths["piper_config_path"] or Path(paths["piper_config_path"]).exists())
    transcription_available = bool(ffmpeg_path and (faster_whisper_available or whisper_available))
    piper_engine = "binary" if piper_path else ("python" if piper_python_available else "")
    synthesis_available = bool((piper_path or piper_python_available) and piper_model_ready and piper_config_ready)
    available = transcription_available or synthesis_available
    detail_parts: list[str] = []
    if not ffmpeg_path:
        detail_parts.append("ffmpeg missing")
    if not (faster_whisper_available or whisper_available):
        detail_parts.append("Whisper backend missing")
    if not (piper_path or piper_python_available):
        detail_parts.append("Piper runtime missing")
    if (piper_path or piper_python_available) and not piper_model_ready:
        detail_parts.append("Piper model not configured")
    if (piper_path or piper_python_available) and not piper_config_ready:
        detail_parts.append("Piper config path invalid")
    ready_parts: list[str] = []
    if transcription_available:
        ready_parts.append("Local transcription ready")
    if synthesis_available:
        ready_parts.append("Local synthesis ready")
    if ready_parts and detail_parts:
        detail = f"{' • '.join(ready_parts)}; {'; '.join(detail_parts)}"
    elif ready_parts:
        detail = " • ".join(ready_parts)
    else:
        detail = "; ".join(detail_parts) or "Local voice dependencies not installed"
    return {
        "available": available,
        "preferred_mode": "local" if available else "browser",
        "transcription_available": transcription_available,
        "synthesis_available": synthesis_available,
        "ffmpeg_available": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path,
        "faster_whisper_available": faster_whisper_available,
        "whisper_available": whisper_available,
        "piper_available": bool(piper_path or piper_python_available),
        "piper_binary_available": bool(piper_path),
        "piper_python_available": piper_python_available,
        "piper_engine": piper_engine,
        "piper_model_ready": piper_model_ready,
        "piper_config_ready": piper_config_ready,
        "piper_model_path": paths["piper_model_path"],
        "piper_config_path": paths["piper_config_path"],
        "stt_model": paths["stt_model"],
        "language": paths["language"],
        "detail": detail,
        "state": dict(_local_voice_state),
    }


def _run_ffmpeg_to_wav(input_path: str, output_path: str):
    ffmpeg_path = _resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise HTTPException(503, "Local voice transcription requires ffmpeg")
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        input_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, check=False, timeout=90)
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise HTTPException(502, f"ffmpeg conversion failed: {stderr[:240] or 'unknown error'}")


def _transcribe_local_audio(wav_path: str, *, model_name: str, language: str) -> tuple[str, str]:
    if _python_module_available("faster_whisper"):
        from faster_whisper import WhisperModel

        cache_key = f"faster:{model_name}"
        model = _whisper_model_cache.get(cache_key)
        if model is None:
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _whisper_model_cache[cache_key] = model
        segments, _info = model.transcribe(wav_path, language=language or None, vad_filter=False)
        text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
        return text, "faster-whisper"
    if _python_module_available("whisper"):
        import whisper

        cache_key = f"whisper:{model_name}"
        model = _whisper_model_cache.get(cache_key)
        if model is None:
            model = whisper.load_model(model_name)
            _whisper_model_cache[cache_key] = model
        result = model.transcribe(wav_path, language=language or None, fp16=False)
        return str(result.get("text") or "").strip(), "whisper"
    raise HTTPException(503, "Local transcription requires faster-whisper or whisper")


def _speak_local_text(text: str, *, model_path: str, config_path: str = "") -> tuple[bytes, str]:
    piper_path = shutil.which("piper")
    if not model_path or not Path(model_path).exists():
        raise HTTPException(503, "Local speech synthesis requires a configured Piper model path")
    if config_path and not Path(config_path).exists():
        raise HTTPException(503, "Local speech synthesis config path is invalid")
    if piper_path:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            wav_path = output_file.name
        cmd = [piper_path, "--model", model_path, "--output_file", wav_path]
        if config_path and Path(config_path).exists():
            cmd.extend(["--config", config_path])
        result = subprocess.run(
            cmd,
            input=text[:1200].encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=90,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise HTTPException(502, f"Piper synthesis failed: {stderr[:240] or 'unknown error'}")
        try:
            return Path(wav_path).read_bytes(), "piper"
        finally:
            Path(wav_path).unlink(missing_ok=True)
    if _piper_python_available():
        try:
            from piper.voice import PiperVoice

            cache_key = f"{model_path}:{config_path or ''}"
            voice = _piper_voice_cache.get(cache_key)
            if voice is None:
                voice = PiperVoice.load(model_path, config_path=config_path or None, use_cuda=False)
                _piper_voice_cache[cache_key] = voice
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text[:1200], wav_file)
            return buffer.getvalue(), "piper-python"
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"Piper Python synthesis failed: {exc}")
    raise HTTPException(503, "Local speech synthesis requires Piper or the piper Python package")


def _read_settings_sync() -> dict:
    try:
        conn = _sqlite3.connect(devdb.DB_PATH)
        conn.row_factory = _sqlite3.Row
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
        return {str(row["key"]): row["value"] for row in rows}
    except Exception:
        return {}


def _setting_truthy(raw, default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_domain(value: str | None) -> str:
    domain = str(value or "axon.edudashpro.org.za").strip()
    domain = domain.replace("https://", "").replace("http://", "").strip().strip("/")
    return domain or "axon.edudashpro.org.za"


def _normalize_public_base_url(value: str | None, domain: str) -> str:
    url = str(value or "").strip()
    if not url:
        return f"https://{domain}"
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url.rstrip("/")


def _connection_config(settings: Optional[dict] = None) -> dict:
    settings = settings or _read_settings_sync()
    stable_domain = _normalize_domain(settings.get("stable_domain"))
    public_base_url = _normalize_public_base_url(settings.get("public_base_url"), stable_domain)
    tunnel_mode = str(settings.get("tunnel_mode") or "trycloudflare").strip() or "trycloudflare"
    cloudflare_tunnel_token = str(settings.get("cloudflare_tunnel_token") or "").strip()
    return {
        "stable_domain": stable_domain,
        "public_base_url": public_base_url,
        "stable_domain_enabled": _setting_truthy(settings.get("stable_domain_enabled")),
        "tunnel_mode": tunnel_mode,
        "cloudflare_tunnel_token": cloudflare_tunnel_token,
        "named_tunnel_ready": tunnel_mode == "named" and bool(cloudflare_tunnel_token),
    }


# _probe_public_origin — dict-returning version defined earlier in this file


def _terminal_mode_value(raw: str | None, fallback: str = "read_only") -> str:
    value = str(raw or fallback).strip().lower()
    return value if value in {"read_only", "approval_required", "simulation"} else fallback


def _command_is_blocked(command: str) -> bool:
    lowered = f" {str(command or '').strip().lower()} "
    return any(pattern in lowered for pattern in BLOCKED_TERMINAL_PATTERNS)


def _command_is_read_only(command: str) -> bool:
    lowered = str(command or "").strip().lower()
    if not lowered:
        return False
    return any(lowered == prefix or lowered.startswith(prefix + " ") for prefix in SAFE_TERMINAL_PREFIXES)


def _serialize_terminal_session(row, *, running: bool = False, recent_events: Optional[list[dict]] = None) -> dict:
    item = dict(row)
    item["running"] = bool(running)
    item["recent_events"] = recent_events or []
    return item


def _serialize_terminal_event(row) -> dict:
    return dict(row)


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
    asyncio.create_task(sched_module.trigger_scan_now(trigger_type="startup"))

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

# In-memory session store: { token_str: expiry_datetime }
_auth_sessions: dict[str, datetime] = {}
_AUTH_SESSION_HOURS = 72  # sessions last 3 days

# Rate-limit login attempts: { ip_str: (fail_count, last_attempt_time) }
_login_attempts: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 300  # 5-minute lockout after 5 failures


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
                "/api/health", "/api/tunnel/status"}
_AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/icons/", "/js/", "/styles.css", "/ws/")

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
async def auth_login(body: PinLogin, request: Request):
    """Verify PIN and return a session token."""
    import time as _time_mod
    client_ip = request.client.host if request.client else "unknown"
    fails, last_t = _login_attempts.get(client_ip, (0, 0.0))
    if fails >= _LOGIN_MAX_ATTEMPTS and (_time_mod.time() - last_t) < _LOGIN_LOCKOUT_SECONDS:
        raise HTTPException(429, f"Too many failed attempts. Try again in {int(_LOGIN_LOCKOUT_SECONDS - (_time_mod.time() - last_t))}s.")
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    if not pin_hash:
        raise HTTPException(400, "No PIN set — use /api/auth/setup first")
    if _hash_pin(body.pin.strip()) != pin_hash:
        _login_attempts[client_ip] = (fails + 1, _time_mod.time())
        raise HTTPException(401, "Wrong PIN")
    _login_attempts.pop(client_ip, None)
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
    html = ui_file.read_text().replace("__AXON_BUILD_VERSION__", _SW_CACHE_VERSION)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/manual", response_class=HTMLResponse)
@app.get("/manual.html", response_class=HTMLResponse)
async def serve_manual():
    manual_file = UI_DIR / "manual.html"
    if not manual_file.exists():
        return HTMLResponse("<h1>Manual not found</h1>", status_code=404)
    return HTMLResponse(
        manual_file.read_text().replace("__AXON_BUILD_VERSION__", _SW_CACHE_VERSION),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# ─── Projects ────────────────────────────────────────────────────────────────

# ─── Users / Account foundations ─────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: Optional[str] = ''
    username: Optional[str] = ''
    role: Optional[str] = 'operator'


@app.get("/api/users")
async def list_users():
    async with devdb.get_db() as conn:
        cur = await conn.execute(
            "SELECT id, name, email, username, avatar_url, role, status, is_active, created_at FROM users ORDER BY id"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


@app.post("/api/users")
async def create_user(body: UserCreate):
    async with devdb.get_db() as conn:
        cur = await conn.execute(
            "INSERT INTO users (name, email, username, role) VALUES (?, ?, ?, ?)",
            (body.name, body.email or '', body.username or '', body.role or 'operator')
        )
        await conn.commit()
        uid = cur.lastrowid
        await conn.execute(
            "INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (uid,)
        )
        await conn.commit()
        row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (uid,))).fetchone()
        return dict(row)


@app.get("/api/users/me")
async def get_current_user():
    """Return the primary local user, creating a default one if needed."""
    async with devdb.get_db() as conn:
        row = await (await conn.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY id LIMIT 1"
        )).fetchone()
        if row:
            return dict(row)
        # Auto-create a default local user on first use
        import socket
        hostname = socket.gethostname()
        cur = await conn.execute(
            "INSERT INTO users (name, email, username, role) VALUES (?, ?, ?, 'operator')",
            ('Local Operator', '', hostname.lower())
        )
        await conn.commit()
        uid = cur.lastrowid
        await conn.execute("INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)", (uid,))
        await conn.commit()
        row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (uid,))).fetchone()
        return dict(row)


@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, body: dict):
    allowed = {'name', 'email', 'username', 'avatar_url', 'role', 'status'}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    async with devdb.get_db() as conn:
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [user_id]
        await conn.execute(f"UPDATE users SET {sets}, updated_at = datetime('now') WHERE id = ?", vals)
        await conn.commit()
        row = await (await conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))).fetchone()
        return dict(row) if row else {}


@app.get("/api/teams")
async def list_teams():
    async with devdb.get_db() as conn:
        cur = await conn.execute("SELECT * FROM teams ORDER BY id")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ─── Projects ─────────────────────────────────────────────────────────────────

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
        ai = await _ai_params(settings, conn)

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
        ai = await _ai_params(settings, conn)
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
    asyncio.create_task(sched_module.trigger_scan_now(trigger_type="manual"))
    return {"status": "scan started"}


# ─── Prompts ─────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    project_id: Optional[int] = None
    title: str
    content: str
    tags: str = ""
    meta: Optional[dict] = None


@app.get("/api/prompts")
async def list_prompts(project_id: Optional[int] = None):
    async with devdb.get_db() as conn:
        rows = await devdb.get_prompts(conn, project_id=project_id)
        result = [_serialize_prompt(r) for r in rows]
        return result


@app.post("/api/prompts")
async def create_prompt(body: PromptCreate):
    async with devdb.get_db() as conn:
        prompt_id = await devdb.save_prompt(
            conn, body.project_id, body.title, body.content, body.tags,
            meta_json=_json.dumps(body.meta or {}),
        )
        await devdb.log_event(
            conn, "prompt_saved", f"Saved prompt: {body.title}",
            project_id=body.project_id
        )
        row = await devdb.get_prompt(conn, prompt_id)
        return _serialize_prompt(row)


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
    meta: Optional[dict] = None


@app.patch("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: int, body: PromptUpdate):
    async with devdb.get_db() as conn:
        fields = {k: v for k, v in body.dict().items() if v is not None}
        if "meta" in fields:
            fields["meta_json"] = _json.dumps(fields.pop("meta") or {})
        if not fields:
            raise HTTPException(400, "Nothing to update")
        set_clauses = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [prompt_id]
        await conn.execute(
            f"UPDATE prompts SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
            values
        )
        await conn.commit()
        row = await devdb.get_prompt(conn, prompt_id)
        return _serialize_prompt(row)


@app.post("/api/prompts/{prompt_id}/pin")
async def toggle_pin(prompt_id: int):
    async with devdb.get_db() as conn:
        cur = await conn.execute("SELECT id FROM prompts WHERE id = ?", (prompt_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Prompt not found")
        await conn.execute(
            "UPDATE prompts SET pinned = CASE WHEN pinned = 1 THEN 0 ELSE 1 END, "
            "updated_at = datetime('now') WHERE id = ?",
            (prompt_id,)
        )
        await conn.commit()
        cur = await conn.execute("SELECT pinned FROM prompts WHERE id = ?", (prompt_id,))
        row = await cur.fetchone()
        return {"pinned": bool(row["pinned"])}


@app.post("/api/prompts/{prompt_id}/use")
async def use_prompt(prompt_id: int):
    async with devdb.get_db() as conn:
        await devdb.increment_prompt_usage(conn, prompt_id)
        return {"ok": True}


class EnhanceRequest(BaseModel):
    content: str
    project_context: Optional[str] = None


@app.post("/api/prompts/enhance")
async def enhance_prompt(body: EnhanceRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = await _ai_params(settings, conn)
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
    title: Optional[str] = None
    detail: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None
    project_id: Optional[int] = None


class BrowserSessionUpdate(BaseModel):
    connected: Optional[bool] = None
    url: Optional[str] = None
    title: Optional[str] = None
    mode: Optional[str] = None


class BrowserActionProposalCreate(BaseModel):
    action_type: str
    summary: str
    target: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    risk: Optional[str] = "medium"
    scope: Optional[str] = "browser_act"
    requires_confirmation: Optional[bool] = True
    metadata: Optional[dict] = None


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, body: TaskUpdate):
    async with devdb.get_db() as conn:
        fields = body.model_dump(exclude_none=True)
        if not fields:
            raise HTTPException(400, "No fields to update")
        if "status" in fields and len(fields) == 1:
            await devdb.update_task_status(conn, task_id, fields["status"])
        else:
            await devdb.update_task(conn, task_id, **fields)
        return {"updated": True}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    async with devdb.get_db() as conn:
        await devdb.delete_task(conn, task_id)
        return {"deleted": True}


@app.post("/api/tasks/suggest")
async def suggest_tasks():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        ai = await _ai_params(settings, conn)
        projects = [dict(r) for r in await devdb.get_projects(conn)]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        suggestions = await brain.suggest_tasks(
            projects, tasks, **ai
        )
        return {"suggestions": suggestions}


# ─── AI backend helper ────────────────────────────────────────────────────────

async def _ai_params(settings: dict, conn=None) -> dict:
    """Extract AI backend params from settings dict, resolving keys from vault when available."""
    backend = settings.get("ai_backend", "ollama")
    api_runtime = provider_registry.runtime_api_config(settings)
    api_key = api_runtime.get("api_key", "")
    provider_id = api_runtime.get("provider_id", "anthropic")

    # Resolve API key from vault when unlocked
    if devvault.VaultSession.is_unlocked() and (not api_key or api_key == "set"):
        async def _resolve(db):
            return await devvault.vault_resolve_provider_key(db, provider_id)
        if conn:
            vault_key = await _resolve(conn)
        else:
            async with devdb.get_db() as _conn:
                vault_key = await _resolve(_conn)
        if vault_key:
            api_key = vault_key

    cli_path = settings.get("claude_cli_path", "")
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    if backend == "api" and not api_key:
        provider_label = api_runtime.get("provider_label", "External API")
        raise HTTPException(400, f"{provider_label} key not set. Add it to the Secure Vault or Settings → Runtime.")
    if backend == "cli" and not cli_path and not brain._find_cli():
        raise HTTPException(400, "CLI agent not found. Set the path in Settings.")
    return {
        "api_key": api_key,
        "api_provider": provider_id,
        "api_base_url": api_runtime.get("api_base_url", ""),
        "api_model": api_runtime.get("api_model", ""),
        "backend": backend, "cli_path": cli_path,
        "ollama_url": ollama_url, "ollama_model": ollama_model,
    }


def _composer_options_dict(composer_options) -> dict:
    if composer_options is None:
        return {}
    if isinstance(composer_options, dict):
        return {k: v for k, v in composer_options.items() if v not in (None, "", [], {})}
    if hasattr(composer_options, "model_dump"):
        return {k: v for k, v in composer_options.model_dump(exclude_none=True).items() if v not in (None, "", [], {})}
    return {}


def _composer_instruction_block(options: dict) -> str:
    if not options:
        return ""
    lines = ["## Composer Directives"]
    intelligence = options.get("intelligence_mode") or "ask"
    action = options.get("action_mode") or ""
    agent_role = options.get("agent_role") or ""
    external_mode = options.get("external_mode") or "local_first"
    external_provider_hint = options.get("external_provider_hint") or ""
    research_pack_title = options.get("research_pack_title") or ""
    terminal_mode = _terminal_mode_value(options.get("terminal_mode"), "read_only") if options.get("terminal_mode") else ""

    lines.append(f"- Intelligence mode: {str(intelligence).replace('_', ' ').title()}")
    if action:
        lines.append(f"- Action mode: {str(action).replace('_', ' ').title()}")
    if agent_role:
        if str(agent_role).lower() == "multi_agent":
            lines.append("- Agent mode: Multi-Agent orchestration is preferred for planning, execution, and verification.")
        else:
            lines.append(f"- Agent role: {str(agent_role).replace('_', ' ').title()} Agent")
    if options.get("use_workspace_memory", True):
        lines.append("- Use workspace memory when it is relevant.")
    if options.get("include_timeline_history"):
        lines.append("- Include mission and timeline history when it helps.")
    if options.get("require_approval"):
        lines.append("- Require approval before risky actions or destructive changes.")
    if options.get("safe_mode", True):
        lines.append("- Safe mode is on: avoid destructive or high-risk actions.")
    if options.get("simulation_mode"):
        lines.append("- Simulation mode is on: plan and simulate, do not make changes.")
    if research_pack_title:
        lines.append(f"- Use the selected Research Pack: {research_pack_title}.")
    if options.get("live_desktop_feed"):
        lines.append("- Keep the live desktop and operator feed updated with visible progress while working.")
    if terminal_mode:
        if terminal_mode == "read_only":
            lines.append("- Terminal mode is read-only. Limit commands to safe inspection, logs, tests, and status checks.")
        elif terminal_mode == "approval_required":
            lines.append("- Terminal mode requires approval before executing commands that change the system.")
        elif terminal_mode == "simulation":
            lines.append("- Terminal mode is simulation-only. Explain the command plan instead of running it.")
    if external_mode == "disable_external_calls":
        lines.append("- Do not use cloud or external services. Stay fully local-first.")
    elif external_mode == "cloud_assist":
        lines.append("- Cloud assist is allowed when it materially improves the answer.")
    elif external_mode == "external_agent":
        lines.append("- External specialist agents are allowed if enabled, but local-first remains preferred.")
    if external_provider_hint:
        lines.append(f"- If cloud help is needed, prefer this provider family: {str(external_provider_hint).replace('_', ' ').title()}.")

    if intelligence == "deep_research":
        lines.append("- Perform multi-step retrieval and synthesis. Return summary, key findings, supporting context, and gaps.")
        lines.append("- Search local memory first, then attached resources, then workspace memory, and only use cloud help if allowed and truly necessary.")
    elif intelligence == "summarize":
        lines.append("- Compress the input and memory into a concise summary with minimal repetition.")
    elif intelligence == "explain":
        lines.append("- Explain clearly and simply, like a calm operator teaching a beginner.")
    elif intelligence == "compare":
        lines.append("- Compare options with pros, trade-offs, and a recommendation.")
    elif intelligence == "analyze":
        lines.append("- Inspect the available context carefully before concluding.")
    elif intelligence == "build_brief":
        lines.append("- Produce a structured brief with a clear summary, core goals, supporting context, and next actions.")

    return "\n".join(lines)


def _composer_memory_layers(options: dict, *, has_attached_resources: bool = False) -> list[str]:
    intelligence = str(options.get("intelligence_mode") or "ask").lower()
    layers: list[str] = []
    if options.get("use_workspace_memory", True):
        layers.append("workspace")
    if intelligence == "deep_research" or options.get("select_research_pack") or options.get("research_pack_id"):
        layers.append("resource")
    if options.get("include_timeline_history") or intelligence in {"deep_research", "analyze"}:
        layers.append("mission")
    layers.append("user")
    if has_attached_resources and "resource" not in layers:
        layers.append("resource")
    deduped: list[str] = []
    for layer in layers:
        if layer not in deduped:
            deduped.append(layer)
    return deduped


def _loads_json_object(value: str | None) -> dict:
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        parsed = _json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _serialize_prompt(row) -> dict:
    item = dict(row)
    item["meta"] = _loads_json_object(item.get("meta_json"))
    return item


def _serialize_memory_item(row) -> dict:
    item = dict(row)
    item["meta"] = _loads_json_object(item.get("meta_json"))
    item["pinned"] = bool(item.get("pinned"))
    return item


def _serialize_research_pack(row, *, resources: Optional[list[dict]] = None) -> dict:
    item = dict(row)
    item["pinned"] = bool(item.get("pinned"))
    item["resource_count"] = int(item.get("resource_count") or 0)
    if resources is not None:
        item["resources"] = resources
    return item


def _local_role_for_composer(options: dict, agent_request: bool = False) -> str:
    agent_role = str(options.get("agent_role") or "").lower()
    intelligence = str(options.get("intelligence_mode") or "ask").lower()
    action = str(options.get("action_mode") or "").lower()

    if agent_role in {"planner", "reviewer", "repair"}:
        return "reasoning"
    if agent_role == "coder":
        return "code"
    if agent_role == "scanner":
        return "general"
    if action in {"fix_repair", "optimize", "refactor"}:
        return "code"
    if intelligence in {"deep_research", "compare"}:
        return "reasoning"
    if intelligence in {"summarize", "explain", "generate"}:
        return "general"
    if agent_request:
        return "code"
    return "general"


async def _effective_ai_params(settings: dict, composer_options: dict, *, conn=None, agent_request: bool = False, requested_model: str = "") -> dict:
    ai = dict(await _ai_params(settings, conn))
    external_mode = str(composer_options.get("external_mode") or "local_first").lower()

    if not agent_request:
        if external_mode == "disable_external_calls" and ai.get("backend") != "ollama":
            ai["backend"] = "ollama"
        elif external_mode in {"cloud_assist", "external_agent"} and ai.get("backend") == "ollama":
            api_runtime = provider_registry.runtime_api_config(settings)
            provider_id = api_runtime.get("provider_id", "anthropic")
            api_key = api_runtime.get("api_key", "")
            # Resolve from vault if no key in settings
            if not api_key and devvault.VaultSession.is_unlocked():
                if conn:
                    api_key = await devvault.vault_resolve_provider_key(conn, provider_id)
                else:
                    async with devdb.get_db() as _conn:
                        api_key = await devvault.vault_resolve_provider_key(_conn, provider_id)
            if api_key:
                ai.update(
                    {
                        "backend": "api",
                        "api_key": api_key,
                        "api_provider": provider_id,
                        "api_base_url": api_runtime.get("api_base_url", ""),
                        "api_model": api_runtime.get("api_model", ""),
                    }
                )

    if ai.get("backend") == "ollama":
        if requested_model:
            ai["ollama_model"] = requested_model
            return ai
        available_models = await brain.ollama_list_models(settings.get("ollama_url", ""))
        route = resolve_model_for_role(
            _local_role_for_composer(composer_options, agent_request=agent_request),
            available_models,
            runtime_manager.build_router_config(settings),
        )
        if route.get("selected_model"):
            ai["ollama_model"] = route["selected_model"]
    else:
        if requested_model:
            ai["api_model"] = requested_model
            return ai
        # API backend: pick role-specific model when available
        role = _local_role_for_composer(composer_options, agent_request=agent_request)
        provider_id = ai.get("api_provider", "")
        role_map = brain.API_MODEL_BY_ROLE.get(provider_id, {})
        if role in role_map:
            ai["api_model"] = role_map[role]
    return ai


async def _memory_bundle(
    conn,
    *,
    user_message: str,
    project_id: Optional[int],
    resource_ids: list[int],
    settings: dict,
    composer_options: dict,
) -> dict:
    await memory_engine.sync_memory_layers(conn, settings)
    layers = _composer_memory_layers(composer_options, has_attached_resources=bool(resource_ids))
    intelligence = str(composer_options.get("intelligence_mode") or "ask").lower()
    limit = 8 if intelligence == "deep_research" else 5
    results = await memory_engine.search_memory(
        conn,
        query=user_message,
        settings=settings,
        workspace_id=project_id,
        layers=layers,
        limit=limit,
    )
    return {
        "items": results,
        "context_block": memory_engine.build_memory_context(results),
        "overview": await memory_engine.build_memory_overview(conn),
    }


# ─── Resource bank helpers ───────────────────────────────────────────────────

def _clean_resource_ids(resource_ids: Optional[list[int]]) -> list[int]:
    seen: list[int] = []
    for resource_id in resource_ids or []:
        try:
            value = int(resource_id)
        except Exception:
            continue
        if value > 0 and value not in seen:
            seen.append(value)
    return seen


def _stored_message_with_resources(message: str, resources: list[dict]) -> str:
    if not resources:
        return message
    labels = ", ".join(resource.get("title", "resource") for resource in resources[:6])
    suffix = "…" if len(resources) > 6 else ""
    return f"{message}\n\n[Attached resources: {labels}{suffix}]"


async def _resource_bundle(
    conn,
    *,
    resource_ids: list[int],
    user_message: str,
    settings: dict,
) -> dict:
    ids = _clean_resource_ids(resource_ids)
    if not ids:
        return {
            "resources": [],
            "context_block": "",
            "image_paths": [],
            "vision_model": "",
            "warnings": [],
        }

    rows = await devdb.get_resources_by_ids(conn, ids)
    resources = [resource_bank.serialize_resource(row) for row in rows]
    warnings: list[str] = []
    context_parts = ["## Attached Resources"]
    image_paths: list[str] = []
    vision_model = (settings.get("vision_model") or "").strip()

    for resource in resources:
        await devdb.touch_resource_used(conn, resource["id"])
        await devdb.log_event(conn, "resource_used", f"Used resource: {resource['title']}")

        if resource.get("kind") == "image":
            image_paths.append(resource.get("local_path", ""))
            meta = resource.get("meta") or {}
            dimensions = ""
            if meta.get("width") and meta.get("height"):
                dimensions = f" ({meta['width']}×{meta['height']})"
            context_parts.append(
                f"- Image: {resource['title']}{dimensions}. Summary: {resource.get('summary') or 'Image attached.'}"
            )
            continue

        chunk_rows = await devdb.get_resource_chunks(conn, resource["id"])
        chunks = []
        for row in chunk_rows:
            try:
                embedding = _json.loads(row["embedding_json"]) if row["embedding_json"] else None
            except Exception:
                embedding = None
            chunks.append({"text": row["text"], "embedding": embedding})

        selected = await resource_bank.select_relevant_chunks(
            query=user_message,
            chunks=chunks,
            settings=settings,
            limit=4,
        )
        context_parts.append(f"- {resource['title']}: {resource.get('summary') or resource.get('preview_text') or 'Attached document.'}")
        for idx, chunk in enumerate(selected, start=1):
            context_parts.append(f"  Excerpt {idx}: {chunk}")

    if image_paths and not vision_model:
        warnings.append("Image resources are attached, but no vision model is configured. Axon will use metadata only.")

    return {
        "resources": resources,
        "context_block": "\n".join(context_parts),
        "image_paths": [path for path in image_paths if path],
        "vision_model": vision_model,
        "warnings": warnings,
    }


async def _ingest_resource_bytes(
    conn,
    *,
    title: str,
    filename: str,
    content: bytes,
    mime_type: str,
    source_type: str,
    source_url: str,
    settings: dict,
) -> dict:
    if len(content) > resource_bank.upload_limit_bytes(settings):
        raise HTTPException(413, "Resource exceeds the configured upload size limit.")
    if not resource_bank.is_supported(filename, mime_type, source_type=source_type):
        raise HTTPException(415, f"Unsupported resource type: {mime_type or filename}")

    resource_id = await devdb.add_resource(
        conn,
        title=title,
        kind=resource_bank.classify_kind(filename, mime_type),
        source_type=source_type,
        source_url=source_url,
        local_path="",
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=resource_bank.sha256_bytes(content),
        status="pending",
    )
    await devdb.log_event(conn, "resource_added", f"Resource added: {title}")

    local_path = resource_bank.save_resource_file(
        resource_id=resource_id,
        filename=filename,
        content=content,
        settings=settings,
    )
    await devdb.update_resource(conn, resource_id, local_path=str(local_path))

    try:
        analysis = await resource_bank.analyze_resource_file(
            path=local_path,
            title=title,
            mime_type=mime_type,
            settings=settings,
        )
        await devdb.update_resource(
            conn,
            resource_id,
            kind=analysis["kind"],
            status=analysis["status"],
            summary=analysis["summary"],
            preview_text=analysis["preview_text"],
            meta_json=analysis["meta_json"],
        )
        await devdb.replace_resource_chunks(conn, resource_id, analysis["chunks"])
        await devdb.log_event(conn, "resource_processed", f"Resource processed: {title}")
    except Exception as exc:
        await devdb.update_resource(
            conn,
            resource_id,
            status="failed",
            summary=f"Processing failed: {exc}",
            preview_text="",
        )
        await devdb.log_event(conn, "resource_failed", f"Resource failed: {title}")
        raise HTTPException(500, f"Resource processing failed: {exc}")

    row = await devdb.get_resource(conn, resource_id)
    return resource_bank.serialize_resource(row)


class ResourceImportRequest(BaseModel):
    url: str
    title: Optional[str] = None


class ResourceUpdate(BaseModel):
    trust_level: Optional[str] = None
    pinned: Optional[bool] = None
    workspace_id: Optional[int] = None


@app.get("/api/resources")
async def list_resources(
    search: str = "",
    kind: str = "",
    source_type: str = "",
    status: str = "",
    limit: int = Query(200, ge=1, le=500),
):
    async with devdb.get_db() as conn:
        rows = await devdb.list_resources(
            conn,
            search=search,
            kind=kind,
            source_type=source_type,
            status=status,
            limit=limit,
        )
    return {"items": [resource_bank.serialize_resource(row) for row in rows]}


@app.post("/api/resources/upload")
async def upload_resources(files: list[UploadFile] = File(...)):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        created = []
        for upload in files:
            raw = await upload.read()
            filename = upload.filename or "resource"
            mime_type = (upload.content_type or resource_bank.detect_mime_type(filename)).strip().lower()
            title = Path(filename).stem or filename
            created.append(
                await _ingest_resource_bytes(
                    conn,
                    title=title,
                    filename=filename,
                    content=raw,
                    mime_type=mime_type,
                    source_type="upload",
                    source_url="",
                    settings=settings,
                )
            )
    return {"items": created}


@app.post("/api/resources/import-url")
async def import_resource_url(body: ResourceImportRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        fetched = await resource_bank.fetch_url_resource(body.url, settings)
        title = (body.title or Path(fetched["filename"]).stem or fetched["filename"]).strip()
        created = await _ingest_resource_bytes(
            conn,
            title=title,
            filename=fetched["filename"],
            content=fetched["content"],
            mime_type=fetched["mime_type"],
            source_type="url",
            source_url=fetched["final_url"],
            settings=settings,
        )
    return created


@app.get("/api/resources/{resource_id}")
async def get_resource(resource_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_resource(conn, resource_id)
        if not row:
            raise HTTPException(404, "Resource not found")
        chunks = await devdb.get_resource_chunks(conn, resource_id)
    data = resource_bank.serialize_resource(row)
    data["chunk_count"] = len(chunks)
    return data


@app.patch("/api/resources/{resource_id}")
async def update_resource(resource_id: int, body: ResourceUpdate):
    if body.trust_level not in (None, "high", "medium", "low"):
        raise HTTPException(400, "Invalid trust level")
    fields = body.model_dump(exclude_unset=True)
    async with devdb.get_db() as conn:
        row = await devdb.get_resource(conn, resource_id)
        if not row:
            raise HTTPException(404, "Resource not found")
        if fields:
            await devdb.update_resource(conn, resource_id, **fields)
            changes = []
            if "pinned" in fields:
                changes.append("pinned" if fields["pinned"] else "unpinned")
            if "trust_level" in fields:
                changes.append(f"trust={fields['trust_level']}")
            if "workspace_id" in fields:
                changes.append("workspace link updated")
            await devdb.log_event(
                conn,
                "resource_updated",
                f"Resource updated: {dict(row).get('title', 'resource')} ({', '.join(changes) or 'metadata'})",
            )
        updated = await devdb.get_resource(conn, resource_id)
    return resource_bank.serialize_resource(updated)


@app.get("/api/resources/{resource_id}/content")
async def get_resource_content(resource_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_resource(conn, resource_id)
        if not row:
            raise HTTPException(404, "Resource not found")
        chunks = await devdb.get_resource_chunks(conn, resource_id)

    resource = resource_bank.serialize_resource(row)
    path = Path(resource["local_path"])
    if resource.get("kind") == "image":
        if not path.exists():
            raise HTTPException(404, "Image file not found")
        return FileResponse(str(path), media_type=resource.get("mime_type") or "image/png")

    content = "\n\n".join(chunk["text"] for chunk in [dict(r) for r in chunks])[:50000]
    return {
        "id": resource["id"],
        "title": resource["title"],
        "kind": resource["kind"],
        "mime_type": resource.get("mime_type", ""),
        "summary": resource.get("summary", ""),
        "preview_text": resource.get("preview_text", ""),
        "content": content,
    }


@app.post("/api/resources/{resource_id}/reprocess")
async def reprocess_resource(resource_id: int):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        row = await devdb.get_resource(conn, resource_id)
        if not row:
            raise HTTPException(404, "Resource not found")
        resource = resource_bank.serialize_resource(row)
        path = Path(resource["local_path"])
        if not path.exists():
            raise HTTPException(404, "Resource file not found")
        analysis = await resource_bank.analyze_resource_file(
            path=path,
            title=resource["title"],
            mime_type=resource.get("mime_type") or resource_bank.detect_mime_type(path.name),
            settings=settings,
        )
        await devdb.update_resource(
            conn,
            resource_id,
            kind=analysis["kind"],
            status=analysis["status"],
            summary=analysis["summary"],
            preview_text=analysis["preview_text"],
            meta_json=analysis["meta_json"],
        )
        await devdb.replace_resource_chunks(conn, resource_id, analysis["chunks"])
        await devdb.log_event(conn, "resource_processed", f"Resource reprocessed: {resource['title']}")
        updated = await devdb.get_resource(conn, resource_id)
    return resource_bank.serialize_resource(updated)


@app.delete("/api/resources/{resource_id}")
async def delete_resource(resource_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_resource(conn, resource_id)
        if not row:
            raise HTTPException(404, "Resource not found")
        path = Path(dict(row).get("local_path") or "")
        await devdb.delete_resource(conn, resource_id)
        await devdb.log_event(conn, "resource_removed", f"Resource deleted: {dict(row).get('title', 'resource')}")

    try:
        if path.exists():
            folder = path.parent
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass
    return {"deleted": True}


# ─── Research packs ──────────────────────────────────────────────────────────

class ResearchPackCreate(BaseModel):
    title: str
    description: str = ""
    pinned: bool = False


class ResearchPackUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    pinned: Optional[bool] = None


class ResearchPackItemsBody(BaseModel):
    resource_ids: list[int] = []


@app.get("/api/research-packs")
async def list_research_packs(search: str = "", include_resources: bool = False):
    async with devdb.get_db() as conn:
        rows = await devdb.list_research_packs(conn, search=search)
        items = []
        for row in rows:
            resources = None
            if include_resources:
                resource_rows = await devdb.get_research_pack_items(conn, row["id"])
                resources = [resource_bank.serialize_resource(item) for item in resource_rows]
            items.append(_serialize_research_pack(row, resources=resources))
        return {"items": items}


@app.get("/api/research-packs/{pack_id}")
async def get_research_pack(pack_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_research_pack(conn, pack_id)
        if not row:
            raise HTTPException(404, "Research pack not found")
        resource_rows = await devdb.get_research_pack_items(conn, pack_id)
        resources = [resource_bank.serialize_resource(item) for item in resource_rows]
        return _serialize_research_pack(row, resources=resources)


@app.post("/api/research-packs")
async def create_research_pack(body: ResearchPackCreate):
    async with devdb.get_db() as conn:
        pack_id = await devdb.create_research_pack(
            conn,
            title=body.title,
            description=body.description,
            pinned=body.pinned,
        )
        await devdb.log_event(conn, "resource_added", f"Created research pack: {body.title}")
        row = await devdb.get_research_pack(conn, pack_id)
        return _serialize_research_pack(row, resources=[])


@app.patch("/api/research-packs/{pack_id}")
async def update_research_pack(pack_id: int, body: ResearchPackUpdate):
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if "pinned" in fields:
        fields["pinned"] = 1 if fields["pinned"] else 0
    if not fields:
        raise HTTPException(400, "Nothing to update")
    async with devdb.get_db() as conn:
        await devdb.update_research_pack(conn, pack_id, **fields)
        row = await devdb.get_research_pack(conn, pack_id)
        if not row:
            raise HTTPException(404, "Research pack not found")
        resource_rows = await devdb.get_research_pack_items(conn, pack_id)
        resources = [resource_bank.serialize_resource(item) for item in resource_rows]
        return _serialize_research_pack(row, resources=resources)


@app.post("/api/research-packs/{pack_id}/items")
async def add_research_pack_items(pack_id: int, body: ResearchPackItemsBody):
    ids = _clean_resource_ids(body.resource_ids)
    if not ids:
        raise HTTPException(400, "No resources selected")
    async with devdb.get_db() as conn:
        row = await devdb.get_research_pack(conn, pack_id)
        if not row:
            raise HTTPException(404, "Research pack not found")
        await devdb.add_research_pack_items(conn, pack_id, ids)
        await devdb.log_event(conn, "resource_used", f"Updated research pack: {row['title']}")
        resource_rows = await devdb.get_research_pack_items(conn, pack_id)
        resources = [resource_bank.serialize_resource(item) for item in resource_rows]
        fresh = await devdb.get_research_pack(conn, pack_id)
        return _serialize_research_pack(fresh, resources=resources)


@app.delete("/api/research-packs/{pack_id}/items/{resource_id}")
async def remove_research_pack_item(pack_id: int, resource_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_research_pack(conn, pack_id)
        if not row:
            raise HTTPException(404, "Research pack not found")
        await devdb.remove_research_pack_item(conn, pack_id, resource_id)
        resource_rows = await devdb.get_research_pack_items(conn, pack_id)
        resources = [resource_bank.serialize_resource(item) for item in resource_rows]
        fresh = await devdb.get_research_pack(conn, pack_id)
        return _serialize_research_pack(fresh, resources=resources)


@app.delete("/api/research-packs/{pack_id}")
async def delete_research_pack(pack_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_research_pack(conn, pack_id)
        if not row:
            raise HTTPException(404, "Research pack not found")
        await devdb.delete_research_pack(conn, pack_id)
        await devdb.log_event(conn, "resource_removed", f"Deleted research pack: {row['title']}")
    return {"deleted": True}


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    model: Optional[str] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None


@app.post("/api/chat")
async def chat(body: ChatMessage):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        composer_options = _composer_options_dict(body.composer_options)
        ai = await _effective_ai_params(settings, composer_options, conn=conn, requested_model=body.model or "")

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

        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (context_block, memory_bundle["context_block"], composer_block) if block
        )

        # ── PPTX intent interception ──────────────────────────────────────────
        import re as _re
        _pptx_triggers = _re.compile(
            r'\b(create|make|generate|build|produce|prepare)\b.{0,40}'
            r'\b(slides?|presentation|pptx|powerpoint|deck)\b',
            _re.IGNORECASE,
        )
        if _pptx_triggers.search(body.message):
            try:
                from pptx_engine import prompt_to_deck_json, deck_from_dict, build_deck
                import httpx as _httpx

                # Pick the best model for structured JSON output
                _pptx_model_ns = (
                    settings.get("reasoning_model")
                    or settings.get("general_model")
                    or settings.get("code_model")
                    or settings.get("ollama_model")
                    or "qwen2.5-coder:1.5b"
                )

                # Resolve cloud API config for fallback / direct use
                _pptx_api_cfg = provider_registry.runtime_api_config(settings)
                _pptx_api_key = _pptx_api_cfg.get("api_key", "")
                if not _pptx_api_key and devvault.VaultSession.is_unlocked():
                    _pptx_api_key = await devvault.vault_resolve_provider_key(conn, _pptx_api_cfg.get("provider_id", "deepseek"))
                _pptx_api_base = _pptx_api_cfg.get("api_base_url", "https://api.deepseek.com/")
                _pptx_api_model = _pptx_api_cfg.get("api_model", "deepseek-chat")

                def _call_cloud_api(system: str, user: str) -> str:
                    """Call cloud provider (DeepSeek etc.) for slide JSON."""
                    headers = {"Authorization": f"Bearer {_pptx_api_key}", "Content-Type": "application/json"}
                    base = _pptx_api_base.rstrip("/")
                    payload = {
                        "model": _pptx_api_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.3,
                        "stream": False,
                    }
                    r = _httpx.post(f"{base}/chat/completions", json=payload, headers=headers, timeout=120)
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]

                def _model_fn(system: str, user: str) -> str:
                    # If cloud provider is configured, prefer it (faster, smarter)
                    if _pptx_api_key:
                        return _call_cloud_api(system, user)
                    # Otherwise try Ollama
                    payload = {
                        "model": _pptx_model_ns,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.3},
                    }
                    r = _httpx.post(
                        f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                        json=payload, timeout=120,
                    )
                    r.raise_for_status()
                    return r.json()["message"]["content"]

                _set_live_operator(active=True, mode="chat", phase="execute",
                                   title="Generating slides…", detail=body.message[:120],
                                   workspace_id=body.project_id)

                context_for_deck = f"{merged_context_block}\n\nUser request: {body.message}"
                deck_json = prompt_to_deck_json(body.message, context_for_deck, _model_fn)
                spec = deck_from_dict(deck_json)
                out_path = build_deck(spec)

                slide_titles = [s.title for s in spec.slides if s.title]
                reply = (
                    f"✅ **Slides ready** — {len(spec.slides)} slides generated.\n\n"
                    f"**Title:** {spec.title}\n"
                    f"**Theme:** {spec.theme}\n"
                    f"**Saved to:** `{out_path}`\n\n"
                    f"**Slide outline:**\n" +
                    "\n".join(f"  {i+1}. {t}" for i, t in enumerate(slide_titles)) +
                    f"\n\n[Download slides](/api/generate/pptx/download?path={str(out_path)})\n\n"
                    f"Open with LibreOffice Impress or upload to Google Slides."
                )

                _set_live_operator(active=False, mode="chat", phase="verify",
                                   title="Slides ready", detail=f"{len(spec.slides)} slides · {out_path.name}",
                                   summary=reply[:180], workspace_id=body.project_id)

                await devdb.save_message(conn, "user", body.message, project_id=body.project_id)
                await devdb.save_message(conn, "assistant", reply, project_id=body.project_id, tokens=0)
                await devdb.log_event(conn, "pptx_generate", body.message[:100], project_id=body.project_id)

                # Save to memory for future context
                _mem_content_ns = (
                    f"Generated presentation: {spec.title}\n"
                    f"Slides: {len(spec.slides)}\n"
                    f"Outline: {', '.join(slide_titles)}\n"
                    f"Theme: {spec.theme}\n"
                    f"File: {out_path.name}\n"
                    f"User request: {body.message[:300]}"
                )
                await devdb.upsert_memory_item(
                    conn,
                    memory_key=f"mission:pptx:{out_path.stem}",
                    layer="mission",
                    title=f"Presentation: {spec.title}",
                    content=_mem_content_ns,
                    summary=f"Generated {len(spec.slides)}-slide deck: {spec.title}",
                    source="pptx_generate",
                    source_id=str(out_path),
                    workspace_id=body.project_id,
                    trust_level="high",
                    relevance_score=0.8,
                    meta_json=_json.dumps({
                        "slide_count": len(spec.slides),
                        "theme": spec.theme,
                        "file_path": str(out_path),
                        "slide_titles": slide_titles,
                    }),
                )

                return {"response": reply, "tokens": 0}
            except Exception as _pptx_err:
                import traceback as _tb_ns
                _tb_ns.print_exc()
                # Fall through to normal chat if PPTX generation fails
                pass
        # ── end PPTX intent interception ─────────────────────────────────────

        # ── Mission intent interception (non-streaming) ──────────────────────
        import re as _re_mns
        _mission_triggers_ns = _re_mns.compile(
            r'\b(create|add|make|set\s*up|queue|schedule|track|start|turn|convert|break\s*down|organize|log|plan)\b'
            r'.{0,60}'
            r'\b(missions?|tasks?|tracker)\b',
            _re_mns.IGNORECASE,
        )
        if _mission_triggers_ns.search(body.message):
            try:
                import httpx as _httpx_mns

                _mns_api_cfg = provider_registry.runtime_api_config(settings)
                _mns_api_key = _mns_api_cfg.get("api_key", "")
                if not _mns_api_key and devvault.VaultSession.is_unlocked():
                    _mns_api_key = await devvault.vault_resolve_provider_key(conn, _mns_api_cfg.get("provider_id", "deepseek"))
                _mns_api_base = _mns_api_cfg.get("api_base_url", "https://api.deepseek.com/").rstrip("/")
                _mns_api_model = _mns_api_cfg.get("api_model", "deepseek-chat")

                _proj_names_ns = {str(p["id"]): p["name"] for p in projects}
                _proj_list_ns = ", ".join(f'{pid}: {pn}' for pid, pn in _proj_names_ns.items()) or "none"

                _extract_system_ns = (
                    "You are a JSON extractor. Extract mission(s) from the conversation.\n"
                    "The user is asking to create missions/tasks. Look at the FULL conversation history "
                    "(especially the last assistant message) to find all missions/tasks mentioned.\n"
                    "Return ONLY a JSON array of mission objects. Each object has:\n"
                    '  {"title": "string", "detail": "string", "priority": "low|medium|high|urgent", "project_id": null_or_int, "due_date": null_or_"YYYY-MM-DD"}\n'
                    f"Available projects: {_proj_list_ns}\n"
                    "If the user mentions a project name, match it to the project_id.\n"
                    "If multiple missions are requested, return multiple objects.\n"
                    "Keep titles concise (under 80 chars). Put sub-tasks and details in the detail field.\n"
                    "Return ONLY valid JSON array, no markdown fences."
                )

                # Build context from recent history
                _history_context_ns = ""
                if history:
                    _recent_ns = history[-6:]
                    _history_lines_ns = []
                    for h in _recent_ns:
                        _history_lines_ns.append(f"{h['role'].upper()}: {h['content'][:2000]}")
                    _history_context_ns = "\n---\n".join(_history_lines_ns) + "\n---\n"

                def _extract_missions_ns(user_msg: str) -> list:
                    _full_msg = _history_context_ns + "USER (current): " + user_msg if _history_context_ns else user_msg
                    if _mns_api_key:
                        headers = {"Authorization": f"Bearer {_mns_api_key}", "Content-Type": "application/json"}
                        payload = {
                            "model": _mns_api_model,
                            "messages": [
                                {"role": "system", "content": _extract_system_ns},
                                {"role": "user", "content": _full_msg},
                            ],
                            "temperature": 0.1,
                            "stream": False,
                        }
                        r = _httpx_mns.post(f"{_mns_api_base}/chat/completions", json=payload, headers=headers, timeout=60)
                        r.raise_for_status()
                        raw = r.json()["choices"][0]["message"]["content"]
                    else:
                        payload = {
                            "model": settings.get("ollama_model", "qwen2.5-coder:1.5b"),
                            "messages": [
                                {"role": "system", "content": _extract_system_ns},
                                {"role": "user", "content": _full_msg},
                            ],
                            "stream": False,
                            "options": {"temperature": 0.1},
                        }
                        r = _httpx_mns.post(
                            f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                            json=payload, timeout=60,
                        )
                        r.raise_for_status()
                        raw = r.json()["message"]["content"]
                    raw = _re_mns.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=_re_mns.IGNORECASE)
                    raw = _re_mns.sub(r"\s*```$", "", raw.strip())
                    return _json.loads(raw)

                _set_live_operator(active=True, mode="chat", phase="execute",
                                   title="Creating missions…", detail=body.message[:120],
                                   workspace_id=body.project_id, preserve_started=True)

                mission_data_ns = await asyncio.to_thread(_extract_missions_ns, body.message)
                if not isinstance(mission_data_ns, list):
                    mission_data_ns = [mission_data_ns]

                created_ns = []
                for m in mission_data_ns:
                    if not isinstance(m, dict) or not m.get("title"):
                        continue
                    mid = await devdb.add_task(
                        conn,
                        m.get("project_id"),
                        m["title"].strip(),
                        m.get("detail", "").strip(),
                        m.get("priority", "medium"),
                        m.get("due_date"),
                    )
                    await devdb.log_event(conn, "task_added", f"Mission created via chat: {m['title'].strip()}", project_id=m.get("project_id"))
                    created_ns.append({"id": mid, **m})

                if created_ns:
                    reply_lines = [f"✅ **{len(created_ns)} mission(s) created:**\n"]
                    for c in created_ns:
                        p = c.get("priority", "medium")
                        icon = {"urgent": "🔴", "high": "🟠", "medium": "🔵", "low": "⚪"}.get(p, "🔵")
                        line = f"{icon} **{c['title']}** ({p})"
                        if c.get("detail"):
                            line += f"\n   {c['detail'][:150]}"
                        if c.get("due_date"):
                            line += f"\n   Due: {c['due_date']}"
                        proj_name = _proj_names_ns.get(str(c.get("project_id")), "")
                        if proj_name:
                            line += f"\n   Workspace: {proj_name}"
                        reply_lines.append(line)
                    reply_lines.append("\nView them in the **Missions** tab.")
                    reply_ns = "\n".join(reply_lines)

                    _set_live_operator(active=False, mode="chat", phase="verify",
                                       title="Missions created", detail=f"{len(created_ns)} mission(s)",
                                       summary=reply_ns[:180], workspace_id=body.project_id)

                    stored_user_msg = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(conn, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(conn, "assistant", reply_ns, project_id=body.project_id, tokens=0)

                    return {"role": "assistant", "content": reply_ns, "tokens": 0}
            except Exception as _mission_err_ns:
                import traceback as _tb_mns
                _tb_mns.print_exc()
                pass
        # ── end Mission intent interception (non-streaming) ──────────────────

        # ── Playbook intent interception (non-streaming) ─────────────────────
        import re as _re_pbns
        _playbook_triggers_ns = _re_pbns.compile(
            r'\b(create|add|make|save|build|write|generate|draft)\b'
            r'.{0,60}'
            r'\b(playbooks?|prompts?|templates?|sops?|procedures?|checklists?)\b',
            _re_pbns.IGNORECASE,
        )
        if _playbook_triggers_ns.search(body.message):
            try:
                import httpx as _httpx_pbns

                _pbns_api_cfg = provider_registry.runtime_api_config(settings)
                _pbns_api_key = _pbns_api_cfg.get("api_key", "")
                if not _pbns_api_key and devvault.VaultSession.is_unlocked():
                    _pbns_api_key = await devvault.vault_resolve_provider_key(conn, _pbns_api_cfg.get("provider_id", "deepseek"))
                _pbns_api_base = _pbns_api_cfg.get("api_base_url", "https://api.deepseek.com/").rstrip("/")
                _pbns_api_model = _pbns_api_cfg.get("api_model", "deepseek-chat")

                _proj_names_pbns = {str(p["id"]): p["name"] for p in projects}
                _proj_list_pbns = ", ".join(f'{pid}: {pn}' for pid, pn in _proj_names_pbns.items()) or "none"

                _extract_system_pbns = (
                    "You are a JSON extractor. Extract playbook(s)/prompt templates from the conversation.\n"
                    "The user wants to save reusable playbooks. Look at the FULL conversation history.\n"
                    "Return ONLY a JSON array of playbook objects. Each object has:\n"
                    '  {"title": "string", "content": "string (the full playbook/prompt text)", "tags": "comma,separated,tags", "project_id": null_or_int}\n'
                    f"Available projects: {_proj_list_pbns}\n"
                    "Content should be comprehensive and usable as a standalone reference.\n"
                    "Return ONLY valid JSON array, no markdown fences."
                )

                _history_context_pbns = ""
                if history:
                    _recent_pbns = history[-6:]
                    _history_lines_pbns = [f"{h['role'].upper()}: {h['content'][:2000]}" for h in _recent_pbns]
                    _history_context_pbns = "\n---\n".join(_history_lines_pbns) + "\n---\n"

                def _extract_playbooks_ns(user_msg: str) -> list:
                    _full_msg = _history_context_pbns + "USER (current): " + user_msg if _history_context_pbns else user_msg
                    if _pbns_api_key:
                        headers = {"Authorization": f"Bearer {_pbns_api_key}", "Content-Type": "application/json"}
                        payload = {
                            "model": _pbns_api_model,
                            "messages": [
                                {"role": "system", "content": _extract_system_pbns},
                                {"role": "user", "content": _full_msg},
                            ],
                            "temperature": 0.1,
                            "stream": False,
                        }
                        r = _httpx_pbns.post(f"{_pbns_api_base}/chat/completions", json=payload, headers=headers, timeout=60)
                        r.raise_for_status()
                        raw = r.json()["choices"][0]["message"]["content"]
                    else:
                        payload = {
                            "model": settings.get("ollama_model", "qwen2.5-coder:1.5b"),
                            "messages": [
                                {"role": "system", "content": _extract_system_pbns},
                                {"role": "user", "content": _full_msg},
                            ],
                            "stream": False,
                            "options": {"temperature": 0.1},
                        }
                        r = _httpx_pbns.post(
                            f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                            json=payload, timeout=60,
                        )
                        r.raise_for_status()
                        raw = r.json()["message"]["content"]
                    raw = _re_pbns.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=_re_pbns.IGNORECASE)
                    raw = _re_pbns.sub(r"\s*```$", "", raw.strip())
                    return _json.loads(raw)

                _set_live_operator(active=True, mode="chat", phase="execute",
                                   title="Creating playbooks…", detail=body.message[:120],
                                   workspace_id=body.project_id, preserve_started=True)

                pb_data_ns = await asyncio.to_thread(_extract_playbooks_ns, body.message)
                if not isinstance(pb_data_ns, list):
                    pb_data_ns = [pb_data_ns]

                created_pbns = []
                for pb in pb_data_ns:
                    if not isinstance(pb, dict) or not pb.get("title"):
                        continue
                    pid = await devdb.save_prompt(
                        conn,
                        pb.get("project_id"),
                        pb["title"].strip(),
                        pb.get("content", "").strip(),
                        pb.get("tags", ""),
                    )
                    await devdb.log_event(conn, "prompt_saved", f"Playbook created via chat: {pb['title'].strip()}", project_id=pb.get("project_id"))
                    created_pbns.append({"id": pid, **pb})

                if created_pbns:
                    reply_lines = [f"📋 **{len(created_pbns)} playbook(s) saved:**\n"]
                    for c in created_pbns:
                        reply_lines.append(f"📝 **{c['title']}**")
                        if c.get("tags"):
                            reply_lines.append(f"   Tags: {c['tags']}")
                        if c.get("content"):
                            preview = c['content'][:200].replace('\n', ' ')
                            reply_lines.append(f"   {preview}{'…' if len(c.get('content','')) > 200 else ''}")
                        proj_name = _proj_names_pbns.get(str(c.get("project_id")), "")
                        if proj_name:
                            reply_lines.append(f"   Workspace: {proj_name}")
                    reply_lines.append("\nView them in the **Playbooks** tab.")
                    reply_pbns = "\n".join(reply_lines)

                    _set_live_operator(active=False, mode="chat", phase="verify",
                                       title="Playbooks saved", detail=f"{len(created_pbns)} playbook(s)",
                                       summary=reply_pbns[:180], workspace_id=body.project_id)

                    stored_user_msg = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(conn, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(conn, "assistant", reply_pbns, project_id=body.project_id, tokens=0)

                    return {"role": "assistant", "content": reply_pbns, "tokens": 0}
            except Exception as _pb_err_ns:
                import traceback as _tb_pbns
                _tb_pbns.print_exc()
                pass
        # ── end Playbook intent interception (non-streaming) ─────────────────

        # Call AI with timeout handling
        try:
            import asyncio as _aio
            _set_live_operator(
                active=True,
                mode="chat",
                phase="plan",
                title="Preparing the reply",
                detail=body.message[:180],
                workspace_id=body.project_id,
            )
            result = await _aio.wait_for(
                brain.chat(
                    body.message,
                    history,
                    merged_context_block,
                    project_name=project_name,
                    resource_context=resource_bundle["context_block"],
                    resource_image_paths=resource_bundle["image_paths"],
                    vision_model=resource_bundle["vision_model"],
                    **ai,
                ),
                timeout=90.0,
            )
            _set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Reply complete",
                detail="Axon finished the response.",
                summary=result["content"][:180],
                workspace_id=body.project_id,
            )
        except (_aio.TimeoutError, TimeoutError, RuntimeError) as exc:
            _set_live_operator(
                active=False,
                mode="chat",
                phase="recover",
                title="Reply interrupted",
                detail=str(exc),
                summary=body.message[:120],
                workspace_id=body.project_id,
            )
            raise HTTPException(504, f"AI backend timed out — try a shorter message or check Ollama. ({exc})")

        # Persist messages
        stored_user_message = _stored_message_with_resources(body.message, resource_bundle["resources"])
        await devdb.save_message(conn, "user", stored_user_message, project_id=body.project_id)
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
        composer_options = _composer_options_dict(body.composer_options)
        ai = await _effective_ai_params(settings, composer_options, conn=conn, requested_model=body.model or "")
        settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "ollama"))}
        if ai.get("ollama_model"):
            settings["ollama_model"] = ai["ollama_model"]
        backend = settings.get("ai_backend", "ollama")

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
        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (context_block, memory_bundle["context_block"], composer_block) if block
        )

    _set_live_operator(
        active=True,
        mode="chat",
        phase="observe",
        title="Understanding the request",
        detail=body.message[:180],
        workspace_id=body.project_id,
    )

    # ── PPTX intent interception (streaming) ──────────────────────────────
    import re as _re_s
    _pptx_triggers_s = _re_s.compile(
        r'\b(create|make|generate|build|produce|prepare)\b.{0,40}'
        r'\b(slides?|presentation|pptx|powerpoint|deck)\b',
        _re_s.IGNORECASE,
    )
    if _pptx_triggers_s.search(body.message):
        try:
            from pptx_engine import prompt_to_deck_json, deck_from_dict, build_deck
            import httpx as _httpx_s

            # Pick the best model for structured JSON output
            _pptx_model = (
                settings.get("reasoning_model")
                or settings.get("general_model")
                or settings.get("code_model")
                or settings.get("ollama_model")
                or "qwen2.5-coder:1.5b"
            )

            # Resolve cloud API config for fallback / direct use
            _pptx_api_cfg_s = provider_registry.runtime_api_config(settings)
            _pptx_api_key_s = _pptx_api_cfg_s.get("api_key", "")
            if not _pptx_api_key_s and devvault.VaultSession.is_unlocked():
                _pptx_api_key_s = await devvault.vault_resolve_provider_key(conn, _pptx_api_cfg_s.get("provider_id", "deepseek"))
            _pptx_api_base_s = _pptx_api_cfg_s.get("api_base_url", "https://api.deepseek.com/")
            _pptx_api_model_s = _pptx_api_cfg_s.get("api_model", "deepseek-chat")

            def _call_cloud_api_s(system: str, user: str) -> str:
                """Call cloud provider (DeepSeek etc.) for slide JSON."""
                headers = {"Authorization": f"Bearer {_pptx_api_key_s}", "Content-Type": "application/json"}
                base = _pptx_api_base_s.rstrip("/")
                payload = {
                    "model": _pptx_api_model_s,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "stream": False,
                }
                r = _httpx_s.post(f"{base}/chat/completions", json=payload, headers=headers, timeout=120)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]

            def _model_fn_s(system: str, user: str) -> str:
                # If cloud provider is configured, prefer it (faster, smarter)
                if _pptx_api_key_s:
                    return _call_cloud_api_s(system, user)
                # Otherwise try Ollama
                payload = {
                    "model": _pptx_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3},
                }
                r = _httpx_s.post(
                    f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                    json=payload, timeout=120,
                )
                r.raise_for_status()
                return r.json()["message"]["content"]

            _set_live_operator(active=True, mode="chat", phase="execute",
                               title="Generating slides…", detail=body.message[:120],
                               workspace_id=body.project_id, preserve_started=True)

            context_for_deck = f"{merged_context_block}\n\nUser request: {body.message}"
            deck_json = prompt_to_deck_json(body.message, context_for_deck, _model_fn_s)
            spec = deck_from_dict(deck_json)
            out_path = build_deck(spec)

            slide_titles = [s.title for s in spec.slides if s.title]
            reply = (
                f"✅ **Slides ready** — {len(spec.slides)} slides generated.\n\n"
                f"**Title:** {spec.title}\n"
                f"**Theme:** {spec.theme}\n"
                f"**Saved to:** `{out_path}`\n\n"
                f"**Slide outline:**\n" +
                "\n".join(f"  {i+1}. {t}" for i, t in enumerate(slide_titles)) +
                f"\n\n[Download slides](/api/generate/pptx/download?path={str(out_path)})\n\n"
                f"Open with LibreOffice Impress or upload to Google Slides."
            )

            _set_live_operator(active=False, mode="chat", phase="verify",
                               title="Slides ready", detail=f"{len(spec.slides)} slides · {out_path.name}",
                               summary=reply[:180], workspace_id=body.project_id)

            async def _pptx_stream():
                yield {"data": _json.dumps({"chunk": reply})}
                yield {"data": _json.dumps({"done": True, "tokens": 0})}
                # Persist chat messages
                async with devdb.get_db() as _pconn:
                    stored_user_message = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(_pconn, "user", stored_user_message, project_id=body.project_id)
                    await devdb.save_message(_pconn, "assistant", reply, project_id=body.project_id, tokens=0)
                    await devdb.log_event(_pconn, "pptx_generate", body.message[:100], project_id=body.project_id)
                    # Save to memory for future context
                    _mem_content = (
                        f"Generated presentation: {spec.title}\n"
                        f"Slides: {len(spec.slides)}\n"
                        f"Outline: {', '.join(slide_titles)}\n"
                        f"Theme: {spec.theme}\n"
                        f"File: {out_path.name}\n"
                        f"User request: {body.message[:300]}"
                    )
                    await devdb.upsert_memory_item(
                        _pconn,
                        memory_key=f"mission:pptx:{out_path.stem}",
                        layer="mission",
                        title=f"Presentation: {spec.title}",
                        content=_mem_content,
                        summary=f"Generated {len(spec.slides)}-slide deck: {spec.title}",
                        source="pptx_generate",
                        source_id=str(out_path),
                        workspace_id=body.project_id,
                        trust_level="high",
                        relevance_score=0.8,
                        meta_json=_json.dumps({
                            "slide_count": len(spec.slides),
                            "theme": spec.theme,
                            "file_path": str(out_path),
                            "slide_titles": slide_titles,
                        }),
                    )

            return EventSourceResponse(_pptx_stream())
        except Exception as _pptx_stream_err:
            import traceback as _tb_s
            print(f"[Axon] PPTX stream error: {_pptx_stream_err}")
            _tb_s.print_exc()
            # Fall through to normal chat if PPTX generation fails
    # ── end PPTX intent interception (streaming) ─────────────────────────

    # ── Mission intent interception (streaming) ──────────────────────────
    import re as _re_m
    _mission_triggers = _re_m.compile(
        r'\b(create|add|make|set\s*up|queue|schedule|track|start|turn|convert|break\s*down|organize|log|plan)\b'
        r'.{0,60}'
        r'\b(missions?|tasks?|tracker)\b',
        _re_m.IGNORECASE,
    )
    if _mission_triggers.search(body.message):
        try:
            import httpx as _httpx_m

            # Resolve cloud API for structured extraction
            _m_api_cfg = provider_registry.runtime_api_config(settings)
            _m_api_key = _m_api_cfg.get("api_key", "")
            if not _m_api_key and devvault.VaultSession.is_unlocked():
                async with devdb.get_db() as _m_conn:
                    _m_api_key = await devvault.vault_resolve_provider_key(_m_conn, _m_api_cfg.get("provider_id", "deepseek"))
            _m_api_base = _m_api_cfg.get("api_base_url", "https://api.deepseek.com/").rstrip("/")
            _m_api_model = _m_api_cfg.get("api_model", "deepseek-chat")

            # Build project list for context
            _proj_names = {str(p["id"]): p["name"] for p in projects}
            _proj_list = ", ".join(f'{pid}: {pn}' for pid, pn in _proj_names.items()) or "none"

            _extract_system = (
                "You are a JSON extractor. Extract mission(s) from the conversation.\n"
                "The user is asking to create missions/tasks. Look at the FULL conversation history "
                "(especially the last assistant message) to find all missions/tasks mentioned.\n"
                "Return ONLY a JSON array of mission objects. Each object has:\n"
                '  {"title": "string", "detail": "string", "priority": "low|medium|high|urgent", "project_id": null_or_int, "due_date": null_or_"YYYY-MM-DD"}\n'
                f"Available projects: {_proj_list}\n"
                "If the user mentions a project name, match it to the project_id.\n"
                "If multiple missions are requested, return multiple objects.\n"
                "Keep titles concise (under 80 chars). Put sub-tasks and details in the detail field.\n"
                "Return ONLY valid JSON array, no markdown fences."
            )

            # Build context from recent history so extraction sees what "this" refers to
            _history_context = ""
            if history:
                _recent = history[-6:]  # last 3 exchanges
                _history_lines = []
                for h in _recent:
                    _history_lines.append(f"{h['role'].upper()}: {h['content'][:2000]}")
                _history_context = "\n---\n".join(_history_lines) + "\n---\n"

            def _extract_missions(user_msg: str) -> list:
                _full_msg = _history_context + "USER (current): " + user_msg if _history_context else user_msg
                if _m_api_key:
                    headers = {"Authorization": f"Bearer {_m_api_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": _m_api_model,
                        "messages": [
                            {"role": "system", "content": _extract_system},
                            {"role": "user", "content": _full_msg},
                        ],
                        "temperature": 0.1,
                        "stream": False,
                    }
                    r = _httpx_m.post(f"{_m_api_base}/chat/completions", json=payload, headers=headers, timeout=60)
                    r.raise_for_status()
                    raw = r.json()["choices"][0]["message"]["content"]
                else:
                    # Ollama fallback
                    payload = {
                        "model": settings.get("ollama_model", "qwen2.5-coder:1.5b"),
                        "messages": [
                            {"role": "system", "content": _extract_system},
                            {"role": "user", "content": _full_msg},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.1},
                    }
                    r = _httpx_m.post(
                        f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                        json=payload, timeout=60,
                    )
                    r.raise_for_status()
                    raw = r.json()["message"]["content"]
                raw = _re_m.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=_re_m.IGNORECASE)
                raw = _re_m.sub(r"\s*```$", "", raw.strip())
                return _json.loads(raw)

            _set_live_operator(active=True, mode="chat", phase="execute",
                               title="Creating missions…", detail=body.message[:120],
                               workspace_id=body.project_id, preserve_started=True)

            mission_data = await asyncio.to_thread(_extract_missions, body.message)
            if not isinstance(mission_data, list):
                mission_data = [mission_data]

            created = []
            async with devdb.get_db() as _m_db:
                for m in mission_data:
                    if not isinstance(m, dict) or not m.get("title"):
                        continue
                    mid = await devdb.add_task(
                        _m_db,
                        m.get("project_id"),
                        m["title"].strip(),
                        m.get("detail", "").strip(),
                        m.get("priority", "medium"),
                        m.get("due_date"),
                    )
                    await devdb.log_event(_m_db, "task_added", f"Mission created via chat: {m['title'].strip()}", project_id=m.get("project_id"))
                    created.append({"id": mid, **m})

            if created:
                reply_lines = [f"✅ **{len(created)} mission(s) created:**\n"]
                for c in created:
                    p = c.get("priority", "medium")
                    icon = {"urgent": "🔴", "high": "🟠", "medium": "🔵", "low": "⚪"}.get(p, "🔵")
                    line = f"{icon} **{c['title']}** ({p})"
                    if c.get("detail"):
                        line += f"\n   {c['detail'][:150]}"
                    if c.get("due_date"):
                        line += f"\n   Due: {c['due_date']}"
                    proj_name = _proj_names.get(str(c.get("project_id")), "")
                    if proj_name:
                        line += f"\n   Workspace: {proj_name}"
                    reply_lines.append(line)
                reply_lines.append("\nView them in the **Missions** tab.")
                reply = "\n".join(reply_lines)

                _set_live_operator(active=False, mode="chat", phase="verify",
                                   title="Missions created", detail=f"{len(created)} mission(s)",
                                   summary=reply[:180], workspace_id=body.project_id)

                # Persist chat messages
                async with devdb.get_db() as _m_db2:
                    stored_user_msg = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(_m_db2, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(_m_db2, "assistant", reply, project_id=body.project_id, tokens=0)

                async def _mission_stream():
                    yield {"data": _json.dumps({"chunk": reply})}
                    yield {"data": _json.dumps({"done": True, "tokens": 0})}
                return EventSourceResponse(_mission_stream())
        except Exception as _mission_err:
            import traceback as _tb_m
            print(f"[Axon] Mission stream error: {_mission_err}")
            _tb_m.print_exc()
            # Fall through to normal chat
    # ── end Mission intent interception (streaming) ──────────────────────

    # ── Playbook intent interception (streaming) ─────────────────────────
    import re as _re_pb
    _playbook_triggers = _re_pb.compile(
        r'\b(create|add|make|save|build|write|generate|draft)\b'
        r'.{0,60}'
        r'\b(playbooks?|prompts?|templates?|sops?|procedures?|checklists?)\b',
        _re_pb.IGNORECASE,
    )
    if _playbook_triggers.search(body.message):
        try:
            import httpx as _httpx_pb

            _pb_api_cfg = provider_registry.runtime_api_config(settings)
            _pb_api_key = _pb_api_cfg.get("api_key", "")
            if not _pb_api_key and devvault.VaultSession.is_unlocked():
                async with devdb.get_db() as _pb_conn:
                    _pb_api_key = await devvault.vault_resolve_provider_key(_pb_conn, _pb_api_cfg.get("provider_id", "deepseek"))
            _pb_api_base = _pb_api_cfg.get("api_base_url", "https://api.deepseek.com/").rstrip("/")
            _pb_api_model = _pb_api_cfg.get("api_model", "deepseek-chat")

            _proj_names_pb = {str(p["id"]): p["name"] for p in projects}
            _proj_list_pb = ", ".join(f'{pid}: {pn}' for pid, pn in _proj_names_pb.items()) or "none"

            _extract_system_pb = (
                "You are a JSON extractor. Extract playbook(s)/prompt templates from the conversation.\n"
                "The user wants to save reusable playbooks. Look at the FULL conversation history.\n"
                "Return ONLY a JSON array of playbook objects. Each object has:\n"
                '  {"title": "string", "content": "string (the full playbook/prompt text)", "tags": "comma,separated,tags", "project_id": null_or_int}\n'
                f"Available projects: {_proj_list_pb}\n"
                "Content should be comprehensive and usable as a standalone reference.\n"
                "Return ONLY valid JSON array, no markdown fences."
            )

            _history_context_pb = ""
            if history:
                _recent_pb = history[-6:]
                _history_lines_pb = [f"{h['role'].upper()}: {h['content'][:2000]}" for h in _recent_pb]
                _history_context_pb = "\n---\n".join(_history_lines_pb) + "\n---\n"

            def _extract_playbooks(user_msg: str) -> list:
                _full_msg = _history_context_pb + "USER (current): " + user_msg if _history_context_pb else user_msg
                if _pb_api_key:
                    headers = {"Authorization": f"Bearer {_pb_api_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": _pb_api_model,
                        "messages": [
                            {"role": "system", "content": _extract_system_pb},
                            {"role": "user", "content": _full_msg},
                        ],
                        "temperature": 0.1,
                        "stream": False,
                    }
                    r = _httpx_pb.post(f"{_pb_api_base}/chat/completions", json=payload, headers=headers, timeout=60)
                    r.raise_for_status()
                    raw = r.json()["choices"][0]["message"]["content"]
                else:
                    payload = {
                        "model": settings.get("ollama_model", "qwen2.5-coder:1.5b"),
                        "messages": [
                            {"role": "system", "content": _extract_system_pb},
                            {"role": "user", "content": _full_msg},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.1},
                    }
                    r = _httpx_pb.post(
                        f"{settings.get('ollama_url', 'http://localhost:11434')}/api/chat",
                        json=payload, timeout=60,
                    )
                    r.raise_for_status()
                    raw = r.json()["message"]["content"]
                raw = _re_pb.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=_re_pb.IGNORECASE)
                raw = _re_pb.sub(r"\s*```$", "", raw.strip())
                return _json.loads(raw)

            _set_live_operator(active=True, mode="chat", phase="execute",
                               title="Creating playbooks…", detail=body.message[:120],
                               workspace_id=body.project_id, preserve_started=True)

            pb_data = await asyncio.to_thread(_extract_playbooks, body.message)
            if not isinstance(pb_data, list):
                pb_data = [pb_data]

            created_pb = []
            async with devdb.get_db() as _pb_db:
                for pb in pb_data:
                    if not isinstance(pb, dict) or not pb.get("title"):
                        continue
                    pid = await devdb.save_prompt(
                        _pb_db,
                        pb.get("project_id"),
                        pb["title"].strip(),
                        pb.get("content", "").strip(),
                        pb.get("tags", ""),
                    )
                    await devdb.log_event(_pb_db, "prompt_saved", f"Playbook created via chat: {pb['title'].strip()}", project_id=pb.get("project_id"))
                    created_pb.append({"id": pid, **pb})

            if created_pb:
                reply_lines = [f"📋 **{len(created_pb)} playbook(s) saved:**\n"]
                for c in created_pb:
                    reply_lines.append(f"📝 **{c['title']}**")
                    if c.get("tags"):
                        reply_lines.append(f"   Tags: {c['tags']}")
                    if c.get("content"):
                        preview = c['content'][:200].replace('\n', ' ')
                        reply_lines.append(f"   {preview}{'…' if len(c.get('content','')) > 200 else ''}")
                    proj_name = _proj_names_pb.get(str(c.get("project_id")), "")
                    if proj_name:
                        reply_lines.append(f"   Workspace: {proj_name}")
                reply_lines.append("\nView them in the **Playbooks** tab.")
                reply_pb = "\n".join(reply_lines)

                _set_live_operator(active=False, mode="chat", phase="verify",
                                   title="Playbooks saved", detail=f"{len(created_pb)} playbook(s)",
                                   summary=reply_pb[:180], workspace_id=body.project_id)

                async with devdb.get_db() as _pb_db2:
                    stored_user_msg = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(_pb_db2, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(_pb_db2, "assistant", reply_pb, project_id=body.project_id, tokens=0)

                async def _playbook_stream():
                    yield {"data": _json.dumps({"chunk": reply_pb})}
                    yield {"data": _json.dumps({"done": True, "tokens": 0})}
                return EventSourceResponse(_playbook_stream())
        except Exception as _pb_err:
            import traceback as _tb_pb
            print(f"[Axon] Playbook stream error: {_pb_err}")
            _tb_pb.print_exc()
            # Fall through to normal chat
    # ── end Playbook intent interception (streaming) ─────────────────────

    if backend != "ollama":
        # Fall back to non-streaming for API/CLI — emit single SSE event
        try:
            _set_live_operator(
                active=True,
                mode="chat",
                phase="plan",
                title="Preparing the reply",
                detail="Axon is using the configured non-local stream path.",
                workspace_id=body.project_id,
                preserve_started=True,
            )
            result = await brain.chat(
                body.message,
                history,
                merged_context_block,
                project_name=project_name,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                **ai,
            )
            # Persist messages to DB (was missing — messages lost on refresh)
            stored_user_message_api = _stored_message_with_resources(body.message, resource_bundle["resources"])
            async with devdb.get_db() as _api_conn:
                await devdb.save_message(_api_conn, "user", stored_user_message_api, project_id=body.project_id)
                await devdb.save_message(_api_conn, "assistant", result["content"], project_id=body.project_id, tokens=result.get("tokens", 0))
                await devdb.log_event(_api_conn, "chat", body.message[:100], project_id=body.project_id)

            async def _buffered():
                for warning in resource_bundle["warnings"]:
                    yield {"data": _json.dumps({"chunk": f"⚠️ {warning}\n\n"})}
                yield {"data": _json.dumps({"chunk": result["content"]})}
                _set_live_operator(
                    active=False,
                    mode="chat",
                    phase="verify",
                    title="Reply complete",
                    detail="Axon finished the response.",
                    summary=result["content"][:180],
                    workspace_id=body.project_id,
                )
                yield {"data": _json.dumps({"done": True, "tokens": result["tokens"]})}
            return EventSourceResponse(_buffered())
        except Exception as exc:
            _err_msg = str(exc)
            _set_live_operator(
                active=False,
                mode="chat",
                phase="recover",
                title="Reply interrupted",
                detail=_err_msg,
                summary=body.message[:120],
                workspace_id=body.project_id,
            )
            async def _err():
                yield {"data": _json.dumps({"error": _err_msg})}
            return EventSourceResponse(_err())

    # Ollama: true streaming
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    full_content: list[str] = []

    async def generate():
        try:
            started_stream = False
            for warning in resource_bundle["warnings"]:
                full_content.append(f"⚠️ {warning}\n\n")
                yield {"data": _json.dumps({"chunk": f"⚠️ {warning}\n\n"})}
            async for chunk in brain.stream_chat(
                body.message,
                history,
                merged_context_block,
                project_name=project_name,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                ollama_url=ollama_url, ollama_model=ollama_model,
            ):
                if not started_stream:
                    _set_live_operator(
                        active=True,
                        mode="chat",
                        phase="execute",
                        title="Writing the reply",
                        detail="Axon is streaming the answer live.",
                        workspace_id=body.project_id,
                        preserve_started=True,
                    )
                    started_stream = True
                full_content.append(chunk)
                if await request.is_disconnected():
                    return
                yield {"data": _json.dumps({"chunk": chunk})}
            # Persist after stream completes
            async with devdb.get_db() as conn:
                stored_user_message = _stored_message_with_resources(body.message, resource_bundle["resources"])
                await devdb.save_message(conn, "user", stored_user_message,
                                          project_id=body.project_id)
                await devdb.save_message(conn, "assistant", "".join(full_content),
                                          project_id=body.project_id, tokens=0)
                await devdb.log_event(conn, "chat", body.message[:100],
                                       project_id=body.project_id)
            _set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Reply complete",
                detail="Axon finished streaming the answer.",
                summary="".join(full_content)[:180],
                workspace_id=body.project_id,
            )
            yield {"data": _json.dumps({"done": True, "tokens": 0})}
        except Exception as exc:
            _err_msg = str(exc)
            _set_live_operator(
                active=False,
                mode="chat",
                phase="recover",
                title="Reply interrupted",
                detail=_err_msg,
                summary=body.message[:120],
                workspace_id=body.project_id,
            )
            yield {"data": _json.dumps({"error": _err_msg})}

    return EventSourceResponse(generate())


# ─── Agent endpoint ───────────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    tools: Optional[list[str]] = None    # None = all tools
    model: Optional[str] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None


@app.post("/api/agent")
async def agent_endpoint(body: AgentRequest, request: Request):
    """SSE streaming agent with tool-calling (Ollama only)."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        composer_options = _composer_options_dict(body.composer_options)
        backend = settings.get("ai_backend", "ollama")
        if backend != "ollama" and str(composer_options.get("external_mode") or "").lower() == "disable_external_calls":
            backend = "ollama"
            settings["ai_backend"] = "ollama"

        # Resolve API credentials for non-Ollama agent mode
        _agent_api_key = ""
        _agent_api_base = ""
        _agent_api_model = ""
        _agent_api_provider = ""
        if backend != "ollama":
            _agent_api_cfg = provider_registry.runtime_api_config(settings)
            _agent_api_key = _agent_api_cfg.get("api_key", "")
            if not _agent_api_key and devvault.VaultSession.is_unlocked():
                _agent_api_key = await devvault.vault_resolve_provider_key(conn, _agent_api_cfg.get("provider_id", "deepseek"))
            _agent_api_base = _agent_api_cfg.get("api_base_url", "https://api.deepseek.com/")
            _agent_api_model = _agent_api_cfg.get("api_model", "deepseek-chat")
            _agent_api_provider = _agent_api_cfg.get("provider_id", "api")
            # Use role-specific model for code/reasoning tasks
            _agent_role = _local_role_for_composer(composer_options, agent_request=True)
            _agent_role_map = brain.API_MODEL_BY_ROLE.get(_agent_api_provider, {})
            if _agent_role in _agent_role_map:
                _agent_api_model = _agent_role_map[_agent_role]
            if not _agent_api_key:
                raise HTTPException(400, "Agent mode with API backend requires a configured API key. Check Settings or Vault.")

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
        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (context_block, memory_bundle["context_block"], composer_block) if block
        )

    ai = await _effective_ai_params(settings, composer_options, agent_request=True, requested_model=body.model or "")
    ollama_url = ai.get("ollama_url", settings.get("ollama_url", ""))
    ollama_model = ai.get("ollama_model") or resource_bundle["vision_model"] or settings.get("ollama_model", "")

    # Agent tool-calling needs a capable model — upgrade tiny models automatically
    _AGENT_MIN_SIZES = {"qwen2.5-coder": "7b", "llama3.2": "3b", "phi4-mini": "latest"}
    _model_lower = ollama_model.lower()
    for family, min_tag in _AGENT_MIN_SIZES.items():
        if _model_lower.startswith(family) and min_tag not in _model_lower:
            available = await brain.ollama_list_models(ollama_url)
            upgrade = next((m for m in available if m.lower().startswith(family) and min_tag in m.lower()), None)
            if upgrade:
                ollama_model = upgrade
            break

    collected_text: list[str] = []
    _set_live_operator(
        active=True,
        mode="agent",
        phase="observe",
        title="Inspecting the task",
        detail=body.message[:180],
        workspace_id=body.project_id,
    )

    async def generate():
        try:
            for warning in resource_bundle["warnings"]:
                collected_text.append(f"⚠️ {warning}\n\n")
                yield {"data": _json.dumps({"type": "text", "chunk": f"⚠️ {warning}\n\n"})}
            async for event in brain.run_agent(
                body.message,
                history,
                merged_context_block,
                project_name=project_name,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                tools=body.tools,
                ollama_url=ollama_url, ollama_model=ollama_model,
                force_tool_mode=bool(composer_options.get("action_mode") or composer_options.get("agent_role")),
                api_key=_agent_api_key,
                api_base_url=_agent_api_base,
                api_model=_agent_api_model,
                api_provider=_agent_api_provider,
            ):
                if event.get("type") == "text":
                    collected_text.append(event["chunk"])
                    _set_live_operator(
                        active=True,
                        mode="agent",
                        phase="plan",
                        title="Planning the next step",
                        detail="Axon is reasoning through the task.",
                        workspace_id=body.project_id,
                        preserve_started=True,
                    )
                elif event.get("type") == "thinking":
                    _set_live_operator(
                        active=True,
                        mode="agent",
                        phase="plan",
                        title="Thinking through the task",
                        detail=str(event.get("chunk") or "Axon is reasoning through the task.")[:180],
                        workspace_id=body.project_id,
                        preserve_started=True,
                    )
                elif event.get("type") == "tool_call":
                    _set_live_operator(
                        active=True,
                        mode="agent",
                        phase="execute",
                        title=f"Running {str(event.get('name') or 'tool').replace('_', ' ')}",
                        detail=_json.dumps(event.get("args") or {})[:180],
                        tool=event.get("name", ""),
                        workspace_id=body.project_id,
                        preserve_started=True,
                    )
                elif event.get("type") == "tool_result":
                    _set_live_operator(
                        active=True,
                        mode="agent",
                        phase="verify",
                        title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
                        detail=str(event.get("result") or "Axon is reviewing the tool output.")[:180],
                        tool=event.get("name", ""),
                        workspace_id=body.project_id,
                        preserve_started=True,
                    )
                elif event.get("type") == "done":
                    _set_live_operator(
                        active=False,
                        mode="agent",
                        phase="verify",
                        title="Task complete",
                        detail="Axon finished the operator pass.",
                        summary="".join(collected_text)[:180],
                        workspace_id=body.project_id,
                    )
                elif event.get("type") == "error":
                    _set_live_operator(
                        active=False,
                        mode="agent",
                        phase="recover",
                        title="Needs attention",
                        detail=str(event.get("message") or "Axon hit an error and stopped safely.")[:180],
                        summary=body.message[:120],
                        workspace_id=body.project_id,
                    )
                if await request.is_disconnected():
                    return
                yield {"data": _json.dumps(event)}

            # Persist final answer
            final_text = "".join(collected_text)
            if final_text:
                async with devdb.get_db() as conn:
                    stored_user_message = _stored_message_with_resources(body.message, resource_bundle["resources"])
                    await devdb.save_message(conn, "user", stored_user_message,
                                              project_id=body.project_id)
                    await devdb.save_message(conn, "assistant", final_text,
                                              project_id=body.project_id, tokens=0)
                    await devdb.log_event(conn, "agent", body.message[:100],
                                           project_id=body.project_id)
        except Exception as exc:
            _err_msg = str(exc)
            _set_live_operator(
                active=False,
                mode="agent",
                phase="recover",
                title="Needs attention",
                detail=_err_msg,
                summary=body.message[:120],
                workspace_id=body.project_id,
            )
            yield {"data": _json.dumps({"type": "error", "message": _err_msg})}

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
        s["ollama_runtime_mode"] = _stored_ollama_runtime_mode(s)
        for key in (
            "cloud_agents_enabled",
            "openai_gpts_enabled",
            "gemini_gems_enabled",
            "generic_api_enabled",
            "resource_url_import_enabled",
            "live_feed_enabled",
            "stable_domain_enabled",
            "alerts_enabled",
            "alerts_desktop",
            "alerts_mobile",
            "alerts_missions",
            "alerts_runtime",
            "alerts_morning_brief",
            "alerts_tunnel",
            "dash_bridge_enabled",
        ):
            s[key] = str(s.get(key, "")).strip().lower() in {"1", "true", "yes", "on"}
        for key_name in (
            "anthropic_api_key",
            "openai_api_key",
            "gemini_api_key",
            "deepseek_api_key",
            "generic_api_key",
            "azure_speech_key",
            "cloudflare_tunnel_token",
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
        if s.get("dash_bridge_token"):
            token = s["dash_bridge_token"]
            s["dash_bridge_token"] = provider_registry.mask_secret(token)
            s["dash_bridge_token_set"] = True
        else:
            s["dash_bridge_token_set"] = False
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
    ollama_runtime_mode: Optional[str] = None
    ollama_model: Optional[str] = None
    code_model: Optional[str] = None
    general_model: Optional[str] = None
    reasoning_model: Optional[str] = None
    embeddings_model: Optional[str] = None
    vision_model: Optional[str] = None
    resource_storage_path: Optional[str] = None
    resource_upload_max_mb: Optional[str] = None
    resource_url_import_enabled: Optional[bool] = None
    live_feed_enabled: Optional[bool] = None
    stable_domain_enabled: Optional[bool] = None
    stable_domain: Optional[str] = None
    public_base_url: Optional[str] = None
    tunnel_mode: Optional[str] = None
    cloudflare_tunnel_token: Optional[str] = None
    terminal_default_mode: Optional[str] = None
    terminal_command_timeout_seconds: Optional[str] = None
    cloud_agents_enabled: Optional[bool] = None
    openai_gpts_enabled: Optional[bool] = None
    gemini_gems_enabled: Optional[bool] = None
    deepseek_enabled: Optional[bool] = None
    generic_api_enabled: Optional[bool] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_api_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    gemini_api_model: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    deepseek_api_model: Optional[str] = None
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
    local_stt_model: Optional[str] = None
    local_stt_language: Optional[str] = None
    local_tts_model_path: Optional[str] = None
    local_tts_config_path: Optional[str] = None
    alerts_enabled: Optional[bool] = None
    alerts_desktop: Optional[bool] = None
    alerts_mobile: Optional[bool] = None
    alerts_missions: Optional[bool] = None
    alerts_runtime: Optional[bool] = None
    alerts_morning_brief: Optional[bool] = None
    alerts_tunnel: Optional[bool] = None
    dash_bridge_enabled: Optional[bool] = None
    dash_bridge_url: Optional[str] = None
    dash_bridge_token: Optional[str] = None
    dash_bridge_mode: Optional[str] = None


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
        # Merge vault-resolved keys so configured=True even when key is vault-only
        vault_keys = await devvault.vault_resolve_all_provider_keys(conn)
        for provider_id, api_key in vault_keys.items():
            spec = provider_registry.PROVIDER_BY_ID.get(provider_id)
            if spec and api_key and not settings.get(spec.key_setting):
                settings = {**settings, spec.key_setting: api_key}
    return {
        "selected": provider_registry.runtime_api_config(settings),
        "providers": provider_registry.api_provider_cards(settings),
        "adapters": provider_registry.cloud_adapter_cards(settings),
    }


@app.post("/api/cloud/providers/test")
async def test_cloud_provider(body: CloudProviderTestRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        # If no API key supplied, try vault fallback
        api_key = body.api_key
        if not api_key and body.provider_id:
            api_key = await devvault.vault_resolve_provider_key(conn, body.provider_id) or ""
    return await provider_registry.test_provider_connection(
        body.provider_id,
        settings,
        overrides={
            "api_key": api_key,
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


@app.get("/api/vault/provider-keys")
async def vault_provider_keys():
    """Check which providers have keys resolvable from the vault."""
    result = {}
    if devvault.VaultSession.is_unlocked():
        async with devdb.get_db() as conn:
            resolved = await devvault.vault_resolve_all_provider_keys(conn)
            for pid in resolved:
                result[pid] = True
    return {"unlocked": devvault.VaultSession.is_unlocked(), "resolved": result}


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


@app.post("/api/memory/sync")
async def sync_memory():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        overview = await memory_engine.sync_memory_layers(conn, settings)
    return {"synced": True, "overview": overview}


@app.get("/api/memory/overview")
async def memory_overview():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        await memory_engine.sync_memory_layers(conn, settings)
        overview = await memory_engine.build_memory_overview(conn)
    return overview


@app.get("/api/memory/search")
async def memory_search(
    q: str = Query("", alias="q"),
    project_id: Optional[int] = None,
    layers: str = "",
    limit: int = Query(6, ge=1, le=20),
):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        await memory_engine.sync_memory_layers(conn, settings)
        selected_layers = [item.strip() for item in layers.split(",") if item.strip()]
        results = await memory_engine.search_memory(
            conn,
            query=q,
            settings=settings,
            workspace_id=project_id,
            layers=selected_layers or None,
            limit=limit,
        )
    return {
        "items": [
            {
                "id": item["id"],
                "layer": item["layer"],
                "title": item["title"],
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "trust_level": item.get("trust_level", "medium"),
                "workspace_id": item.get("workspace_id"),
                "score": item.get("score", 0),
            }
            for item in results
        ]
    }


class MemoryUpdate(BaseModel):
    pinned: Optional[bool] = None
    trust_level: Optional[str] = None


@app.get("/api/memory/items")
async def list_memory_items(
    q: str = Query("", alias="q"),
    layer: str = "",
    trust_level: str = "",
    pinned: Optional[bool] = None,
    project_id: Optional[int] = None,
    limit: int = Query(120, ge=1, le=300),
):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        await memory_engine.sync_memory_layers(conn, settings)
        rows = await devdb.list_memory_items_filtered(
            conn,
            search=q,
            layer=layer,
            trust_level=trust_level,
            pinned=pinned,
            workspace_id=project_id,
            limit=limit,
        )
    return {"items": [_serialize_memory_item(row) for row in rows]}


@app.patch("/api/memory/items/{memory_id}")
async def update_memory_item(memory_id: int, body: MemoryUpdate):
    if body.trust_level not in (None, "high", "medium", "low"):
        raise HTTPException(400, "Invalid trust level")
    async with devdb.get_db() as conn:
        row = await devdb.get_memory_item(conn, memory_id)
        if not row:
            raise HTTPException(404, "Memory item not found")
        await devdb.update_memory_item_state(
            conn,
            memory_id,
            pinned=body.pinned,
            trust_level=body.trust_level,
        )
        updated = await devdb.get_memory_item(conn, memory_id)
    return _serialize_memory_item(updated)


@app.get("/api/runtime/status")
async def runtime_status():
    """Return the Axon runtime snapshot used by the dashboard and settings."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        # Merge vault-resolved keys so configured=True for vault-only keys
        vault_keys = await devvault.vault_resolve_all_provider_keys(conn)
        for provider_id, api_key in vault_keys.items():
            spec = provider_registry.PROVIDER_BY_ID.get(provider_id)
            if spec and api_key and not settings.get(spec.key_setting):
                settings = {**settings, spec.key_setting: api_key}
        projects = await devdb.get_projects(conn, status="active")
        resources = await devdb.list_resources(conn)
        memory_overview = await memory_engine.sync_memory_layers(conn, settings)
        terminal_sessions = await devdb.list_terminal_sessions(conn, limit=6)

    available_models = await brain.ollama_list_models(settings.get("ollama_url", ""))
    ollama_service = _ollama_service_status()
    status = runtime_manager.build_runtime_status(
        settings=settings,
        available_models=available_models,
        ollama_running=bool(ollama_service.get("running")),
        vault_unlocked=devvault.VaultSession.is_unlocked(),
        workspace_count=len(projects),
        resource_count=len(resources),
        memory_overview=memory_overview,
        usage=brain.get_session_usage(),
    )
    status["ollama_service"] = ollama_service
    status["ollama_runtime_mode"] = _stored_ollama_runtime_mode(settings)
    status["connection"] = _connection_snapshot()
    status["live_operator"] = dict(_live_operator_snapshot)
    status["terminal"] = {
        "active_session_id": next((row["id"] for row in terminal_sessions if row["id"] in _terminal_processes), None),
        "session_count": len(terminal_sessions),
        "running_count": sum(1 for row in terminal_sessions if row["id"] in _terminal_processes),
    }
    status["browser_actions"] = _serialize_browser_action_state()
    return status


async def _build_live_snapshot() -> dict:
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        terminal_rows = await devdb.list_terminal_sessions(conn, limit=6)
        activity_rows = await devdb.get_activity(conn, limit=6)
    running_session_id = next((row["id"] for row in terminal_rows if row["id"] in _terminal_processes), None)
    # Run the blocking domain probe in a thread to avoid stalling the event loop
    connection = await asyncio.get_event_loop().run_in_executor(None, _connection_snapshot)
    return {
        "type": "snapshot",
        "at": _now_iso(),
        "connection": connection,
        "operator": dict(_live_operator_snapshot),
        "runtime": {
            "runtime_label": (
                "Local Ollama" if settings.get("ai_backend", "ollama") == "ollama"
                else "External API" if settings.get("ai_backend") == "api"
                else "CLI Agent" if settings.get("ai_backend") == "cli"
                else "Runtime offline"
            ),
            "active_model": settings.get("code_model") or settings.get("ollama_model") or settings.get("general_model") or "Saved default",
        },
        "terminal": {
            "active_session_id": running_session_id,
            "sessions": [
                _serialize_terminal_session(row, running=row["id"] in _terminal_processes)
                for row in terminal_rows
            ],
        },
        "browser_actions": _serialize_browser_action_state(),
        "activity": [dict(row) for row in activity_rows],
    }


@app.get("/api/connection/status")
async def connection_status():
    return _connection_snapshot()


@app.get("/api/live/feed")
async def live_feed(request: Request):
    async def generate():
        tick = 0
        while True:
            if await request.is_disconnected():
                return
            try:
                snapshot = await _build_live_snapshot()
                yield {"data": _json.dumps(snapshot)}
            except Exception:
                yield {"data": _json.dumps({"type": "heartbeat", "at": _now_iso()})}
            await asyncio.sleep(4)
            tick += 1
            # Send lightweight heartbeat between full snapshots
            if tick % 2 == 1:
                if await request.is_disconnected():
                    return
                yield {"data": _json.dumps({"type": "heartbeat", "at": _now_iso()})}
                await asyncio.sleep(4)

    return EventSourceResponse(generate())


# ─── Mobile info ──────────────────────────────────────────────────────────────

@app.get("/api/mobile/info")
async def mobile_info():
    """Return local IP, Tailscale IP + QR code for mobile access."""
    import socket, io, base64
    config = _connection_config()
    probe = _probe_public_origin(config["public_base_url"], config["stable_domain_enabled"])
    tunnel_running = _tunnel_running()

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
    cloudflared_url = _read_tunnel_url(config)

    # Prefer cloudflared (HTTPS) > Tailscale > LAN for QR code
    if probe["active"] and config["public_base_url"]:
        qr_url = config["public_base_url"]
    elif cloudflared_url:
        qr_url = cloudflared_url
    elif config["stable_domain_enabled"] and stable_domain_url:
        qr_url = stable_domain_url
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
        "tunnel_running": tunnel_running,
        "stable_domain": config["stable_domain"],
        "stable_domain_url": config["public_base_url"],
        "stable_domain_enabled": config["stable_domain_enabled"],
        "stable_domain_status": probe["status"],
        "stable_domain_detail": probe["detail"],
        "tunnel_mode": config.get("tunnel_mode", "trycloudflare"),
        "named_tunnel_ready": config.get("named_tunnel_ready", False),
        "qr_url": qr_url,
        "port": PORT,
        "qr_data_uri": qr_data_uri,
    }


@app.get("/api/browser/actions")
async def browser_actions_status():
    return _serialize_browser_action_state()


@app.post("/api/browser/session")
async def update_browser_session(body: BrowserSessionUpdate):
    session = dict(_browser_action_state["session"])
    if body.connected is not None:
        session["connected"] = bool(body.connected)
    if body.url is not None:
        session["url"] = str(body.url or "").strip()
    if body.title is not None:
        session["title"] = str(body.title or "").strip()
    if body.mode is not None:
        mode = str(body.mode or "approval_required").strip().lower()
        session["mode"] = mode if mode in {"approval_required", "inspect_auto"} else "approval_required"
    session["last_seen_at"] = _now_iso()
    _browser_action_state["session"] = session
    return _serialize_browser_action_state()


@app.post("/api/browser/actions/propose")
async def create_browser_action_proposal(body: BrowserActionProposalCreate):
    created_at = _now_iso()
    proposal = {
        "id": _next_browser_action_id(),
        "action_type": str(body.action_type or "inspect").strip().lower(),
        "summary": str(body.summary or "Browser action requested").strip(),
        "target": str(body.target or "").strip(),
        "value": str(body.value or "").strip(),
        "url": str(body.url or "").strip(),
        "risk": str(body.risk or "medium").strip().lower(),
        "scope": str(body.scope or "browser_act").strip().lower(),
        "requires_confirmation": bool(body.requires_confirmation if body.requires_confirmation is not None else True),
        "metadata": body.metadata or {},
        "status": "pending",
        "created_at": created_at,
        "updated_at": created_at,
    }
    _browser_action_state["proposals"] = [proposal, *(_browser_action_state["proposals"] or [])]
    return {"created": True, "proposal": proposal, **_serialize_browser_action_state()}


@app.post("/api/browser/actions/{proposal_id}/reject")
async def reject_browser_action(proposal_id: int):
    proposals = list(_browser_action_state["proposals"] or [])
    for idx, proposal in enumerate(proposals):
        if int(proposal.get("id") or 0) != proposal_id:
            continue
        updated = {
            **proposal,
            "status": "rejected",
            "updated_at": _now_iso(),
        }
        proposals.pop(idx)
        _browser_action_state["proposals"] = proposals
        _browser_action_state["history"] = [updated, *(_browser_action_state["history"] or [])][:50]
        return {"rejected": True, "proposal": updated, **_serialize_browser_action_state()}
    raise HTTPException(404, "Browser action proposal not found")


# ── Browser Bridge (Playwright) ──────────────────────────────────────────────

@app.post("/api/browser/bridge/start")
async def browser_bridge_start(headless: bool = False):
    """Start the Playwright browser bridge."""
    try:
        import browser_bridge
        bridge = browser_bridge.get_bridge()
        if bridge.is_running:
            return {"status": "already_running", **bridge.status()}
        proxy = None
        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            proxy_url = settings.get("resource_fetch_proxy", "").strip()
            if proxy_url:
                proxy = {"server": proxy_url}
        await bridge.start(headless=headless, proxy=proxy)
        return {"status": "started", **bridge.status()}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to start browser bridge: {e}")


@app.post("/api/browser/bridge/stop")
async def browser_bridge_stop():
    """Stop the Playwright browser bridge."""
    try:
        import browser_bridge
        bridge = browser_bridge.get_bridge()
        await bridge.stop()
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(500, f"Failed to stop bridge: {e}")


@app.get("/api/browser/bridge/status")
async def browser_bridge_status():
    """Get browser bridge status."""
    try:
        import browser_bridge
        bridge = browser_bridge.get_bridge()
        return bridge.status()
    except Exception:
        return {"running": False, "url": "", "title": ""}


@app.post("/api/browser/bridge/execute")
async def browser_bridge_execute(request: Request):
    """Execute an approved browser action via the Playwright bridge."""
    try:
        import browser_bridge
        bridge = browser_bridge.get_bridge()
        if not bridge.is_running:
            raise HTTPException(400, "Browser bridge is not running. Start it first.")
        body = await request.json()
        result = await bridge.execute_action(body)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Execution error: {e}")


@app.post("/api/browser/actions/{proposal_id}/approve")
async def approve_and_execute_browser_action(proposal_id: int):
    """Approve a browser action AND execute it via the Playwright bridge if running."""
    proposals = list(_browser_action_state["proposals"] or [])
    for idx, proposal in enumerate(proposals):
        if int(proposal.get("id") or 0) != proposal_id:
            continue
        updated = {
            **proposal,
            "status": "approved",
            "updated_at": _now_iso(),
        }
        proposals.pop(idx)
        _browser_action_state["proposals"] = proposals
        _browser_action_state["history"] = [updated, *(_browser_action_state["history"] or [])][:50]

        # Execute via bridge if running
        execution_result = None
        try:
            import browser_bridge
            bridge = browser_bridge.get_bridge()
            if bridge.is_running:
                execution_result = await bridge.execute_action(updated)
                updated["execution_result"] = execution_result
        except Exception:
            pass

        return {"approved": True, "proposal": updated, "execution": execution_result, **_serialize_browser_action_state()}
    raise HTTPException(404, "Browser action proposal not found")


@app.get("/api/desktop/preview")
async def desktop_preview(w: int = 960, h: int = 540):
    """Return a lightweight PNG preview of the current desktop."""
    width = max(320, min(int(w), 1600))
    height = max(180, min(int(h), 900))
    display = os.environ.get("DISPLAY", "")

    # ── Fallback chain for screen capture ────────────────────────────────────
    strategies: list[tuple[str, list[str]]] = []
    if display:
        if shutil.which("scrot"):
            strategies.append(("scrot", ["scrot", "-z", "-o", "--quality", "70", "/dev/stdout"]))
        if shutil.which("gnome-screenshot"):
            strategies.append(("gnome-screenshot", ["gnome-screenshot", "-f", "/dev/stdout"]))
        if shutil.which("import"):
            strategies.append(("import", ["import", "-silent", "-window", "root", "-resize", f"{width}x{height}", "png:-"]))
    if shutil.which("xvfb-run") and shutil.which("import"):
        strategies.append(("xvfb-import", ["xvfb-run", "--auto-servernum", "import", "-silent", "-window", "root", "-resize", f"{width}x{height}", "png:-"]))

    if not strategies:
        return JSONResponse(
            status_code=503,
            content={
                "status": "no_display",
                "message": "No display server available for screen capture. Set DISPLAY or install scrot/xvfb.",
            },
        )

    last_error = ""
    for name, cmd in strategies:
        env = os.environ.copy()
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=8, check=False, env=env)
        except subprocess.TimeoutExpired:
            last_error = f"{name}: timed out"
            continue
        except Exception as exc:
            last_error = f"{name}: {exc}"
            continue

        if result.returncode != 0 or not result.stdout:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            last_error = f"{name}: exit {result.returncode} — {stderr[:120]}"
            continue

        return Response(
            content=result.stdout,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    return JSONResponse(
        status_code=503,
        content={
            "status": "capture_failed",
            "message": f"All capture strategies failed. Last: {last_error[:200]}",
        },
    )


# ─── Tunnel management ────────────────────────────────────────────────────────

import subprocess as _subprocess
import re as _re

TUNNEL_LOG = Path.home() / ".devbrain" / "cloudflared.log"
TUNNEL_PID = Path.home() / ".devbrain" / ".tunnel.pid"
TUNNEL_BIN = Path.home() / ".devbrain" / "cloudflared"
TUNNEL_SH  = Path.home() / ".devbrain" / "tunnel.sh"


def _read_tunnel_url(config: Optional[dict] = None) -> str:
    config = config or _connection_config()
    try:
        if config.get("tunnel_mode") == "named" and _tunnel_running():
            return config.get("public_base_url") or ""
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
    config = _connection_config()
    running = _tunnel_running()
    url = _read_tunnel_url(config) if running else ""
    return {
        "running": running,
        "url": url,
        "mode": config.get("tunnel_mode", "trycloudflare"),
        "named_tunnel_ready": config.get("named_tunnel_ready", False),
    }


@app.post("/api/tunnel/start")
async def tunnel_start():
    config = _connection_config()
    if _tunnel_running():
        return {
            "running": True,
            "url": _read_tunnel_url(config),
            "mode": config["tunnel_mode"],
            "msg": "Already running",
        }
    if not TUNNEL_BIN.exists():
        raise HTTPException(400, "cloudflared binary not found")
    if config["tunnel_mode"] == "external":
        raise HTTPException(400, "External domain mode does not start a local tunnel.")
    if config.get("tunnel_mode") == "named" and not config.get("named_tunnel_ready"):
        raise HTTPException(400, "Named tunnel mode needs a saved Cloudflare tunnel token.")
    # Clear old log
    TUNNEL_LOG.write_text("")
    cmd = [str(TUNNEL_BIN)]
    expected_url = ""
    if config["tunnel_mode"] == "named":
        cmd.extend(["--no-autoupdate", "tunnel", "run", "--token", config["cloudflare_tunnel_token"]])
        expected_url = config["public_base_url"]
    else:
        cmd.extend(["tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"])
    proc = _subprocess.Popen(cmd, stdout=open(str(TUNNEL_LOG), "a"), stderr=_subprocess.STDOUT)
    TUNNEL_PID.write_text(str(proc.pid))
    # Wait up to 12s for URL
    import asyncio as _aio
    for _ in range(24):
        await _aio.sleep(0.5)
        if config["tunnel_mode"] == "named":
            if _tunnel_running():
                return {"running": True, "url": expected_url, "mode": "named", "msg": "Named tunnel started"}
        else:
            url = _read_tunnel_url(config)
            if url:
                return {"running": True, "url": url, "mode": "trycloudflare", "msg": "Tunnel started"}
    return {
        "running": True,
        "url": expected_url if config["tunnel_mode"] == "named" else "",
        "mode": config["tunnel_mode"],
        "msg": "Started — URL not yet ready",
    }


@app.post("/api/tunnel/stop")
async def tunnel_stop():
    config = _connection_config()
    if TUNNEL_PID.exists():
        try:
            pid = int(TUNNEL_PID.read_text().strip())
            _subprocess.run(["kill", str(pid)], check=False)
        except Exception:
            pass
        TUNNEL_PID.unlink(missing_ok=True)
    TUNNEL_LOG.write_text("")
    return {"running": False, "url": "", "mode": config["tunnel_mode"], "msg": "Tunnel stopped"}


# ─── GitHub integration ───────────────────────────────────────────────────────

# ─── Azure TTS proxy ─────────────────────────────────────────────────────────

from fastapi.responses import Response as FastAPIResponse


class TTSRequest(BaseModel):
    text: str
    voice: str = "en-ZA-LeahNeural"   # South African English


class VoiceSpeakRequest(BaseModel):
    text: str
    format: str = "wav"


async def _issue_azure_speech_token(region: str, key: str) -> str:
    """Mint a short-lived Azure Speech auth token."""
    import aiohttp
    token_url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            token_url,
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status != 200:
                detail = await r.text()
                raise HTTPException(400, f"Azure auth failed ({r.status})")
            return await r.text()


@app.post("/api/tts")
async def azure_tts(body: TTSRequest):
    """Proxy text-to-speech via Azure Cognitive Services."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    key = settings.get("azure_speech_key", "")
    region = settings.get("azure_speech_region", "eastus")
    if not key:
        raise HTTPException(400, "Azure Speech key not set in Settings")

    ssml = f"""<speak version='1.0' xml:lang='en-ZA'>
        <voice name='{body.voice}'>{body.text[:500]}</voice>
    </speak>"""
    tts_url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    import aiohttp
    try:
        token = await _issue_azure_speech_token(region, key)
        async with aiohttp.ClientSession() as session:
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


@app.get("/api/stt/token")
async def azure_stt_token():
    """Return a short-lived Azure Speech auth token for browser microphone STT."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    key = settings.get("azure_speech_key", "")
    region = settings.get("azure_speech_region", "eastus")
    if not key:
        raise HTTPException(400, "Azure Speech key not set in Settings")
    token = await _issue_azure_speech_token(region, key)
    return {
        "token": token,
        "region": region,
        "expires_in": 540,
    }


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


@app.get("/api/voice/status")
async def voice_status():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    return _local_voice_status(settings)


@app.post("/api/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...), language: str = Query(default="en")):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    status = _local_voice_status(settings)
    if not status["transcription_available"]:
        raise HTTPException(503, status["detail"])

    suffix = Path(file.filename or "voice.webm").suffix or ".webm"
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "No audio payload received")

    input_path = ""
    wav_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as input_file:
            input_file.write(raw_bytes)
            input_path = input_file.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name
        _run_ffmpeg_to_wav(input_path, wav_path)
        text, engine = _transcribe_local_audio(
            wav_path,
            model_name=status["stt_model"],
            language=language or status["language"],
        )
        _local_voice_state.update({
            "last_engine": engine,
            "last_error": "",
            "updated_at": _now_iso(),
        })
        return {
            "text": text,
            "engine": engine,
            "language": language or status["language"],
        }
    except HTTPException as exc:
        _local_voice_state.update({
            "last_error": str(exc.detail),
            "updated_at": _now_iso(),
        })
        raise
    except Exception as exc:
        _local_voice_state.update({
            "last_error": str(exc),
            "updated_at": _now_iso(),
        })
        raise HTTPException(502, f"Voice transcription failed: {exc}")
    finally:
        if input_path:
            Path(input_path).unlink(missing_ok=True)
        if wav_path:
            Path(wav_path).unlink(missing_ok=True)


@app.post("/api/voice/speak")
async def voice_speak(body: VoiceSpeakRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    status = _local_voice_status(settings)
    if not status["synthesis_available"]:
        raise HTTPException(503, status["detail"])
    paths = _local_voice_paths(settings)
    _local_voice_state.update({
        "speaking": True,
        "last_error": "",
        "updated_at": _now_iso(),
    })
    try:
        audio, engine = _speak_local_text(
            body.text,
            model_path=paths["piper_model_path"],
            config_path=paths["piper_config_path"],
        )
        _local_voice_state.update({
            "speaking": False,
            "last_engine": engine,
            "updated_at": _now_iso(),
        })
        return FastAPIResponse(content=audio, media_type="audio/wav")
    except HTTPException as exc:
        _local_voice_state.update({
            "speaking": False,
            "last_error": str(exc.detail),
            "updated_at": _now_iso(),
        })
        raise
    except Exception as exc:
        _local_voice_state.update({
            "speaking": False,
            "last_error": str(exc),
            "updated_at": _now_iso(),
        })
        raise HTTPException(502, f"Voice synthesis failed: {exc}")


@app.post("/api/voice/stop")
async def voice_stop():
    _local_voice_state.update({
        "speaking": False,
        "updated_at": _now_iso(),
    })
    return {"stopped": True}


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


# ─── Terminal control ────────────────────────────────────────────────────────

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


async def _resolve_terminal_cwd(conn, session_row, requested_cwd: Optional[str] = None) -> Path:
    if requested_cwd:
        return _safe_path(requested_cwd)
    session_cwd = (session_row.get("cwd") or "").strip()
    if session_cwd:
        return _safe_path(session_cwd)
    workspace_id = session_row.get("workspace_id")
    if workspace_id:
        proj = await devdb.get_project(conn, int(workspace_id))
        if proj and proj.get("path"):
            return _safe_path(proj["path"])
    return _HOME


def _terminal_timeout_seconds(settings: dict, requested: Optional[int]) -> int:
    base = settings.get("terminal_command_timeout_seconds") or "25"
    try:
        default = int(str(base).strip())
    except Exception:
        default = 25
    if requested is None:
        return max(5, min(300, default))
    return max(5, min(300, int(requested)))


async def _terminal_capture(session_id: int, process, command: str, timeout_seconds: int):
    info = _terminal_processes.get(session_id, {})
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
            async with devdb.get_db() as conn:
                await devdb.add_terminal_event(
                    conn,
                    session_id=session_id,
                    event_type="output",
                    content=text[:4000],
                )
            _set_live_operator(
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
        async with devdb.get_db() as conn:
            await devdb.update_terminal_session(
                conn,
                session_id,
                status=status,
                pending_command="",
                active_command="",
                pid=0,
            )
            await devdb.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="status",
                content=final_message,
                exit_code=return_code,
            )
        _set_live_operator(
            active=False,
            mode="terminal",
            phase="verify" if status == "completed" else "recover",
            title="Terminal command finished",
            detail=final_message,
            summary=f"{command} · exit {return_code}",
            preserve_started=False,
        )
    except Exception as exc:
        async with devdb.get_db() as conn:
            await devdb.update_terminal_session(
                conn,
                session_id,
                status="failed",
                pending_command="",
                active_command="",
                pid=0,
            )
            await devdb.add_terminal_event(
                conn,
                session_id=session_id,
                event_type="error",
                content=str(exc),
            )
        _set_live_operator(
            active=False,
            mode="terminal",
            phase="recover",
            title="Terminal command failed",
            detail=str(exc),
            summary=command,
        )
    finally:
        _terminal_processes.pop(session_id, None)


async def _start_terminal_command(
    *,
    session_id: int,
    command: str,
    cwd: Path,
    timeout_seconds: int,
):
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
    )
    _terminal_processes[session_id] = {
        "process": process,
        "command": command,
        "cwd": str(cwd),
        "started_at": _now_iso(),
    }
    async with devdb.get_db() as conn:
        await devdb.update_terminal_session(
            conn,
            session_id,
            status="running",
            active_command=command,
            pending_command="",
            cwd=str(cwd),
            pid=process.pid or 0,
        )
        await devdb.add_terminal_event(
            conn,
            session_id=session_id,
            event_type="command",
            content=f"$ {command}",
        )
    _set_live_operator(
        active=True,
        mode="terminal",
        phase="execute",
        title="Running terminal command",
        detail=f"{command} · {cwd}",
        summary=f"Running: {command}",
    )
    asyncio.create_task(_terminal_capture(session_id, process, command, timeout_seconds))
    return {
        "status": "running",
        "command": command,
        "cwd": str(cwd),
        "pid": process.pid or 0,
        "timeout_seconds": timeout_seconds,
    }


async def _terminal_execute_request(session_id: int, body: TerminalCommandBody, *, approved: bool = False):
    command = (body.command or "").strip()
    if not command:
        raise HTTPException(400, "Command is required")
    if _command_is_blocked(command):
        raise HTTPException(400, "That command is blocked in Axon terminal mode.")

    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        session_row = await devdb.get_terminal_session(conn, session_id)
        if not session_row:
            raise HTTPException(404, "Terminal session not found")
        if session_row["status"] == "running" and session_id in _terminal_processes:
            raise HTTPException(409, "A command is already running in this session.")

        mode = _terminal_mode_value(body.mode, session_row["mode"] or settings.get("terminal_default_mode", "read_only"))
        cwd = await _resolve_terminal_cwd(conn, session_row, body.cwd)
        timeout_seconds = _terminal_timeout_seconds(settings, body.timeout_seconds)

        # Block dangerous commands regardless of mode
        if _command_is_blocked(command):
            await devdb.add_terminal_event(
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
            await devdb.update_terminal_session(conn, session_id, mode=mode, cwd=str(cwd), status="idle", pending_command="")
            await devdb.add_terminal_event(
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

        if mode == "read_only" and not _command_is_read_only(command):
            await devdb.add_terminal_event(
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
            await devdb.update_terminal_session(
                conn,
                session_id,
                mode=mode,
                cwd=str(cwd),
                status="pending_approval",
                pending_command=command,
            )
            await devdb.add_terminal_event(
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

        await devdb.update_terminal_session(conn, session_id, mode=mode, cwd=str(cwd), status="idle")
    return await _start_terminal_command(
        session_id=session_id,
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )


@app.get("/api/terminal/sessions")
async def list_terminal_sessions(workspace_id: Optional[int] = None, limit: int = 20):
    async with devdb.get_db() as conn:
        rows = await devdb.list_terminal_sessions(conn, workspace_id=workspace_id, limit=limit)
    return [
        _serialize_terminal_session(
            row,
            running=row["id"] in _terminal_processes,
        )
        for row in rows
    ]


@app.post("/api/terminal/sessions")
async def create_terminal_session(body: TerminalSessionCreate):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        mode = _terminal_mode_value(body.mode, settings.get("terminal_default_mode", "read_only"))
        cwd = str(await _resolve_terminal_cwd(conn, {"cwd": body.cwd or "", "workspace_id": body.workspace_id}))
        title = (body.title or "").strip() or f"Terminal {datetime.now().strftime('%H:%M')}"
        session_id = await devdb.create_terminal_session(
            conn,
            title=title,
            workspace_id=body.workspace_id,
            mode=mode,
            cwd=cwd,
        )
        session = await devdb.get_terminal_session(conn, session_id)
        await devdb.add_terminal_event(
            conn,
            session_id=session_id,
            event_type="status",
            content=f"Session ready in {cwd}",
        )
    return _serialize_terminal_session(session, running=False)


@app.get("/api/terminal/sessions/{session_id}")
async def get_terminal_session(session_id: int, limit: int = 160):
    async with devdb.get_db() as conn:
        row = await devdb.get_terminal_session(conn, session_id)
        if not row:
            raise HTTPException(404, "Terminal session not found")
        events = await devdb.list_terminal_events(conn, session_id, limit=limit)
    return _serialize_terminal_session(
        row,
        running=session_id in _terminal_processes,
        recent_events=[_serialize_terminal_event(event) for event in events],
    )


@app.post("/api/terminal/sessions/{session_id}/execute")
async def terminal_execute(session_id: int, body: TerminalCommandBody):
    return await _terminal_execute_request(session_id, body, approved=bool(body.approved))


@app.post("/api/terminal/sessions/{session_id}/approve")
async def terminal_approve(session_id: int, body: TerminalCommandBody):
    return await _terminal_execute_request(session_id, body, approved=True)


@app.post("/api/terminal/sessions/{session_id}/stop")
async def terminal_stop(session_id: int):
    entry = _terminal_processes.get(session_id)
    if not entry:
        async with devdb.get_db() as conn:
            row = await devdb.get_terminal_session(conn, session_id)
            if not row:
                raise HTTPException(404, "Terminal session not found")
        return {"status": "idle", "message": "No running command to stop."}

    process = entry.get("process")
    if process and process.returncode is None:
        process.terminate()
        await asyncio.sleep(0.5)
        if process.returncode is None:
            process.kill()
    async with devdb.get_db() as conn:
        await devdb.update_terminal_session(
            conn,
            session_id,
            status="stopped",
            active_command="",
            pending_command="",
            pid=0,
        )
        await devdb.add_terminal_event(
            conn,
            session_id=session_id,
            event_type="status",
            content="Command stopped by the user.",
        )
    _set_live_operator(
        active=False,
        mode="terminal",
        phase="recover",
        title="Terminal command stopped",
        detail="Axon stopped the running command safely.",
        summary=str(entry.get("command") or ""),
    )
    return {"status": "stopped", "message": "Command stopped."}


@app.delete("/api/terminal/sessions/{session_id}")
async def close_terminal_session(session_id: int):
    """Close/terminate a terminal session (kills running process, marks closed)."""
    # Kill PTY if active
    pty_info = _pty_sessions.get(session_id)
    if pty_info:
        try:
            pty_info["proc"].terminate()
        except Exception:
            pass
        _pty_sessions.pop(session_id, None)
    # Kill subprocess process if active
    entry = _terminal_processes.pop(session_id, None)
    if entry:
        process = entry.get("process")
        if process and process.returncode is None:
            try:
                process.terminate()
            except Exception:
                pass
    async with devdb.get_db() as conn:
        row = await devdb.get_terminal_session(conn, session_id)
        if not row:
            raise HTTPException(404, "Terminal session not found")
        await devdb.update_terminal_session(conn, session_id, status="closed", active_command="", pending_command="")
    return {"status": "closed", "message": "Session closed."}


# ─── PTY / Interactive Terminal WebSocket ────────────────────────────────────

@app.websocket("/ws/pty/{session_id}")
async def pty_websocket(websocket: WebSocket, session_id: str):
    """
    Full interactive PTY over WebSocket.
    Protocol (text frames):
      Client → server: raw keystrokes / paste text
      Client → server: JSON {"type":"resize","cols":N,"rows":N}
      Server → client: raw terminal output bytes (base64-encoded JSON {"type":"data","data":"<b64>"})
      Server → client: JSON {"type":"exit","code":N}
    """
    import base64

    await websocket.accept()

    # Auth check — skip if no PIN set, otherwise require token query param
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    if pin_hash:
        token = websocket.query_params.get("token", "")
        if not token or not _valid_session(token):
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
    home = str(Path.home())

    pty_proc = PtyProcess.spawn(
        [shell, "--login"],
        dimensions=(rows, cols),
        env={**os.environ, "TERM": "xterm-256color"},
        cwd=home,
    )

    entry = {"pty": pty_proc, "ws": websocket, "alive": True}
    _pty_sessions[session_id] = entry

    async def _read_pty():
        loop = asyncio.get_event_loop()
        try:
            while entry["alive"] and pty_proc.isalive():
                try:
                    data = await loop.run_in_executor(None, pty_proc.read, 4096)
                    if data:
                        await websocket.send_json({
                            "type": "data",
                            "data": base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode(),
                        })
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

    read_task = asyncio.create_task(_read_pty())
    entry["task"] = read_task

    try:
        while True:
            msg = await websocket.receive_text()
            if not pty_proc.isalive():
                break
            try:
                parsed = _json.loads(msg)
                if parsed.get("type") == "resize":
                    c = int(parsed.get("cols", cols))
                    r = int(parsed.get("rows", rows))
                    pty_proc.setwinsize(r, c)
                elif parsed.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif parsed.get("type") == "input":
                    pty_proc.write(parsed.get("data", ""))
            except (_json.JSONDecodeError, ValueError):
                # Plain text input (keystroke)
                pty_proc.write(msg)
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
        _pty_sessions.pop(session_id, None)


# ─── Ollama endpoints ─────────────────────────────────────────────────────────

@app.get("/api/ollama/status")
async def ollama_status():
    """Check if Ollama is running and return available models."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    url = settings.get("ollama_url", "")
    status = await brain.ollama_status(ollama_url=url)
    service = _ollama_service_status()
    status["runtime_mode"] = _stored_ollama_runtime_mode(settings)
    status["service_mode"] = service.get("mode", "")
    status["service_detail"] = service.get("detail", "")
    return status


class OllamaRuntimeModeBody(BaseModel):
    mode: str


@app.post("/api/ollama/runtime-mode")
async def switch_ollama_runtime_mode(body: OllamaRuntimeModeBody):
    requested = (body.mode or "").strip().lower()
    if requested not in {"cpu_safe", "gpu_default"}:
        raise HTTPException(400, "Unknown Ollama runtime mode.")

    if not OLLAMA_SH.exists():
        raise HTTPException(500, "Ollama launcher not found.")

    launcher_command = "cpu" if requested == "cpu_safe" else "start"
    result = _run_capture([str(OLLAMA_SH), launcher_command], timeout=25)
    if not result["ok"]:
        raise HTTPException(500, result["output"] or "Failed to switch Ollama runtime mode.")

    ollama_url = "http://127.0.0.1:11435" if requested == "cpu_safe" else brain.OLLAMA_BASE_URL
    status = await brain.ollama_status(ollama_url=ollama_url)

    async with devdb.get_db() as conn:
        await devdb.set_setting(conn, "ollama_runtime_mode", requested)
        await devdb.set_setting(conn, "ollama_url", ollama_url)

    return {
        "ok": True,
        "runtime_mode": requested,
        "ollama_url": ollama_url,
        "status": status,
        "launcher_output": result["output"],
    }


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
            _err_msg = str(exc)
            yield {"data": _json.dumps({"error": _err_msg, "status": "error"})}

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

    if lower.startswith("cpu-safe: running"):
        mode = "cpu_safe"
        running = True
    elif lower.startswith("systemd: active"):
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


def _stored_ollama_runtime_mode(settings: dict) -> str:
    explicit = (settings.get("ollama_runtime_mode") or "").strip().lower()
    if explicit in {"cpu_safe", "gpu_default"}:
        return explicit
    url = (settings.get("ollama_url") or "").strip().rstrip("/")
    return "cpu_safe" if url.endswith(":11435") else "gpu_default"


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


# ─── Backup — export / import ─────────────────────────────────────────────────

@app.get("/api/backup/export")
async def backup_export():
    """Export all Axon data as a JSON snapshot (vault secrets excluded)."""
    async with devdb.get_db() as conn:
        projects = [dict(r) for r in await devdb.get_projects(conn)]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status=None)]
        prompts = [dict(r) for r in await devdb.get_prompts(conn)]
        memory = [dict(r) for r in await devdb.list_memory_items(conn, limit=5000)]
        resources = [dict(r) for r in await devdb.list_resources(conn, limit=5000)]
        settings = await devdb.get_all_settings(conn)
        chat = [dict(r) for r in await devdb.get_chat_history(conn, limit=10000)]

    # Strip sensitive settings
    for key in ("auth_pin_hash", "vault_key_hash"):
        settings.pop(key, None)

    snapshot = {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "projects": projects,
        "tasks": tasks,
        "prompts": prompts,
        "memory_items": memory,
        "resources_metadata": resources,
        "settings": settings,
        "chat_history": chat,
    }
    return JSONResponse(snapshot)


@app.post("/api/backup/import")
async def backup_import(request: Request):
    """Import a JSON snapshot into Axon (additive — does not delete existing data)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(data, dict) or "version" not in data:
        raise HTTPException(400, "Missing version field — not a valid Axon backup")

    counts: dict[str, int] = {}
    async with devdb.get_db() as conn:
        # Import tasks
        for t in data.get("tasks", []):
            try:
                await conn.execute(
                    """INSERT OR IGNORE INTO tasks
                       (project_id, title, detail, status, priority, due_date)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (t.get("project_id", 1), t["title"], t.get("detail", ""),
                     t.get("status", "open"), t.get("priority", "medium"),
                     t.get("due_date")),
                )
            except Exception:
                continue
        counts["tasks"] = len(data.get("tasks", []))

        # Import prompts
        for p in data.get("prompts", []):
            try:
                await conn.execute(
                    """INSERT OR IGNORE INTO prompts (project_id, label, body)
                       VALUES (?, ?, ?)""",
                    (p.get("project_id", 1), p["label"], p.get("body", "")),
                )
            except Exception:
                continue
        counts["prompts"] = len(data.get("prompts", []))

        # Import memory items
        for m in data.get("memory_items", []):
            try:
                await conn.execute(
                    """INSERT OR IGNORE INTO memory_items
                       (workspace_id, memory_key, summary, layer, source, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (m.get("workspace_id", 1), m.get("memory_key", ""),
                     m.get("summary", ""), m.get("layer", "general"),
                     m.get("source", "import"), m.get("metadata_json", "{}")),
                )
            except Exception:
                continue
        counts["memory_items"] = len(data.get("memory_items", []))

        # Import settings (skip auth-related)
        skip_keys = {"auth_pin_hash", "vault_key_hash"}
        for key, val in data.get("settings", {}).items():
            if key not in skip_keys:
                await devdb.set_setting(conn, key, val)
        counts["settings"] = len(data.get("settings", {}))

        await conn.commit()

    return {"status": "imported", "counts": counts}


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "port": PORT}


# ─── PPTX Generation ──────────────────────────────────────────────────────────

class _PptxFromPromptRequest(BaseModel):
    prompt: str
    context: str = ""
    theme: str = "dark"
    output_path: str = ""

class _PptxFromDataRequest(BaseModel):
    deck: dict
    output_path: str = ""

@app.post("/api/generate/pptx/ai")
async def generate_pptx_ai(body: _PptxFromPromptRequest):
    """Generate a PPTX deck from a natural-language prompt using the AI model."""
    try:
        from pptx_engine import prompt_to_deck_json, deck_from_dict, build_deck
    except ImportError as e:
        return JSONResponse({"error": f"pptx_engine not available: {e}"}, status_code=500)

    try:
        # Build a simple model_fn using Ollama or provider
        import httpx

        def model_fn(system: str, user: str) -> str:
            settings = {}
            try:
                import sqlite3
                conn = sqlite3.connect(str(DB_PATH))
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT key, value FROM settings").fetchall()
                settings = {r["key"]: r["value"] for r in rows}
                conn.close()
            except Exception:
                pass

            ollama_model = settings.get("code_model") or settings.get("ollama_model") or "qwen2.5-coder:1.5b"
            payload = {
                "model": ollama_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.3},
            }
            resp = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

        deck_json = prompt_to_deck_json(body.prompt, body.context, model_fn)
        if body.output_path:
            deck_json["output_path"] = body.output_path
        if body.theme:
            deck_json["theme"] = body.theme

        spec = deck_from_dict(deck_json)
        out_path = build_deck(spec)

        return JSONResponse({
            "ok": True,
            "path": str(out_path),
            "filename": out_path.name,
            "slides": len(spec.slides),
            "title": spec.title,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/generate/pptx")
async def generate_pptx_from_data(body: _PptxFromDataRequest):
    """Generate a PPTX deck from a pre-structured deck JSON object."""
    try:
        from pptx_engine import deck_from_dict, build_deck
    except ImportError as e:
        return JSONResponse({"error": f"pptx_engine not available: {e}"}, status_code=500)
    try:
        data = body.deck
        if body.output_path:
            data["output_path"] = body.output_path
        spec = deck_from_dict(data)
        out_path = build_deck(spec)
        return JSONResponse({
            "ok": True,
            "path": str(out_path),
            "filename": out_path.name,
            "slides": len(spec.slides),
            "title": spec.title,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/generate/pptx/download")
async def download_pptx(path: str):
    """Stream a generated PPTX file to the browser."""
    from fastapi.responses import FileResponse
    import urllib.parse
    file_path = Path(urllib.parse.unquote(path))
    if not file_path.exists() or file_path.suffix != ".pptx":
        raise HTTPException(404, "File not found")
    # Safety: must be within home directory
    home = Path.home()
    try:
        file_path.relative_to(home)
    except ValueError:
        raise HTTPException(403, "Access denied")
    return FileResponse(
        str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=file_path.name,
    )


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


@app.get("/styles.css")
async def serve_styles():
    css_path = UI_DIR / "styles.css"
    if not css_path.exists():
        return Response("/* not found */", media_type="text/css", status_code=404)
    return FileResponse(css_path, media_type="text/css", headers={"Cache-Control": "no-cache"})

@app.get("/js/{filename:path}")
async def serve_js(filename: str):
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_\-]+\.js$', filename):
        return Response("// not found", media_type="application/javascript", status_code=404)
    js_path = UI_DIR / "js" / filename
    if not js_path.exists():
        return Response("// not found", media_type="application/javascript", status_code=404)
    return FileResponse(js_path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

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
