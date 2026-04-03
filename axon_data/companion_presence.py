from __future__ import annotations

import aiosqlite


async def upsert_companion_presence(
    db: aiosqlite.Connection,
    *,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
    presence_state: str = "online",
    voice_state: str = "idle",
    app_state: str = "foreground",
    active_route: str = "",
    meta_json: str = "{}",
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO companion_presence (
            device_id, session_id, workspace_id, presence_state, voice_state,
            app_state, active_route, last_seen_at, meta_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, datetime('now'))
        ON CONFLICT(device_id) DO UPDATE SET
            session_id = excluded.session_id,
            workspace_id = excluded.workspace_id,
            presence_state = excluded.presence_state,
            voice_state = excluded.voice_state,
            app_state = excluded.app_state,
            active_route = excluded.active_route,
            last_seen_at = datetime('now'),
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            device_id,
            session_id,
            workspace_id,
            presence_state,
            voice_state,
            app_state,
            active_route,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT * FROM companion_presence WHERE device_id = ?", (device_id,))
    return await cur.fetchone()


async def get_companion_presence(db: aiosqlite.Connection, device_id: int):
    cur = await db.execute("SELECT * FROM companion_presence WHERE device_id = ?", (device_id,))
    return await cur.fetchone()


async def list_companion_presence(db: aiosqlite.Connection, *, workspace_id: int | None = None, limit: int = 100):
    clauses = []
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT * FROM companion_presence
        {where}
        ORDER BY COALESCE(last_seen_at, updated_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def clear_companion_presence(db: aiosqlite.Connection, device_id: int, *, commit: bool = True):
    await db.execute("DELETE FROM companion_presence WHERE device_id = ?", (device_id,))
    if commit:
        await db.commit()

