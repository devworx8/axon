from __future__ import annotations

import aiosqlite


async def save_message(
    db: aiosqlite.Connection,
    role: str,
    content: str,
    project_id: int | None = None,
    tokens: int = 0,
):
    await db.execute(
        """
        INSERT INTO chat_history (project_id, role, content, tokens_used)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, role, content, tokens),
    )
    await db.commit()


async def get_chat_history(
    db: aiosqlite.Connection,
    project_id: int | None = None,
    limit: int = 20,
):
    if project_id is not None:
        cur = await db.execute(
            "SELECT * FROM chat_history WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    rows = await cur.fetchall()
    return list(reversed(rows))


async def clear_chat_history(db: aiosqlite.Connection, project_id: int | None = None):
    if project_id is not None:
        await db.execute("DELETE FROM chat_history WHERE project_id = ?", (project_id,))
    else:
        await db.execute("DELETE FROM chat_history")
    await db.commit()
