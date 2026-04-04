"""Shared companion request auth helpers for mobile-facing routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from axon_api.services import companion_auth as companion_auth_service
from axon_data import get_companion_device, get_db


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (
        request.headers.get("X-Axon-Token")
        or request.headers.get("X-DevBrain-Token")
        or request.headers.get("X-Session-Token")
        or request.query_params.get("token")
        or ""
    ).strip()


def expires_at_passed(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return expiry <= datetime.now(timezone.utc)


async def companion_auth_context(request: Request) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    token = token_from_request(request)
    if not token:
        return "", None, None
    async with get_db() as db:
        auth_row = await companion_auth_service.resolve_companion_auth_session(db, access_token=token)
        if not auth_row or expires_at_passed(str(auth_row.get("expires_at") or "")):
            return token, None, None
        device_row = await get_companion_device(db, int(auth_row["device_id"]))
    return token, dict(auth_row), row_dict(device_row) if device_row else None


async def require_companion_context(request: Request) -> tuple[str, dict[str, Any], dict[str, Any]]:
    token, auth_row, device_row = await companion_auth_context(request)
    if not token or not auth_row or not device_row:
        raise HTTPException(401, "Companion auth token required")
    return token, auth_row, device_row
