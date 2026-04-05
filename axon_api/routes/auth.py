"""Authentication routes extracted from the legacy server facade."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


class PinSetup(BaseModel):
    pin: str


class PinLogin(BaseModel):
    pin: str


class AuthRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        dev_local_auth_bypass_active: Callable[[Request | None], bool],
        extract_session_token: Callable[[Request], str],
        valid_session_async: Callable[[str], Awaitable[bool]],
        hash_pin: Callable[[str], str],
        create_session: Callable[[], str],
        auth_sessions: dict[str, Any],
        login_attempts: dict[str, tuple[int, float]],
        login_max_attempts: int,
        login_lockout_seconds: int,
        revoke_companion_access_token: Callable[[Any, str], Awaitable[None]],
        revoke_companion_device_id: Callable[[Any, int], Awaitable[None]],
    ) -> None:
        self._db = db_module
        self._dev_local_auth_bypass_active = dev_local_auth_bypass_active
        self._extract_session_token = extract_session_token
        self._valid_session_async = valid_session_async
        self._hash_pin = hash_pin
        self._create_session = create_session
        self._auth_sessions = auth_sessions
        self._login_attempts = login_attempts
        self._login_max_attempts = login_max_attempts
        self._login_lockout_seconds = login_lockout_seconds
        self._revoke_companion_access_token = revoke_companion_access_token
        self._revoke_companion_device_id = revoke_companion_device_id

    async def auth_status(self, request: Request):
        async with self._db.get_db() as conn:
            pin_hash = await self._db.get_setting(conn, "auth_pin_hash")
        if not pin_hash and self._dev_local_auth_bypass_active(request):
            return {
                "auth_enabled": False,
                "session_valid": True,
                "dev_bypass": True,
            }
        token = self._extract_session_token(request)
        return {
            "auth_enabled": bool(pin_hash),
            "session_valid": (not pin_hash) or bool(token and await self._valid_session_async(token)),
            "dev_bypass": False,
        }

    async def auth_setup(self, body: PinSetup):
        pin = body.pin.strip()
        if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
            raise HTTPException(400, "PIN must be 4-6 digits")
        async with self._db.get_db() as conn:
            await self._db.set_setting(conn, "auth_pin_hash", self._hash_pin(pin))
        token = self._create_session()
        return {"status": "ok", "token": token}

    async def auth_login(self, body: PinLogin, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        fails, last_attempt = self._login_attempts.get(client_ip, (0, 0.0))
        if fails >= self._login_max_attempts and (time.time() - last_attempt) < self._login_lockout_seconds:
            retry_after = int(self._login_lockout_seconds - (time.time() - last_attempt))
            raise HTTPException(429, f"Too many failed attempts. Try again in {retry_after}s.")
        async with self._db.get_db() as conn:
            pin_hash = await self._db.get_setting(conn, "auth_pin_hash")
        if not pin_hash:
            raise HTTPException(400, "No PIN set — use /api/auth/setup first")
        if self._hash_pin(body.pin.strip()) != pin_hash:
            self._login_attempts[client_ip] = (fails + 1, time.time())
            raise HTTPException(401, "Wrong PIN")
        self._login_attempts.pop(client_ip, None)
        token = self._create_session()
        return {"status": "ok", "token": token}

    async def auth_logout(self, request: Request):
        token = self._extract_session_token(request)
        if token and token in self._auth_sessions:
            del self._auth_sessions[token]
        elif token:
            async with self._db.get_db() as conn:
                await self._revoke_companion_access_token(conn, token)
        return {"status": "ok"}

    async def auth_remove(self, body: PinLogin):
        async with self._db.get_db() as conn:
            pin_hash = await self._db.get_setting(conn, "auth_pin_hash")
        if not pin_hash:
            return {"status": "ok", "message": "No PIN was set"}
        if self._hash_pin(body.pin.strip()) != pin_hash:
            raise HTTPException(401, "Wrong PIN")
        async with self._db.get_db() as conn:
            await self._db.set_setting(conn, "auth_pin_hash", "")
            rows = await conn.execute("SELECT id FROM companion_devices")
            device_rows = await rows.fetchall()
            for row in device_rows:
                await self._revoke_companion_device_id(conn, int(row["id"]))
        self._auth_sessions.clear()
        return {"status": "ok"}


def build_auth_router(**deps: Any) -> tuple[APIRouter, AuthRouteHandlers]:
    handlers = AuthRouteHandlers(**deps)
    router = APIRouter(tags=["auth"])
    router.add_api_route("/api/auth/status", handlers.auth_status, methods=["GET"])
    router.add_api_route("/api/auth/setup", handlers.auth_setup, methods=["POST"])
    router.add_api_route("/api/auth/login", handlers.auth_login, methods=["POST"])
    router.add_api_route("/api/auth/logout", handlers.auth_logout, methods=["POST"])
    router.add_api_route("/api/auth/remove", handlers.auth_remove, methods=["POST"])
    return router, handlers
