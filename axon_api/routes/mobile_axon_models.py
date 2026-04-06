"""Request models for Axon mode mobile routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MobileAxonArmRequest(BaseModel):
    session_id: int | None = None
    workspace_id: int | None = None
    wake_phrase: str = "Axon"
    boot_sound_enabled: bool = True
    spoken_reply_enabled: bool = True
    continuous_monitoring_enabled: bool = True
    voice_provider_preference: str = "cloud"
    voice_identity_preference: str = ""
    active_route: str = "/voice"
    app_state: str = "foreground"
    meta: dict[str, Any] | None = Field(default=None)


class MobileAxonDisarmRequest(BaseModel):
    session_id: int | None = None
    workspace_id: int | None = None
    active_route: str = "/voice"
    app_state: str = "foreground"


class MobileAxonEventRequest(BaseModel):
    event_type: str
    session_id: int | None = None
    workspace_id: int | None = None
    monitoring_state: str = ""
    wake_phrase: str = ""
    transcript: str = ""
    command_text: str = ""
    error: str = ""
    active_route: str = "/voice"
    app_state: str = ""
    meta: dict[str, Any] | None = Field(default=None)


class MobileAxonSpeakRequest(BaseModel):
    text: str
    preferred_provider: str = ""
    voice_identity: str = ""


class MobileVoiceSettingsRequest(BaseModel):
    settings: dict[str, str | None] = Field(default_factory=dict)
