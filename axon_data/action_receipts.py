from __future__ import annotations

import aiosqlite


async def create_action_receipt(
    db: aiosqlite.Connection,
    *,
    receipt_key: str,
    device_id: int | None = None,
    session_id: int | None = None,
    workspace_id: int | None = None,
    challenge_id: int | None = None,
    action_type: str,
    risk_tier: str = "observe",
    status: str = "completed",
    outcome: str = "",
    title: str = "",
    summary: str = "",
    request_json: str = "{}",
    result_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO action_receipts (
            receipt_key, device_id, session_id, workspace_id, challenge_id, action_type,
            risk_tier, status, outcome, title, summary, request_json, result_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            receipt_key,
            device_id,
            session_id,
            workspace_id,
            challenge_id,
            action_type,
            risk_tier,
            status,
            outcome,
            title,
            summary,
            request_json,
            result_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM action_receipts WHERE receipt_key = ?", (receipt_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_action_receipt(db: aiosqlite.Connection, receipt_id: int):
    cur = await db.execute("SELECT * FROM action_receipts WHERE id = ?", (receipt_id,))
    return await cur.fetchone()


async def list_action_receipts(
    db: aiosqlite.Connection,
    *,
    device_id: int | None = None,
    workspace_id: int | None = None,
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if device_id is not None:
        clauses.append("device_id = ?")
        params.append(device_id)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM action_receipts
        {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()

