from __future__ import annotations

import aiosqlite


async def upsert_memory_item(
    db: aiosqlite.Connection,
    *,
    memory_key: str,
    layer: str,
    title: str,
    content: str,
    summary: str = "",
    source: str = "",
    source_id: str = "",
    workspace_id: int | None = None,
    mission_id: int | None = None,
    trust_level: str = "medium",
    relevance_score: float = 0.0,
    embedding_json: str = "",
    meta_json: str = "{}",
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO memory_items (
            memory_key, layer, memory_type, title, content, summary, source, source_id, source_ref,
            workspace_id, mission_id, trust_level, relevance_score, embedding_json, meta_json,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(memory_key) DO UPDATE SET
            layer = excluded.layer,
            memory_type = excluded.memory_type,
            title = excluded.title,
            content = excluded.content,
            summary = excluded.summary,
            source = excluded.source,
            source_id = excluded.source_id,
            source_ref = excluded.source_ref,
            workspace_id = excluded.workspace_id,
            mission_id = excluded.mission_id,
            trust_level = excluded.trust_level,
            relevance_score = excluded.relevance_score,
            embedding_json = excluded.embedding_json,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            memory_key,
            layer,
            layer,
            title,
            content,
            summary,
            source,
            source_id,
            source or source_id,
            workspace_id,
            mission_id,
            trust_level,
            relevance_score,
            embedding_json,
            meta_json,
        ),
    )
    if commit:
        await db.commit()


async def get_memory_item(db: aiosqlite.Connection, memory_id: int):
    cur = await db.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,))
    return await cur.fetchone()


async def get_memory_item_by_key(db: aiosqlite.Connection, memory_key: str):
    cur = await db.execute("SELECT * FROM memory_items WHERE memory_key = ?", (memory_key,))
    return await cur.fetchone()


async def list_memory_items(
    db: aiosqlite.Connection,
    *,
    layer: str = "",
    workspace_id: int | None = None,
    limit: int = 500,
):
    clauses = []
    params: list[object] = []
    if layer:
        clauses.append("layer = ?")
        params.append(layer)
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT * FROM memory_items
        {where}
        ORDER BY COALESCE(last_accessed_at, updated_at) DESC, updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def search_memory_items(
    db: aiosqlite.Connection,
    *,
    query: str,
    workspace_id: int | None = None,
    layers: list[str] | None = None,
    limit: int = 120,
):
    token = f"%{str(query or '').strip()}%"
    clauses = ["(title LIKE ? OR summary LIKE ? OR content LIKE ? OR source LIKE ?)"]
    params: list[object] = [token, token, token, token]
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    if layers:
        placeholders = ",".join("?" for _ in layers)
        clauses.append(f"layer IN ({placeholders})")
        params.extend(list(layers))
    cur = await db.execute(
        f"""
        SELECT *
        FROM memory_items
        WHERE {' AND '.join(clauses)}
        ORDER BY pinned DESC, COALESCE(last_accessed_at, updated_at) DESC, updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def delete_stale_memory_items(
    db: aiosqlite.Connection,
    *,
    layer: str,
    keep_keys: list[str],
    commit: bool = True,
):
    if keep_keys:
        placeholders = ",".join("?" for _ in keep_keys)
        await db.execute(
            f"DELETE FROM memory_items WHERE layer = ? AND memory_key NOT IN ({placeholders})",
            (layer, *keep_keys),
        )
    else:
        await db.execute("DELETE FROM memory_items WHERE layer = ?", (layer,))
    if commit:
        await db.commit()


async def touch_memory_item(db: aiosqlite.Connection, memory_id: int, *, commit: bool = True):
    await db.execute(
        "UPDATE memory_items SET last_accessed_at = datetime('now'), last_used_at = datetime('now') WHERE id = ?",
        (memory_id,),
    )
    if commit:
        await db.commit()


async def touch_memory_items(db: aiosqlite.Connection, memory_ids: list[int], *, commit: bool = True):
    ids: list[int] = []
    for item in memory_ids:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0:
            ids.append(value)
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    await db.execute(
        f"""
        UPDATE memory_items
        SET last_accessed_at = datetime('now'),
            last_used_at = datetime('now')
        WHERE id IN ({placeholders})
        """,
        ids,
    )
    if commit:
        await db.commit()


async def count_memory_items_by_layer(db: aiosqlite.Connection) -> dict[str, int]:
    cur = await db.execute("SELECT layer, COUNT(*) AS total FROM memory_items GROUP BY layer")
    rows = await cur.fetchall()
    return {row["layer"]: row["total"] for row in rows}


async def update_memory_item_state(
    db: aiosqlite.Connection,
    memory_id: int,
    *,
    pinned: bool | None = None,
    trust_level: str | None = None,
):
    fields = []
    values: list[object] = []
    if pinned is not None:
        fields.append("pinned = ?")
        values.append(1 if pinned else 0)
    if trust_level is not None:
        fields.append("trust_level = ?")
        values.append(trust_level)
    if not fields:
        return
    values.append(memory_id)
    await db.execute(
        f"UPDATE memory_items SET {', '.join(fields)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def list_memory_items_filtered(
    db: aiosqlite.Connection,
    *,
    search: str = "",
    layer: str = "",
    trust_level: str = "",
    pinned: bool | None = None,
    workspace_id: int | None = None,
    limit: int = 200,
):
    clauses = []
    params: list[object] = []
    if search.strip():
        token = f"%{search.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR content LIKE ? OR source LIKE ?)")
        params.extend([token, token, token, token])
    if layer:
        clauses.append("layer = ?")
        params.append(layer)
    if trust_level:
        clauses.append("trust_level = ?")
        params.append(trust_level)
    if pinned is not None:
        clauses.append("pinned = ?")
        params.append(1 if pinned else 0)
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT mi.*, p.name as workspace_name
        FROM memory_items mi
        LEFT JOIN projects p ON mi.workspace_id = p.id
        {where}
        ORDER BY mi.pinned DESC,
                 COALESCE(mi.last_accessed_at, mi.updated_at) DESC,
                 mi.updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def upsert_memory_link(
    db: aiosqlite.Connection,
    *,
    from_memory_id: int,
    to_memory_id: int,
    link_type: str = "related",
    weight: float = 1.0,
):
    await db.execute(
        """
        INSERT INTO memory_links (from_memory_id, to_memory_id, link_type, weight)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(from_memory_id, to_memory_id, link_type)
        DO UPDATE SET weight = excluded.weight
        """,
        (from_memory_id, to_memory_id, link_type, weight),
    )
    await db.commit()


async def list_memory_links(db: aiosqlite.Connection, memory_id: int, *, limit: int = 50):
    cur = await db.execute(
        """
        SELECT ml.*, src.title AS from_title, dst.title AS to_title
        FROM memory_links ml
        LEFT JOIN memory_items src ON src.id = ml.from_memory_id
        LEFT JOIN memory_items dst ON dst.id = ml.to_memory_id
        WHERE ml.from_memory_id = ? OR ml.to_memory_id = ?
        ORDER BY ml.weight DESC, ml.created_at DESC
        LIMIT ?
        """,
        (memory_id, memory_id, limit),
    )
    return await cur.fetchall()
