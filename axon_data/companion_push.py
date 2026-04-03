from __future__ import annotations

import aiosqlite


async def upsert_companion_push_subscription(
    db: aiosqlite.Connection,
    *,
    device_id: int,
    endpoint: str,
    provider: str = "webpush",
    auth_json: str = "{}",
    p256dh: str = "",
    expiration_at: str | None = None,
    status: str = "active",
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO companion_push_subscriptions (
            device_id, provider, endpoint, auth_json, p256dh, expiration_at,
            status, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(endpoint) DO UPDATE SET
            device_id = excluded.device_id,
            provider = excluded.provider,
            auth_json = excluded.auth_json,
            p256dh = excluded.p256dh,
            expiration_at = excluded.expiration_at,
            status = excluded.status,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            device_id,
            provider,
            endpoint,
            auth_json,
            p256dh,
            expiration_at,
            status,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute(
        "SELECT id FROM companion_push_subscriptions WHERE endpoint = ?",
        (endpoint,),
    )
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_companion_push_subscription(db: aiosqlite.Connection, subscription_id: int):
    cur = await db.execute(
        "SELECT * FROM companion_push_subscriptions WHERE id = ?",
        (subscription_id,),
    )
    return await cur.fetchone()


async def list_companion_push_subscriptions(
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
        FROM companion_push_subscriptions
        {where}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def disable_companion_push_subscription(
    db: aiosqlite.Connection,
    subscription_id: int,
    *,
    commit: bool = True,
):
    await db.execute(
        "UPDATE companion_push_subscriptions SET status = 'disabled', updated_at = datetime('now') WHERE id = ?",
        (subscription_id,),
    )
    if commit:
        await db.commit()

