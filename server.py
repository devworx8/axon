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
import re as _re
import shlex as _shlex
import shutil
import sqlite3 as _sqlite3
import subprocess
import tempfile
import time as _time
import wave
import textwrap
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib import error as _urlerror, request as _urlrequest

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import uvicorn
import json as _json
from PIL import Image, ImageDraw

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
from axon_api.settings_models import SettingsUpdate
from axon_api.services import auto_sessions as auto_session_service
from axon_api.services import companion_auth as companion_auth_service
from axon_api.services import claude_cli_runtime, codex_cli_runtime
from axon_api.services import console_commands as console_command_service
from axon_api.services import live_preview_sessions as live_preview_service
from axon_api.services import local_tool_env
from axon_api.services import runtime_login_sessions as runtime_login_service
from axon_api.services import runtime_truth as runtime_truth_service
from axon_core.cli_pacing import current_cli_cooldown
from axon_core.cli_command import cli_session_persistence_enabled
from axon_core.chat_context import select_history_for_chat
from axon_core import agent_runtime_state
from axon_core.approval_actions import build_command_approval_action, build_edit_approval_action
from axon_api.services import task_sandboxes as task_sandbox_service
from axon_data.sqlite_utils import managed_connection
from axon_core.vision_runtime import auto_route_vision_runtime
from axon_api import ui_renderer
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

_live_operator_snapshot = {
    "active": False,
    "mode": "idle",
    "phase": "observe",
    "title": "Standing by",
    "detail": "Axon is ready for the next request.",
    "tool": "",
    "summary": "",
    "workspace_id": None,
    "auto_session_id": "",
    "changed_files_count": 0,
    "apply_allowed": False,
    "started_at": "",
    "updated_at": "",
    "feed": [],
}
_terminal_processes: dict[int, dict] = {}
# PTY WebSocket sessions: session_id → {pty, ws_set, task}
_pty_sessions: dict[str, dict] = {}
_task_sandbox_runs: dict[int, asyncio.Task] = {}
_auto_session_runs: dict[str, asyncio.Task] = {}
_domain_probe_cache = {
    "url": "",
    "active": False,
    "status": "planned",
    "detail": "",
    "checked_at": 0.0,
}
_memory_sync_cache = {
    "checked_at": 0.0,
    "overview": None,
}
_MEMORY_SYNC_CACHE_TTL_SECONDS = 45.0


def _default_browser_session() -> dict[str, object]:
    return {
        "connected": False,
        "url": "",
        "title": "",
        "last_seen_at": "",
        "mode": "approval_required",
        "control_owner": "manual",
        "control_state": "idle",
        "ownership_label": "Manual browser",
        "attached_preview_url": "",
        "attached_preview_status": "",
        "attached_workspace_id": None,
        "attached_workspace_name": "",
        "attached_auto_session_id": "",
        "attached_scope_key": "",
        "attached_source_workspace_path": "",
    }


def _normalize_browser_session(session: dict | None = None, **updates: object) -> dict[str, object]:
    item = {**_default_browser_session(), **(session or {})}
    for key, value in updates.items():
        if value is not None:
            item[key] = value

    mode = str(item.get("mode") or "approval_required").strip().lower()
    item["mode"] = mode if mode in {"approval_required", "inspect_auto"} else "approval_required"

    owner = str(item.get("control_owner") or "manual").strip().lower()
    item["control_owner"] = "axon" if owner == "axon" else "manual"
    item["connected"] = bool(item.get("connected"))
    item["url"] = str(item.get("url") or "")
    item["title"] = str(item.get("title") or "")
    item["last_seen_at"] = str(item.get("last_seen_at") or "")
    item["attached_preview_url"] = str(item.get("attached_preview_url") or "")
    item["attached_preview_status"] = str(item.get("attached_preview_status") or "")
    item["attached_workspace_name"] = str(item.get("attached_workspace_name") or "")
    item["attached_auto_session_id"] = str(item.get("attached_auto_session_id") or "")
    item["attached_scope_key"] = str(item.get("attached_scope_key") or "")
    item["attached_source_workspace_path"] = str(item.get("attached_source_workspace_path") or "")

    workspace_id = item.get("attached_workspace_id")
    if workspace_id in ("", 0, "0"):
        item["attached_workspace_id"] = None

    if item["control_owner"] == "axon":
        item["ownership_label"] = "Axon controls this browser now"
    else:
        item["ownership_label"] = "Manual browser"
        item["attached_preview_url"] = ""
        item["attached_preview_status"] = ""
        item["attached_workspace_id"] = None
        item["attached_workspace_name"] = ""
        item["attached_auto_session_id"] = ""
        item["attached_scope_key"] = ""
        item["attached_source_workspace_path"] = ""

    control_state = str(item.get("control_state") or "").strip().lower()
    if control_state not in {"idle", "attached", "blocked"}:
        control_state = "attached" if item["control_owner"] == "axon" and item["connected"] else ("connected" if item["connected"] else "idle")
    item["control_state"] = control_state
    return item


_browser_action_state = {
    "session": _default_browser_session(),
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    auto_session_id: str = "",
    changed_files_count: int = 0,
    apply_allowed: bool = False,
    preserve_started: bool = False,
):
    started_at = _live_operator_snapshot.get("started_at") if preserve_started else _now_iso()
    if not started_at:
        started_at = _now_iso()
    updated_at = _now_iso()
    tracked_auto_session_id = auto_session_id if auto_session_id else (_live_operator_snapshot.get("auto_session_id") if mode == "auto" else "")
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
            "auto_session_id": tracked_auto_session_id or "",
            "changed_files_count": int(changed_files_count or 0) if (active or tracked_auto_session_id) else 0,
            "apply_allowed": bool(apply_allowed) if (active or tracked_auto_session_id) else False,
            "started_at": started_at if active else "",
            "updated_at": updated_at,
        }
    )
    if active or tracked_auto_session_id:
        entry = {
            "id": f"{int(_time.time() * 1000)}-{phase}",
            "phase": phase,
            "title": title,
            "detail": detail,
            "at": updated_at,
        }
        feed = list(_live_operator_snapshot.get("feed") or [])
        last = feed[-1] if feed else None
        if not last or any(str(last.get(key) or "") != str(entry.get(key) or "") for key in ("phase", "title", "detail")):
            feed.append(entry)
            _live_operator_snapshot["feed"] = feed[-12:]
    else:
        _live_operator_snapshot["feed"] = []


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
        "session": _normalize_browser_session(_browser_action_state["session"]),
        "pending_count": sum(1 for item in proposals if item.get("status") == "pending"),
        "proposals": [dict(item) for item in proposals[:20]],
        "history": [dict(item) for item in history[:20]],
        "approval_mode": _normalize_browser_session(_browser_action_state["session"]).get("mode", "approval_required"),
    }


def _next_browser_action_id() -> int:
    current = int(_browser_action_state.get("next_id") or 1)
    _browser_action_state["next_id"] = current + 1
    return current


_BROWSER_ALLOWED_ACTION_TYPES = {
    "navigate",
    "click",
    "type",
    "scroll",
    "screenshot",
    "inspect",
    "wait",
    "go_back",
    "go_forward",
    "evaluate",
}
_BROWSER_DIRECT_READ_ONLY_TYPES = {"inspect", "screenshot", "wait"}


def _normalize_browser_action_payload(action: dict[str, object]) -> dict[str, object]:
    action_type = str(action.get("action_type") or "inspect").strip().lower()
    if action_type not in _BROWSER_ALLOWED_ACTION_TYPES:
        raise HTTPException(400, f"Unsupported browser action_type: {action_type}")

    risk = str(action.get("risk") or "medium").strip().lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"

    normalized: dict[str, object] = {
        "action_type": action_type,
        "summary": str(action.get("summary") or "Browser action requested").strip() or "Browser action requested",
        "target": str(action.get("target") or "").strip(),
        "value": str(action.get("value") or "").strip(),
        "url": str(action.get("url") or "").strip(),
        "risk": risk,
        "scope": str(action.get("scope") or "browser_act").strip().lower() or "browser_act",
        "requires_confirmation": bool(action.get("requires_confirmation", True)),
        "metadata": action.get("metadata") if isinstance(action.get("metadata"), dict) else {},
    }
    for key in ("id", "created_at", "updated_at", "status", "executed_at", "execution_result"):
        if key not in action or action.get(key) is None:
            continue
        normalized[key] = action.get(key)
    return normalized


def _find_approved_browser_action(proposal_id: int) -> Optional[dict]:
    for item in _browser_action_state["history"] or []:
        if int(item.get("id") or 0) == proposal_id and str(item.get("status") or "") == "approved":
            return item
    return None


def _is_chat_history_db_corruption(exc: Exception) -> bool:
    if not isinstance(exc, _sqlite3.DatabaseError):
        return False
    text = str(exc).lower()
    return (
        "database disk image is malformed" in text
        or "file is not a database" in text
        or "database or disk is full" in text
        or "malformed" in text
    )


def _chat_history_db_detail() -> str:
    return (
        "Chat history is temporarily unavailable because the Axon database needs repair or restore. "
        "Export a backup if possible, then run an integrity check on ~/.devbrain/devbrain.db."
    )


async def _load_chat_history_rows(
    conn,
    *,
    project_id: Optional[int] = None,
    limit: int = 20,
    degrade_to_empty: bool = False,
):
    try:
        return await devdb.get_chat_history(conn, project_id=project_id, limit=limit)
    except _sqlite3.DatabaseError as exc:
        if not _is_chat_history_db_corruption(exc):
            raise
        print(f"[Axon] Chat history read failed: {exc}")
        if degrade_to_empty:
            return []
        raise HTTPException(503, _chat_history_db_detail())


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
        with managed_connection(devdb.DB_PATH, row_factory=_sqlite3.Row) as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
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
        # PTY processes never survive a server restart, but their transcript
        # history is still useful. Preserve sessions and mark them stopped.
        try:
            await devdb.mark_terminal_sessions_stopped(conn)
        except Exception:
            pass  # table may not exist yet on first run

    scheduler = sched_module.setup_scheduler(
        scan_interval_hours=scan_hours,
        digest_hour=digest_hour,
    )
    scheduler.start()
    print(f"[Axon] Server started on http://localhost:{PORT}")
    print(f"[Axon] Scheduler running — scan every {scan_hours}h, digest at {digest_hour}:00")

    # Structured exact-action approvals supersede the legacy broad command allowlist.

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

# ── Extracted routers ────────────────────────────────────────────────────────
from axon_api.routes.attention import router as _attention_router
from axon_api.routes.devops import router as _devops_router
from axon_api.routes.companion import router as _companion_router
from axon_api.routes.connectors import router as _connectors_router
app.include_router(_devops_router)
app.include_router(_attention_router)
app.include_router(_companion_router)
app.include_router(_connectors_router)


# ─── Auth — PIN-based session authentication ─────────────────────────────────

import hashlib
import secrets as _secrets

# In-memory session store: { token_str: expiry_datetime }
_auth_sessions: dict[str, datetime] = {}
_AUTH_SESSION_HOURS = 72  # sessions last 3 days
_LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}

# Rate-limit login attempts: { ip_str: (fail_count, last_attempt_time) }
_login_attempts: dict[str, tuple[int, float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 300  # 5-minute lockout after 5 failures


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


_LEGACY_DEV_LOCAL_BYPASS = _env_flag("AXON_DEV_LOCAL_BYPASS", "1")
_DEV_LOCAL_AUTH_BYPASS = _env_flag(
    "AXON_DEV_LOCAL_AUTH_BYPASS",
    "1" if _LEGACY_DEV_LOCAL_BYPASS else "0",
)
_DEV_LOCAL_VAULT_BYPASS = _env_flag(
    "AXON_DEV_LOCAL_VAULT_BYPASS",
    "0",
)


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


def _request_is_localhost(request: Request | None = None) -> bool:
    if request is None:
        return False
    host = str(getattr(request.url, "hostname", "") or "").strip().strip("[]").lower()
    client = str(getattr(getattr(request, "client", None), "host", "") or "").strip().strip("[]").lower()
    return host in _LOCALHOST_NAMES or client in _LOCALHOST_NAMES


def _dev_local_auth_bypass_active(request: Request | None = None) -> bool:
    return _DEV_LOCAL_AUTH_BYPASS and _request_is_localhost(request)


def _dev_local_vault_bypass_active(request: Request | None = None) -> bool:
    return _DEV_LOCAL_VAULT_BYPASS and _request_is_localhost(request)

def _create_session() -> str:
    """Create a new session token, store it, and return it."""
    token = _secrets.token_hex(32)
    _auth_sessions[token] = _utc_now() + timedelta(hours=_AUTH_SESSION_HOURS)
    # Prune expired sessions
    now = _utc_now()
    expired = [k for k, v in _auth_sessions.items() if v < now]
    for k in expired:
        del _auth_sessions[k]
    return token

def _valid_session(token: str) -> bool:
    """Check if a session token is valid and not expired."""
    exp = _auth_sessions.get(token)
    if not exp:
        return False
    if _utc_now() > exp:
        del _auth_sessions[token]
        return False
    return True


async def _valid_session_async(token: str) -> bool:
    if _valid_session(token):
        return True
    if not token:
        return False
    try:
        async with devdb.get_db() as conn:
            companion_session = await companion_auth_service.resolve_companion_auth_session(
                conn,
                access_token=token,
            )
        if not companion_session:
            return False
        if str(companion_session.get("revoked_at") or "").strip():
            return False
        expires_at = str(companion_session.get("expires_at") or "").strip()
        if expires_at:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if _utc_now() > expires:
                return False
        return True
    except Exception:
        return False

# Paths that don't require auth
_AUTH_EXEMPT = {"/", "/sw.js", "/manifest.json", "/manual", "/manual.html",
                "/api/health", "/api/tunnel/status"}
_AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/api/companion/auth/", "/icons/", "/js/", "/styles.css", "/ws/")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protect API routes with session token when a PIN is set."""
    path = request.url.path

    # Always allow auth endpoints, static assets, and the UI itself
    if path in _AUTH_EXEMPT or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return await call_next(request)

    if _dev_local_auth_bypass_active(request):
        return await call_next(request)

    # Check if auth is enabled (PIN is set)
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")

    # No PIN set = auth disabled, allow everything
    if not pin_hash:
        return await call_next(request)

    # PIN is set — require valid session token
    token = _extract_session_token(request)
    if not token or not await _valid_session_async(token):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    return await call_next(request)


class PinSetup(BaseModel):
    pin: str  # 4-6 digit PIN

class PinLogin(BaseModel):
    pin: str

@app.get("/api/auth/status")
async def auth_status(request: Request):
    """Check if auth is enabled and if current session is valid."""
    if _dev_local_auth_bypass_active(request):
        return {
            "auth_enabled": False,
            "session_valid": True,
            "dev_bypass": True,
        }
    async with devdb.get_db() as conn:
        pin_hash = await devdb.get_setting(conn, "auth_pin_hash")
    token = _extract_session_token(request)
    return {
        "auth_enabled": bool(pin_hash),
        "session_valid": (not pin_hash) or bool(token and await _valid_session_async(token)),
        "dev_bypass": False,
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
    elif token:
        async with devdb.get_db() as conn:
            await companion_auth_service.revoke_companion_device_auth(conn, access_token=token)
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
        rows = await conn.execute("SELECT id FROM companion_devices")
        device_rows = await rows.fetchall()
        for row in device_rows:
            await companion_auth_service.revoke_companion_device_auth(conn, device_id=int(row["id"]))
    # Clear all sessions
    _auth_sessions.clear()
    return {"status": "ok"}


# ─── Serve UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return ui_renderer.render_index(UI_DIR, _SW_CACHE_VERSION)


@app.get("/manual", response_class=HTMLResponse)
@app.get("/manual.html", response_class=HTMLResponse)
async def serve_manual():
    return ui_renderer.render_manual(UI_DIR, _SW_CACHE_VERSION)


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

class WorkspacePreviewRequest(BaseModel):
    auto_session_id: Optional[str] = None
    restart: bool = False
    attach_browser: bool = True

@app.get("/api/workspace/env")
async def workspace_env(
    path: str = Query(default=""),
    project_id: int | None = Query(default=None),
    auto_session_id: str = Query(default=""),
):
    """Return venv / git-branch / dir name for an arbitrary workspace path."""
    resolved_path = str(path or "").strip()
    if project_id and not resolved_path:
        async with devdb.get_db() as conn:
            project = await devdb.get_project(conn, int(project_id))
        if project:
            project_path = project["path"] if "path" in project.keys() else ""
            resolved_path = str(project_path or "").strip()
    if project_id and auto_session_id:
        auto_meta = auto_session_service.read_auto_session(auto_session_id)
        if auto_meta and int(auto_meta.get("workspace_id") or 0) == int(project_id):
            resolved_path = str(auto_meta.get("sandbox_path") or resolved_path).strip()

    payload = runtime_manager.env_snapshot(resolved_path or None)
    if resolved_path:
        payload.update(
            live_preview_service.workspace_env_snapshot(
                resolved_path,
                workspace_id=project_id,
                auto_session_id=auto_session_id,
            )
        )
    return payload


@app.get("/api/workspaces/{project_id}/preview")
async def workspace_preview_status(project_id: int, auto_session_id: str = Query(default="")):
    workspace, auto_meta, _ = await _workspace_preview_target(project_id, auto_session_id)
    preview = await asyncio.to_thread(
        lambda: live_preview_service.get_preview_session(
            workspace_id=int(workspace.get("id") or 0),
            auto_session_id=str((auto_meta or {}).get("session_id") or auto_session_id or ""),
        )
    )
    return {
        "workspace_id": workspace.get("id"),
        "workspace_name": workspace.get("name") or "",
        "auto_session_id": str((auto_meta or {}).get("session_id") or auto_session_id or ""),
        "preview": _serialize_preview_session(preview),
    }


@app.post("/api/workspaces/{project_id}/preview/start")
async def start_workspace_preview(project_id: int, body: WorkspacePreviewRequest | None = None):
    payload = body or WorkspacePreviewRequest()
    workspace, auto_meta, target_path = await _workspace_preview_target(project_id, payload.auto_session_id or "")
    title = str((auto_meta or {}).get("title") or workspace.get("name") or "")
    try:
        preview = await asyncio.to_thread(
            lambda: live_preview_service.ensure_preview_session(
                workspace_id=int(workspace.get("id") or 0),
                workspace_name=str(workspace.get("name") or ""),
                source_path=target_path,
                source_workspace_path=str(workspace.get("path") or ""),
                auto_session_id=str((auto_meta or {}).get("session_id") or payload.auto_session_id or ""),
                title=title,
                restart=bool(payload.restart),
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    attached = None
    if payload.attach_browser and preview and preview.get("url"):
        attached = await _attach_preview_browser(
            str(preview.get("url") or ""),
            preview=preview,
            workspace=workspace,
            auto_meta=auto_meta,
        )
    if auto_meta and preview:
        auto_meta["preview_url"] = str(preview.get("url") or "")
        auto_meta["dev_url"] = str(preview.get("url") or "")
        auto_meta["preview_status"] = str(preview.get("status") or "")
        auto_session_service.write_auto_session(auto_meta)
    return {
        "workspace_id": workspace.get("id"),
        "workspace_name": workspace.get("name") or "",
        "preview": _serialize_preview_session(preview),
        "browser": attached,
        "browser_actions": _serialize_browser_action_state(),
    }


@app.delete("/api/workspaces/{project_id}/preview")
async def stop_workspace_preview(project_id: int, auto_session_id: str = Query(default="")):
    workspace, auto_meta, _ = await _workspace_preview_target(project_id, auto_session_id)
    try:
        preview = await asyncio.to_thread(
            lambda: live_preview_service.stop_preview_session(
                workspace_id=int(workspace.get("id") or 0),
                auto_session_id=str((auto_meta or {}).get("session_id") or auto_session_id or ""),
            )
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    _release_browser_preview_attachment(preview)
    return {
        "stopped": True,
        "workspace_id": workspace.get("id"),
        "preview": _serialize_preview_session(preview),
    }


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


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    async with devdb.get_db() as conn:
        row = await devdb.get_project(conn, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        payload = dict(row)
        await devdb.delete_project(conn, project_id)
        await devdb.log_event(conn, "workspace_deleted", f"Deleted workspace {payload.get('name') or project_id}")
        return {"deleted": True, "project": payload}


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

        analysis = await brain.analyse_project(project, tasks, prompts, **_model_call_kwargs(ai))
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
            suggestions = await brain.suggest_tasks_for_project(dict(project), open_tasks, **_model_call_kwargs(ai))
        except Exception as e:
            raise HTTPException(500, f"Suggestion failed: {e}")
        return {"suggestions": suggestions, "project_name": project["name"]}


# ─── Scan ────────────────────────────────────────────────────────────────────

@app.post("/api/scan")
async def run_scan():
    """Trigger an immediate project scan."""
    asyncio.create_task(sched_module.trigger_scan_now(trigger_type="manual"))
    return {"status": "scan started"}


class AddFolderBody(BaseModel):
    path: str                   # Absolute or ~-relative path to the folder
    persist_root: bool = True   # Also add the parent dir to projects_root setting


@app.post("/api/workspaces/add-folder")
async def add_workspace_folder(body: AddFolderBody):
    """Manually add a local folder as a workspace (scan + upsert into DB)."""
    folder = Path(os.path.realpath(os.path.expanduser(body.path)))
    if not folder.exists():
        raise HTTPException(400, f"Path does not exist: {folder}")
    if not folder.is_dir():
        raise HTTPException(400, f"Path is not a directory: {folder}")

    # Scan the folder immediately
    loop = asyncio.get_event_loop()
    proj_data = await loop.run_in_executor(None, scanner.scan_project, folder)

    async with devdb.get_db() as conn:
        project_id = await devdb.upsert_project(conn, proj_data)
        project = dict(await devdb.get_project(conn, project_id))

        if body.persist_root:
            # Ensure the parent dir is included in projects_root for future scans
            parent_str = str(folder.parent)
            existing = (await devdb.get_setting(conn, "projects_root")) or "~/Desktop"
            roots = [r.strip() for r in existing.split(",") if r.strip()]
            # Add the folder itself as an explicit root so it always gets scanned
            folder_str = str(folder)
            if folder_str not in roots and parent_str not in roots:
                roots.append(folder_str)
                await devdb.set_setting(conn, "projects_root", ",".join(roots))

        await devdb.log_event(conn, "scan", f"Manually added workspace: {proj_data['name']}")

    return {"project": project, "scanned": proj_data}


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
        enhanced = await brain.enhance_prompt(body.content, body.project_context, **_model_call_kwargs(ai))
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
    control_owner: Optional[str] = None
    control_state: Optional[str] = None
    attached_preview_url: Optional[str] = None
    attached_preview_status: Optional[str] = None
    attached_workspace_id: Optional[int] = None
    attached_workspace_name: Optional[str] = None
    attached_auto_session_id: Optional[str] = None
    attached_scope_key: Optional[str] = None
    attached_source_workspace_path: Optional[str] = None


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
            projects, tasks, **_model_call_kwargs(ai)
        )
        return {"suggestions": suggestions}


def _serialize_task_sandbox(meta: dict | None, *, include_report: bool = False) -> dict | None:
    if not meta:
        return None
    item = dict(meta)
    changed_files = list(item.get("changed_files") or [])
    item["changed_files"] = changed_files if include_report else changed_files[:10]
    item["changed_files_count"] = len(changed_files)
    item["has_report"] = bool(item.get("report_markdown"))
    if not include_report:
        item.pop("report_markdown", None)
    return item


def _serialize_auto_session(meta: dict | None, *, include_report: bool = False) -> dict | None:
    if not meta:
        return None
    item = dict(meta)
    changed_files = list(item.get("changed_files") or [])
    item["changed_files"] = changed_files if include_report else changed_files[:10]
    item["changed_files_count"] = len(changed_files)
    item["has_report"] = bool(item.get("report_markdown"))
    item["apply_allowed"] = bool(item.get("status") == "review_ready" and changed_files)
    item["resume_target"] = str(item.get("session_id") or "")
    item["resume_reason"] = str(item.get("resume_reason") or item.get("status") or "auto_session")
    preview = live_preview_service.get_preview_session(
        workspace_id=int(item.get("workspace_id") or 0) or None,
        auto_session_id=str(item.get("session_id") or ""),
    )
    if preview:
        item["preview_url"] = str(preview.get("url") or "")
        item["dev_url"] = str(preview.get("url") or "")
        item["preview_status"] = str(preview.get("status") or "")
    if not include_report:
        item.pop("report_markdown", None)
    return item


def _auto_session_summary(meta: dict | None) -> dict | None:
    item = _serialize_auto_session(meta)
    if not item:
        return None
    return {
        "session_id": item.get("session_id", ""),
        "workspace_id": item.get("workspace_id"),
        "workspace_name": item.get("workspace_name") or item.get("source_name") or "",
        "status": item.get("status") or "ready",
        "phase": "review" if item.get("status") == "review_ready" else item.get("status") or "ready",
        "title": item.get("title") or item.get("workspace_name") or "Auto session",
        "detail": item.get("last_error") or item.get("final_output") or "",
        "changed_files_count": item.get("changed_files_count") or 0,
        "apply_allowed": bool(item.get("apply_allowed")),
        "resume_target": item.get("resume_target") or "",
        "resume_reason": item.get("resume_reason") or "auto_session",
        "updated_at": item.get("updated_at") or item.get("created_at") or "",
        "runtime": item.get("resolved_runtime") or {},
        "preview_url": item.get("preview_url") or "",
        "preview_status": item.get("preview_status") or "",
    }


def _serialize_preview_session(meta: dict | None) -> dict | None:
    if not meta:
        return None
    item = {
        "status": "",
        "healthy": False,
        "source_workspace_path": "",
        "last_error": "",
        "log_tail": "",
        **dict(meta),
    }
    item["url"] = str(item.get("url") or "")
    item["healthy"] = bool(item.get("healthy"))
    item["running"] = str(item.get("status") or "") in {"running", "starting"}
    item["source_workspace_path"] = str(item.get("source_workspace_path") or "")
    item["last_error"] = str(item.get("last_error") or "")
    item["log_tail"] = str(item.get("log_tail") or "")
    return item


async def _workspace_preview_target(project_id: int, auto_session_id: str = "") -> tuple[dict, dict | None, str]:
    async with devdb.get_db() as conn:
        workspace = await devdb.get_project(conn, int(project_id))
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    workspace_dict = dict(workspace)
    auto_meta = None
    target_path = str(workspace_dict.get("path") or "")
    auto_session_id = str(auto_session_id or "").strip()
    if auto_session_id:
        auto_meta = auto_session_service.read_auto_session(auto_session_id)
        if not auto_meta:
            raise HTTPException(404, "Auto session not found.")
        if int(auto_meta.get("workspace_id") or 0) != int(project_id):
            raise HTTPException(400, "Auto session does not belong to this workspace.")
        target_path = str(auto_meta.get("sandbox_path") or target_path)
    return workspace_dict, auto_meta, target_path


def _release_browser_preview_attachment(preview: dict | None = None) -> None:
    session = _normalize_browser_session(_browser_action_state.get("session") or {})
    preview_url = str((preview or {}).get("url") or "")
    scope_key = str((preview or {}).get("scope_key") or "")
    if preview_url and session.get("attached_preview_url") not in {"", preview_url}:
        return
    if scope_key and session.get("attached_scope_key") not in {"", scope_key}:
        return
    session = _normalize_browser_session(
        session,
        control_owner="manual",
        control_state="connected" if session.get("connected") else "idle",
    )
    _browser_action_state["session"] = session


async def _attach_preview_browser(
    url: str,
    *,
    preview: dict | None = None,
    workspace: dict | None = None,
    auto_meta: dict | None = None,
) -> dict[str, object]:
    if not url:
        return {"attached": False, "result": "No preview URL available"}
    try:
        import browser_bridge

        bridge = browser_bridge.get_bridge()
        if not bridge.is_running:
            await bridge.start(headless=False)
        result = await bridge.execute_action({"action_type": "navigate", "url": url})
        bridge_status = bridge.status()
        session = _normalize_browser_session(
            _browser_action_state["session"],
            connected=bool(result.get("success")),
            url=url,
            title=str(bridge_status.get("title") or _browser_action_state["session"].get("title") or ""),
            last_seen_at=_now_iso(),
            control_owner="axon" if result.get("success") else "manual",
            control_state="attached" if result.get("success") else "blocked",
            attached_preview_url=url,
            attached_preview_status=str((preview or {}).get("status") or ""),
            attached_workspace_id=int((workspace or {}).get("id") or 0) or None,
            attached_workspace_name=str((workspace or {}).get("name") or (auto_meta or {}).get("workspace_name") or ""),
            attached_auto_session_id=str((auto_meta or {}).get("session_id") or ""),
            attached_scope_key=str((preview or {}).get("scope_key") or ""),
            attached_source_workspace_path=str((preview or {}).get("source_workspace_path") or (workspace or {}).get("path") or ""),
        )
        _browser_action_state["session"] = session
        return {"attached": bool(result.get("success")), "result": result}
    except Exception as exc:
        return {"attached": False, "result": str(exc)}


async def _get_task_with_project(conn, task_id: int):
    cur = await conn.execute(
        """
        SELECT t.*, pr.name AS project_name
        FROM tasks t
        LEFT JOIN projects pr ON pr.id = t.project_id
        WHERE t.id = ?
        """,
        (task_id,),
    )
    return await cur.fetchone()


class TaskSandboxRunRequest(BaseModel):
    backend: Optional[str] = None
    api_provider: Optional[str] = None
    api_model: Optional[str] = None
    cli_path: Optional[str] = None
    cli_model: Optional[str] = None
    cli_session_persistence_enabled: Optional[bool] = None
    ollama_model: Optional[str] = None


class AutoSessionStartRequest(TaskSandboxRunRequest):
    message: str
    project_id: Optional[int] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None


def _task_sandbox_runtime_override(payload: TaskSandboxRunRequest | None) -> dict[str, str]:
    if not payload:
        return {}
    backend = str(payload.backend or "").strip().lower()
    override: dict[str, str] = {}
    if backend in {"api", "cli", "ollama"}:
        override["backend"] = backend
    provider_id = str(payload.api_provider or "").strip().lower()
    if provider_id in provider_registry.PROVIDER_BY_ID:
        override["api_provider"] = provider_id
    if payload.api_model:
        override["api_model"] = str(payload.api_model).strip()
    if payload.cli_path:
        override["cli_path"] = str(payload.cli_path).strip()
    if payload.cli_model:
        override["cli_model"] = str(payload.cli_model).strip()
    if payload.cli_session_persistence_enabled is not None:
        override["cli_session_persistence_enabled"] = bool(payload.cli_session_persistence_enabled)
    if payload.ollama_model:
        override["ollama_model"] = str(payload.ollama_model).strip()
    return override


async def _task_sandbox_ai_params(
    settings: dict,
    *,
    conn,
    runtime_override: dict[str, str] | None = None,
) -> dict:
    merged = dict(settings)
    runtime_override = runtime_override or {}
    backend = str(runtime_override.get("backend") or merged.get("ai_backend") or "api").strip().lower()
    if backend not in {"api", "cli", "ollama"}:
        backend = str(merged.get("ai_backend") or "api").strip().lower() or "api"
    merged["ai_backend"] = backend

    if backend == "api":
        provider_id = str(runtime_override.get("api_provider") or provider_registry.selected_api_provider_id(merged)).strip().lower()
        if provider_id not in provider_registry.PROVIDER_BY_ID:
            provider_id = provider_registry.selected_api_provider_id(merged)
        spec = provider_registry.PROVIDER_BY_ID[provider_id]
        merged["api_provider"] = provider_id
        if "api_model" in runtime_override:
            merged[spec.model_setting] = runtime_override.get("api_model", "")
    elif backend == "cli":
        if "cli_path" in runtime_override:
            merged["cli_runtime_path"] = runtime_override.get("cli_path", "")
        if "cli_model" in runtime_override:
            merged["cli_runtime_model"] = runtime_override.get("cli_model", "")
        if "cli_session_persistence_enabled" in runtime_override:
            merged["claude_cli_session_persistence_enabled"] = "1" if runtime_override.get("cli_session_persistence_enabled") else "0"
    elif backend == "ollama":
        if "ollama_model" in runtime_override:
            merged["ollama_model"] = runtime_override.get("ollama_model", "")

    requested_model = ""
    if backend == "api":
        requested_model = runtime_override.get("api_model", "")
    elif backend == "cli":
        requested_model = runtime_override.get("cli_model", "")
    elif backend == "ollama":
        requested_model = runtime_override.get("ollama_model", "")

    return await _effective_ai_params(
        merged,
        {},
        conn=conn,
        agent_request=True,
        requested_model=requested_model,
    )


def _task_sandbox_prompt(task: dict, sandbox_meta: dict) -> str:
    title = str(task.get("title") or f"Mission {task.get('id')}")
    detail = str(task.get("detail") or "").strip()
    lines = [
        f"Complete this mission inside the current sandbox workspace: {title}",
        "",
        "You are in Axon Auto mode inside an isolated git worktree sandbox.",
        f"Sandbox path: {sandbox_meta.get('sandbox_path')}",
        f"Source workspace: {sandbox_meta.get('source_path')}",
        "",
        "Rules:",
        "- Only inspect and edit files inside the sandbox path.",
        "- Do not merge, rebase, push, or modify the source workspace.",
        "- Work autonomously until the mission is complete or clearly blocked.",
        "- Treat edits and local shell work inside the sandbox as pre-approved. Do not stop to ask for routine permission.",
        "- Do not stop at a plan or commentary. The mission is only complete once the requested repo change or concrete diagnostic output exists in the sandbox and has been verified.",
        "- Run concrete checks that fit the workspace before stopping.",
        "- Ask the user only if the mission itself is ambiguous, required credentials are missing, or external access beyond the sandbox is required.",
        "- End with a concise handoff covering what changed, what still remains, and what should be reviewed before merge.",
    ]
    if detail:
        lines.extend(["", "Mission details:", detail])
    return "\n".join(lines).strip()


def _selected_cli_path(settings: dict) -> str:
    return str(settings.get("cli_runtime_path", settings.get("claude_cli_path", "")) or "").strip()


def _selected_cli_model(settings: dict) -> str:
    return str(settings.get("cli_runtime_model", settings.get("claude_cli_model", "")) or "").strip()


def _selected_cli_family(settings: dict) -> str:
    cli_path = _selected_cli_path(settings)
    if not cli_path:
        return "claude"
    return brain._cli_runtime_family(cli_path) or "claude"


def _family_cli_override_path(settings: dict, family: str) -> str:
    family_name = str(family or "").strip().lower()
    cli_path = _selected_cli_path(settings)
    if not cli_path:
        return ""
    return cli_path if _selected_cli_family(settings) == family_name else ""


def _apply_cli_runtime_settings(data: dict, current_settings: dict) -> None:
    selected_cli_path = str(
        data.get(
            "cli_runtime_path",
            data.get("claude_cli_path", _selected_cli_path(current_settings)),
        )
        or ""
    ).strip()
    requested_cli_model = str(
        data.get(
            "cli_runtime_model",
            data.get("claude_cli_model", _selected_cli_model(current_settings)),
        )
        or ""
    ).strip()
    normalized_model = brain.normalize_cli_model(selected_cli_path, requested_cli_model)
    selected_family = brain._cli_runtime_family(selected_cli_path) if selected_cli_path else "claude"
    data["cli_runtime_path"] = selected_cli_path
    data["cli_runtime_model"] = normalized_model
    # Keep the legacy Claude-only keys readable, but only mirror them when Claude is selected.
    data["claude_cli_path"] = selected_cli_path if selected_family == "claude" else ""
    data["claude_cli_model"] = normalized_model if selected_family == "claude" else ""


def _auto_session_prompt(message: str, session_meta: dict) -> str:
    workspace_name = str(session_meta.get("workspace_name") or session_meta.get("source_name") or "workspace")
    lines = [
        f"Continue this request inside the current Axon Auto sandbox for {workspace_name}.",
        "",
        "You are in Axon Auto mode inside an isolated git worktree sandbox.",
        f"Sandbox path: {session_meta.get('sandbox_path')}",
        f"Source workspace: {session_meta.get('source_path')}",
        "",
        "Rules:",
        "- Only inspect and edit files inside the sandbox path.",
        "- Do not modify the source workspace directly. Source changes are only applied through the Auto session Apply action.",
        "- Keep working autonomously until the request is complete or clearly blocked.",
        "- Treat routine edits and local shell work inside the sandbox as pre-approved.",
        "- If you hit a real blocker, explain it with tool-backed receipts instead of guessing.",
        "- End with a concise checkpoint using these exact sections:",
        "  Verified In This Run",
        "  Inferred From Repo State",
        "  Not Yet Verified",
        "  Next Action Not Yet Taken",
        "",
        "User request:",
        message.strip(),
    ]
    return "\n".join(lines).strip()


def _auto_runtime_summary(ai: dict) -> dict[str, str]:
    backend = str(ai.get("backend") or "").strip().lower()
    if backend == "api":
        provider_id = str(ai.get("api_provider") or "").strip().lower()
        provider = provider_registry.PROVIDER_BY_ID.get(provider_id)
        return {
            "backend": backend,
            "label": provider.label if provider else (provider_id or "API"),
            "model": str(ai.get("api_model") or ""),
        }
    if backend == "cli":
        cli_path = str(ai.get("cli_path") or "").strip()
        binary = Path(cli_path).name.lower() if cli_path else ""
        label = "Codex CLI" if binary == "codex" else "Claude CLI" if binary == "claude" else "CLI Runtime"
        return {
            "backend": backend,
            "label": label,
            "model": str(ai.get("cli_model") or ""),
            "binary": cli_path,
        }
    return {
        "backend": "ollama",
        "label": "Local Ollama",
        "model": str(ai.get("ollama_model") or ""),
    }


def _auto_tool_command(tool_name: str, tool_args: dict) -> tuple[str, str, str]:
    name = str(tool_name or "").strip()
    args = tool_args or {}
    if name in {"shell_cmd", "shell_bg", "shell_bg_check"}:
        command = str(args.get("cmd") or args.get("command") or args.get("check") or "").strip()
        cwd = str(args.get("cwd") or "").strip()
        return command, cwd, command
    if name == "git_status":
        cwd = str(args.get("cwd") or args.get("path") or "").strip()
        return "git status", cwd, "git status"
    if name == "git_diff":
        cwd = str(args.get("cwd") or args.get("path") or "").strip()
        target = str(args.get("path") or "").strip()
        label = "git diff" if not target else f"git diff {target}"
        return label, cwd, label
    if name == "read_file":
        target = str(args.get("path") or "").strip()
        return "", "", f"read_file {target}".strip()
    if name == "edit_file":
        target = str(args.get("path") or "").strip()
        return "", "", f"edit_file {target}".strip()
    if name == "list_files":
        target = str(args.get("path") or "").strip()
        return "", "", f"list_files {target}".strip()
    return "", "", name or "tool"


def _is_verification_command(tool_name: str, tool_args: dict) -> bool:
    command, _cwd, label = _auto_tool_command(tool_name, tool_args)
    haystack = f"{command} {label}".lower()
    verification_terms = (
        " test",
        "test ",
        "pytest",
        "jest",
        "vitest",
        "build",
        "tsc",
        "typecheck",
        "lint",
        "check",
        "ruff",
        "mypy",
        "go test",
        "cargo test",
        "phpunit",
        "next build",
        "npm run build",
        "npm run test",
        "pnpm build",
        "pnpm test",
        "yarn build",
        "yarn test",
    )
    return any(term in haystack for term in verification_terms)


def _auto_receipt_summary(result: str) -> str:
    text = str(result or "").strip()
    if not text:
        return ""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:220]


def _auto_session_live_operator(session_meta: dict, event: dict):
    event_type = str(event.get("type") or "")
    workspace_id = session_meta.get("workspace_id")
    session_id = str(session_meta.get("session_id") or "")
    changed_files_count = len(session_meta.get("changed_files") or [])
    if event_type == "tool_call":
        _set_live_operator(
            active=True,
            mode="auto",
            phase="execute",
            title=f"Auto: {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=_json.dumps(event.get("args") or {})[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "tool_result":
        _set_live_operator(
            active=True,
            mode="auto",
            phase="verify",
            title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=str(event.get("result") or "")[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "text":
        _set_live_operator(
            active=True,
            mode="auto",
            phase="verify",
            title="Writing Auto handoff",
            detail="Axon is preparing the sandbox review handoff.",
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "thinking":
        _set_live_operator(
            active=True,
            mode="auto",
            phase="plan",
            title="Planning inside Auto sandbox",
            detail=str(event.get("chunk") or "")[:180],
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=changed_files_count,
            apply_allowed=False,
            preserve_started=True,
        )
    elif event_type == "approval_required":
        _set_live_operator(
            active=False,
            mode="auto",
            phase="recover",
            title="Auto session awaiting approval",
            detail=str(event.get("message") or "Axon paused for approval inside the sandbox.")[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
            auto_session_id=session_id,
        )
    elif event_type == "error":
        _set_live_operator(
            active=False,
            mode="auto",
            phase="recover",
            title="Auto session needs attention",
            detail=str(event.get("message") or "Axon stopped inside the sandbox.")[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
            auto_session_id=session_id,
        )


def _task_sandbox_live_operator(task: dict, event: dict):
    event_type = event.get("type")
    workspace_id = task.get("project_id")
    if event_type == "tool_call":
        _set_live_operator(
            active=True,
            mode="agent",
            phase="execute",
            title=f"Sandbox: {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=_json.dumps(event.get("args") or {})[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "tool_result":
        _set_live_operator(
            active=True,
            mode="agent",
            phase="verify",
            title=f"Reviewing {str(event.get('name') or 'tool').replace('_', ' ')}",
            detail=str(event.get("result") or "")[:180],
            tool=event.get("name", ""),
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "text":
        _set_live_operator(
            active=True,
            mode="agent",
            phase="verify",
            title="Writing sandbox handoff",
            detail="Axon is turning the sandbox run into a reviewable report.",
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "thinking":
        _set_live_operator(
            active=True,
            mode="agent",
            phase="plan",
            title="Planning inside sandbox",
            detail=str(event.get("chunk") or "")[:180],
            workspace_id=workspace_id,
            preserve_started=True,
        )
    elif event_type == "approval_required":
        _set_live_operator(
            active=False,
            mode="agent",
            phase="recover",
            title="Sandbox awaiting approval",
            detail=str(event.get("message") or "Axon paused for approval inside the sandbox.")[:180],
            summary=task.get("title", "")[:120],
            workspace_id=workspace_id,
        )
    elif event_type == "error":
        _set_live_operator(
            active=False,
            mode="agent",
            phase="recover",
            title="Sandbox needs attention",
            detail=str(event.get("message") or "Axon stopped inside the sandbox.")[:180],
            summary=task.get("title", "")[:120],
            workspace_id=workspace_id,
        )


async def _run_task_sandbox_background(
    task: dict,
    project: dict,
    sandbox_meta: dict,
    *,
    resume: bool = False,
    runtime_override: dict[str, str] | None = None,
):
    task_id = int(task["id"])
    task_title = str(task.get("title") or "")
    prompt = "please continue" if resume else _task_sandbox_prompt(task, sandbox_meta)
    max_iterations = 75
    context_compact = True
    final_output_parts: list[str] = []
    approval_message = ""
    run_error = ""
    starting_commit = ""
    permission_state = brain.agent_capture_permission_state()
    autonomous_shell_cmds = ("rm", "chmod", "ln")

    try:
        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            ai = await _task_sandbox_ai_params(settings, conn=conn, runtime_override=runtime_override)
            projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
            tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
            prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
            context_block = brain._build_context_block(projects, tasks, prompts_list)
            max_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
            context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {"1", "true", "yes", "on"}
            if str(task.get("status") or "").lower() == "open":
                await devdb.update_task_status(conn, task_id, "in_progress")

        sandbox_meta = await asyncio.to_thread(task_sandbox_service.ensure_task_sandbox, task, project)
        sandbox_meta = await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, task_title) or sandbox_meta
        starting_commit = str(sandbox_meta.get("latest_commit") or "")
        sandbox_meta.update(
            {
                "mode": "auto",
                "autonomous": True,
                "status": "running",
                "last_error": "",
                "last_run_started_at": _now_iso(),
                "run_prompt": prompt,
            }
        )
        await asyncio.to_thread(task_sandbox_service.write_task_sandbox, sandbox_meta)

        brain.agent_allow_edit(sandbox_meta["sandbox_path"], scope="repo")
        for cmd_name in autonomous_shell_cmds:
            brain.agent_allow_command(cmd_name)

        _set_live_operator(
            active=True,
            mode="agent",
            phase="execute",
            title="Running mission sandbox",
            detail=str(task.get("title") or "Mission")[:180],
            summary=str(task.get("title") or "")[:120],
            workspace_id=task.get("project_id"),
        )

        async for event in brain.run_agent(
            prompt,
            [],
            context_block,
            project_name=project.get("name"),
            workspace_path=sandbox_meta["sandbox_path"],
            ollama_url=ai.get("ollama_url", ""),
            ollama_model=ai.get("ollama_model", ""),
            max_iterations=max_iterations,
            context_compact=context_compact,
            api_key=ai.get("api_key", ""),
            api_base_url=ai.get("api_base_url", ""),
            api_model=ai.get("api_model", ""),
            api_provider=ai.get("api_provider", ""),
            cli_path=ai.get("cli_path", ""),
            cli_model=ai.get("cli_model", ""),
            cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
            backend=ai.get("backend", ""),
            force_tool_mode=True,
            autonomy_profile=_normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto"),
            runtime_permissions_mode=_normalized_runtime_permissions_mode(
                settings.get("runtime_permissions_mode") or "",
                fallback="ask_first" if _normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto") == "manual" else "default",
            ),
            external_fetch_policy=_normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first"),
            external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600"),
        ):
            _task_sandbox_live_operator(task, event)
            if event.get("type") == "text":
                final_output_parts.append(str(event.get("chunk") or ""))
            elif event.get("type") == "approval_required":
                approval_message = str(event.get("message") or "Approval required to continue the sandbox run.")
                break
            elif event.get("type") == "error":
                run_error = str(event.get("message") or "Sandbox run failed.")
                break

        sandbox_meta = await asyncio.to_thread(task_sandbox_service.read_task_sandbox, task_id, task_title)
        sandbox_meta = sandbox_meta or {}
        sandbox_meta.update(
            {
                "task_id": task_id,
                "task_title": task_title,
                "project_id": task.get("project_id"),
                "project_name": project.get("name") or "",
                "final_output": "".join(final_output_parts).strip(),
                "last_run_completed_at": _now_iso(),
            }
        )
        if approval_message:
            sandbox_meta["status"] = "approval_required"
            sandbox_meta["last_error"] = approval_message
            _set_live_operator(
                active=False,
                mode="agent",
                phase="recover",
                title="Sandbox awaiting approval",
                detail=approval_message[:180],
                summary=str(task.get("title") or "")[:120],
                workspace_id=task.get("project_id"),
            )
        elif run_error:
            sandbox_meta["status"] = "error"
            sandbox_meta["last_error"] = run_error
            _set_live_operator(
                active=False,
                mode="agent",
                phase="recover",
                title="Sandbox needs attention",
                detail=run_error[:180],
                summary=str(task.get("title") or "")[:120],
                workspace_id=task.get("project_id"),
            )
        else:
            sandbox_meta["status"] = "completed"
            sandbox_meta["last_error"] = ""
            _set_live_operator(
                active=False,
                mode="agent",
                phase="verify",
                title="Sandbox report ready",
                detail="Axon finished the isolated mission run and prepared a review handoff.",
                summary=str(task.get("title") or "")[:120],
                workspace_id=task.get("project_id"),
            )
        await asyncio.to_thread(task_sandbox_service.write_task_sandbox, sandbox_meta)
        refreshed_meta = await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, task_title)
        if not approval_message and not run_error:
            refreshed_meta = refreshed_meta or await asyncio.to_thread(task_sandbox_service.read_task_sandbox, task_id, task_title) or {}
            ending_commit = str(refreshed_meta.get("latest_commit") or "")
            final_output = str(refreshed_meta.get("final_output") or "").strip()
            changed_files = list(refreshed_meta.get("changed_files") or [])
            commit_changed = bool(starting_commit and ending_commit and ending_commit != starting_commit)
            meaningful_completion = bool(final_output or changed_files or commit_changed)
            if final_output.startswith("ERROR:"):
                refreshed_meta["status"] = "error"
                refreshed_meta["last_error"] = final_output
                await asyncio.to_thread(task_sandbox_service.write_task_sandbox, refreshed_meta)
                await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, task_title)
                _set_live_operator(
                    active=False,
                    mode="agent",
                    phase="recover",
                    title="Sandbox needs attention",
                    detail=final_output[:180],
                    summary=task_title[:120],
                    workspace_id=task.get("project_id"),
                )
            elif not meaningful_completion:
                refreshed_meta["status"] = "error"
                refreshed_meta["last_error"] = (
                    "Sandbox run finished without producing repository changes, a new commit, "
                    "or a reviewable handoff."
                )
                await asyncio.to_thread(task_sandbox_service.write_task_sandbox, refreshed_meta)
                await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, task_title)
                _set_live_operator(
                    active=False,
                    mode="agent",
                    phase="recover",
                    title="Sandbox needs attention",
                    detail=str(refreshed_meta["last_error"])[:180],
                    summary=task_title[:120],
                    workspace_id=task.get("project_id"),
                )
    except Exception as exc:
        meta = await asyncio.to_thread(task_sandbox_service.read_task_sandbox, task_id, task_title)
        meta = meta or {
            "task_id": task_id,
            "task_title": task_title,
            "project_id": task.get("project_id"),
            "project_name": project.get("name") or "",
            "source_path": project.get("path") or "",
            "sandbox_path": sandbox_meta.get("sandbox_path") or "",
            "branch_name": sandbox_meta.get("branch_name") or "",
            "base_branch": sandbox_meta.get("base_branch") or "",
            "created_at": _now_iso(),
        }
        meta.update(
            {
                "status": "error",
                "final_output": "".join(final_output_parts).strip(),
                "last_error": str(exc),
                "last_run_completed_at": _now_iso(),
            }
        )
        await asyncio.to_thread(task_sandbox_service.write_task_sandbox, meta)
        _set_live_operator(
            active=False,
            mode="agent",
            phase="recover",
            title="Sandbox needs attention",
            detail=str(exc)[:180],
            summary=str(task.get("title") or "")[:120],
            workspace_id=task.get("project_id"),
        )
    finally:
        brain.agent_restore_permission_state(permission_state)
        _task_sandbox_runs.pop(task_id, None)


async def _queue_task_sandbox_run(
    task_id: int,
    *,
    resume: bool = False,
    runtime_override: dict[str, str] | None = None,
):
    async with devdb.get_db() as conn:
        row = await _get_task_with_project(conn, task_id)
        if not row:
            raise HTTPException(404, "Mission not found")
        task = dict(row)
        if not task.get("project_id"):
            raise HTTPException(400, "Attach this mission to a workspace before using an isolated sandbox.")
        project = await devdb.get_project(conn, int(task["project_id"]))
        if not project:
            raise HTTPException(400, "Workspace not found for this mission.")
        project_dict = dict(project)

    sandbox_meta = await asyncio.to_thread(task_sandbox_service.ensure_task_sandbox, task, project_dict)
    current = _task_sandbox_runs.get(task_id)
    if current and not current.done():
        return {
            "started": False,
            "already_running": True,
            "sandbox": _serialize_task_sandbox(sandbox_meta),
        }

    run_task = asyncio.create_task(
        _run_task_sandbox_background(
            task,
            project_dict,
            sandbox_meta,
            resume=resume,
            runtime_override=runtime_override,
        )
    )
    _task_sandbox_runs[task_id] = run_task
    return {
        "started": True,
        "resume": resume,
        "sandbox": _serialize_task_sandbox(sandbox_meta),
    }


@app.get("/api/tasks/sandboxes")
async def list_task_sandboxes():
    rows = await asyncio.to_thread(task_sandbox_service.list_task_sandboxes)
    return {"sandboxes": [_serialize_task_sandbox(item) for item in rows]}


@app.get("/api/tasks/{task_id}/sandbox")
async def get_task_sandbox(task_id: int):
    async with devdb.get_db() as conn:
        row = await _get_task_with_project(conn, task_id)
    if not row:
        raise HTTPException(404, "Mission not found")
    sandbox = await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, str(row["title"]))
    if not sandbox:
        raise HTTPException(404, "Sandbox not created yet for this mission.")
    return {"sandbox": _serialize_task_sandbox(sandbox, include_report=True)}


@app.post("/api/tasks/{task_id}/sandbox/run")
async def run_task_sandbox(task_id: int, body: TaskSandboxRunRequest | None = None):
    return await _queue_task_sandbox_run(
        task_id,
        resume=False,
        runtime_override=_task_sandbox_runtime_override(body),
    )


@app.post("/api/tasks/{task_id}/sandbox/continue")
async def continue_task_sandbox(task_id: int, body: TaskSandboxRunRequest | None = None):
    return await _queue_task_sandbox_run(
        task_id,
        resume=True,
        runtime_override=_task_sandbox_runtime_override(body),
    )


@app.post("/api/tasks/{task_id}/sandbox/apply")
async def apply_task_sandbox(task_id: int):
    async with devdb.get_db() as conn:
        row = await _get_task_with_project(conn, task_id)
    if not row:
        raise HTTPException(404, "Mission not found")
    result = await asyncio.to_thread(task_sandbox_service.apply_task_sandbox, task_id, str(row["title"]))
    sandbox = await asyncio.to_thread(task_sandbox_service.refresh_task_sandbox, task_id, str(row["title"]))
    return {
        "applied": True,
        "summary": result.get("summary", ""),
        "sandbox": _serialize_task_sandbox(sandbox, include_report=True),
    }


@app.delete("/api/tasks/{task_id}/sandbox")
async def discard_task_sandbox(task_id: int):
    async with devdb.get_db() as conn:
        row = await _get_task_with_project(conn, task_id)
    if not row:
        raise HTTPException(404, "Mission not found")
    result = await asyncio.to_thread(task_sandbox_service.discard_task_sandbox, task_id, str(row["title"]))
    return result


def _auto_session_title(message: str, workspace_name: str = "") -> str:
    text = " ".join(str(message or "").strip().split())
    if not text:
        return f"{workspace_name or 'Workspace'} Auto session".strip()
    return text[:120]


def _auto_resume_prompt(session_meta: dict, resume_message: str = "") -> str:
    text = " ".join(str(resume_message or "").strip().split())
    generic = {"continue", "please continue", "resume", "retry"}
    prompt_lines = [
        "Continue the existing Axon Auto session in this sandbox.",
        "Do not ask whether to continue or start over.",
        "Stay inside the sandbox and either make the next concrete change or report a real blocker with receipts.",
    ]
    if text and text.lower() not in generic:
        prompt_lines.extend(["", f"Resume instruction: {text}"])
    prior = str(session_meta.get("report_markdown") or session_meta.get("final_output") or "").strip()
    if prior:
        prompt_lines.extend(["", "Previous session state:", prior[:4000]])
    return "\n".join(prompt_lines).strip()


async def _run_auto_session_background(
    workspace: dict,
    session_meta: dict,
    *,
    resume: bool = False,
    resume_message: str = "",
    runtime_override: dict[str, str] | None = None,
    composer_options: dict | None = None,
):
    session_id = str(session_meta.get("session_id") or "")
    workspace_id = int(workspace["id"])
    workspace_name = str(workspace.get("name") or "")
    sandbox_path = str(session_meta.get("sandbox_path") or "")
    start_prompt = str(session_meta.get("start_prompt") or "")
    prompt = _auto_resume_prompt(session_meta, resume_message) if resume else _auto_session_prompt(start_prompt, session_meta)
    final_output_parts: list[str] = []
    approval_message = ""
    run_error = ""
    command_receipts = list(session_meta.get("command_receipts") or [])
    verification_receipts = list(session_meta.get("verification_receipts") or [])
    pending_tool_calls: list[dict] = []
    max_iterations = 75
    context_compact = True
    permission_state = brain.agent_capture_permission_state()
    autonomous_shell_cmds = ("rm", "chmod", "ln")

    try:
        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            runtime_override = runtime_override or dict(session_meta.get("runtime_override") or {})
            composer_options = _composer_options_dict(composer_options or session_meta.get("composer_options") or {})
            composer_options["agent_role"] = "auto"
            composer_options["safe_mode"] = True
            composer_options["require_approval"] = False
            composer_options["external_mode"] = composer_options.get("external_mode") or "local_first"
            ai = await _task_sandbox_ai_params(settings, conn=conn, runtime_override=runtime_override)
            projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
            tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
            prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
            context_block = brain._build_context_block(projects, tasks, prompts_list)
            history_rows = await _load_chat_history_rows(conn, project_id=workspace_id, degrade_to_empty=True)
            history = _history_messages_from_rows(history_rows)
            resource_ids = list(session_meta.get("resource_ids") or [])
            resource_bundle = await _resource_bundle(
                conn,
                resource_ids=resource_ids,
                user_message=start_prompt,
                settings=settings,
            )
            ai, _vision_warnings = await auto_route_vision_runtime(
                settings=settings,
                ai=ai,
                resource_bundle=resource_bundle,
                requested_model="",
                resolve_provider_key=lambda provider_id: devvault.vault_resolve_provider_key(conn, provider_id),
                vault_unlocked=devvault.VaultSession.is_unlocked(),
            )
            if _vision_warnings:
                resource_bundle["warnings"].extend(_vision_warnings)
            ai, _image_warnings = await _auto_route_image_generation_runtime(
                conn,
                settings=settings,
                ai=ai,
                user_message=start_prompt,
                requested_model="",
                agent_request=True,
            )
            if _image_warnings:
                resource_bundle["warnings"].extend(_image_warnings)
            settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
            memory_bundle = await _memory_bundle(
                conn,
                user_message=start_prompt,
                project_id=workspace_id,
                resource_ids=resource_ids,
                settings=settings,
                composer_options=composer_options,
            )
            composer_block = _composer_instruction_block(composer_options)
            merged_context_block = "\n\n".join(
                block for block in (context_block, memory_bundle["context_block"], composer_block) if block
            )
            max_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
            context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {"1", "true", "yes", "on"}
            session_meta["resolved_runtime"] = _auto_runtime_summary(ai)

        session_meta = auto_session_service.ensure_auto_session(
            session_id,
            workspace,
            title=str(session_meta.get("title") or workspace_name or "Auto session"),
            detail=str(session_meta.get("detail") or ""),
            runtime_override=runtime_override,
            start_prompt=start_prompt,
            mode="auto",
            metadata={
                "status": "running",
                "last_error": "",
                "last_run_started_at": _now_iso(),
                "runtime_override": runtime_override,
                "resolved_runtime": session_meta.get("resolved_runtime") or {},
                "resource_ids": list(session_meta.get("resource_ids") or []),
                "composer_options": dict(composer_options or {}),
                "command_receipts": command_receipts,
                "verification_receipts": verification_receipts,
                "inferred_notes": list(session_meta.get("inferred_notes") or []),
            },
        )

        brain.agent_allow_edit(sandbox_path, scope="repo")
        for cmd_name in autonomous_shell_cmds:
            brain.agent_allow_command(cmd_name)

        _set_live_operator(
            active=True,
            mode="auto",
            phase="execute",
            title="Running Auto session",
            detail=start_prompt[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
            auto_session_id=session_id,
            changed_files_count=0,
        )

        for warning in resource_bundle["warnings"]:
            final_output_parts.append(f"⚠️ {warning}\n\n")

        async for event in brain.run_agent(
            prompt,
            history,
            merged_context_block,
            project_name=workspace_name,
            workspace_path=sandbox_path,
            resource_context=resource_bundle["context_block"],
            resource_image_paths=resource_bundle["image_paths"],
            vision_model=resource_bundle["vision_model"],
            ollama_url=ai.get("ollama_url", ""),
            ollama_model=ai.get("ollama_model", ""),
            max_iterations=max_iterations,
            context_compact=context_compact,
            force_tool_mode=True,
            api_key=ai.get("api_key", ""),
            api_base_url=ai.get("api_base_url", ""),
            api_model=ai.get("api_model", ""),
            api_provider=ai.get("api_provider", ""),
            cli_path=ai.get("cli_path", ""),
            cli_model=ai.get("cli_model", ""),
            cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
            backend=ai.get("backend", ""),
            workspace_id=workspace_id,
            autonomy_profile=_normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto"),
            runtime_permissions_mode=_normalized_runtime_permissions_mode(
                settings.get("runtime_permissions_mode") or "",
                fallback="ask_first" if _normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto") == "manual" else "default",
            ),
            external_fetch_policy=_normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first"),
            external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600"),
        ):
            if event.get("type") == "tool_call":
                tool_name = str(event.get("name") or "")
                tool_args = dict(event.get("args") or {})
                command, cwd, label = _auto_tool_command(tool_name, tool_args)
                pending_tool_calls.append(
                    {
                        "tool": tool_name,
                        "args": tool_args,
                        "command": command,
                        "cwd": cwd,
                        "label": label,
                        "recorded_at": _now_iso(),
                    }
                )
            elif event.get("type") == "tool_result":
                tool_name = str(event.get("name") or "")
                result = str(event.get("result") or "")
                pending = None
                for index in range(len(pending_tool_calls) - 1, -1, -1):
                    if pending_tool_calls[index].get("tool") == tool_name:
                        pending = pending_tool_calls.pop(index)
                        break
                receipt = {
                    **(pending or {"tool": tool_name, "args": dict(event.get("args") or {}), "label": tool_name, "recorded_at": _now_iso()}),
                    "summary": _auto_receipt_summary(result),
                    "result_preview": result[:500],
                    "success": not result.startswith("ERROR:"),
                }
                command_receipts.append(receipt)
                if _is_verification_command(tool_name, receipt.get("args") or {}):
                    verification_receipts.append(receipt)
            elif event.get("type") == "text":
                final_output_parts.append(str(event.get("chunk") or ""))
            elif event.get("type") == "approval_required":
                approval_message = str(event.get("message") or "Approval required to continue the Auto session.")
                break
            elif event.get("type") == "error":
                run_error = str(event.get("message") or "Auto session failed.")
                break
            _auto_session_live_operator(session_meta, event)

        session_meta = dict(session_meta or {})
        session_meta.update(
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "source_name": workspace_name,
                "source_path": workspace.get("path") or "",
                "resolved_runtime": session_meta.get("resolved_runtime") or _auto_runtime_summary(ai),
                "resource_ids": list(session_meta.get("resource_ids") or []),
                "composer_options": dict(composer_options or {}),
                "command_receipts": command_receipts,
                "verification_receipts": verification_receipts,
                "final_output": "".join(final_output_parts).strip(),
                "last_run_completed_at": _now_iso(),
            }
        )
        if approval_message:
            session_meta["status"] = "approval_required"
            session_meta["last_error"] = approval_message
        elif run_error:
            session_meta["status"] = "error"
            session_meta["last_error"] = run_error
        else:
            session_meta["status"] = "completed"
            session_meta["last_error"] = ""
        auto_session_service.write_auto_session(session_meta)
        refreshed = auto_session_service.refresh_auto_session(session_id) or session_meta

        if not approval_message and not run_error:
            start_snapshot = dict(refreshed.get("start_snapshot") or {})
            start_commit = str(start_snapshot.get("latest_commit") or "")
            end_commit = str(refreshed.get("latest_commit") or "")
            changed_files = list(refreshed.get("changed_files") or [])
            commit_changed = bool(start_commit and end_commit and end_commit != start_commit)
            concrete_blocker = bool(refreshed.get("last_error"))
            if not changed_files and not verification_receipts and not commit_changed and not concrete_blocker:
                refreshed["status"] = "error"
                refreshed["last_error"] = (
                    "Auto session finished without repository changes, verification receipts, "
                    "or a concrete blocker. Axon did not produce a reviewable handoff."
                )
                auto_session_service.write_auto_session(refreshed)
                refreshed = auto_session_service.refresh_auto_session(session_id) or refreshed

        current_status = str(refreshed.get("status") or "")
        changed_files_count = len(refreshed.get("changed_files") or [])
        if current_status == "review_ready":
            _set_live_operator(
                active=False,
                mode="auto",
                phase="verify",
                title="Auto session ready for review",
                detail="Axon finished the sandbox pass and prepared a reviewable handoff.",
                summary=str(refreshed.get("title") or "")[:120],
                workspace_id=workspace_id,
                auto_session_id=session_id,
                changed_files_count=changed_files_count,
                apply_allowed=bool(changed_files_count),
            )
        elif current_status == "approval_required":
            _set_live_operator(
                active=False,
                mode="auto",
                phase="recover",
                title="Auto session awaiting approval",
                detail=str(refreshed.get("last_error") or approval_message or "")[:180],
                summary=str(refreshed.get("title") or "")[:120],
                workspace_id=workspace_id,
                auto_session_id=session_id,
                changed_files_count=changed_files_count,
            )
        else:
            _set_live_operator(
                active=False,
                mode="auto",
                phase="recover" if current_status == "error" else "verify",
                title="Auto session needs attention" if current_status == "error" else "Auto session updated",
                detail=str(refreshed.get("last_error") or refreshed.get("final_output") or "")[:180],
                summary=str(refreshed.get("title") or "")[:120],
                workspace_id=workspace_id,
                auto_session_id=session_id,
                changed_files_count=changed_files_count,
            )
    except Exception as exc:
        meta = dict(session_meta or {})
        meta.update(
            {
                "status": "error",
                "last_error": str(exc),
                "final_output": "".join(final_output_parts).strip(),
                "last_run_completed_at": _now_iso(),
                "command_receipts": command_receipts,
                "verification_receipts": verification_receipts,
            }
        )
        auto_session_service.write_auto_session(meta)
        auto_session_service.refresh_auto_session(session_id)
        _set_live_operator(
            active=False,
            mode="auto",
            phase="recover",
            title="Auto session needs attention",
            detail=str(exc)[:180],
            summary=str(session_meta.get("title") or "")[:120],
            workspace_id=workspace_id,
        )
    finally:
        brain.agent_restore_permission_state(permission_state)
        _auto_session_runs.pop(session_id, None)


async def _queue_auto_session_run(
    body: AutoSessionStartRequest,
    *,
    resume: bool = False,
    session_id: str = "",
):
    resume_message = str(body.message or "").strip()
    existing_session = None
    project_id = body.project_id
    if resume and session_id:
        existing_session = auto_session_service.refresh_auto_session(session_id)
        project_id = project_id or int(existing_session.get("workspace_id") or 0) if existing_session else project_id

    if not project_id:
        raise HTTPException(400, "Select a workspace before starting Auto mode.")

    async with devdb.get_db() as conn:
        workspace = await devdb.get_project(conn, int(project_id))
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    workspace_dict = dict(workspace)

    normalized_options = _composer_options_dict(body.composer_options)
    normalized_options["agent_role"] = "auto"
    normalized_options["require_approval"] = False
    normalized_options["safe_mode"] = True
    normalized_options["external_mode"] = normalized_options.get("external_mode") or "local_first"
    runtime_override = _task_sandbox_runtime_override(body)

    existing = auto_session_service.find_workspace_auto_session(
        int(project_id),
        active_only=True,
    )
    if existing:
        existing = auto_session_service.refresh_auto_session(
            str(existing.get("session_id") or ""),
        ) or existing

    if resume:
        target_id = session_id or str((existing or {}).get("session_id") or "").strip()
        if not target_id:
            raise HTTPException(404, "No Auto session to continue for this workspace.")
        session_meta = (
            existing_session
            if existing_session and str(existing_session.get("session_id") or "") == target_id
            else auto_session_service.refresh_auto_session(target_id)
        )
        if not session_meta:
            raise HTTPException(404, "Auto session not found.")
        if not runtime_override:
            runtime_override = dict(session_meta.get("runtime_override") or {})
        current = _auto_session_runs.get(target_id)
        if current and not current.done():
            return {"started": False, "already_running": True, "session": _serialize_auto_session(session_meta, include_report=True)}
    else:
        if existing and str(existing.get("status") or "") not in {"applied", "discarded"}:
            current = _auto_session_runs.get(str(existing.get("session_id") or ""))
            return {
                "started": False,
                "already_running": bool(current and not current.done()),
                "requires_resolution": True,
                "session": _serialize_auto_session(existing, include_report=True),
            }
        target_id = f"{int(_time.time() * 1000)}-{workspace_dict['id']}"
        session_meta = auto_session_service.ensure_auto_session(
            target_id,
            workspace_dict,
            title=_auto_session_title(body.message, str(workspace_dict.get("name") or "")),
            detail=str(body.message or "").strip()[:300],
            runtime_override=runtime_override,
            start_prompt=str(body.message or "").strip(),
            mode="auto",
            metadata={
                "resource_ids": list(body.resource_ids or []),
                "composer_options": dict(normalized_options),
                "status": "ready",
            },
        )

    run_task = asyncio.create_task(
        _run_auto_session_background(
            workspace_dict,
            session_meta,
            resume=resume,
            resume_message=resume_message,
            runtime_override=runtime_override,
            composer_options=normalized_options,
        )
    )
    _auto_session_runs[target_id] = run_task
    return {
        "started": True,
        "resume": resume,
        "session": _serialize_auto_session(session_meta, include_report=True),
    }


@app.get("/api/auto/sessions")
async def list_auto_sessions():
    rows = auto_session_service.list_auto_sessions()
    refreshed_rows: list[dict] = []
    for row in rows:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue
        status = str(row.get("status") or "").strip().lower()
        if status in {"running", "completed", "ready", "error", "approval_required"} or row.get("last_run_completed_at"):
            try:
                refreshed = auto_session_service.refresh_auto_session(session_id)
            except Exception as exc:
                degraded = dict(row)
                degraded["status"] = "error"
                degraded["last_error"] = str(exc)
                refreshed_rows.append(degraded)
            else:
                refreshed_rows.append(refreshed or row)
        else:
            refreshed_rows.append(row)
    return {"sessions": [_serialize_auto_session(item) for item in refreshed_rows]}


@app.post("/api/auto/start")
async def start_auto_session(body: AutoSessionStartRequest):
    return await _queue_auto_session_run(body, resume=False)


@app.get("/api/auto/{session_id}")
async def get_auto_session(session_id: str):
    session = auto_session_service.refresh_auto_session(session_id)
    if not session:
        raise HTTPException(404, "Auto session not found.")
    return {"session": _serialize_auto_session(session, include_report=True)}


@app.post("/api/auto/{session_id}/continue")
async def continue_auto_session(session_id: str, body: AutoSessionStartRequest | None = None):
    payload = body or AutoSessionStartRequest(message="please continue")
    return await _queue_auto_session_run(payload, resume=True, session_id=session_id)


@app.post("/api/auto/{session_id}/apply")
async def apply_auto_session(session_id: str):
    try:
        result = auto_session_service.apply_auto_session(session_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    session = auto_session_service.refresh_auto_session(session_id)
    return {
        "applied": True,
        "summary": result.get("summary", ""),
        "session": _serialize_auto_session(session, include_report=True),
    }


@app.delete("/api/auto/{session_id}")
async def discard_auto_session(session_id: str):
    try:
        result = auto_session_service.discard_auto_session(session_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return result


# ─── AI backend helper ────────────────────────────────────────────────────────

async def _resolved_api_runtime(settings: dict, provider_id: str, conn=None) -> tuple[dict, str]:
    candidate_settings = dict(settings)
    candidate_settings["api_provider"] = provider_id
    runtime = provider_registry.runtime_api_config(candidate_settings)
    resolved_key = runtime.get("api_key", "")

    if devvault.VaultSession.is_unlocked() and (not resolved_key or resolved_key == "set"):
        async def _resolve(db):
            return await devvault.vault_resolve_provider_key(db, provider_id)

        if conn:
            vault_key = await _resolve(conn)
        else:
            async with devdb.get_db() as _conn:
                vault_key = await _resolve(_conn)
        if vault_key:
            resolved_key = vault_key

    return runtime, resolved_key


async def _selected_api_runtime_truth(settings: dict, conn=None) -> dict:
    provider_id = provider_registry.selected_api_provider_id(settings)
    runtime, resolved_key = await _resolved_api_runtime(settings, provider_id, conn)
    public = provider_registry.public_runtime_api_config(settings)
    public["provider_id"] = provider_id
    public["provider_label"] = runtime.get("provider_label", public.get("provider_label", "API"))
    public["transport"] = runtime.get("transport", public.get("transport", ""))
    public["api_base_url"] = runtime.get("api_base_url", public.get("api_base_url", ""))
    public["api_model"] = runtime.get("api_model", public.get("api_model", ""))
    public["api_key_configured"] = bool(str(resolved_key or "").strip())
    public["key_hint"] = provider_registry.mask_secret(str(resolved_key or "")) if resolved_key else public.get("key_hint", "")
    return public


async def _runtime_truth_for_settings(settings: dict, conn=None, *, backend_override: str = "") -> tuple[dict, dict]:
    truth_settings = dict(settings)
    if backend_override:
        truth_settings["ai_backend"] = backend_override
    selected_cli_override = _selected_cli_path(settings)
    selected_cli_family = brain._cli_runtime_family(selected_cli_override) if selected_cli_override else "claude"
    claude_runtime = {
        **claude_cli_runtime.build_cli_runtime_snapshot(selected_cli_override if selected_cli_family == "claude" else ""),
        "runtime_id": "claude",
        "runtime_name": "Claude CLI",
    }
    codex_runtime = {
        **codex_cli_runtime.build_codex_runtime_snapshot(selected_cli_override if selected_cli_family == "codex" else ""),
        "runtime_id": "codex",
        "runtime_name": "Codex CLI",
    }
    cli_runtime = codex_runtime if selected_cli_family == "codex" else claude_runtime
    cli_binary = str(cli_runtime.get("binary") or brain._resolve_selected_cli_binary(selected_cli_override) or "")
    cooldown = current_cli_cooldown(key=brain._cli_runtime_key(cli_binary)) if cli_binary else {}
    status = {
        "selected_api_provider": await _selected_api_runtime_truth(settings, conn),
        "cli_runtime": cli_runtime,
        "codex_runtime": codex_runtime,
        "cli_cooldown_remaining_seconds": float(cooldown.get("remaining_seconds") or 0),
    }
    truth = runtime_truth_service.build_runtime_truth(
        status,
        settings=truth_settings,
        ollama_running=bool(_ollama_service_status().get("running")),
    )
    return truth, status


async def _ai_params(settings: dict, conn=None, *, allow_degraded_api: bool = False) -> dict:
    """Extract AI backend params from settings dict, resolving keys from vault when available."""
    backend = settings.get("ai_backend", "api")
    selected_provider_id = provider_registry.selected_api_provider_id(settings)

    api_runtime, api_key = await _resolved_api_runtime(settings, selected_provider_id, conn)
    provider_id = api_runtime.get("provider_id", selected_provider_id or "deepseek")

    if backend in {"cli", "ollama"} and not api_key:
        fallback_candidates = [
            spec.provider_id
            for spec in provider_registry.PROVIDERS
            if spec.runtime_capable and spec.provider_id != provider_id
        ]
        for candidate_id in fallback_candidates:
            candidate_runtime, candidate_key = await _resolved_api_runtime(settings, candidate_id, conn)
            if candidate_key:
                api_runtime = candidate_runtime
                api_key = candidate_key
                provider_id = candidate_runtime.get("provider_id", candidate_id)
                break

    cli_path = _selected_cli_path(settings)
    cli_model = _selected_cli_model(settings)
    cli_session_persistence = cli_session_persistence_enabled(settings.get("claude_cli_session_persistence_enabled"))
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    if backend == "api" and not api_key and not allow_degraded_api:
        provider_label = api_runtime.get("provider_label", "External API")
        raise HTTPException(400, f"{provider_label} key not set. Add it to the Secure Vault or Settings → Runtime.")
    if backend == "cli" and not cli_path and not brain._find_cli():
        raise HTTPException(400, "CLI agent not found. Set the path in Settings.")
    return {
        "api_key": api_key,
        "api_provider": provider_id,
        "api_base_url": api_runtime.get("api_base_url", ""),
        "api_model": api_runtime.get("api_model", ""),
        "backend": backend, "cli_path": cli_path, "cli_model": cli_model,
        "cli_session_persistence": cli_session_persistence,
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
        elif str(agent_role).lower() == "auto":
            lines.append("- Agent mode: Autonomous workspace execution is active.")
            lines.append("- Keep working inside the selected workspace until the request is complete or clearly blocked.")
            lines.append("- Do not stop at a plan, commentary, or partial diagnosis when you can execute and verify the next step.")
            lines.append("- Ask the user only if the request is materially ambiguous, credentials are missing, or a risky action truly needs confirmation.")
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
    if agent_role == "auto":
        return "code"
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


def _normalized_autonomy_profile(value: str, *, reject_elevated: bool = False) -> str:
    profile = str(value or "workspace_auto").strip().lower() or "workspace_auto"
    if profile == "manual":
        return "manual"
    if profile in {"branch_auto", "pr_auto", "merge_auto", "deploy_auto"}:
        if reject_elevated:
            raise HTTPException(400, "Elevated autonomy profiles are disabled in this hardening phase.")
        return "workspace_auto"
    return "workspace_auto"


def _normalized_runtime_permissions_mode(value: str, *, fallback: str = "default") -> str:
    mode = str(value or "").strip().lower()
    if mode in {"default", "ask_first", "full_access"}:
        return mode
    return fallback


def _effective_agent_runtime_permissions_mode(
    settings: dict,
    *,
    override: str = "",
    backend: str = "",
    cli_path: str = "",
    autonomy_profile: str = "",
) -> str:
    normalized_autonomy = _normalized_autonomy_profile(autonomy_profile or settings.get("autonomy_profile") or "workspace_auto")
    default_fallback = "ask_first" if normalized_autonomy == "manual" else "default"
    current_mode = _normalized_runtime_permissions_mode(
        settings.get("runtime_permissions_mode") or "",
        fallback=default_fallback,
    )
    requested_mode = _normalized_runtime_permissions_mode(override or "", fallback=current_mode)
    if requested_mode != "full_access":
        return requested_mode
    if str(backend or "").strip().lower() != "cli":
        return current_mode
    if brain._cli_runtime_family(str(cli_path or "")) != "codex":
        return current_mode
    return "full_access"


def _normalized_external_fetch_policy(value: str) -> str:
    policy = str(value or "cache_first").strip().lower()
    if policy in {"", "memory_first", "cache_first"}:
        return "cache_first"
    if policy == "live_first":
        return "live_first"
    return "cache_first"


def _normalized_max_history_turns(settings_or_payload: dict, key: str = "max_history_turns") -> str:
    raw = str((settings_or_payload or {}).get(key) or "").strip()
    if raw in {"", "12"}:
        return "10"
    return str(_setting_int(settings_or_payload, key, 10, minimum=6, maximum=60))


def _model_budget_for_request(composer_options: dict, *, agent_request: bool = False) -> str:
    options = _composer_options_dict(composer_options)
    intelligence = str(options.get("intelligence_mode") or "ask").strip().lower()
    action = str(options.get("action_mode") or "").strip().lower()
    agent_role = str(options.get("agent_role") or "").strip().lower()
    if intelligence in {"deep_research", "compare"} or agent_role in {"planner", "reviewer", "repair"}:
        return "deep"
    if agent_request or agent_role in {"auto", "coder"} or action in {"fix_repair", "optimize", "refactor"}:
        return "standard"
    return "quick"


def _configured_budget_model(settings: dict, budget: str) -> str:
    quick = str(settings.get("quick_model") or "").strip()
    standard = str(settings.get("standard_model") or "").strip()
    deep = str(settings.get("deep_model") or "").strip()
    if budget == "deep":
        return deep or standard or quick
    if budget == "quick":
        return quick or standard or deep
    return standard or quick or deep


def _default_budget_model_for_ai(ai: dict, settings: dict, budget: str) -> str:
    backend = str(ai.get("backend") or settings.get("ai_backend") or "api").strip().lower()
    if backend == "cli":
        cli_path = str(ai.get("cli_path") or _selected_cli_path(settings) or "").strip()
        family = brain._cli_runtime_family(cli_path)
        if family == "codex":
            if budget == "quick":
                return "gpt-5.1-codex-mini"
            return "gpt-5.4"
        if budget == "quick":
            return "haiku"
        if budget == "deep":
            return "opus"
        return "sonnet"
    if backend == "ollama":
        if budget == "quick":
            return brain.OLLAMA_FAST_MODEL
        return str(settings.get("ollama_model") or brain.OLLAMA_DEFAULT_MODEL).strip()
    return ""


def _model_call_kwargs(ai: dict) -> dict:
    allowed_keys = {
        "backend",
        "api_key",
        "api_provider",
        "api_base_url",
        "api_model",
        "cli_path",
        "cli_model",
        "cli_session_persistence",
        "ollama_url",
        "ollama_model",
    }
    return {key: value for key, value in dict(ai or {}).items() if key in allowed_keys}


async def _effective_ai_params(settings: dict, composer_options: dict, *, conn=None, agent_request: bool = False, requested_model: str = "") -> dict:
    ai = dict(await _ai_params(settings, conn, allow_degraded_api=True))
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

    runtime_truth, runtime_status = await _runtime_truth_for_settings(
        settings,
        conn,
        backend_override=str(ai.get("backend") or ""),
    )
    effective_runtime = str(runtime_truth.get("effective_runtime") or "").strip().lower()
    selected_runtime = str(runtime_truth.get("selected_runtime") or "").strip().lower()
    if effective_runtime == runtime_truth_service.SELF_HEAL_RUNTIME and selected_runtime != effective_runtime:
        codex_runtime = dict(runtime_status.get("codex_runtime") or {})
        codex_binary = str(codex_runtime.get("binary") or _family_cli_override_path(settings, "codex") or brain._find_codex_cli()).strip()
        if codex_binary:
            ai.update(
                {
                    "backend": "cli",
                    "cli_path": codex_binary,
                    "cli_model": runtime_truth_service.SELF_HEAL_MODEL,
                }
            )

    budget = _model_budget_for_request(composer_options, agent_request=agent_request)
    budget_model = _configured_budget_model(settings, budget) or _default_budget_model_for_ai(ai, settings, budget)

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
    elif ai.get("backend") == "api":
        if requested_model:
            ai["api_model"] = requested_model
            return ai
        # API backend: pick role-specific model when available
        role = _local_role_for_composer(composer_options, agent_request=agent_request)
        provider_id = ai.get("api_provider", "")
        role_map = brain.API_MODEL_BY_ROLE.get(provider_id, {})
        if role in role_map:
            ai["api_model"] = role_map[role]
    else:
        if runtime_truth.get("self_heal_active") and effective_runtime == runtime_truth_service.SELF_HEAL_RUNTIME:
            ai["cli_model"] = runtime_truth_service.SELF_HEAL_MODEL
        elif requested_model:
            ai["cli_model"] = requested_model

    if not requested_model and budget_model:
        if ai.get("backend") == "api":
            ai["api_model"] = budget_model
        elif ai.get("backend") == "cli":
            selected_cli_path = str(ai.get("cli_path") or _selected_cli_path(settings) or "").strip()
            normalized_budget = brain.normalize_cli_model(selected_cli_path, budget_model)
            ai["cli_model"] = normalized_budget or budget_model
        elif ai.get("backend") == "ollama":
            ai["ollama_model"] = budget_model

    ai["budget_class"] = budget

    if ai.get("backend") == "api" and not ai.get("api_key"):
        provider_label = str(runtime_truth.get("selected_runtime_label") or "External API")
        raise HTTPException(400, f"{provider_label} key not set. Add it to the Secure Vault or Settings → Runtime.")
    return ai


def _looks_like_image_generation_request(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    strong_markers = (
        "generate an image",
        "create an image",
        "make an image",
        "make me an image",
        "generate a logo",
        "create a logo",
        "generate an illustration",
        "create an illustration",
        "generate a poster",
        "create a poster",
        "generate concept art",
        "text to image",
    )
    if any(marker in text for marker in strong_markers):
        return True
    visual_nouns = ("image", "logo", "illustration", "poster", "sticker", "banner", "icon", "mockup", "render")
    visual_verbs = ("generate", "create", "make", "design", "draw")
    return any(verb in text for verb in visual_verbs) and any(noun in text for noun in visual_nouns)


async def _auto_route_image_generation_runtime(
    conn,
    *,
    settings: dict,
    ai: dict,
    user_message: str,
    requested_model: str = "",
    agent_request: bool = False,
) -> tuple[dict, list[str]]:
    if not _looks_like_image_generation_request(user_message):
        return ai, []

    warnings: list[str] = []
    if not agent_request:
        warnings.append("Image generation requests work best in Agent mode so Axon can call the generate_image tool automatically.")
        return ai, warnings

    if (requested_model or "").strip():
        warnings.append(f"Image generation request kept on explicitly selected model `{requested_model}`.")
        return ai, warnings

    routed = dict(ai)
    candidate_id = "gemini_gems"
    candidate = provider_registry.merged_provider_config(
        candidate_id,
        settings,
        {"model": settings.get("gemini_image_model") or "gemini-3.1-flash-image-preview"},
    )
    candidate_key = settings.get(candidate.get("key_setting", ""), "") or ""
    if not candidate_key and devvault.VaultSession.is_unlocked():
        candidate_key = await devvault.vault_resolve_provider_key(conn, candidate_id)
    if not candidate_key:
        warnings.append("Image generation was requested, but no Gemini key is configured. Axon can plan the image prompt, but cannot render it yet.")
        return routed, warnings

    routed.update(
        {
            "backend": "api",
            "api_provider": candidate_id,
            "api_key": candidate_key,
            "api_base_url": candidate.get("base_url", ""),
            "api_model": candidate.get("model", "gemini-3.1-flash-image-preview"),
        }
    )
    warnings.append(f"Image generation request — auto-routed to {candidate.get('label', candidate_id)} for image-capable tool use.")
    return routed, warnings


async def _memory_bundle(
    conn,
    *,
    user_message: str,
    project_id: Optional[int],
    resource_ids: list[int],
    settings: dict,
    composer_options: dict,
    snapshot_revision: str = "",
) -> dict:
    if str(settings.get("memory_first_enabled", "1")).strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "items": [],
            "context_block": "",
            "overview": {"total": 0, "layers": {}, "state": "memory_first_disabled"},
            "evidence_source": "model_only",
        }
    try:
        await _ensure_memory_layers_synced(conn, settings)
    except _sqlite3.DatabaseError as exc:
        print(f"[Axon] Memory bundle sync degraded: {exc}")
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
        snapshot_revision=snapshot_revision,
    )
    try:
        overview = await memory_engine.build_memory_overview(conn)
    except _sqlite3.DatabaseError as exc:
        print(f"[Axon] Memory overview degraded: {exc}")
        overview = {"total": 0, "layers": {}, "state": "degraded"}
    return {
        "items": results,
        "context_block": memory_engine.build_memory_context(results),
        "overview": overview,
        "evidence_source": "memory" if results else "model_only",
    }


async def _ensure_memory_layers_synced(conn, settings: dict, *, force: bool = False) -> dict:
    now = _time.time()
    cached_overview = _memory_sync_cache.get("overview")
    cached_at = float(_memory_sync_cache.get("checked_at") or 0.0)
    if (
        not force
        and isinstance(cached_overview, dict)
        and cached_overview
        and (now - cached_at) < _MEMORY_SYNC_CACHE_TTL_SECONDS
    ):
        return dict(cached_overview)

    overview = await memory_engine.sync_memory_layers(conn, settings)
    _memory_sync_cache["checked_at"] = now
    _memory_sync_cache["overview"] = dict(overview or {})
    return dict(overview or {})


def _setting_int(settings: dict, key: str, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(str(settings.get(key, default) or default).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _compact_text(value: str, *, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def _build_thread_summary_text(rows) -> str:
    if not rows:
        return ""
    lines = ["## Conversation Summary"]
    for raw_row in rows[-12:]:
        row = dict(raw_row)
        parsed = _parse_stored_chat_message(str(row.get("content") or ""))
        content = _compact_text(str(parsed.get("content") or ""), limit=180)
        if not content:
            continue
        role = str(row.get("role") or "assistant").strip().lower()
        label = "User" if role == "user" else "Axon"
        lines.append(f"- {label}: {content}")
    return "\n".join(lines[:13])


async def _workspace_snapshot_bundle(
    conn,
    *,
    project_id: Optional[int],
    settings: dict,
) -> dict:
    if project_id is None:
        projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
        context_block = brain._build_context_block(projects, tasks, prompts_list)
        return {
            "revision": "global",
            "context_block": context_block,
            "data": {"projects": projects[:10], "tasks": tasks[:10], "prompts": prompts_list[:5]},
            "evidence_source": "workspace_snapshot",
        }

    ttl_seconds = _setting_int(settings, "workspace_snapshot_ttl_seconds", 60, minimum=10, maximum=3600)
    snapshot_key = f"workspace:{project_id}"
    revision = await devdb.compute_workspace_revision(conn, project_id)
    existing = await devdb.get_workspace_snapshot(conn, workspace_id=project_id, snapshot_key=snapshot_key)
    if existing and str(existing["revision"] or "") == revision:
        updated_at = str(existing["updated_at"] or "")
        age_ok = True
        if updated_at:
            try:
                stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00").replace(" ", "T"))
                age_ok = (_time.time() - stamp.timestamp()) < ttl_seconds
            except Exception:
                age_ok = True
        if age_ok:
            try:
                data = _json.loads(str(existing["data_json"] or "{}"))
            except Exception:
                data = {}
            return {
                "revision": revision,
                "context_block": str(existing["context_block"] or ""),
                "data": data,
                "evidence_source": "workspace_snapshot",
            }

    project_row = await devdb.get_project(conn, project_id)
    projects = [dict(project_row)] if project_row else []
    tasks = [dict(r) for r in await devdb.get_tasks(conn, project_id=project_id, status="open")]
    prompts_list = [dict(r) for r in await devdb.get_prompts(conn, project_id=project_id)]
    high_trust_memory = [
        dict(r)
        for r in await devdb.list_memory_items_filtered(
            conn,
            workspace_id=project_id,
            trust_level="high",
            limit=4,
        )
    ]
    context_block = brain._build_context_block(projects, tasks, prompts_list)
    if high_trust_memory:
        memory_lines = [
            f"- {item.get('title', 'Memory')}: {_compact_text(item.get('summary') or item.get('content') or '', limit=160)}"
            for item in high_trust_memory[:2]
        ]
        context_block = "\n\n".join(
            block for block in (
                context_block,
                "## Known Workspace Facts\n" + "\n".join(memory_lines),
            ) if block
        )
    snapshot_data = {
        "project": projects[0] if projects else {},
        "tasks": tasks[:8],
        "prompts": prompts_list[:5],
        "memory": high_trust_memory[:4],
    }
    await devdb.upsert_workspace_snapshot(
        conn,
        workspace_id=project_id,
        snapshot_key=snapshot_key,
        revision=revision,
        context_block=context_block,
        data_json=_json.dumps(snapshot_data, ensure_ascii=True),
        commit=False,
    )
    await conn.commit()
    return {
        "revision": revision,
        "context_block": context_block,
        "data": snapshot_data,
        "evidence_source": "workspace_snapshot",
    }


async def _chat_history_bundle(
    conn,
    *,
    project_id: Optional[int],
    settings: dict,
    backend: str,
    history_rows=None,
) -> dict:
    history_budget = _setting_int(
        settings,
        "max_history_turns",
        _setting_int(settings, "max_chat_history", 12, minimum=6, maximum=120),
        minimum=6,
        maximum=60,
    )
    rows = list(history_rows or [])
    if not rows:
        rows = await _load_chat_history_rows(
            conn,
            project_id=project_id,
            limit=max(history_budget * 4, 40),
            degrade_to_empty=True,
        )
    recent_rows = rows[-history_budget:]
    history = select_history_for_chat(
        "",
        _history_messages_from_rows(recent_rows),
        backend=backend,
        max_turns=history_budget,
    )
    summary_block = ""
    if len(rows) > len(recent_rows):
        older_rows = rows[:-len(recent_rows)] if recent_rows else rows
        revision_payload = "|".join(str(dict(row).get("id") or "") for row in older_rows[-20:]) + f":{len(older_rows)}"
        revision = _json.dumps({"digest": revision_payload}, sort_keys=True)
        thread_key = f"chat:{project_id or 0}:{backend}"
        existing = await devdb.get_thread_summary(conn, thread_key)
        if existing and str(existing["revision"] or "") == revision:
            summary_block = str(existing["summary"] or "")
        else:
            summary_block = _build_thread_summary_text(older_rows)
            if summary_block:
                await devdb.upsert_thread_summary(
                    conn,
                    thread_key=thread_key,
                    workspace_id=project_id,
                    revision=revision,
                    summary=summary_block,
                    message_count=len(rows),
                    commit=False,
                )
                await conn.commit()
    return {
        "history": history,
        "summary_block": summary_block,
        "history_budget": history_budget,
        "row_count": len(rows),
    }


def _extract_first_url(message: str) -> str:
    match = _re.search(r"https?://[^\s<>'\"`]+", str(message or ""))
    if not match:
        return ""
    return match.group(0).rstrip(").,;!?]}")


def _requires_fresh_external_fetch(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    if _extract_first_url(lowered):
        return bool(_re.search(r"\b(latest|today|current|recent|right now|as of|up[- ]to[- ]date)\b", lowered))
    return False


def _looks_like_mutating_or_generation_request(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    return bool(
        _re.search(
            r"\b(create|generate|build|write|draft|fix|change|edit|update|modify|implement|refactor|commit|push|deploy|rollback|delete|remove)\b",
            lowered,
        )
    )


def _looks_like_local_fast_path_candidate(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    if _looks_like_mutating_or_generation_request(lowered):
        return False
    if _extract_first_url(lowered):
        return True
    if len(lowered.split()) > 40:
        return False
    starters = (
        "what ",
        "what's ",
        "what is ",
        "which ",
        "where ",
        "show ",
        "list ",
        "summarize ",
        "summarise ",
        "recall ",
        "remember ",
        "tell me ",
        "do you know ",
    )
    if lowered.startswith(starters) or lowered.endswith("?"):
        return True
    return bool(
        _re.search(
            r"\b(path|branch|status|health|stack|workspace|project|tasks?|missions?|playbooks?|prompts?|memory|cached)\b",
            lowered,
        )
    )


def _format_cached_web_fast_answer(row, *, url: str) -> str:
    title = str(row["title"] or "").strip()
    summary = _compact_text(str(row["summary"] or ""), limit=320)
    content = _compact_text(str(row["content"] or ""), limit=520)
    status_code = int(row["status_code"] or 200)
    lines = ["Using Axon's cached web copy (no model call)."]
    if title:
        lines.append(f"Title: {title}")
    lines.append(f"URL: {url}")
    lines.append(f"HTTP status: {status_code}")
    if summary:
        lines.append(f"Summary: {summary}")
    elif content:
        lines.append(f"Content: {content}")
    return "\n".join(lines)


def _workspace_snapshot_fast_answer(message: str, snapshot_bundle: dict) -> str:
    lowered = str(message or "").strip().lower()
    data = dict(snapshot_bundle.get("data") or {})
    project = dict(data.get("project") or {})
    tasks = [dict(item) for item in (data.get("tasks") or []) if isinstance(item, dict)]
    prompts = [dict(item) for item in (data.get("prompts") or []) if isinstance(item, dict)]
    memories = [dict(item) for item in (data.get("memory") or []) if isinstance(item, dict)]
    if not project and not tasks and not prompts and not memories:
        return ""

    lines: list[str] = ["Using Axon's workspace snapshot (no model call)."]
    answered = False

    if project and any(token in lowered for token in ("path", "where is", "workspace path", "repo path", "root")):
        answered = True
        lines.append(f"Workspace: {project.get('name') or 'Current workspace'}")
        lines.append(f"Path: {project.get('path') or 'unknown'}")
        if project.get("git_branch"):
            lines.append(f"Branch: {project['git_branch']}")
    elif project and any(token in lowered for token in ("branch", "git branch")):
        answered = True
        lines.append(f"Workspace: {project.get('name') or 'Current workspace'}")
        lines.append(f"Branch: {project.get('git_branch') or 'unknown'}")
        if project.get("path"):
            lines.append(f"Path: {project['path']}")
    elif project and any(token in lowered for token in ("stack", "framework", "tech stack")):
        answered = True
        lines.append(f"Workspace: {project.get('name') or 'Current workspace'}")
        lines.append(f"Stack: {project.get('stack') or 'unknown'}")
        if project.get("description"):
            lines.append(f"Description: {_compact_text(project['description'], limit=220)}")
    elif tasks and any(token in lowered for token in ("task", "tasks", "mission", "missions", "todo", "open work")):
        answered = True
        lines.append(f"Open tasks: {len(tasks)}")
        for task in tasks[:4]:
            detail = _compact_text(str(task.get("detail") or ""), limit=120)
            line = f"- {task.get('title') or 'Untitled'}"
            if task.get("priority"):
                line += f" [{task['priority']}]"
            if detail:
                line += f": {detail}"
            lines.append(line)
    elif prompts and any(token in lowered for token in ("prompt", "prompts", "playbook", "playbooks", "template", "templates")):
        answered = True
        lines.append(f"Saved playbooks: {len(prompts)}")
        for prompt in prompts[:4]:
            lines.append(f"- {prompt.get('title') or 'Untitled'}")
    elif any(token in lowered for token in ("workspace", "project", "status", "health", "what do you know", "known facts")):
        answered = True
        if project:
            lines.append(f"Workspace: {project.get('name') or 'Current workspace'}")
            if project.get("path"):
                lines.append(f"Path: {project['path']}")
            if project.get("git_branch"):
                lines.append(f"Branch: {project['git_branch']}")
            if project.get("stack"):
                lines.append(f"Stack: {project['stack']}")
            if project.get("health") not in (None, ""):
                lines.append(f"Health: {project['health']}")
        if tasks:
            lines.append(f"Open tasks tracked here: {len(tasks)}")
        if prompts:
            lines.append(f"Saved playbooks/prompts: {len(prompts)}")
        for memory in memories[:2]:
            snippet = _compact_text(str(memory.get("summary") or memory.get("content") or ""), limit=160)
            if snippet:
                lines.append(f"- {memory.get('title') or 'Known fact'}: {snippet}")

    return "\n".join(lines) if answered else ""


def _memory_fast_answer(message: str, memory_bundle: dict) -> str:
    lowered = str(message or "").strip().lower()
    items = [dict(item) for item in (memory_bundle.get("items") or []) if isinstance(item, dict)]
    if not items:
        return ""
    if not (
        "memory" in lowered
        or "remember" in lowered
        or "recall" in lowered
        or "what do you know" in lowered
        or "known facts" in lowered
        or "summar" in lowered
        or lowered.endswith("?")
    ):
        return ""
    lines = ["Using Axon's memory bank (no model call)."]
    for item in items[:3]:
        snippet = _compact_text(str(item.get("summary") or item.get("content") or ""), limit=200)
        if not snippet:
            continue
        lines.append(f"- {item.get('title') or 'Memory'}: {snippet}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def _maybe_local_fast_chat_response(
    conn,
    *,
    user_message: str,
    project_id: Optional[int],
    settings: dict,
    snapshot_bundle: dict,
    memory_bundle: dict,
) -> dict | None:
    text = str(user_message or "").strip()
    if not _looks_like_local_fast_path_candidate(text):
        return None

    fetch_policy = _normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first")
    url = _extract_first_url(text)
    if url and fetch_policy != "live_first" and not _requires_fresh_external_fetch(text):
        try:
            cached_row = await devdb.get_external_fetch_cache(conn, url)
        except Exception:
            cached_row = None
        if cached_row:
            return {
                "content": _format_cached_web_fast_answer(cached_row, url=url),
                "tokens": 0,
                "evidence_source": "cached_external",
                "model_label": "Cached web",
                "fast_path": True,
            }

    workspace_answer = _workspace_snapshot_fast_answer(text, snapshot_bundle)
    if workspace_answer:
        return {
            "content": workspace_answer,
            "tokens": 0,
            "evidence_source": "workspace_snapshot",
            "model_label": "Workspace snapshot",
            "fast_path": True,
        }

    memory_answer = _memory_fast_answer(text, memory_bundle)
    if memory_answer:
        return {
            "content": memory_answer,
            "tokens": 0,
            "evidence_source": "memory",
            "model_label": "Memory fast path",
            "fast_path": True,
        }
    return None


async def _persist_chat_reply(
    conn,
    *,
    project_id: Optional[int],
    user_message: str,
    assistant_message: str,
    resources: list[dict],
    thread_mode: str,
    tokens: int = 0,
    model_label: str = "",
    event_name: str = "chat",
    event_summary: str = "",
):
    stored_user_message = _stored_chat_message(
        user_message,
        resources=resources,
        mode="chat",
        thread_mode=thread_mode,
    )
    await devdb.save_message(conn, "user", stored_user_message, project_id=project_id)
    await devdb.save_message(
        conn,
        "assistant",
        _stored_chat_message(
            assistant_message,
            mode="chat",
            thread_mode=thread_mode,
            model_label=model_label,
        ),
        project_id=project_id,
        tokens=tokens,
    )
    await devdb.log_event(conn, event_name, event_summary or user_message[:100], project_id=project_id)


async def _maybe_handle_chat_console_command(
    conn,
    *,
    project_id: Optional[int],
    user_message: str,
    thread_mode: str,
):
    text = str(user_message or "").strip().lower()
    login_overrides = None
    if text.startswith("/login") or text.startswith("/login-cli"):
        login_overrides = {
            "claude": str(await devdb.get_setting(conn, "claude_cli_path") or "").strip(),
            "codex": str(await devdb.get_setting(conn, "cli_runtime_path") or "").strip(),
        }

    command_result = console_command_service.maybe_handle_console_command(
        user_message,
        login_overrides=login_overrides,
    )
    if not command_result:
        return None

    assistant_message = str(command_result.get("response") or "")
    _set_live_operator(
        active=False,
        mode="chat",
        phase="execute",
        title="Handled console command",
        detail=str(command_result.get("command") or "command"),
        summary=assistant_message[:180],
        workspace_id=project_id,
    )
    await _persist_chat_reply(
        conn,
        project_id=project_id,
        user_message=user_message,
        assistant_message=assistant_message,
        resources=[],
        thread_mode=thread_mode,
        tokens=0,
        model_label="Axon console",
        event_name=str(command_result.get("event_name") or "chat_console_command"),
        event_summary=str(command_result.get("event_summary") or user_message[:100]),
    )
    payload = dict(command_result.get("data") or {})
    payload.update(
        {
            "response": assistant_message,
            "tokens": 0,
            "console_command": True,
            "command": str(command_result.get("command") or ""),
        }
    )
    return payload


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


_CHAT_HISTORY_ENVELOPE_PREFIX = "AXON_CHAT_V1:"


def _thread_mode_from_composer_options(composer_options: dict | None, *, agent_request: bool = False) -> str:
    options = _composer_options_dict(composer_options)
    intelligence = str(options.get("intelligence_mode") or "ask").strip().lower()
    action = str(options.get("action_mode") or "").strip().lower()
    agent_role = str(options.get("agent_role") or "").strip().lower()
    if agent_role == "auto":
        return "auto"
    if agent_request or agent_role:
        return "agent"
    if intelligence == "deep_research":
        return "research"
    if intelligence == "analyze" and action == "generate":
        return "code"
    if intelligence == "build_brief" and action == "generate":
        return "business"
    return "ask"


def _stored_chat_message(
    message: str,
    *,
    resources: list[dict] | None = None,
    mode: str = "",
    thread_mode: str = "",
    model_label: str = "",
) -> str:
    payload = {"content": str(message or "")}
    resource_refs = []
    for resource in resources or []:
        title = str(resource.get("title") or "resource").strip() or "resource"
        ref = {"title": title}
        resource_id = resource.get("id")
        if resource_id not in (None, ""):
            ref["id"] = resource_id
        kind = str(resource.get("kind") or "").strip()
        if kind:
            ref["kind"] = kind
        resource_refs.append(ref)
    if resource_refs:
        payload["resources"] = resource_refs
    if mode:
        payload["mode"] = str(mode)
    if thread_mode:
        payload["thread_mode"] = str(thread_mode)
    if model_label:
        payload["model_label"] = str(model_label)
    if tuple(payload.keys()) == ("content",):
        return payload["content"]
    return f"{_CHAT_HISTORY_ENVELOPE_PREFIX}{_json.dumps(payload, separators=(',', ':'))}"


def _stored_message_with_resources(message: str, resources: list[dict]) -> str:
    return _stored_chat_message(message, resources=resources)


def _parse_stored_chat_message(raw_content: str) -> dict[str, object]:
    raw = str(raw_content or "")
    if raw.startswith(_CHAT_HISTORY_ENVELOPE_PREFIX):
        try:
            payload = _json.loads(raw[len(_CHAT_HISTORY_ENVELOPE_PREFIX):])
        except Exception:
            payload = None
        if isinstance(payload, dict):
            resources = payload.get("resources") if isinstance(payload.get("resources"), list) else []
            return {
                "content": str(payload.get("content") or ""),
                "resources": [dict(item) for item in resources if isinstance(item, dict)],
                "mode": str(payload.get("mode") or ""),
                "thread_mode": str(payload.get("thread_mode") or ""),
                "model_label": str(payload.get("model_label") or ""),
            }

    match = _re.match(r"(?s)^(.*?)(?:\n\n\[Attached resources: ([^\]]+)\]\s*)?$", raw)
    content = raw
    resources: list[dict[str, object]] = []
    if match and match.group(2):
        content = match.group(1).rstrip()
        resources = [
            {"id": f"history-{index}-{title.strip()}", "title": title.strip()}
            for index, title in enumerate(match.group(2).split(","))
            if title.strip()
        ]
    return {
        "content": content,
        "resources": resources,
        "mode": "",
        "thread_mode": "",
        "model_label": "",
    }


def _history_messages_from_rows(rows) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for row in rows or []:
        parsed = _parse_stored_chat_message(row["content"])
        content = str(parsed.get("content") or "")
        resources = parsed.get("resources") if isinstance(parsed.get("resources"), list) else []
        if resources:
            labels = ", ".join(str(item.get("title") or "resource") for item in resources[:6])
            suffix = "…" if len(resources) > 6 else ""
            content = f"{content}\n\n[Attached resources: {labels}{suffix}]".strip()
        messages.append({"role": row["role"], "content": content})
    return messages


def _serialize_chat_history_row(row) -> dict[str, object]:
    parsed = _parse_stored_chat_message(row["content"])
    return {
        "role": row["role"],
        "content": parsed.get("content") or "",
        "created_at": row["created_at"],
        "tokens_used": row["tokens_used"],
        "resources": parsed.get("resources") or [],
        "mode": parsed.get("mode") or "",
        "thread_mode": parsed.get("thread_mode") or "",
        "model_label": parsed.get("model_label") or "",
    }


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
    # Only Ollama uses a separate explicit vision model setting here.
    _backend = (settings.get("ai_backend") or "api").lower()
    if not vision_model and _backend == "api":
        vision_model = settings.get("api_model") or ""

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

    if image_paths and not vision_model and _backend not in {"api", "cli"}:
        warnings.append("Image resources are attached, but the current runtime does not have direct vision enabled. Axon will use image metadata only.")

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
    workspace_id: Optional[int] = None,
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
        workspace_id=workspace_id,
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
    workspace_id: Optional[int] = None


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
async def upload_resources(files: list[UploadFile] = File(...), workspace_id: Optional[int] = Form(None)):
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
                    workspace_id=workspace_id,
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
            workspace_id=body.workspace_id,
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
        composer_options = _composer_options_dict(body.composer_options)
        chat_thread_mode = _thread_mode_from_composer_options(composer_options)
        console_command = await _maybe_handle_chat_console_command(
            conn,
            project_id=body.project_id,
            user_message=body.message,
            thread_mode=chat_thread_mode,
        )
        if console_command:
            return console_command

        settings = await devdb.get_all_settings(conn)
        ai = await _effective_ai_params(settings, composer_options, conn=conn, requested_model=body.model or "")
        backend = ai.get("backend", settings.get("ai_backend", "api"))

        snapshot_bundle = await _workspace_snapshot_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
        )
        history_rows = await _load_chat_history_rows(
            conn,
            project_id=body.project_id,
            limit=max(_setting_int(settings, "max_history_turns", 10, minimum=6, maximum=60) * 4, 40),
            degrade_to_empty=True,
        )
        history_bundle = await _chat_history_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
            backend=backend,
            history_rows=history_rows,
        )
        history = history_bundle["history"]

        # Get project scope if present
        project_name = None
        workspace_path = ""
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]
                workspace_path = proj["path"] or ""

        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        ai, _vision_warnings = await auto_route_vision_runtime(
            settings=settings,
            ai=ai,
            resource_bundle=resource_bundle,
            requested_model=body.model or "",
            resolve_provider_key=lambda provider_id: devvault.vault_resolve_provider_key(conn, provider_id),
            vault_unlocked=devvault.VaultSession.is_unlocked(),
        )
        if _vision_warnings:
            resource_bundle["warnings"].extend(_vision_warnings)
        ai, _image_warnings = await _auto_route_image_generation_runtime(
            conn,
            settings=settings,
            ai=ai,
            user_message=body.message,
            requested_model=body.model or "",
            agent_request=False,
        )
        if _image_warnings:
            resource_bundle["warnings"].extend(_image_warnings)
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
            snapshot_revision=snapshot_bundle["revision"],
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (
                snapshot_bundle["context_block"],
                history_bundle["summary_block"],
                memory_bundle["context_block"],
                composer_block,
            ) if block
        )

        fast_path = await _maybe_local_fast_chat_response(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            settings=settings,
            snapshot_bundle=snapshot_bundle,
            memory_bundle=memory_bundle,
        )
        if fast_path:
            _set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Answered from local context",
                detail=str(fast_path.get("evidence_source") or "workspace"),
                summary=str(fast_path.get("content") or "")[:180],
                workspace_id=body.project_id,
            )
            await _persist_chat_reply(
                conn,
                project_id=body.project_id,
                user_message=body.message,
                assistant_message=str(fast_path.get("content") or ""),
                resources=resource_bundle["resources"],
                thread_mode=chat_thread_mode,
                tokens=0,
                model_label=str(fast_path.get("model_label") or ""),
                event_name="chat_fast_path",
                event_summary=f"{fast_path.get('evidence_source', 'local')}: {body.message[:100]}",
            )
            return {
                "response": str(fast_path.get("content") or ""),
                "tokens": 0,
                "evidence_source": str(fast_path.get("evidence_source") or ""),
                "fast_path": True,
            }

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
                _pptx_api_model = _pptx_api_cfg.get("api_model", "deepseek-reasoner")

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

                await devdb.save_message(
                    conn,
                    "user",
                    _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    ),
                    project_id=body.project_id,
                )
                await devdb.save_message(
                    conn,
                    "assistant",
                    _stored_chat_message(reply, mode="chat", thread_mode=chat_thread_mode),
                    project_id=body.project_id,
                    tokens=0,
                )
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
                _mns_api_model = _mns_api_cfg.get("api_model", "deepseek-reasoner")

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

                    stored_user_msg = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    )
                    await devdb.save_message(conn, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(
                        conn,
                        "assistant",
                        _stored_chat_message(reply_ns, mode="chat", thread_mode=chat_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )

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
                _pbns_api_model = _pbns_api_cfg.get("api_model", "deepseek-reasoner")

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

                    stored_user_msg = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    )
                    await devdb.save_message(conn, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(
                        conn,
                        "assistant",
                        _stored_chat_message(reply_pbns, mode="chat", thread_mode=chat_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )

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
                    workspace_path=workspace_path,
                    resource_context=resource_bundle["context_block"],
                    resource_image_paths=resource_bundle["image_paths"],
                    vision_model=resource_bundle["vision_model"],
                    **_model_call_kwargs(ai),
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
        await _persist_chat_reply(
            conn,
            project_id=body.project_id,
            user_message=body.message,
            assistant_message=result["content"],
            resources=resource_bundle["resources"],
            thread_mode=chat_thread_mode,
            tokens=result["tokens"],
            event_name="chat",
            event_summary=body.message[:100],
        )

        return {"response": result["content"], "tokens": result["tokens"]}


@app.get("/api/chat/history")
async def get_chat_history(project_id: Optional[int] = None, limit: int = 30):
    async with devdb.get_db() as conn:
        rows = await _load_chat_history_rows(conn, project_id=project_id, limit=limit)
        return [_serialize_chat_history_row(r) for r in rows]


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
        composer_options = _composer_options_dict(body.composer_options)
        chat_thread_mode = _thread_mode_from_composer_options(composer_options)
        console_command = await _maybe_handle_chat_console_command(
            conn,
            project_id=body.project_id,
            user_message=body.message,
            thread_mode=chat_thread_mode,
        )
        if console_command:
            reply = str(console_command.get("response") or "")

            async def _console_command_stream():
                yield {"data": _json.dumps({"chunk": reply})}
                yield {"data": _json.dumps({**console_command, "done": True})}

            return EventSourceResponse(_console_command_stream())

        settings = await devdb.get_all_settings(conn)
        ai = await _effective_ai_params(settings, composer_options, conn=conn, requested_model=body.model or "")
        settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
        if ai.get("ollama_model"):
            settings["ollama_model"] = ai["ollama_model"]
        backend = settings.get("ai_backend", "api")

        snapshot_bundle = await _workspace_snapshot_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
        )
        history_rows = await _load_chat_history_rows(
            conn,
            project_id=body.project_id,
            limit=max(_setting_int(settings, "max_history_turns", 10, minimum=6, maximum=60) * 4, 40),
            degrade_to_empty=True,
        )
        history_bundle = await _chat_history_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
            backend=backend,
            history_rows=history_rows,
        )
        history = history_bundle["history"]
        project_name = None
        workspace_path = ""
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]
                workspace_path = proj["path"] or ""
        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        ai, _vision_warnings = await auto_route_vision_runtime(
            settings=settings,
            ai=ai,
            resource_bundle=resource_bundle,
            requested_model=body.model or "",
            resolve_provider_key=lambda provider_id: devvault.vault_resolve_provider_key(conn, provider_id),
            vault_unlocked=devvault.VaultSession.is_unlocked(),
        )
        if _vision_warnings:
            resource_bundle["warnings"].extend(_vision_warnings)
        ai, _image_warnings = await _auto_route_image_generation_runtime(
            conn,
            settings=settings,
            ai=ai,
            user_message=body.message,
            requested_model=body.model or "",
            agent_request=False,
        )
        if _image_warnings:
            resource_bundle["warnings"].extend(_image_warnings)
        settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
        if ai.get("ollama_model"):
            settings["ollama_model"] = ai["ollama_model"]
        backend = settings.get("ai_backend", backend)
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
            snapshot_revision=snapshot_bundle["revision"],
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (
                snapshot_bundle["context_block"],
                history_bundle["summary_block"],
                memory_bundle["context_block"],
                composer_block,
            ) if block
        )

        fast_path = await _maybe_local_fast_chat_response(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            settings=settings,
            snapshot_bundle=snapshot_bundle,
            memory_bundle=memory_bundle,
        )
        if fast_path:
            reply = str(fast_path.get("content") or "")
            _set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Answered from local context",
                detail=str(fast_path.get("evidence_source") or "workspace"),
                summary=reply[:180],
                workspace_id=body.project_id,
            )

            async def _fast_path_stream():
                yield {"data": _json.dumps({"chunk": reply})}
                yield {"data": _json.dumps({"done": True, "tokens": 0, "fast_path": True, "evidence_source": fast_path.get("evidence_source", "")})}
                async with devdb.get_db() as _fast_conn:
                    await _persist_chat_reply(
                        _fast_conn,
                        project_id=body.project_id,
                        user_message=body.message,
                        assistant_message=reply,
                        resources=resource_bundle["resources"],
                        thread_mode=chat_thread_mode,
                        tokens=0,
                        model_label=str(fast_path.get("model_label") or ""),
                        event_name="chat_fast_path",
                        event_summary=f"{fast_path.get('evidence_source', 'local')}: {body.message[:100]}",
                    )

            return EventSourceResponse(_fast_path_stream())

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
            _pptx_api_model_s = _pptx_api_cfg_s.get("api_model", "deepseek-reasoner")

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
                    stored_user_message = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    )
                    await devdb.save_message(_pconn, "user", stored_user_message, project_id=body.project_id)
                    await devdb.save_message(
                        _pconn,
                        "assistant",
                        _stored_chat_message(reply, mode="chat", thread_mode=chat_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )
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
            _m_api_model = _m_api_cfg.get("api_model", "deepseek-reasoner")

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
                    stored_user_msg = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    )
                    await devdb.save_message(_m_db2, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(
                        _m_db2,
                        "assistant",
                        _stored_chat_message(reply, mode="chat", thread_mode=chat_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )

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
            _pb_api_model = _pb_api_cfg.get("api_model", "deepseek-reasoner")

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
                    stored_user_msg = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="chat",
                        thread_mode=chat_thread_mode,
                    )
                    await devdb.save_message(_pb_db2, "user", stored_user_msg, project_id=body.project_id)
                    await devdb.save_message(
                        _pb_db2,
                        "assistant",
                        _stored_chat_message(reply_pb, mode="chat", thread_mode=chat_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )

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

    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    full_content: list[str] = []

    async def generate():
        try:
            started_stream = False
            usage_sink: dict[str, object] = {}
            for warning in resource_bundle["warnings"]:
                full_content.append(f"⚠️ {warning}\n\n")
                yield {"data": _json.dumps({"chunk": f"⚠️ {warning}\n\n"})}
            async for chunk in brain.stream_chat(
                body.message,
                history,
                merged_context_block,
                project_name=project_name,
                workspace_path=workspace_path,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                backend=backend,
                api_key=ai.get("api_key", ""),
                api_provider=ai.get("api_provider", ""),
                api_base_url=ai.get("api_base_url", ""),
                api_model=ai.get("api_model", ""),
                cli_path=ai.get("cli_path", ""),
                cli_model=ai.get("cli_model", ""),
                cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
                ollama_url=ollama_url, ollama_model=ollama_model,
                usage_sink=usage_sink,
            ):
                if not started_stream:
                    _set_live_operator(
                        active=True,
                        mode="chat",
                        phase="execute",
                        title="Writing the reply",
                        detail=(
                            "Axon is streaming the answer live."
                            if backend == "ollama"
                            else "Axon is streaming the external provider response live."
                        ),
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
                stored_user_message = _stored_chat_message(
                    body.message,
                    resources=resource_bundle["resources"],
                    mode="chat",
                    thread_mode=chat_thread_mode,
                )
                await devdb.save_message(conn, "user", stored_user_message,
                                          project_id=body.project_id)
                await devdb.save_message(
                    conn,
                    "assistant",
                    _stored_chat_message("".join(full_content), mode="chat", thread_mode=chat_thread_mode),
                    project_id=body.project_id,
                    tokens=int(usage_sink.get("tokens") or 0),
                )
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
            yield {"data": _json.dumps({"done": True, "tokens": int(usage_sink.get("tokens") or 0)})}
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
    resume_session_id: Optional[str] = None
    resume_reason: Optional[str] = None
    continue_task: Optional[str] = None
    runtime_permissions_mode_override: Optional[str] = None


@app.post("/api/agent")
async def agent_endpoint(body: AgentRequest, request: Request):
    """SSE streaming agent with tool-calling (Ollama only)."""
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        composer_options = _composer_options_dict(body.composer_options)
        agent_thread_mode = _thread_mode_from_composer_options(composer_options, agent_request=True)
        ai = await _effective_ai_params(settings, composer_options, conn=conn, agent_request=True, requested_model=body.model or "")
        settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
        agent_runtime_permissions_mode = _effective_agent_runtime_permissions_mode(
            settings,
            override=body.runtime_permissions_mode_override or "",
            backend=ai.get("backend", settings.get("ai_backend", "api")),
            cli_path=ai.get("cli_path", ""),
            autonomy_profile=settings.get("autonomy_profile") or "workspace_auto",
        )

        _max_agent_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
        _context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {"1", "true", "yes", "on"}

        projects = [dict(r) for r in await devdb.get_projects(conn, status="active")]
        tasks = [dict(r) for r in await devdb.get_tasks(conn, status="open")]
        prompts_list = [dict(r) for r in await devdb.get_prompts(conn)]
        snapshot_bundle = await _workspace_snapshot_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
        )
        history_rows = await _load_chat_history_rows(
            conn,
            project_id=body.project_id,
            limit=max(_setting_int(settings, "max_history_turns", 10, minimum=6, maximum=60) * 4, 40),
            degrade_to_empty=True,
        )
        history_bundle = await _chat_history_bundle(
            conn,
            project_id=body.project_id,
            settings=settings,
            backend=settings.get("ai_backend", "api"),
            history_rows=history_rows,
        )
        history = history_bundle["history"]
        project_name = None
        workspace_path = ""
        if body.project_id:
            proj = await devdb.get_project(conn, body.project_id)
            if proj:
                project_name = proj["name"]
                workspace_path = proj["path"] or ""
        resource_bundle = await _resource_bundle(
            conn,
            resource_ids=body.resource_ids or [],
            user_message=body.message,
            settings=settings,
        )
        ai, _vision_warnings = await auto_route_vision_runtime(
            settings=settings,
            ai=ai,
            resource_bundle=resource_bundle,
            requested_model=body.model or "",
            resolve_provider_key=lambda provider_id: devvault.vault_resolve_provider_key(conn, provider_id),
            vault_unlocked=devvault.VaultSession.is_unlocked(),
        )
        if _vision_warnings:
            resource_bundle["warnings"].extend(_vision_warnings)
        ai, _image_warnings = await _auto_route_image_generation_runtime(
            conn,
            settings=settings,
            ai=ai,
            user_message=body.message,
            requested_model=body.model or "",
            agent_request=True,
        )
        if _image_warnings:
            resource_bundle["warnings"].extend(_image_warnings)
        settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
        memory_bundle = await _memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=settings,
            composer_options=composer_options,
            snapshot_revision=snapshot_bundle["revision"],
        )
        composer_block = _composer_instruction_block(composer_options)
        merged_context_block = "\n\n".join(
            block for block in (
                snapshot_bundle["context_block"],
                history_bundle["summary_block"],
                memory_bundle["context_block"],
                composer_block,
            ) if block
        )
        backend = settings.get("ai_backend", "api")
        _agent_api_key = ai.get("api_key", "")
        _agent_api_base = ai.get("api_base_url", "")
        _agent_api_model = ai.get("api_model", "")
        _agent_api_provider = ai.get("api_provider", "")
        if backend == "api" and not _agent_api_key:
            raise HTTPException(400, "Agent mode with API backend requires a configured API key. Check Settings or Vault.")

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
                workspace_path=workspace_path,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                tools=body.tools,
                ollama_url=ollama_url, ollama_model=ollama_model,
                max_iterations=_max_agent_iterations,
                context_compact=_context_compact,
                force_tool_mode=bool(composer_options.get("action_mode") or composer_options.get("agent_role")),
                api_key=_agent_api_key,
                api_base_url=_agent_api_base,
                api_model=_agent_api_model,
                api_provider=_agent_api_provider,
                cli_path=ai.get("cli_path", ""),
                cli_model=ai.get("cli_model", ""),
                cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
                backend=backend,
                workspace_id=body.project_id,
                autonomy_profile=_normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto"),
                runtime_permissions_mode=agent_runtime_permissions_mode,
                external_fetch_policy=_normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first"),
                external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600"),
                resume_session_id=body.resume_session_id or "",
                resume_reason=body.resume_reason or "",
                continue_task=body.continue_task or "",
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
                elif event.get("type") == "approval_required":
                    _set_live_operator(
                        active=False,
                        mode="agent",
                        phase="recover",
                        title="Awaiting approval",
                        detail=str(event.get("message") or "Axon paused until you approve or deny the blocked action.")[:180],
                        summary=body.message[:120],
                        workspace_id=body.project_id,
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
                    stored_user_message = _stored_chat_message(
                        body.message,
                        resources=resource_bundle["resources"],
                        mode="agent",
                        thread_mode=agent_thread_mode,
                    )
                    await devdb.save_message(conn, "user", stored_user_message,
                                              project_id=body.project_id)
                    await devdb.save_message(
                        conn,
                        "assistant",
                        _stored_chat_message(final_text, mode="agent", thread_mode=agent_thread_mode),
                        project_id=body.project_id,
                        tokens=0,
                    )
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
        s.pop("extra_allowed_cmds", None)
        s["autonomy_profile"] = _normalized_autonomy_profile(s.get("autonomy_profile") or "workspace_auto")
        s["runtime_permissions_mode"] = _normalized_runtime_permissions_mode(
            s.get("runtime_permissions_mode") or "",
            fallback="ask_first" if s["autonomy_profile"] == "manual" else "default",
        )
        s["external_fetch_policy"] = _normalized_external_fetch_policy(s.get("external_fetch_policy") or "cache_first")
        s["max_history_turns"] = _normalized_max_history_turns(s)
        s["ai_backend"] = s.get("ai_backend") or "api"
        s["api_provider"] = provider_registry.selected_api_provider_id(s)
        s["cli_runtime_path"] = _selected_cli_path(s)
        s["cli_runtime_model"] = _selected_cli_model(s)
        s["ollama_runtime_mode"] = _stored_ollama_runtime_mode(s)
        for key in (
            "cloud_agents_enabled",
            "openai_gpts_enabled",
            "gemini_gems_enabled",
            "resource_url_import_enabled",
            "claude_cli_session_persistence_enabled",
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
            "gemini_api_key",
            "deepseek_api_key",
            "azure_speech_key",
            "cloudflare_tunnel_token",
        ):
            raw = s.get(key_name, "")
            s[f"{key_name}_set"] = bool(raw)
            s[key_name] = provider_registry.mask_secret(raw) if raw else ""
        s["api_key_set"] = s.get("deepseek_api_key_set", False)
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


@app.post("/api/settings")
async def update_settings(body: SettingsUpdate):
    async with devdb.get_db() as conn:
        data = body.model_dump(exclude_none=True)
        current_settings = await devdb.get_all_settings(conn)
        current_runtime_permissions_mode = _normalized_runtime_permissions_mode(
            current_settings.get("runtime_permissions_mode") or "",
            fallback="ask_first" if _normalized_autonomy_profile(current_settings.get("autonomy_profile") or "workspace_auto") == "manual" else "default",
        )
        if "runtime_permissions_mode" in data:
            data["runtime_permissions_mode"] = _normalized_runtime_permissions_mode(
                data.get("runtime_permissions_mode") or "",
                fallback=current_runtime_permissions_mode,
            )
            if "autonomy_profile" not in data:
                data["autonomy_profile"] = "manual" if data["runtime_permissions_mode"] == "ask_first" else "workspace_auto"
        if "autonomy_profile" in data:
            data["autonomy_profile"] = _normalized_autonomy_profile(data.get("autonomy_profile") or "workspace_auto", reject_elevated=True)
            if "runtime_permissions_mode" not in data:
                data["runtime_permissions_mode"] = "ask_first" if data["autonomy_profile"] == "manual" else "default"
        if "external_fetch_policy" in data:
            data["external_fetch_policy"] = _normalized_external_fetch_policy(data.get("external_fetch_policy") or "cache_first")
        if "max_history_turns" in data:
            data["max_history_turns"] = _normalized_max_history_turns(data)
        for ttl_key, ttl_default in (
            ("workspace_snapshot_ttl_seconds", 120),
            ("memory_query_cache_ttl_seconds", 60),
            ("external_fetch_cache_ttl_seconds", 21600),
        ):
            if ttl_key in data:
                data[ttl_key] = str(_setting_int(data, ttl_key, ttl_default, minimum=30, maximum=86400))
        for spec in provider_registry.PROVIDERS:
            key_name = spec.base_url_setting
            if key_name in data:
                raw_value = str(data.get(key_name, "") or "").strip()
                if raw_value:
                    merged = provider_registry.merged_provider_config(
                        spec.provider_id,
                        current_settings,
                        {"base_url": raw_value},
                    )
                    data[key_name] = merged.get("base_url", raw_value)
                else:
                    data[key_name] = ""
        if any(key in data for key in ("cli_runtime_model", "cli_runtime_path", "claude_cli_model", "claude_cli_path")):
            _apply_cli_runtime_settings(data, current_settings)
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
    remember_me: bool = False   # True → 24h TTL, False → 1h TTL


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
async def vault_status(request: Request):
    """Return vault setup state and lock state."""
    if _dev_local_vault_bypass_active(request):
        return {
            "is_setup": False,
            "is_unlocked": True,
            "ttl_remaining": 0,
            "dev_bypass": True,
        }
    async with devdb.get_db() as conn:
        is_setup = await devvault.vault_is_setup(conn)
    return {
        "is_setup": is_setup,
        "is_unlocked": devvault.VaultSession.is_unlocked(),
        "ttl_remaining": devvault.VaultSession.ttl_remaining(),
        "dev_bypass": False,
    }


@app.get("/api/vault/provider-keys")
async def vault_provider_keys(request: Request):
    """Check which providers have keys resolvable from the vault."""
    if _dev_local_vault_bypass_active(request):
        return {"unlocked": True, "resolved": {}, "dev_bypass": True}
    result = {}
    if devvault.VaultSession.is_unlocked():
        async with devdb.get_db() as conn:
            resolved = await devvault.vault_resolve_all_provider_keys(conn)
            for pid in resolved:
                result[pid] = True
    return {"unlocked": devvault.VaultSession.is_unlocked(), "resolved": result, "dev_bypass": False}


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
    """Unlock the vault with master password + TOTP code.
    remember_me=True → 24-hour session; False (default) → 1-hour session.
    The master password is NEVER stored; only the derived key lives in memory.
    """
    ttl = devvault.VaultSession.EXTENDED_TTL if body.remember_me else devvault.VaultSession.DEFAULT_TTL
    async with devdb.get_db() as conn:
        ok, err = await devvault.unlock_vault(conn, body.master_password, body.totp_code, session_ttl=ttl)
    if not ok:
        raise HTTPException(401, err)
    return {
        "unlocked": True,
        "session_ttl": ttl,
        "ttl_label": "24 hours" if body.remember_me else "1 hour",
    }


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
        overview = await _ensure_memory_layers_synced(conn, settings, force=True)
    return {"synced": True, "overview": overview}


@app.get("/api/memory/overview")
async def memory_overview():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        overview = await _ensure_memory_layers_synced(conn, settings)
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
        await _ensure_memory_layers_synced(conn, settings)
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
        await _ensure_memory_layers_synced(conn, settings)
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
        try:
            memory_overview = await _ensure_memory_layers_synced(conn, settings)
        except _sqlite3.DatabaseError as exc:
            print(f"[Axon] Runtime status memory sync degraded: {exc}")
            memory_overview = {
                "total": 0,
                "layers": {},
                "state": "degraded",
                "warning": "Memory sync is temporarily unavailable.",
            }
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
    status.update(
        runtime_truth_service.build_runtime_truth(
            status,
            settings=settings,
            ollama_running=bool(ollama_service.get("running")),
        )
    )
    status["browser_actions"] = _serialize_browser_action_state()
    return status


class ClaudeCliLoginRequest(BaseModel):
    mode: Optional[str] = None
    email: Optional[str] = None


class RuntimeLoginStartRequest(BaseModel):
    mode: Optional[str] = None
    email: Optional[str] = None


def _normalize_runtime_login_family(family: str) -> str:
    text = str(family or "").strip().lower()
    if text in {"cli", "claude"}:
        return "claude"
    if text == "codex":
        return "codex"
    raise HTTPException(404, "Runtime family not found.")


async def _runtime_login_start(family: str, body: RuntimeLoginStartRequest | None = None):
    family_name = _normalize_runtime_login_family(family)
    payload = body or RuntimeLoginStartRequest()
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        override_path = _family_cli_override_path(settings, family_name)
        result = runtime_login_service.start_login_session(
            family_name,
            override_path=override_path,
            mode=payload.mode or "claudeai",
            email=payload.email or "",
        )
        await devdb.log_event(conn, "maintenance", f"{family_name.title()} CLI guided login started")
    return {"session": result}


async def _runtime_login_refresh(family: str, session_id: str):
    family_name = _normalize_runtime_login_family(family)
    session = runtime_login_service.refresh_login_session(family_name, session_id)
    if not session:
        raise HTTPException(404, "Runtime login session not found.")
    return {"session": session}


async def _runtime_login_cancel(family: str, session_id: str):
    family_name = _normalize_runtime_login_family(family)
    async with devdb.get_db() as conn:
        try:
            session = runtime_login_service.cancel_login_session(family_name, session_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        await devdb.log_event(conn, "maintenance", f"{family_name.title()} CLI login cancelled")
    return {"session": session}


@app.get("/api/runtime/cli/status")
async def runtime_cli_status():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    return claude_cli_runtime.build_cli_runtime_snapshot(_family_cli_override_path(settings, "claude"))


@app.post("/api/runtime/cli/install")
async def runtime_cli_install():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        result = await asyncio.to_thread(
            claude_cli_runtime.install_claude_cli,
            _family_cli_override_path(settings, "claude"),
        )
        await devdb.log_event(conn, "maintenance", "Claude CLI install action requested")
    return result


@app.post("/api/runtime/cli/login")
async def runtime_cli_login(body: ClaudeCliLoginRequest):
    return await _runtime_login_start("claude", RuntimeLoginStartRequest(mode=body.mode, email=body.email))


@app.post("/api/runtime/claude/login/start")
async def runtime_claude_login_start(body: RuntimeLoginStartRequest | None = None):
    return await _runtime_login_start("claude", body)


@app.get("/api/runtime/claude/login/{session_id}")
async def runtime_claude_login_status(session_id: str):
    return await _runtime_login_refresh("claude", session_id)


@app.post("/api/runtime/claude/login/{session_id}/cancel")
async def runtime_claude_login_cancel(session_id: str):
    return await _runtime_login_cancel("claude", session_id)


@app.post("/api/runtime/cli/logout")
async def runtime_cli_logout():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        result = await asyncio.to_thread(
            claude_cli_runtime.logout_claude_cli,
            _family_cli_override_path(settings, "claude"),
        )
        await devdb.log_event(conn, "maintenance", "Claude CLI sign-out requested")
    return result


@app.get("/api/runtime/codex/status")
async def runtime_codex_status():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
    return codex_cli_runtime.build_codex_runtime_snapshot(_family_cli_override_path(settings, "codex"))


@app.post("/api/runtime/codex/install")
async def runtime_codex_install():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        result = await asyncio.to_thread(
            codex_cli_runtime.install_codex_cli,
            _family_cli_override_path(settings, "codex"),
        )
        await devdb.log_event(conn, "maintenance", "Codex CLI install action requested")
    return result


@app.post("/api/runtime/codex/login")
async def runtime_codex_login():
    return await _runtime_login_start("codex")


@app.post("/api/runtime/codex/login/start")
async def runtime_codex_login_start(body: RuntimeLoginStartRequest | None = None):
    return await _runtime_login_start("codex", body)


@app.get("/api/runtime/codex/login/{session_id}")
async def runtime_codex_login_status(session_id: str):
    return await _runtime_login_refresh("codex", session_id)


@app.post("/api/runtime/codex/login/{session_id}/cancel")
async def runtime_codex_login_cancel(session_id: str):
    return await _runtime_login_cancel("codex", session_id)


@app.post("/api/runtime/codex/logout")
async def runtime_codex_logout():
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        result = await asyncio.to_thread(
            codex_cli_runtime.logout_codex_cli,
            _family_cli_override_path(settings, "codex"),
        )
        await devdb.log_event(conn, "maintenance", "Codex CLI sign-out requested")
    return result


@app.get("/api/server/logs")
async def server_logs(tail: int = 200):
    line_limit = max(20, min(int(tail), 2000))
    if not DEVBRAIN_LOG.exists():
        return {"path": str(DEVBRAIN_LOG), "lines": [], "text": "", "available": False}

    from collections import deque

    try:
        with DEVBRAIN_LOG.open("r", encoding="utf-8", errors="replace") as handle:
            lines = list(deque((line.rstrip("\n") for line in handle), maxlen=line_limit))
    except Exception as exc:
        raise HTTPException(500, f"Unable to read server log: {exc}")

    return {
        "path": str(DEVBRAIN_LOG),
        "lines": lines,
        "text": "\n".join(lines),
        "available": True,
    }


async def _build_live_snapshot() -> dict:
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        terminal_rows = await devdb.list_terminal_sessions(conn, limit=6)
        activity_rows = await devdb.get_activity(conn, limit=6)
    auto_rows = auto_session_service.list_auto_sessions()
    running_session_id = next((row["id"] for row in terminal_rows if row["id"] in _terminal_processes), None)
    connection = _connection_snapshot()
    return {
        "type": "snapshot",
        "at": _now_iso(),
        "connection": connection,
        "operator": dict(_live_operator_snapshot),
        "runtime": {
            "runtime_label": (
                "Local Ollama" if settings.get("ai_backend", "api") == "ollama"
                else "External API" if settings.get("ai_backend") == "api"
                else "CLI Agent" if settings.get("ai_backend") == "cli"
                else "Runtime offline"
            ),
            "active_model": (
                settings.get("api_model") or provider_registry.runtime_api_config(settings).get("api_model", "deepseek-reasoner")
            ) if settings.get("ai_backend") == "api" else (
                (_selected_cli_model(settings) or "CLI default") if settings.get("ai_backend") == "cli"
                else settings.get("code_model") or settings.get("ollama_model") or settings.get("general_model") or "Saved default"
            ),
        },
        "terminal": {
            "active_session_id": running_session_id,
            "sessions": [
                _serialize_terminal_session(row, running=row["id"] in _terminal_processes)
                for row in terminal_rows
            ],
        },
        "auto_sessions": [
            item for item in (_auto_session_summary(row) for row in auto_rows[:12]) if item
        ],
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
    session = _normalize_browser_session(
        _browser_action_state["session"],
        connected=body.connected,
        url=str(body.url or "").strip() if body.url is not None else None,
        title=str(body.title or "").strip() if body.title is not None else None,
        mode=body.mode,
        control_owner=body.control_owner,
        control_state=body.control_state,
        attached_preview_url=body.attached_preview_url,
        attached_preview_status=body.attached_preview_status,
        attached_workspace_id=body.attached_workspace_id,
        attached_workspace_name=body.attached_workspace_name,
        attached_auto_session_id=body.attached_auto_session_id,
        attached_scope_key=body.attached_scope_key,
        attached_source_workspace_path=body.attached_source_workspace_path,
        last_seen_at=_now_iso(),
    )
    _browser_action_state["session"] = session
    return _serialize_browser_action_state()


@app.post("/api/browser/actions/propose")
async def create_browser_action_proposal(body: BrowserActionProposalCreate):
    created_at = _now_iso()
    proposal = _normalize_browser_action_payload(
        {
            "id": _next_browser_action_id(),
            "action_type": body.action_type,
            "summary": body.summary,
            "target": body.target,
            "value": body.value,
            "url": body.url,
            "risk": body.risk,
            "scope": body.scope,
            "requires_confirmation": bool(body.requires_confirmation if body.requires_confirmation is not None else True),
            "metadata": body.metadata or {},
            "status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
        }
    )
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
    """Replay an approved browser action, or a read-only inspect action in inspect_auto mode."""
    try:
        import browser_bridge
        bridge = browser_bridge.get_bridge()
        if not bridge.is_running:
            raise HTTPException(400, "Browser bridge is not running. Start it first.")
        body = await request.json()

        proposal_id = int(body.get("proposal_id") or body.get("id") or 0)
        approved_action = _find_approved_browser_action(proposal_id) if proposal_id else None
        if approved_action:
            execution_target = _normalize_browser_action_payload(approved_action)
        else:
            execution_target = _normalize_browser_action_payload(body)
            session_mode = str(_browser_action_state["session"].get("mode") or "approval_required")
            if session_mode != "inspect_auto" or str(execution_target.get("action_type")) not in _BROWSER_DIRECT_READ_ONLY_TYPES:
                raise HTTPException(
                    403,
                    "Direct browser execution is limited to read-only inspect actions in inspect_auto mode. "
                    "Approve a proposal first for browser mutations.",
                )

        result = await bridge.execute_action(execution_target)
        if approved_action is not None:
            approved_action["execution_result"] = result
            approved_action["executed_at"] = _now_iso()
            approved_action["updated_at"] = approved_action["executed_at"]
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
                execution_result = await bridge.execute_action(_normalize_browser_action_payload(updated))
                updated["execution_result"] = execution_result
                updated["executed_at"] = _now_iso()
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

    def _placeholder_png(status: str, message: str) -> Response:
        image = Image.new("RGB", (width, height), color=(11, 15, 25))
        draw = ImageDraw.Draw(image)
        accent = (245, 158, 11)
        text = (226, 232, 240)
        muted = (148, 163, 184)
        draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24, outline=(51, 65, 85), width=2, fill=(15, 23, 42))
        draw.text((48, 44), "Axon Desktop Preview Unavailable", fill=accent)
        draw.text((48, 76), f"Status: {status}", fill=text)
        body = textwrap.fill(message.strip() or "Desktop preview is unavailable in the current environment.", width=56)
        draw.multiline_text((48, 116), body, fill=muted, spacing=6)
        draw.text((48, height - 56), f"Display: {display or 'not set'}", fill=(100, 116, 139))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Response(
            content=buf.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "X-Axon-Preview-Status": status,
            },
        )

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
        return _placeholder_png(
            "no_display",
            "No display server or supported capture tool is available. Set DISPLAY or install a supported desktop capture backend.",
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

    return _placeholder_png(
        "capture_failed",
        f"All desktop capture strategies failed. Last error: {last_error[:220]}",
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
    row = dict(session_row) if session_row is not None else {}
    session_cwd = str(row.get("cwd") or "").strip()
    if session_cwd:
        return _safe_path(session_cwd)
    workspace_id = row.get("workspace_id")
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
        env=local_tool_env.build_tool_env(os.environ.copy()),
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
            content=(
                f"Session ready in {cwd}. "
                f"Installs stay inside Axon at {local_tool_env.install_scope_label()}."
            ),
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


@app.patch("/api/terminal/sessions/{session_id}")
async def patch_terminal_session(session_id: int, request: Request):
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    async with devdb.get_db() as conn:
        row = await devdb.get_terminal_session(conn, session_id)
        if not row:
            raise HTTPException(404, "Terminal session not found")
        await devdb.update_terminal_session(conn, session_id, title=title)
    return {"ok": True, "title": title}


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
    pty_key = str(session_id)
    pty_info = _pty_sessions.get(pty_key) or _pty_sessions.get(session_id)
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
        _pty_sessions.pop(pty_key, None)
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
    _pty_sessions[session_id] = entry

    def _pty_write_input(raw):
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
                    _pty_write_input(parsed.get("data", ""))
            except _json.JSONDecodeError:
                # Plain text input (keystroke)
                _pty_write_input(msg)
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
        chat = [dict(r) for r in await _load_chat_history_rows(conn, limit=10000, degrade_to_empty=True)]

    # Strip sensitive settings
    for key in ("auth_pin_hash", "vault_key_hash"):
        settings.pop(key, None)

    snapshot = {
        "version": 1,
        "exported_at": _now_iso(),
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


# ─── Agent command approval ────────────────────────────────────────────────────

class ApproveActionBody(BaseModel):
    action: dict = {}
    scope: str = "once"
    session_id: str = ""


def _normalize_exact_approval_action(action: dict, *, workspace_root: str = "") -> dict:
    raw = dict(action or {})
    action_type = str(raw.get("action_type") or "").strip().lower()
    workspace_id = raw.get("workspace_id")
    session_id = str(raw.get("session_id") or "").strip()
    if action_type.startswith("file_"):
        operation = str(raw.get("operation") or action_type.removeprefix("file_") or "edit").strip().lower()
        path = str(raw.get("path") or "").strip()
        if not path:
            return {}
        return build_edit_approval_action(
            operation,
            path,
            workspace_id=workspace_id,
            session_id=session_id,
            workspace_root=workspace_root,
        )
    command_preview = str(raw.get("command_preview") or raw.get("full_command") or raw.get("command") or "").strip()
    if command_preview:
        return build_command_approval_action(
            command_preview,
            cwd=str(raw.get("repo_root") or ""),
            workspace_id=workspace_id,
            session_id=session_id,
        )
    return {}


async def _approval_workspace_root(workspace_id: object) -> str:
    try:
        workspace_int = int(workspace_id)
    except Exception:
        return ""
    if workspace_int <= 0:
        return ""
    async with devdb.get_db() as conn:
        project = await devdb.get_project(conn, workspace_int)
    if not project:
        return ""
    if isinstance(project, dict):
        return str(project.get("path") or "").strip()
    try:
        return str(project["path"] or "").strip()
    except Exception:
        return str(getattr(project, "path", "") or "").strip()


@app.post("/api/agent/approve-action")
async def approve_agent_action(body: ApproveActionBody):
    action = dict(body.action or {})
    scope = str(body.scope or "once").strip().lower()
    if scope not in {"once", "task", "session", "persist"}:
        raise HTTPException(400, "Invalid approval scope")
    if not action.get("action_fingerprint"):
        raise HTTPException(400, "approval action fingerprint is required")
    workspace_root = await _approval_workspace_root(action.get("workspace_id"))
    canonical_action = _normalize_exact_approval_action(action, workspace_root=workspace_root)
    if not canonical_action:
        raise HTTPException(400, "approval action could not be validated")
    if canonical_action.get("action_fingerprint") != action.get("action_fingerprint"):
        raise HTTPException(400, "approval action fingerprint mismatch")
    action = canonical_action
    if scope == "persist" and (bool(action.get("destructive")) or not bool(action.get("persist_allowed", False))):
        raise HTTPException(400, "This action cannot be persisted")
    brain.agent_allow_action(action, scope=scope, session_id=body.session_id or str(action.get("session_id") or ""))
    return {"ok": True, "scope": scope, "action": action, "state": brain.agent_get_action_state()}


class AllowCommandBody(BaseModel):
    command: str = ""          # specific command name to allow (e.g. "pgrep")
    allow_all: bool = False    # allow ALL commands (no filter)
    persist: bool = False      # also save to settings for future sessions


@app.post("/api/agent/allow-command")
async def allow_agent_command(body: AllowCommandBody):
    raise HTTPException(410, "Broad command grants are disabled. Use /api/agent/approve-action for the exact blocked action.")


@app.get("/api/agent/sessions/interrupted")
async def get_interrupted_session(project_id: Optional[int] = None):
    """Return the most-recent interrupted/active agent session (for resume banner)."""
    from axon_core.session_store import SessionStore
    ss = SessionStore(devdb.DB_PATH)
    workspace_path = ""
    project_name = None
    if project_id:
        async with devdb.get_db() as conn:
            proj = await devdb.get_project(conn, project_id)
            if proj:
                project_name = proj["name"]
                workspace_path = proj["path"] or ""
    session = ss.get_interrupted(
        workspace_id=project_id,
        workspace_path=workspace_path,
        project_name=project_name,
        strict_workspace=project_id is not None,
    )   # prefer current workspace first; stale sessions are hidden
    if not session:
        return {"session": None}

    last_assistant_message = ""
    for message in reversed(session.messages or []):
        if str(message.get("role") or "") != "assistant":
            continue
        candidate = str(message.get("content") or "").strip()
        if candidate:
            last_assistant_message = candidate
            break

    metadata = dict(session.metadata or {})
    return {
        "session": {
            "session_id": session.session_id,
            "resume_target": session.session_id,
            "resume_reason": str(metadata.get("resume_reason") or session.status or "resume"),
            "task": session.task,
            "iteration": session.iteration,
            "status": session.status,
            "age_seconds": session.age_seconds(),
            "summary": session.summary(),
            "tool_count": len(session.tool_log),
            "project_name": session.project_name,
            "workspace_id": metadata.get("workspace_id"),
            "workspace_path": str(metadata.get("workspace_path") or "").strip(),
            "backend": session.backend,
            "updated_at": session.updated_at,
            "last_assistant_message": last_assistant_message,
            "error_message": str(metadata.get("error_message") or "").strip(),
            "approval": metadata if session.status == "approval_required" else None,
        }
    }



class AllowEditBody(BaseModel):
    path: str = ""
    scope: str = "file"   # "file" | "repo" | "session"


@app.post("/api/agent/allow-edit")
async def allow_agent_edit(body: AllowEditBody):
    raise HTTPException(410, "Broad edit grants are disabled. Use /api/agent/approve-action for the exact blocked action.")


@app.post("/api/agent/steer")
async def steer_agent(body: dict):
    """Send guidance to the matching running agent session/workspace."""
    message = (body.get("message") or "").strip()
    if not message:
        return {"ok": False, "detail": "Empty steer message"}
    session_id = str(body.get("session_id") or "").strip()
    workspace_id = body.get("project_id")
    if workspace_id in ("", None):
        workspace_id = body.get("workspace_id")
    queued = agent_runtime_state.enqueue_steer_message(
        message,
        session_id=session_id,
        workspace_id=workspace_id,
    )
    return {"ok": True, "queued": queued, "session_id": session_id, "workspace_id": workspace_id}


@app.get("/api/agent/allowed-commands")
async def get_allowed_commands():
    """Return the current command approval state."""
    return {
        "deprecated": True,
        "detail": "Broad command grants are disabled. Use structured exact-action approvals instead.",
        "base": sorted(brain._ALLOWED_CMDS),
        "session": brain.agent_get_session_allowed(),
        "allow_all": False,
        "persistent_extra": [],
        "actions": brain.agent_get_action_state(),
    }


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
                with managed_connection(devdb.DB_PATH, row_factory=_sqlite3.Row) as conn:
                    rows = conn.execute("SELECT key, value FROM settings").fetchall()
                    settings = {r["key"]: r["value"] for r in rows}
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
    return ui_renderer.render_manifest()


@app.get("/styles.css")
async def serve_styles():
    return ui_renderer.render_styles(UI_DIR)

@app.get("/js/{filename:path}")
async def serve_js(filename: str):
    return ui_renderer.render_js(UI_DIR, filename)

@app.get("/icons/{filename}")
async def serve_icon(filename: str):
    """Serve PWA icon PNG files."""
    return ui_renderer.render_icon(UI_DIR, filename)


@app.get("/sw.js")
async def service_worker():
    """Service worker — PWA install support."""
    return ui_renderer.render_service_worker(_SW_CACHE_VERSION)


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",   # bind all interfaces — enables Tailscale + LAN access
        port=PORT,
        reload=False,
        log_level="warning",
    )
