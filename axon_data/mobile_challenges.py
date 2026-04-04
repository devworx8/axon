from __future__ import annotations

import aiosqlite


async def create_risk_challenge(
    db: aiosqlite.Connection,
    *,
    challenge_key: str,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
    action_type: str,
    risk_tier: str = "destructive",
    title: str = "",
    summary: str = "",
    status: str = "pending",
    requires_biometric: bool = True,
    request_json: str = "{}",
    meta_json: str = "{}",
    expires_at: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO risk_challenges (
            challenge_key, device_id, session_id, workspace_id, action_type, risk_tier,
            title, summary, status, requires_biometric, request_json, meta_json,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            challenge_key,
            device_id,
            session_id,
            workspace_id,
            action_type,
            risk_tier,
            title,
            summary,
            status,
            1 if requires_biometric else 0,
            request_json,
            meta_json,
            expires_at,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM risk_challenges WHERE challenge_key = ?", (challenge_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_risk_challenge(db: aiosqlite.Connection, challenge_id: int):
    cur = await db.execute("SELECT * FROM risk_challenges WHERE id = ?", (challenge_id,))
    return await cur.fetchone()


async def get_risk_challenge_by_key(db: aiosqlite.Connection, challenge_key: str):
    cur = await db.execute("SELECT * FROM risk_challenges WHERE challenge_key = ?", (challenge_key,))
    return await cur.fetchone()


async def list_risk_challenges(
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
        FROM risk_challenges
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def update_risk_challenge(
    db: aiosqlite.Connection,
    challenge_id: int,
    *,
    status: str | None = None,
    confirmed_at: str | None = None,
    rejected_at: str | None = None,
    meta_json: str | None = None,
    commit: bool = True,
):
    fields = []
    values: list[object] = []
    for name, value in (
        ("status", status),
        ("confirmed_at", confirmed_at),
        ("rejected_at", rejected_at),
        ("meta_json", meta_json),
    ):
        if value is not None:
            fields.append(f"{name} = ?")
            values.append(value)
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    await db.execute(
        f"UPDATE risk_challenges SET {', '.join(fields)} WHERE id = ?",
        (*values, challenge_id),
    )
    if commit:
        await db.commit()

