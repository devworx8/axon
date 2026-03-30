from __future__ import annotations

import aiosqlite


async def create_research_pack(
    db: aiosqlite.Connection,
    *,
    title: str,
    description: str = "",
    workspace_id: int | None = None,
    pinned: bool = False,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO research_packs (title, description, workspace_id, pinned)
        VALUES (?, ?, ?, ?)
        """,
        (title, description, workspace_id, 1 if pinned else 0),
    )
    await db.commit()
    return cur.lastrowid


async def list_research_packs(
    db: aiosqlite.Connection,
    *,
    search: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if search.strip():
        token = f"%{search.strip()}%"
        clauses.append("(rp.title LIKE ? OR rp.description LIKE ?)")
        params.extend([token, token])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT
            rp.*,
            p.name AS workspace_name,
            COUNT(rpi.resource_id) AS resource_count
        FROM research_packs rp
        LEFT JOIN projects p ON p.id = rp.workspace_id
        LEFT JOIN research_pack_items rpi ON rpi.pack_id = rp.id
        {where}
        GROUP BY rp.id
        ORDER BY rp.pinned DESC, rp.updated_at DESC, rp.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_research_pack(db: aiosqlite.Connection, pack_id: int):
    cur = await db.execute(
        """
        SELECT
            rp.*,
            p.name AS workspace_name,
            COUNT(rpi.resource_id) AS resource_count
        FROM research_packs rp
        LEFT JOIN projects p ON p.id = rp.workspace_id
        LEFT JOIN research_pack_items rpi ON rpi.pack_id = rp.id
        WHERE rp.id = ?
        GROUP BY rp.id
        """,
        (pack_id,),
    )
    return await cur.fetchone()


async def update_research_pack(db: aiosqlite.Connection, pack_id: int, **fields):
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values()) + [pack_id]
    await db.execute(
        f"UPDATE research_packs SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def delete_research_pack(db: aiosqlite.Connection, pack_id: int):
    await db.execute("DELETE FROM research_packs WHERE id = ?", (pack_id,))
    await db.commit()


async def add_research_pack_items(
    db: aiosqlite.Connection,
    pack_id: int,
    resource_ids: list[int],
):
    for resource_id in resource_ids:
        await db.execute(
            """
            INSERT OR IGNORE INTO research_pack_items (pack_id, resource_id)
            VALUES (?, ?)
            """,
            (pack_id, resource_id),
        )
    await db.execute(
        "UPDATE research_packs SET updated_at = datetime('now') WHERE id = ?",
        (pack_id,),
    )
    await db.commit()


async def remove_research_pack_item(
    db: aiosqlite.Connection,
    pack_id: int,
    resource_id: int,
):
    await db.execute(
        "DELETE FROM research_pack_items WHERE pack_id = ? AND resource_id = ?",
        (pack_id, resource_id),
    )
    await db.execute(
        "UPDATE research_packs SET updated_at = datetime('now') WHERE id = ?",
        (pack_id,),
    )
    await db.commit()


async def get_research_pack_items(db: aiosqlite.Connection, pack_id: int):
    cur = await db.execute(
        """
        SELECT
            rpi.pack_id,
            r.id,
            r.title,
            r.kind,
            r.source_type,
            r.source_url,
            r.local_path,
            r.mime_type,
            r.size_bytes,
            r.sha256,
            r.status,
            r.summary,
            r.preview_text,
            r.trust_level,
            r.pinned,
            r.workspace_id,
            r.meta_json,
            r.created_at,
            r.updated_at,
            r.last_used_at
        FROM research_pack_items rpi
        JOIN resources r ON r.id = rpi.resource_id
        WHERE rpi.pack_id = ?
        ORDER BY rpi.created_at ASC, r.created_at ASC
        """,
        (pack_id,),
    )
    return await cur.fetchall()
