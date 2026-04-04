from __future__ import annotations

import aiosqlite


async def create_mobile_elevation_session(
    db: aiosqlite.Connection,
    *,
    device_id: int,
    elevation_key: str,
    risk_tier: str = "destructive",
    granted_scopes_json: str = "[]",
    status: str = "active",
    verified_via: str = "",
    verified_at: str | None = None,
    expires_at: str | None = None,
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO mobile_elevation_sessions (
            device_id, elevation_key, risk_tier, granted_scopes_json, status,
            verified_via, verified_at, expires_at, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            device_id,
            elevation_key,
            risk_tier,
            granted_scopes_json,
            status,
            verified_via,
            verified_at,
            expires_at,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM mobile_elevation_sessions WHERE elevation_key = ?", (elevation_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_mobile_elevation_session(db: aiosqlite.Connection, session_id: int):
    cur = await db.execute("SELECT * FROM mobile_elevation_sessions WHERE id = ?", (session_id,))
    return await cur.fetchone()


async def get_mobile_elevation_session_by_key(db: aiosqlite.Connection, elevation_key: str):
    cur = await db.execute("SELECT * FROM mobile_elevation_sessions WHERE elevation_key = ?", (elevation_key,))
    return await cur.fetchone()


async def list_mobile_elevation_sessions(
    db: aiosqlite.Connection,
    *,
    device_id: int | None = None,
    status: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM mobile_elevation_sessions
        {where}
        ORDER BY COALESCE(expires_at, updated_at) DESC, updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def update_mobile_elevation_session(
    db: aiosqlite.Connection,
    session_id: int,
    *,
    status: str | None = None,
    verified_at: str | None = None,
    expires_at: str | None = None,
    meta_json: str | None = None,
    commit: bool = True,
):
    fields = []
    values: list[object] = []
    for name, value in (
        ("status", status),
        ("verified_at", verified_at),
        ("expires_at", expires_at),
        ("meta_json", meta_json),
    ):
        if value is not None:
            fields.append(f"{name} = ?")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    await db.execute(
        f"UPDATE mobile_elevation_sessions SET {', '.join(fields)} WHERE id = ?",
        (*values, session_id),
    )
    if commit:
        await db.commit()

