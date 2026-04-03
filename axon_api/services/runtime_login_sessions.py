"""Guided CLI runtime login sessions for Claude and Codex."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time as _time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axon_api.services import claude_cli_runtime, codex_cli_runtime

SESSION_ROOT = Path.home() / ".devbrain" / "runtime_login_sessions"
SESSION_META = ".axon-runtime-login.json"

_LOGIN_URL_RE = re.compile(r"https?://[^\s<>()\"']+")
_DEVICE_CODE_RE = re.compile(
    r"(?:code|device code|enter code)\s*[:#-]?\s*([A-Z0-9]{4}(?:[- ][A-Z0-9]{4,8})+)",
    re.IGNORECASE,
)
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_CODEX_LOGIN_URL = "https://auth.openai.com/log-in"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str, max_len: int = 48) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return (text or "login")[:max_len].strip("-") or "login"


def _session_dir(family: str, session_id: str) -> Path:
    return SESSION_ROOT / f"{_slugify(family)}-{_slugify(session_id, 24)}"


def _session_meta_path(family: str, session_id: str) -> Path:
    return _session_dir(family, session_id) / SESSION_META


def _session_log_path(target_dir: Path) -> Path:
    return target_dir / "login.log"


def _clean_env() -> dict[str, str]:
    env = {**os.environ, "NO_COLOR": "1"}
    env.setdefault("BROWSER", "none")
    return env


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _stop_process(meta: dict[str, Any]) -> None:
    pid = int(meta.get("pid") or 0)
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def _tail(path: str, limit: int = 8000) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-limit:] if len(text) > limit else text


def _clean_terminal_text(text: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", str(text or ""))
    return _CONTROL_CHAR_RE.sub("", cleaned)


def _family_snapshot(family: str, override_path: str = "") -> dict[str, Any]:
    family_name = str(family or "").strip().lower()
    if family_name == "claude":
        return claude_cli_runtime.build_cli_runtime_snapshot(override_path)
    if family_name == "codex":
        return codex_cli_runtime.build_codex_runtime_snapshot(override_path)
    raise ValueError(f"Unsupported runtime login family: {family}")


def _family_login_command(
    family: str,
    snapshot: dict[str, Any],
    *,
    mode: str = "claudeai",
    email: str = "",
) -> list[str]:
    binary = str(snapshot.get("binary") or ("claude" if family == "claude" else "codex"))
    if family == "claude":
        parts = [binary, "auth", "login"]
        parts.append("--console" if str(mode or "").strip().lower() == "console" else "--claudeai")
        email = str(email or "").strip()
        if email:
            parts.extend(["--email", email])
        return parts
    if family == "codex":
        return [binary, "login", "--device-auth"]
    raise ValueError(f"Unsupported runtime login family: {family}")


def _normalize_browser_url(url: str, *, family: str = "") -> str:
    cleaned = _clean_terminal_text(url).strip().rstrip(").,")
    if family == "codex" and ("auth.openai.com" in cleaned or not cleaned):
        return _CODEX_LOGIN_URL
    return cleaned


def _extract_browser_url(text: str, *, family: str = "") -> str:
    for match in _LOGIN_URL_RE.findall(_clean_terminal_text(text)):
        url = _normalize_browser_url(match, family=family)
        if "localhost:7734" in url:
            continue
        return url
    if family == "codex":
        return _CODEX_LOGIN_URL
    return ""


def _extract_user_code(text: str) -> str:
    match = _DEVICE_CODE_RE.search(_clean_terminal_text(text))
    if not match:
        return ""
    return match.group(1).strip().replace(" ", "-").upper()


def _status_from_meta(meta: dict[str, Any], snapshot: dict[str, Any], log_tail: str) -> dict[str, Any]:
    auth = dict(snapshot.get("auth") or {})
    family = str(meta.get("family") or "").strip().lower()
    pid = int(meta.get("pid") or 0) or None
    alive = _pid_alive(pid)
    browser_url = _extract_browser_url(log_tail, family=family) or _normalize_browser_url(
        str(meta.get("browser_url") or ""),
        family=family,
    )
    user_code = _extract_user_code(log_tail) or str(meta.get("user_code") or "")
    last_message = str(auth.get("message") or "").strip()
    status = str(meta.get("status") or "pending")
    return_code = meta.get("returncode")

    if auth.get("logged_in"):
        status = "authenticated"
        last_message = last_message or "Authenticated"
        if alive:
            _stop_process(meta)
            alive = False
    elif status == "cancelled":
        last_message = last_message or "Login cancelled."
    elif alive:
        status = "browser_opened" if browser_url else "waiting"
        last_message = last_message or ("Browser opened. Finish sign-in to continue." if browser_url else "Waiting for sign-in to complete.")
    elif browser_url or user_code:
        status = "waiting"
        last_message = last_message or "Continue sign-in in the browser, then refresh or wait for Axon to detect completion."
    elif return_code not in (None, 0):
        status = "failed"
        last_message = log_tail.splitlines()[-1][:300] if log_tail.splitlines() else "Runtime login failed."
    elif not auth.get("logged_in") and str(meta.get("started_at") or ""):
        status = "waiting"
        last_message = last_message or "Waiting for the runtime to finish the sign-in flow."

    refreshed = {
        **meta,
        "browser_url": browser_url,
        "user_code": user_code,
        "status": status,
        "auth_snapshot": auth,
        "log_tail": log_tail,
        "process_alive": alive,
        "message": last_message,
        "updated_at": _now_iso(),
    }
    if status == "authenticated" and not refreshed.get("completed_at"):
        refreshed["completed_at"] = _now_iso()
    return refreshed


def read_login_session(family: str, session_id: str) -> dict[str, Any] | None:
    path = _session_meta_path(family, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_login_session(meta: dict[str, Any]) -> dict[str, Any]:
    family = str(meta.get("family") or "").strip().lower()
    session_id = str(meta.get("session_id") or "").strip()
    if not family or not session_id:
        raise ValueError("Runtime login session requires family and session_id.")
    target_dir = _session_dir(family, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    meta["session_dir"] = str(target_dir)
    meta["updated_at"] = _now_iso()
    (_session_meta_path(family, session_id)).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def refresh_login_session(family: str, session_id: str) -> dict[str, Any] | None:
    meta = read_login_session(family, session_id)
    if not meta:
        return None
    pid = int(meta.get("pid") or 0) or None
    if pid and not _pid_alive(pid) and meta.get("returncode") is None:
        try:
            _, status = os.waitpid(pid, os.WNOHANG)
            if status:
                meta["returncode"] = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            meta["returncode"] = meta.get("returncode") if meta.get("returncode") is not None else 0
        except Exception:
            pass
    log_tail = _tail(str(meta.get("log_path") or ""))
    snapshot = _family_snapshot(family, str(meta.get("binary") or ""))
    refreshed = _status_from_meta(meta, snapshot, log_tail)
    return write_login_session(refreshed)


def list_login_sessions(family: str) -> list[dict[str, Any]]:
    root = SESSION_ROOT
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    prefix = f"{_slugify(family)}-"
    for meta_path in sorted(root.glob(f"{prefix}*/{SESSION_META}"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(meta)
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return rows


def find_active_login_session(family: str) -> dict[str, Any] | None:
    for session in list_login_sessions(family):
        status = str(session.get("status") or "")
        if status in {"pending", "browser_opened", "waiting"}:
            return refresh_login_session(family, str(session.get("session_id") or "")) or session
    return None


def start_login_session(
    family: str,
    *,
    override_path: str = "",
    mode: str = "claudeai",
    email: str = "",
) -> dict[str, Any]:
    family_name = str(family or "").strip().lower()
    active = find_active_login_session(family_name)
    if active:
        return active

    snapshot = _family_snapshot(family_name, override_path)
    auth = dict(snapshot.get("auth") or {})
    session_id = f"{int(_time.time() * 1000)}-{family_name}"
    title = f"{family_name} login"
    command_parts = _family_login_command(family_name, snapshot, mode=mode, email=email)
    command_preview = claude_cli_runtime._command_preview(command_parts)

    initial = {
        "session_id": session_id,
        "family": family_name,
        "title": title,
        "binary": str(snapshot.get("binary") or ""),
        "mode": str(mode or ""),
        "email": str(email or ""),
        "command_preview": command_preview,
        "browser_url": _CODEX_LOGIN_URL if family_name == "codex" else "",
        "user_code": "",
        "status": "pending",
        "auth_snapshot": auth,
        "message": str(auth.get("message") or ""),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "started_at": "",
        "completed_at": "",
        "cancelled_at": "",
        "returncode": None,
        "log_path": "",
        "log_tail": "",
        "process_alive": False,
    }

    if auth.get("logged_in"):
        initial["status"] = "authenticated"
        initial["completed_at"] = _now_iso()
        return write_login_session(initial)

    if not snapshot.get("installed"):
        initial["status"] = "failed"
        initial["message"] = "Install the runtime before starting login."
        return write_login_session(initial)

    target_dir = _session_dir(family_name, session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = _session_log_path(target_dir)
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            command_parts,
            cwd=str(Path.home()),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=_clean_env(),
            start_new_session=True,
        )

    initial.update(
        {
            "started_at": _now_iso(),
            "pid": proc.pid,
            "process_alive": True,
            "log_path": str(log_path),
        }
    )
    write_login_session(initial)
    return refresh_login_session(family_name, session_id) or initial


def cancel_login_session(family: str, session_id: str) -> dict[str, Any]:
    meta = read_login_session(family, session_id)
    if not meta:
        raise ValueError("Runtime login session not found.")
    _stop_process(meta)
    meta["status"] = "cancelled"
    meta["cancelled_at"] = _now_iso()
    meta["process_alive"] = False
    return write_login_session(meta)
