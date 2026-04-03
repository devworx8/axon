from __future__ import annotations

import aiosqlite


async def upsert_project(db: aiosqlite.Connection, data: dict) -> int:
    await db.execute(
        """
        INSERT INTO projects (name, path, stack, description, git_branch, last_commit,
                              last_commit_age_days, todo_count, health, updated_at)
        VALUES (:name, :path, :stack, :description, :git_branch, :last_commit,
                :last_commit_age_days, :todo_count, :health, datetime('now'))
        ON CONFLICT(name) DO UPDATE SET
            path                 = excluded.path,
            stack                = excluded.stack,
            git_branch           = excluded.git_branch,
            last_commit          = excluded.last_commit,
            last_commit_age_days = excluded.last_commit_age_days,
            todo_count           = excluded.todo_count,
            health               = excluded.health,
            updated_at           = datetime('now')
        """,
        data,
    )
    await db.commit()
    cur = await db.execute("SELECT id FROM projects WHERE name = ?", (data["name"],))
    row = await cur.fetchone()
    return row["id"]


async def get_projects(db: aiosqlite.Connection, status: str | None = None):
    if status:
        cur = await db.execute(
            "SELECT * FROM projects WHERE status = ? ORDER BY health ASC, name ASC",
            (status,),
        )
    else:
        cur = await db.execute("SELECT * FROM projects ORDER BY health ASC, name ASC")
    return await cur.fetchall()


async def get_project(db: aiosqlite.Connection, project_id: int):
    cur = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return await cur.fetchone()


async def update_project_note(db: aiosqlite.Connection, project_id: int, note: str):
    await db.execute(
        "UPDATE projects SET note = ?, updated_at = datetime('now') WHERE id = ?",
        (note, project_id),
    )
    await db.commit()


async def update_project_status(db: aiosqlite.Connection, project_id: int, status: str):
    await db.execute(
        "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, project_id),
    )
    await db.commit()


async def delete_project(db: aiosqlite.Connection, project_id: int):
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()
