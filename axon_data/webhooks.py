from __future__ import annotations

import aiosqlite


async def enqueue_webhook(
    db: aiosqlite.Connection,
    url: str,
    event: str,
    payload_json: str,
    secret: str = "",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO webhook_jobs (webhook_url, event, payload_json, secret)
        VALUES (?, ?, ?, ?)
        """,
        (url, event, payload_json, secret),
    )
    await db.commit()
    return cur.lastrowid


async def get_pending_webhooks(db: aiosqlite.Connection, limit: int = 20):
    cur = await db.execute(
        """
        SELECT * FROM webhook_jobs
        WHERE status = 'pending' AND next_retry_at <= datetime('now')
        ORDER BY created_at ASC LIMIT ?
        """,
        (limit,),
    )
    return await cur.fetchall()


async def mark_webhook_sent(db: aiosqlite.Connection, job_id: int):
    await db.execute(
        """
        UPDATE webhook_jobs SET status = 'sent', updated_at = datetime('now')
        WHERE id = ?
        """,
        (job_id,),
    )
    await db.commit()


async def mark_webhook_failed(
    db: aiosqlite.Connection,
    job_id: int,
    error: str,
    backoff_seconds: int,
):
    await db.execute(
        """
        UPDATE webhook_jobs
        SET attempt_count = attempt_count + 1,
            last_error = ?,
            next_retry_at = datetime('now', '+' || ? || ' seconds'),
            status = CASE WHEN attempt_count + 1 >= max_attempts
                          THEN 'abandoned' ELSE 'pending' END,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (error, backoff_seconds, job_id),
    )
    await db.commit()
