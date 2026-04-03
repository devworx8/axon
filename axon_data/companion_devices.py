from __future__ import annotations

import aiosqlite


async def upsert_companion_device(
    db: aiosqlite.Connection,
    *,
    device_key: str,
    name: str,
    user_id: int | None = None,
    kind: str = "mobile",
    platform: str = "",
    model: str = "",
    os_version: str = "",
    status: str = "active",
    meta_json: str = "{}",
    last_seen_at: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO companion_devices (
            device_key, user_id, name, kind, platform, model, os_version,
            status, meta_json, last_seen_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), datetime('now'), datetime('now'))
        ON CONFLICT(device_key) DO UPDATE SET
            user_id = excluded.user_id,
            name = excluded.name,
            kind = excluded.kind,
            platform = excluded.platform,
            model = excluded.model,
            os_version = excluded.os_version,
            status = excluded.status,
            meta_json = excluded.meta_json,
            last_seen_at = COALESCE(excluded.last_seen_at, companion_devices.last_seen_at),
            updated_at = datetime('now')
        """,
        (
            device_key,
            user_id,
            name,
            kind,
            platform,
            model,
            os_version,
            status,
            meta_json,
            last_seen_at,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM companion_devices WHERE device_key = ?", (device_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_companion_device(db: aiosqlite.Connection, device_id: int):
    cur = await db.execute("SELECT * FROM companion_devices WHERE id = ?", (device_id,))
    return await cur.fetchone()


async def get_companion_device_by_key(db: aiosqlite.Connection, device_key: str):
    cur = await db.execute("SELECT * FROM companion_devices WHERE device_key = ?", (device_key,))
    return await cur.fetchone()


async def list_companion_devices(
    db: aiosqlite.Connection,
    *,
    user_id: int | None = None,
    status: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT * FROM companion_devices
        {where}
        ORDER BY COALESCE(last_seen_at, updated_at) DESC, created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def touch_companion_device(db: aiosqlite.Connection, device_id: int, *, commit: bool = True):
    await db.execute(
        "UPDATE companion_devices SET last_seen_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (device_id,),
    )
    if commit:
        await db.commit()


async def update_companion_device_status(
    db: aiosqlite.Connection,
    device_id: int,
    *,
    status: str,
    commit: bool = True,
):
    await db.execute(
        "UPDATE companion_devices SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, device_id),
    )
    if commit:
        await db.commit()


async def revoke_companion_device(db: aiosqlite.Connection, device_id: int, *, commit: bool = True):
    await update_companion_device_status(db, device_id, status="revoked", commit=False)
    await db.execute(
        "UPDATE companion_auth_sessions SET revoked_at = datetime('now'), updated_at = datetime('now') WHERE device_id = ? AND revoked_at IS NULL",
        (device_id,),
    )
    if commit:
        await db.commit()

