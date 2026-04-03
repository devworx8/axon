from __future__ import annotations

import aiosqlite


async def log_companion_voice_turn(
    db: aiosqlite.Connection,
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
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO companion_voice_turns (
            session_id, workspace_id, role, content, transcript, response_text,
            provider, voice_mode, language, audio_format, duration_ms, tokens_used,
            status, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            workspace_id,
            role,
            content,
            transcript,
            response_text,
            provider,
            voice_mode,
            language,
            audio_format,
            duration_ms,
            tokens_used,
            status,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    return int(cur.lastrowid)


async def get_companion_voice_turn(db: aiosqlite.Connection, turn_id: int):
    cur = await db.execute("SELECT * FROM companion_voice_turns WHERE id = ?", (turn_id,))
    return await cur.fetchone()


async def list_companion_voice_turns(
    db: aiosqlite.Connection,
    *,
    session_id: int | None = None,
    workspace_id: int | None = None,
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM companion_voice_turns
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()

