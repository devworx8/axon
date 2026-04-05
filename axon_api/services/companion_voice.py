"""Companion voice turn helpers."""

from __future__ import annotations

import json
from typing import Any

from axon_data import get_companion_voice_turn, list_companion_voice_turns, log_companion_voice_turn


async def record_companion_voice_turn(
    db,
    *,
    session_id: int,
    workspace_id: int | None = None,
    role: str,
    content: str,
    transcript: str = "",
    response_text: str = "",
    provider: str = "",
    voice_mode: str = "",
    language: str = "",
    audio_format: str = "",
    duration_ms: int = 0,
    tokens_used: int = 0,
    status: str = "recorded",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turn_id = await log_companion_voice_turn(
        db,
        session_id=session_id,
        workspace_id=workspace_id,
        role=role,
        content=content,
        transcript=transcript,
        response_text=response_text,
        provider=provider,
        voice_mode=voice_mode,
        language=language,
        audio_format=audio_format,
        duration_ms=duration_ms,
        tokens_used=tokens_used,
        status=status,
        meta_json="{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    row = await get_companion_voice_turn(db, turn_id)
    return dict(row) if row else {"id": turn_id, "session_id": session_id, "role": role}


async def list_recent_companion_voice_turns(
    db,
    *,
    session_id: int | None = None,
    workspace_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = await list_companion_voice_turns(
        db,
        session_id=session_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    return [dict(row) for row in rows]

