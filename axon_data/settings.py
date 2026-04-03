from __future__ import annotations

import aiosqlite


async def get_setting(db: aiosqlite.Connection, key: str) -> str | None:
    cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def set_setting(db: aiosqlite.Connection, key: str, value: str):
    await db.execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        (key, value),
    )
    await db.commit()


async def get_all_settings(db: aiosqlite.Connection) -> dict[str, str]:
    cur = await db.execute("SELECT key, value FROM settings")
    rows = await cur.fetchall()
    return {row["key"]: row["value"] for row in rows}
