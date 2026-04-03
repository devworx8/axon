from __future__ import annotations

import aiosqlite


async def upsert_companion_session(
    db: aiosqlite.Connection,
    *,
    session_key: str,
    device_id: int | None = None,
    workspace_id: int | None = None,
    agent_session_id: str = "",
    status: str = "active",
    mode: str = "companion",
    current_route: str = "",
    current_view: str = "",
    active_task: str = "",
    summary: str = "",
    last_seen_at: str | None = None,
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO companion_sessions (
            session_key, device_id, workspace_id, agent_session_id, status, mode,
            current_route, current_view, active_task, summary, last_seen_at,
            started_at, updated_at, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), datetime('now'), datetime('now'), ?)
        ON CONFLICT(session_key) DO UPDATE SET
            device_id = excluded.device_id,
            workspace_id = excluded.workspace_id,
            agent_session_id = excluded.agent_session_id,
            status = excluded.status,
            mode = excluded.mode,
            current_route = excluded.current_route,
            current_view = excluded.current_view,
            active_task = excluded.active_task,
            summary = excluded.summary,
            last_seen_at = COALESCE(excluded.last_seen_at, companion_sessions.last_seen_at),
            updated_at = datetime('now'),
            meta_json = excluded.meta_json
        """,
        (
            session_key,
            device_id,
            workspace_id,
            agent_session_id,
            status,
            mode,
            current_route,
            current_view,
            active_task,
            summary,
            last_seen_at,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM companion_sessions WHERE session_key = ?", (session_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_companion_session(db: aiosqlite.Connection, session_id: int):
    cur = await db.execute("SELECT * FROM companion_sessions WHERE id = ?", (session_id,))
    return await cur.fetchone()


async def get_companion_session_by_key(db: aiosqlite.Connection, session_key: str):
    cur = await db.execute("SELECT * FROM companion_sessions WHERE session_key = ?", (session_key,))
    return await cur.fetchone()


async def list_companion_sessions(
    db: aiosqlite.Connection,
    *,
    device_id: int | None = None,
    workspace_id: int | None = None,
    status: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM companion_sessions
        {where}
        ORDER BY COALESCE(last_seen_at, updated_at) DESC, started_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def update_companion_session_state(
    db: aiosqlite.Connection,
    session_id: int,
    *,
    status: str | None = None,
    agent_session_id: str | None = None,
    current_route: str | None = None,
    current_view: str | None = None,
    active_task: str | None = None,
    summary: str | None = None,
    last_seen_at: str | None = None,
    commit: bool = True,
):
    fields = []
    values: list[object] = []
    for name, value in (
        ("status", status),
        ("agent_session_id", agent_session_id),
        ("current_route", current_route),
        ("current_view", current_view),
        ("active_task", active_task),
        ("summary", summary),
        ("last_seen_at", last_seen_at),
    ):
        if value is not None:
            fields.append(f"{name} = ?")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    await db.execute(
        f"UPDATE companion_sessions SET {', '.join(fields)} WHERE id = ?",
        (*values, session_id),
    )
    if commit:
        await db.commit()


async def close_companion_session(db: aiosqlite.Connection, session_id: int, *, commit: bool = True):
    await update_companion_session_state(db, session_id, status="closed", commit=False)
    if commit:
        await db.commit()

