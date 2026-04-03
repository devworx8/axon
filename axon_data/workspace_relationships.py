from __future__ import annotations

import aiosqlite


async def upsert_workspace_relationship(
    db: aiosqlite.Connection,
    *,
    workspace_id: int,
    external_system: str,
    external_id: str = "",
    relationship_type: str = "primary",
    external_name: str = "",
    external_url: str = "",
    status: str = "active",
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO workspace_relationships (
            workspace_id, external_system, relationship_type, external_id,
            external_name, external_url, status, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(workspace_id, external_system, external_id) DO UPDATE SET
            relationship_type = excluded.relationship_type,
            external_name = excluded.external_name,
            external_url = excluded.external_url,
            status = excluded.status,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            workspace_id,
            external_system,
            relationship_type,
            external_id,
            external_name,
            external_url,
            status,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute(
        """
        SELECT id
        FROM workspace_relationships
        WHERE workspace_id = ? AND external_system = ? AND external_id = ?
        """,
        (workspace_id, external_system, external_id),
    )
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_workspace_relationship(db: aiosqlite.Connection, relationship_id: int):
    cur = await db.execute("SELECT * FROM workspace_relationships WHERE id = ?", (relationship_id,))
    return await cur.fetchone()


async def list_workspace_relationships(
    db: aiosqlite.Connection,
    *,
    workspace_id: int | None = None,
    external_system: str = "",
    status: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if external_system:
        clauses.append("external_system = ?")
        params.append(external_system)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM workspace_relationships
        {where}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def resolve_workspace_relationship(
    db: aiosqlite.Connection,
    *,
    external_system: str,
    external_id: str,
):
    cur = await db.execute(
        """
        SELECT wr.*, p.name AS workspace_name, p.path AS workspace_path
        FROM workspace_relationships wr
        LEFT JOIN projects p ON p.id = wr.workspace_id
        WHERE wr.external_system = ? AND wr.external_id = ?
        ORDER BY wr.updated_at DESC
        LIMIT 1
        """,
        (external_system, external_id),
    )
    return await cur.fetchone()

