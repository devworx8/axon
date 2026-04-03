from __future__ import annotations

import aiosqlite


async def upsert_companion_auth_session(
    db: aiosqlite.Connection,
    *,
    device_id: int,
    access_token_hash: str,
    refresh_token_hash: str = "",
    expires_at: str,
    revoked_at: str | None = None,
    last_refreshed_at: str | None = None,
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO companion_auth_sessions (
            device_id, access_token_hash, refresh_token_hash, expires_at,
            revoked_at, last_refreshed_at, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(access_token_hash) DO UPDATE SET
            device_id = excluded.device_id,
            refresh_token_hash = excluded.refresh_token_hash,
            expires_at = excluded.expires_at,
            revoked_at = excluded.revoked_at,
            last_refreshed_at = excluded.last_refreshed_at,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            device_id,
            access_token_hash,
            refresh_token_hash,
            expires_at,
            revoked_at,
            last_refreshed_at,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute(
        "SELECT id FROM companion_auth_sessions WHERE access_token_hash = ?",
        (access_token_hash,),
    )
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_companion_auth_session(db: aiosqlite.Connection, session_id: int):
    cur = await db.execute("SELECT * FROM companion_auth_sessions WHERE id = ?", (session_id,))
    return await cur.fetchone()


async def get_companion_auth_session_by_access_hash(db: aiosqlite.Connection, access_token_hash: str):
    cur = await db.execute(
        """
        SELECT *
        FROM companion_auth_sessions
        WHERE access_token_hash = ?
          AND (revoked_at IS NULL OR revoked_at = '')
          AND expires_at > datetime('now')
        """,
        (access_token_hash,),
    )
    return await cur.fetchone()


async def get_active_companion_auth_sessions_for_device(db: aiosqlite.Connection, device_id: int):
    cur = await db.execute(
        """
        SELECT *
        FROM companion_auth_sessions
        WHERE device_id = ?
          AND (revoked_at IS NULL OR revoked_at = '')
          AND expires_at > datetime('now')
        ORDER BY updated_at DESC
        """,
        (device_id,),
    )
    return await cur.fetchall()


async def get_companion_auth_session_by_refresh_hash(db: aiosqlite.Connection, refresh_token_hash: str):
    cur = await db.execute(
        """
        SELECT *
        FROM companion_auth_sessions
        WHERE refresh_token_hash = ?
          AND (revoked_at IS NULL OR revoked_at = '')
          AND expires_at > datetime('now')
        """,
        (refresh_token_hash,),
    )
    return await cur.fetchone()


async def list_companion_auth_sessions(
    db: aiosqlite.Connection,
    *,
    device_id: int | None = None,
    limit: int = 50,
):
    clauses = []
    params: list[object] = []
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM companion_auth_sessions
        {where}
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def revoke_companion_auth_session(
    db: aiosqlite.Connection,
    *,
    session_id: int | None = None,
    access_token_hash: str = "",
    refresh_token_hash: str = "",
    commit: bool = True,
):
    clauses = []
    params: list[object] = []
    if session_id is not None:
        clauses.append("id = ?")
        params.append(session_id)
    if access_token_hash:
        clauses.append("access_token_hash = ?")
        params.append(access_token_hash)
    if refresh_token_hash:
        clauses.append("refresh_token_hash = ?")
        params.append(refresh_token_hash)
    if not clauses:
        return
    where = " AND ".join(clauses)
    await db.execute(
        f"UPDATE companion_auth_sessions SET revoked_at = datetime('now'), updated_at = datetime('now') WHERE {where}",
        params,
    )
    if commit:
        await db.commit()


async def revoke_companion_auth_sessions_for_device(
    db: aiosqlite.Connection,
    device_id: int,
    *,
    commit: bool = True,
):
    await db.execute(
        """
        UPDATE companion_auth_sessions
        SET revoked_at = datetime('now'), updated_at = datetime('now')
        WHERE device_id = ? AND (revoked_at IS NULL OR revoked_at = '')
        """,
        (device_id,),
    )
    if commit:
        await db.commit()
