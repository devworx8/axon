"""Local voice configuration/status helpers extracted from server.py."""
from __future__ import annotations

from typing import Optional


def local_voice_paths(settings: Optional[dict] = None, *, read_settings_sync, os_module) -> dict:
    settings = settings or read_settings_sync()
    return {
        "piper_model_path": str(settings.get("local_tts_model_path") or os_module.environ.get("AXON_PIPER_MODEL_PATH") or "").strip(),
        "piper_config_path": str(settings.get("local_tts_config_path") or os_module.environ.get("AXON_PIPER_CONFIG_PATH") or "").strip(),
        "stt_model": str(settings.get("local_stt_model") or os_module.environ.get("AXON_WHISPER_MODEL") or "base").strip() or "base",
        "language": str(settings.get("local_stt_language") or os_module.environ.get("AXON_WHISPER_LANGUAGE") or "en").strip() or "en",
    }


def local_voice_status(
    settings: Optional[dict] = None,
    *,
    read_settings_sync,
    local_voice_paths_fn,
    resolve_ffmpeg_path_fn,
    piper_python_available_fn,
    python_module_available_fn,
    local_voice_state: dict,
    shutil_module,
    pathlib_path_cls,
) -> dict:
    settings = settings or read_settings_sync()
    paths = local_voice_paths_fn(settings)
    ffmpeg_path = resolve_ffmpeg_path_fn()
    piper_path = shutil_module.which("piper") or ""
    piper_python_available = piper_python_available_fn()
    faster_whisper_available = python_module_available_fn("faster_whisper")
    whisper_available = python_module_available_fn("whisper")
    piper_model_ready = bool(paths["piper_model_path"] and pathlib_path_cls(paths["piper_model_path"]).exists())
    piper_config_ready = bool(not paths["piper_config_path"] or pathlib_path_cls(paths["piper_config_path"]).exists())
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
        "state": dict(local_voice_state),
    }
