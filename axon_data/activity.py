from __future__ import annotations

import aiosqlite


async def log_event(
    db: aiosqlite.Connection,
    event_type: str,
    summary: str,
    project_id: int | None = None,
):
    await db.execute(
        "INSERT INTO activity_log (project_id, event_type, summary) VALUES (?, ?, ?)",
        (project_id, event_type, summary),
    )
    await db.commit()


async def get_activity(db: aiosqlite.Connection, limit: int = 50):
    cur = await db.execute(
        """
        SELECT a.*, p.name as project_name FROM activity_log a
        LEFT JOIN projects p ON a.project_id = p.id
        ORDER BY a.created_at DESC LIMIT ?
        """,
        (limit,),
    )
    return await cur.fetchall()
