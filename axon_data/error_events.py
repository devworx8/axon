"""Axon — Error event repository.

Stores errors ingested from Sentry, CI failures, and other monitoring sources.
Each error has a fingerprint for deduplication and a status lifecycle:
  new → triaging → fixing → fixed → resolved | ignored
"""
from __future__ import annotations

import aiosqlite


async def ingest_error_event(
    db: aiosqlite.Connection,
    *,
    source: str,
    event_id: str,
    title: str,
    level: str = "error",
    fingerprint: str = "",
    project_name: str = "",
    workspace_id: int | None = None,
    meta_json: str = "{}",
) -> int:
    """Insert or update an error event, deduplicating on (source, event_id)."""
    cur = await db.execute(
        """
        INSERT INTO error_events (source, event_id, title, level, fingerprint,
                                  project_name, workspace_id, meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, event_id) DO UPDATE SET
            title = excluded.title,
            level = excluded.level,
            occurrence_count = occurrence_count + 1,
            last_seen_at = datetime('now'),
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (source, event_id, title, level, fingerprint,
         project_name, workspace_id, meta_json),
    )
    await db.commit()
    return cur.lastrowid


async def get_unresolved_errors(
    db: aiosqlite.Connection,
    *,
    source: str = "",
    workspace_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Fetch errors not yet resolved or ignored, newest first."""
    clauses = ["status NOT IN ('resolved', 'ignored')"]
    params: list = []
    if source:
        clauses.append("source = ?")
        params.append(source)
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    where = " AND ".join(clauses)
    params.append(limit)
    cur = await db.execute(
        f"SELECT * FROM error_events WHERE {where} ORDER BY last_seen_at DESC LIMIT ?",
        params,
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_error_by_fingerprint(
    db: aiosqlite.Connection,
    fingerprint: str,
) -> dict | None:
    cur = await db.execute(
        "SELECT * FROM error_events WHERE fingerprint = ? ORDER BY last_seen_at DESC LIMIT 1",
        (fingerprint,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_error_event(db: aiosqlite.Connection, event_id: int) -> dict | None:
    cur = await db.execute("SELECT * FROM error_events WHERE id = ?", (event_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def update_error_status(
    db: aiosqlite.Connection,
    event_id: int,
    status: str,
    *,
    fix_session_id: str = "",
) -> None:
    """Update the lifecycle status of an error event."""
    if fix_session_id:
        await db.execute(
            """UPDATE error_events
               SET status = ?, fix_session_id = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (status, fix_session_id, event_id),
        )
    else:
        await db.execute(
            "UPDATE error_events SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, event_id),
        )
    await db.commit()


async def mark_error_resolved(
    db: aiosqlite.Connection,
    event_id: int,
) -> None:
    await update_error_status(db, event_id, "resolved")


async def list_error_events(
    db: aiosqlite.Connection,
    *,
    status: str = "",
    source: str = "",
    limit: int = 100,
) -> list[dict]:
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    cur = await db.execute(
        f"SELECT * FROM error_events {where} ORDER BY last_seen_at DESC LIMIT ?",
        params,
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]
