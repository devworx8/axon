"""Request models for the companion API routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CompanionPairRequest(BaseModel):
    device_key: str
    name: str
    pin: str = ""
    user_id: int | None = None
    kind: str = "mobile"
    platform: str = ""
    model: str = ""
    os_version: str = ""
    status: str = "active"
    ttl_seconds: int = 60 * 60 * 24 * 30
    meta: dict[str, Any] | None = Field(default=None)


class CompanionRefreshRequest(BaseModel):
    refresh_token: str
    ttl_seconds: int = 60 * 60 * 24 * 30


class CompanionRevokeRequest(BaseModel):
    device_id: int | None = None
    auth_session_id: int | None = None
    access_token: str = ""
    refresh_token: str = ""


class CompanionDeviceTouchRequest(BaseModel):
    status: str = "active"


class CompanionPresenceRequest(BaseModel):
    device_id: int | None = None
    session_id: int | None = None
    workspace_id: int | None = None
    presence_state: str = "online"
    voice_state: str = "idle"
    app_state: str = "foreground"
    active_route: str = ""
    meta: dict[str, Any] | None = Field(default=None)


class CompanionSessionRequest(BaseModel):
    session_key: str = ""
    device_id: int | None = None
    workspace_id: int | None = None
    agent_session_id: str = ""
    status: str = "active"
    mode: str = "companion"
    current_route: str = ""
    current_view: str = ""
    active_task: str = ""
    summary: str = ""
    meta: dict[str, Any] | None = Field(default=None)


class CompanionSessionResumeRequest(BaseModel):
    agent_session_id: str = ""
    status: str = "active"


class CompanionSessionTouchRequest(BaseModel):
    current_route: str | None = None
    current_view: str | None = None
    active_task: str | None = None
    summary: str | None = None


class CompanionVoiceTurnRequest(BaseModel):
    session_id: int | None = None
    workspace_id: int | None = None
    role: str = "user"
    content: str
    transcript: str = ""
    response_text: str = ""
    provider: str = ""
    voice_mode: str = ""
    language: str = ""
    audio_format: str = ""
    duration_ms: int = 0
    tokens_used: int = 0
    status: str = "recorded"
    meta: dict[str, Any] | None = Field(default=None)


class CompanionPushSubscriptionRequest(BaseModel):
    device_id: int | None = None
    endpoint: str
    provider: str = "webpush"
    auth: dict[str, Any] | None = Field(default=None)
    p256dh: str = ""
    expiration_at: str | None = None
    status: str = "active"
    meta: dict[str, Any] | None = Field(default=None)
