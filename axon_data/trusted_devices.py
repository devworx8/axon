from __future__ import annotations

import aiosqlite


async def upsert_trusted_device_state(
    db: aiosqlite.Connection,
    *,
    device_id: int,
    trust_state: str = "paired",
    max_risk_tier: str = "act",
    biometric_enabled: bool = False,
    last_biometric_at: str | None = None,
    elevated_until: str | None = None,
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO trusted_device_states (
            device_id, trust_state, max_risk_tier, biometric_enabled,
            last_biometric_at, elevated_until, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(device_id) DO UPDATE SET
            trust_state = excluded.trust_state,
            max_risk_tier = excluded.max_risk_tier,
            biometric_enabled = excluded.biometric_enabled,
            last_biometric_at = COALESCE(excluded.last_biometric_at, trusted_device_states.last_biometric_at),
            elevated_until = excluded.elevated_until,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            device_id,
            trust_state,
            max_risk_tier,
            1 if biometric_enabled else 0,
            last_biometric_at,
            elevated_until,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    return device_id


async def get_trusted_device_state(db: aiosqlite.Connection, device_id: int):
    cur = await db.execute("SELECT * FROM trusted_device_states WHERE device_id = ?", (device_id,))
    return await cur.fetchone()


async def list_trusted_device_states(
    db: aiosqlite.Connection,
    *,
    trust_state: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if trust_state:
        clauses.append("trust_state = ?")
        params.append(trust_state)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM trusted_device_states
        {where}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()

