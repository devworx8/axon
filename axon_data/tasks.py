from __future__ import annotations

import aiosqlite


async def add_task(
    db: aiosqlite.Connection,
    project_id: int | None,
    title: str,
    detail: str = "",
    priority: str = "medium",
    due_date: str | None = None,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO tasks (project_id, title, detail, priority, due_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, title, detail, priority, due_date),
    )
    await db.commit()
    return cur.lastrowid


async def get_tasks(
    db: aiosqlite.Connection,
    project_id: int | None = None,
    status: str | None = "open",
):
    clauses = []
    params = []
    if project_id is not None:
        clauses.append("t.project_id = ?")
        params.append(project_id)
    if status:
        clauses.append("t.status = ?")
        params.append(status)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    cur = await db.execute(
        f"""
        SELECT t.*, pr.name as project_name FROM tasks t
        LEFT JOIN projects pr ON t.project_id = pr.id
        {where}
        ORDER BY
            CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2 ELSE 3 END,
            t.due_date ASC NULLS LAST,
            t.created_at ASC
        """,
        params,
    )
    return await cur.fetchall()


async def update_task_status(db: aiosqlite.Connection, task_id: int, status: str):
    await db.execute(
        "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, task_id),
    )
    await db.commit()


async def update_task(db: aiosqlite.Connection, task_id: int, **fields):
    allowed = {"title", "detail", "priority", "status", "due_date", "project_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [task_id]
    await db.execute(
        f"UPDATE tasks SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        params,
    )
    await db.commit()


async def delete_task(db: aiosqlite.Connection, task_id: int):
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    await db.commit()
