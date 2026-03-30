from __future__ import annotations

import aiosqlite


async def add_resource(
    db: aiosqlite.Connection,
    *,
    title: str,
    kind: str,
    source_type: str,
    source_url: str,
    local_path: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    status: str = "pending",
    summary: str = "",
    preview_text: str = "",
    trust_level: str = "medium",
    pinned: bool = False,
    workspace_id: int | None = None,
    meta_json: str = "{}",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO resources (
            title, kind, source_type, source_url, local_path, file_path, mime_type,
            size_bytes, sha256, status, summary, preview_text, trust_level, pinned, workspace_id, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            kind,
            source_type,
            source_url,
            local_path,
            local_path,
            mime_type,
            size_bytes,
            sha256,
            status,
            summary,
            preview_text,
            trust_level,
            1 if pinned else 0,
            workspace_id,
            meta_json,
        ),
    )
    await db.commit()
    return cur.lastrowid


async def update_resource(db: aiosqlite.Connection, resource_id: int, **fields):
    if not fields:
        return
    if "local_path" in fields and "file_path" not in fields:
        fields["file_path"] = fields["local_path"]
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values())
    values.append(resource_id)
    await db.execute(
        f"UPDATE resources SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def list_resources(
    db: aiosqlite.Connection,
    *,
    search: str = "",
    kind: str = "",
    source_type: str = "",
    status: str = "",
    limit: int = 200,
):
    clauses = []
    params = []
    if search.strip():
        clauses.append("(title LIKE ? OR preview_text LIKE ? OR source_url LIKE ?)")
        token = f"%{search.strip()}%"
        params.extend([token, token, token])
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = await db.execute(
        f"""
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        {where}
        ORDER BY r.pinned DESC, COALESCE(r.last_used_at, r.updated_at) DESC, r.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_resource(db: aiosqlite.Connection, resource_id: int):
    cur = await db.execute(
        """
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        WHERE r.id = ?
        """,
        (resource_id,),
    )
    return await cur.fetchone()


async def get_resources_by_ids(db: aiosqlite.Connection, resource_ids: list[int]):
    if not resource_ids:
        return []
    placeholders = ",".join("?" for _ in resource_ids)
    cur = await db.execute(
        f"""
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        WHERE r.id IN ({placeholders})
        ORDER BY r.created_at ASC
        """,
        resource_ids,
    )
    return await cur.fetchall()


async def delete_resource(db: aiosqlite.Connection, resource_id: int):
    await db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    await db.commit()


async def replace_resource_chunks(
    db: aiosqlite.Connection,
    resource_id: int,
    chunks: list[dict],
    *,
    embedding_model: str = "",
):
    await db.execute("DELETE FROM resource_chunks WHERE resource_id = ?", (resource_id,))
    for chunk in chunks:
        text = chunk.get("text") or chunk.get("content") or ""
        embedding_json = chunk.get("embedding_json", "") or chunk.get(
            "embedding_vector", ""
        )
        await db.execute(
            """
            INSERT INTO resource_chunks (
                resource_id, chunk_index, text, content, token_estimate,
                embedding_model, embedding_json, embedding_vector
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resource_id,
                chunk.get("chunk_index", 0),
                text,
                text,
                chunk.get("token_estimate", max(1, len(text) // 4) if text else 0),
                chunk.get("embedding_model", embedding_model),
                embedding_json,
                embedding_json,
            ),
        )
    await db.commit()


async def get_resource_chunks(db: aiosqlite.Connection, resource_id: int):
    cur = await db.execute(
        "SELECT * FROM resource_chunks WHERE resource_id = ? ORDER BY chunk_index ASC",
        (resource_id,),
    )
    return await cur.fetchall()


async def touch_resource_used(db: aiosqlite.Connection, resource_id: int):
    await db.execute(
        "UPDATE resources SET last_used_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (resource_id,),
    )
    await db.commit()
