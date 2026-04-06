"""Shared voice-rate and pitch normalization helpers."""

from __future__ import annotations

from typing import Any

DEFAULT_VOICE_RATE = 0.85
DEFAULT_VOICE_PITCH = 1.04


def _normalized_voice_scalar(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("%"):
            try:
                value = 1.0 + (float(raw[:-1]) / 100.0)
            except ValueError:
                value = default
        else:
            value = raw or default
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        scalar = default
    return max(minimum, min(maximum, scalar))


def normalized_voice_rate(value: Any) -> float:
    return _normalized_voice_scalar(value, DEFAULT_VOICE_RATE, minimum=0.50, maximum=1.15)


def normalized_voice_pitch(value: Any) -> float:
    return _normalized_voice_scalar(value, DEFAULT_VOICE_PITCH, minimum=0.50, maximum=1.50)


def azure_voice_rate_attr(value: Any) -> str:
    rate = normalized_voice_rate(value)
    delta = int(round((rate - 1.0) * 100))
    return f"{delta:+d}%"


def azure_voice_pitch_attr(value: Any) -> str:
    pitch = normalized_voice_pitch(value)
    delta = int(round((pitch - 1.0) * 100))
    return f"{delta:+d}%"
