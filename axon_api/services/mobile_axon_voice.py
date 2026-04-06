"""Voice-readiness and provider helpers for mobile Axon mode."""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from axon_api.services.local_voice_dependencies import (
    piper_python_available,
    python_module_available,
    resolve_ffmpeg_path,
)
from axon_api.services.local_voice_execution import speak_local_text
from axon_api.services.local_voice_runtime import local_voice_paths, local_voice_status
from axon_data import get_all_settings

DEFAULT_AZURE_VOICE = "en-ZA-LukeNeural"
_PIPER_VOICE_CACHE: dict[str, object] = {}


def _voice_python_module(name: str) -> bool:
    return python_module_available(name, importlib_util_module=importlib.util)


def voice_dependency_snapshot(settings: dict[str, Any]) -> dict[str, Any]:
    return local_voice_status(
        settings,
        read_settings_sync=lambda: settings,
        local_voice_paths_fn=lambda current=None: local_voice_paths(
            current or settings,
            read_settings_sync=lambda: settings,
            os_module=os,
        ),
        resolve_ffmpeg_path_fn=lambda: resolve_ffmpeg_path(
            shutil_module=shutil,
            python_module_available_fn=_voice_python_module,
            pathlib_path_cls=Path,
        ),
        piper_python_available_fn=lambda: piper_python_available(
            python_module_available_fn=_voice_python_module
        ),
        python_module_available_fn=_voice_python_module,
        local_voice_state={},
        shutil_module=shutil,
        pathlib_path_cls=Path,
    )


async def local_voice_snapshot(db) -> dict[str, Any]:
    settings = await get_all_settings(db)
    return voice_dependency_snapshot(dict(settings or {}))


def resolve_axon_voice_profile(
    settings: dict[str, Any],
    voice_status: dict[str, Any],
    *,
    preferred_provider: str = "",
    preferred_voice: str = "",
) -> dict[str, Any]:
    provider_preference = str(preferred_provider or "cloud").strip().lower() or "cloud"
    cloud_ready = bool(settings.get("azure_speech_key") and settings.get("azure_speech_region"))
    local_ready = bool(voice_status.get("synthesis_available"))
    default_voice = str(settings.get("azure_voice") or DEFAULT_AZURE_VOICE).strip() or DEFAULT_AZURE_VOICE
    voice_identity = str(preferred_voice or default_voice).strip() or default_voice

    if provider_preference == "device":
        provider = "device"
    elif provider_preference == "local" and local_ready:
        provider = "local"
    elif provider_preference == "cloud" and cloud_ready:
        provider = "cloud"
    elif cloud_ready:
        provider = "cloud"
    elif local_ready:
        provider = "local"
    elif provider_preference == "device":
        provider = "device"
    else:
        provider = "unavailable"

    if provider == "cloud":
        detail = f"Azure speech ready · {voice_identity}"
    elif provider == "local":
        detail = f"Local synthesis ready · {voice_status.get('piper_engine') or 'piper'}"
    elif provider == "device":
        detail = "Client device speech fallback"
    else:
        detail = str(voice_status.get("detail") or "Speech reply is not ready.")

    return {
        "voice_provider_preference": provider_preference,
        "voice_provider": provider,
        "voice_provider_ready": provider in {"cloud", "local", "device"},
        "voice_identity": voice_identity if provider == "cloud" else (str(voice_status.get("piper_engine") or "local") if provider == "local" else ""),
        "voice_identity_label": voice_identity if provider == "cloud" else ("Local synthesis" if provider == "local" else "Device speech"),
        "voice_provider_detail": detail,
        "cloud_ready": cloud_ready,
        "local_ready": local_ready,
    }


def speak_local_mobile_text(settings: dict[str, Any], text: str) -> tuple[bytes, str]:
    paths = local_voice_paths(
        settings,
        read_settings_sync=lambda: settings,
        os_module=os,
    )
    return speak_local_text(
        text,
        model_path=paths["piper_model_path"],
        config_path=paths["piper_config_path"],
        shutil_module=shutil,
        piper_python_available_fn=lambda: piper_python_available(
            python_module_available_fn=_voice_python_module
        ),
        piper_voice_cache=_PIPER_VOICE_CACHE,
        pathlib_path_cls=Path,
        io_module=io,
        http_exception_cls=HTTPException,
    )
