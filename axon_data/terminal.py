from __future__ import annotations

import aiosqlite


async def create_terminal_session(
    db: aiosqlite.Connection,
    *,
    title: str,
    workspace_id: int | None = None,
    mode: str = "read_only",
    cwd: str = "",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO terminal_sessions (title, workspace_id, status, mode, cwd)
        VALUES (?, ?, 'idle', ?, ?)
        """,
        (title, workspace_id, mode, cwd),
    )
    await db.commit()
    return cur.lastrowid


async def list_terminal_sessions(
    db: aiosqlite.Connection,
    *,
    workspace_id: int | None = None,
    limit: int = 30,
):
    clauses = []
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("ts.workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT ts.*, p.name AS workspace_name,
               (SELECT COUNT(*) FROM terminal_events te WHERE te.session_id = ts.id) AS event_count
        FROM terminal_sessions ts
        LEFT JOIN projects p ON p.id = ts.workspace_id
        {where}
        ORDER BY ts.updated_at DESC, ts.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_terminal_session(db: aiosqlite.Connection, session_id: int):
    cur = await db.execute(
        """
        SELECT ts.*, p.name AS workspace_name,
               (SELECT COUNT(*) FROM terminal_events te WHERE te.session_id = ts.id) AS event_count
        FROM terminal_sessions ts
        LEFT JOIN projects p ON p.id = ts.workspace_id
        WHERE ts.id = ?
        """,
        (session_id,),
    )
    return await cur.fetchone()


async def update_terminal_session(db: aiosqlite.Connection, session_id: int, **fields):
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values()) + [session_id]
    await db.execute(
        f"UPDATE terminal_sessions SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def mark_terminal_sessions_stopped(db: aiosqlite.Connection):
    await db.execute(
        """
        UPDATE terminal_sessions
        SET status = 'stopped',
            active_command = '',
            pending_command = '',
            pid = 0,
            updated_at = datetime('now')
        WHERE COALESCE(status, '') != 'closed'
        """
    )
    await db.commit()


async def add_terminal_event(
    db: aiosqlite.Connection,
    *,
    session_id: int,
    event_type: str,
    content: str = "",
    exit_code: int | None = None,
):
    await db.execute(
        """
        INSERT INTO terminal_events (session_id, event_type, content, exit_code)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, event_type, content, exit_code),
    )
    await db.execute(
        """
        UPDATE terminal_sessions
        SET last_output_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (session_id,),
    )
    await db.commit()


async def list_terminal_events(
    db: aiosqlite.Connection,
    session_id: int,
    *,
    limit: int = 200,
):
    cur = await db.execute(
        """
        SELECT * FROM terminal_events
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = await cur.fetchall()
    return list(reversed(rows))
