from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import aiosqlite


def build_attention_key(
    source: str,
    event_id: str = "",
    *,
    workspace_id: int | None = None,
    external_system: str = "",
    external_id: str = "",
    title: str = "",
) -> str:
    payload = "|".join(
        str(part or "").strip().lower()
        for part in (source, event_id, workspace_id or "", external_system, external_id, title)
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


async def upsert_attention_item(
    db: aiosqlite.Connection,
    *,
    attention_key: str,
    source: str,
    title: str,
    summary: str = "",
    detail: str = "",
    item_type: str = "",
    source_event_id: str = "",
    severity: str = "medium",
    status: str = "new",
    workspace_id: int | None = None,
    project_name: str = "",
    owner_kind: str = "",
    owner_id: int | None = None,
    link_url: str = "",
    meta_json: str = "{}",
    occurrence_count: int = 1,
    acknowledged_at: str | None = None,
    resolved_at: str | None = None,
    snoozed_until: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO attention_items (
            attention_key, source, source_event_id, item_type, title, summary, detail,
            workspace_id, project_name, severity, status, owner_kind, owner_id, link_url,
            meta_json, occurrence_count, acknowledged_at, resolved_at, snoozed_until,
            first_seen_at, last_seen_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
        ON CONFLICT(attention_key) DO UPDATE SET
            source = excluded.source,
            source_event_id = excluded.source_event_id,
            item_type = excluded.item_type,
            title = excluded.title,
            summary = excluded.summary,
            detail = excluded.detail,
            workspace_id = excluded.workspace_id,
            project_name = excluded.project_name,
            severity = excluded.severity,
            status = excluded.status,
            owner_kind = excluded.owner_kind,
            owner_id = excluded.owner_id,
            link_url = excluded.link_url,
            meta_json = excluded.meta_json,
            occurrence_count = COALESCE(attention_items.occurrence_count, 0) + COALESCE(excluded.occurrence_count, 1),
            acknowledged_at = COALESCE(excluded.acknowledged_at, attention_items.acknowledged_at),
            resolved_at = COALESCE(excluded.resolved_at, attention_items.resolved_at),
            snoozed_until = COALESCE(excluded.snoozed_until, attention_items.snoozed_until),
            last_seen_at = datetime('now'),
            updated_at = datetime('now')
        """,
        (
            attention_key,
            source,
            source_event_id,
            item_type,
            title,
            summary,
            detail,
            workspace_id,
            project_name,
            severity,
            status,
            owner_kind,
            owner_id,
            link_url,
            meta_json,
            occurrence_count,
            acknowledged_at,
            resolved_at,
            snoozed_until,
        ),
    )
    if commit:
        await db.commit()
    return await get_attention_item_id_by_key(db, attention_key)


async def get_attention_item(db: aiosqlite.Connection, attention_id: int):
    cur = await db.execute("SELECT * FROM attention_items WHERE id = ?", (attention_id,))
    return await cur.fetchone()


async def get_attention_item_id_by_key(db: aiosqlite.Connection, attention_key: str) -> int:
    cur = await db.execute(
        "SELECT id FROM attention_items WHERE attention_key = ?",
        (attention_key,),
    )
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_attention_item_by_key(db: aiosqlite.Connection, attention_key: str):
    cur = await db.execute(
        "SELECT * FROM attention_items WHERE attention_key = ?",
        (attention_key,),
    )
    return await cur.fetchone()


async def list_attention_items(
    db: aiosqlite.Connection,
    *,
    workspace_id: int | None = None,
    status: str = "",
    source: str = "",
    severity: str = "",
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM attention_items
        {where}
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            COALESCE(last_seen_at, updated_at) DESC,
            created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def search_attention_items(
    db: aiosqlite.Connection,
    *,
    query: str,
    workspace_id: int | None = None,
    limit: int = 100,
):
    token = f"%{str(query or '').strip()}%"
    clauses = ["(title LIKE ? OR summary LIKE ? OR detail LIKE ? OR source LIKE ? OR project_name LIKE ?)"]
    params: list[object] = [token, token, token, token, token]
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    cur = await db.execute(
        f"""
        SELECT *
        FROM attention_items
        WHERE {' AND '.join(clauses)}
        ORDER BY
            CASE severity
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
            END,
            COALESCE(last_seen_at, updated_at) DESC,
            created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def update_attention_item_state(
    db: aiosqlite.Connection,
    attention_id: int,
    *,
    status: str | None = None,
    acknowledged_at: str | None = None,
    resolved_at: str | None = None,
    snoozed_until: str | None = None,
    owner_kind: str | None = None,
    owner_id: int | None = None,
    commit: bool = True,
):
    fields = []
    values: list[object] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if acknowledged_at is not None:
        fields.append("acknowledged_at = ?")
        values.append(acknowledged_at)
    if resolved_at is not None:
        fields.append("resolved_at = ?")
        values.append(resolved_at)
    if snoozed_until is not None:
        fields.append("snoozed_until = ?")
        values.append(snoozed_until)
    if owner_kind is not None:
        fields.append("owner_kind = ?")
        values.append(owner_kind)
    if owner_id is not None:
        fields.append("owner_id = ?")
        values.append(owner_id)
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    await db.execute(
        f"UPDATE attention_items SET {', '.join(fields)} WHERE id = ?",
        (*values, attention_id),
    )
    if commit:
        await db.commit()


async def acknowledge_attention_item(db: aiosqlite.Connection, attention_id: int):
    await update_attention_item_state(
        db,
        attention_id,
        status="acknowledged",
        acknowledged_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )


async def snooze_attention_item(db: aiosqlite.Connection, attention_id: int, snoozed_until: str):
    await update_attention_item_state(
        db,
        attention_id,
        status="snoozed",
        snoozed_until=snoozed_until,
    )


async def assign_attention_item(
    db: aiosqlite.Connection,
    attention_id: int,
    *,
    owner_kind: str,
    owner_id: int | None = None,
):
    await update_attention_item_state(
        db,
        attention_id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        status="assigned",
    )


async def resolve_attention_item(db: aiosqlite.Connection, attention_id: int):
    await update_attention_item_state(
        db,
        attention_id,
        status="resolved",
        resolved_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
