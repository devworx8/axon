from __future__ import annotations

import aiosqlite


async def upsert_control_capability(
    db: aiosqlite.Connection,
    *,
    action_type: str,
    system_name: str = "axon",
    scope: str = "global",
    risk_tier: str = "observe",
    mobile_direct_allowed: bool = False,
    destructive: bool = False,
    available: bool = True,
    description: str = "",
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO control_capabilities (
            action_type, system_name, scope, risk_tier, mobile_direct_allowed,
            destructive, available, description, meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(action_type) DO UPDATE SET
            system_name = excluded.system_name,
            scope = excluded.scope,
            risk_tier = excluded.risk_tier,
            mobile_direct_allowed = excluded.mobile_direct_allowed,
            destructive = excluded.destructive,
            available = excluded.available,
            description = excluded.description,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            action_type,
            system_name,
            scope,
            risk_tier,
            1 if mobile_direct_allowed else 0,
            1 if destructive else 0,
            1 if available else 0,
            description,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM control_capabilities WHERE action_type = ?", (action_type,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_control_capability(db: aiosqlite.Connection, action_type: str):
    cur = await db.execute("SELECT * FROM control_capabilities WHERE action_type = ?", (action_type,))
    return await cur.fetchone()


async def list_control_capabilities(
    db: aiosqlite.Connection,
    *,
    system_name: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if system_name:
        clauses.append("system_name = ?")
        params.append(system_name)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM control_capabilities
        {where}
        ORDER BY
            CASE risk_tier
                WHEN 'observe' THEN 0
                WHEN 'act' THEN 1
                WHEN 'destructive' THEN 2
                WHEN 'break_glass' THEN 3
                ELSE 4
            END,
            action_type ASC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()

