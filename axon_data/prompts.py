from __future__ import annotations

import aiosqlite


async def save_prompt(
    db: aiosqlite.Connection,
    project_id: int | None,
    title: str,
    content: str,
    tags: str = "",
    meta_json: str = "{}",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO prompts (project_id, title, content, tags, meta_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, title, content, tags, meta_json),
    )
    await db.commit()
    return cur.lastrowid


async def get_prompts(db: aiosqlite.Connection, project_id: int | None = None):
    if project_id is not None:
        cur = await db.execute(
            "SELECT * FROM prompts WHERE project_id = ? ORDER BY pinned DESC, used_count DESC, created_at DESC",
            (project_id,),
        )
    else:
        cur = await db.execute(
            "SELECT p.*, pr.name as project_name FROM prompts p "
            "LEFT JOIN projects pr ON p.project_id = pr.id "
            "ORDER BY pinned DESC, used_count DESC, created_at DESC"
        )
    return await cur.fetchall()


async def increment_prompt_usage(db: aiosqlite.Connection, prompt_id: int):
    await db.execute(
        "UPDATE prompts SET used_count = used_count + 1, updated_at = datetime('now') WHERE id = ?",
        (prompt_id,),
    )
    await db.commit()


async def delete_prompt(db: aiosqlite.Connection, prompt_id: int):
    await db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
    await db.commit()


async def get_prompt(db: aiosqlite.Connection, prompt_id: int):
    cur = await db.execute(
        "SELECT p.*, pr.name as project_name FROM prompts p LEFT JOIN projects pr ON p.project_id = pr.id WHERE p.id = ?",
        (prompt_id,),
    )
    return await cur.fetchone()
