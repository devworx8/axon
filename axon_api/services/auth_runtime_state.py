"""Authentication session state and middleware helpers extracted from server.py."""
from __future__ import annotations

import logging
import hashlib
import os
import secrets as _secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable


AUTH_SESSIONS: dict[str, datetime] = {}
AUTH_SESSION_HOURS = 72
LOCALHOST_NAMES = {"localhost", "127.0.0.1", "::1"}

LOGIN_ATTEMPTS: dict[str, tuple[int, float]] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300


def env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


LEGACY_DEV_LOCAL_BYPASS = env_flag("AXON_DEV_LOCAL_BYPASS", "1")
DEV_LOCAL_AUTH_BYPASS = env_flag(
    "AXON_DEV_LOCAL_AUTH_BYPASS",
    "1" if LEGACY_DEV_LOCAL_BYPASS else "0",
)
DEV_LOCAL_VAULT_BYPASS = env_flag("AXON_DEV_LOCAL_VAULT_BYPASS", "0")

AUTH_EXEMPT = {"/", "/sw.js", "/manifest.json", "/manual", "/manual.html", "/api/health", "/api/tunnel/status"}
AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/api/companion/auth/", "/icons/", "/js/", "/styles.css", "/ws/")
COMPANION_SAFE_PREFIXES = (
    "/api/companion/",
    "/api/attention/",
    "/api/mobile/",
    "/api/mcp/",
    "/api/voice/",
    "/api/connectors/overview",
    "/api/connectors/workspaces/",
)


def extract_session_token(request) -> str:
    return (
        request.headers.get("X-Axon-Token")
        or request.headers.get("X-DevBrain-Token")
        or request.headers.get("X-Session-Token")
        or request.query_params.get("token")
        or ""
    )


def extract_bearer_token(request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"devbrain-pin-{pin}".encode()).hexdigest()


def request_is_localhost(request=None, *, localhost_names: set[str] | None = None) -> bool:
    if request is None:
        return False
    names = localhost_names or LOCALHOST_NAMES
    host = str(getattr(request.url, "hostname", "") or "").strip().strip("[]").lower()
    client = str(getattr(getattr(request, "client", None), "host", "") or "").strip().strip("[]").lower()
    return host in names or client in names


def dev_local_auth_bypass_active(
    request=None,
    *,
    request_is_localhost_fn: Callable[[Any], bool] | None = None,
) -> bool:
    checker = request_is_localhost_fn or request_is_localhost
    return DEV_LOCAL_AUTH_BYPASS and checker(request)


def dev_local_vault_bypass_active(
    request=None,
    *,
    request_is_localhost_fn: Callable[[Any], bool] | None = None,
) -> bool:
    checker = request_is_localhost_fn or request_is_localhost
    return DEV_LOCAL_VAULT_BYPASS and checker(request)


def create_session(
    *,
    auth_sessions: dict[str, datetime] | None = None,
    utc_now_fn: Callable[[], datetime],
    session_hours: int = AUTH_SESSION_HOURS,
    token_hex_fn: Callable[[int], str] = _secrets.token_hex,
) -> str:
    sessions = auth_sessions if auth_sessions is not None else AUTH_SESSIONS
    token = token_hex_fn(32)
    sessions[token] = utc_now_fn() + timedelta(hours=session_hours)
    now = utc_now_fn()
    expired = [token_key for token_key, expires_at in sessions.items() if expires_at < now]
    for token_key in expired:
        del sessions[token_key]
    return token


def valid_session(
    token: str,
    *,
    auth_sessions: dict[str, datetime] | None = None,
    utc_now_fn: Callable[[], datetime],
) -> bool:
    sessions = auth_sessions if auth_sessions is not None else AUTH_SESSIONS
    expires_at = sessions.get(token)
    if not expires_at:
        return False
    if utc_now_fn() > expires_at:
        del sessions[token]
        return False
    return True


async def valid_session_async(
    token: str,
    *,
    valid_session_fn: Callable[[str], bool],
    db_module: Any,
    resolve_companion_auth_session: Callable[..., Awaitable[dict | None]],
    utc_now_fn: Callable[[], datetime],
    datetime_cls,
) -> bool:
    if valid_session_fn(token):
        return True
    if not token:
        return False
    try:
        async with db_module.get_db() as conn:
            companion_session = await resolve_companion_auth_session(
                conn,
                access_token=token,
            )
        if not companion_session:
            return False
        if str(companion_session.get("revoked_at") or "").strip():
            return False
        expires_at = str(companion_session.get("expires_at") or "").strip()
        if expires_at:
            expires = datetime_cls.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = utc_now_fn()
            if expires.tzinfo is not None and getattr(now, "tzinfo", None) is None:
                now = now.replace(tzinfo=timezone.utc)
            elif expires.tzinfo is None and getattr(now, "tzinfo", None) is not None:
                expires = expires.replace(tzinfo=now.tzinfo)
            if now > expires:
                return False
        return True
    except Exception:
        logging.getLogger(__name__).warning("Session validation failed", exc_info=True)
        return False


async def auth_middleware(
    request,
    call_next,
    *,
    auth_exempt: set[str] | None = None,
    auth_exempt_prefixes: tuple[str, ...] | None = None,
    dev_local_auth_bypass_active_fn: Callable[[Any], bool],
    db_module: Any,
    extract_session_token_fn: Callable[[Any], str],
    valid_session_async_fn: Callable[[str], Awaitable[bool]],
    json_response_cls,
):
    path = request.url.path
    exempt = auth_exempt if auth_exempt is not None else AUTH_EXEMPT
    exempt_prefixes = auth_exempt_prefixes if auth_exempt_prefixes is not None else AUTH_EXEMPT_PREFIXES

    if str(getattr(request, "method", "") or "").upper() == "OPTIONS":
        return await call_next(request)

    if path in exempt or path.startswith(exempt_prefixes):
        return await call_next(request)

    async with db_module.get_db() as conn:
        pin_hash = await db_module.get_setting(conn, "auth_pin_hash")

    if not pin_hash and dev_local_auth_bypass_active_fn(request):
        return await call_next(request)

    if not pin_hash:
        return await call_next(request)

    token = extract_session_token_fn(request)
    if not token and path.startswith(COMPANION_SAFE_PREFIXES):
        token = extract_bearer_token(request)
    if not token or not await valid_session_async_fn(token):
        return json_response_cls({"detail": "Authentication required"}, status_code=401)

    return await call_next(request)
