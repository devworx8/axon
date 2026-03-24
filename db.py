"""
Axon — Database layer (SQLite via aiosqlite)
All persistent state lives here.
"""

import aiosqlite
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH = Path.home() / ".devbrain" / "devbrain.db"


class _DevBrainDB:
    """Async context manager that yields a configured aiosqlite connection."""
    async def __aenter__(self) -> aiosqlite.Connection:
        self._conn = await aiosqlite.connect(DB_PATH)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def __aexit__(self, *args):
        await self._conn.close()


def get_db():
    """Return an aiosqlite context manager. Use as: async with devdb.get_db() as conn:"""
    return _DevBrainDB()


async def init_db():
    """Create all tables on first run."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                path        TEXT NOT NULL,
                stack       TEXT,          -- detected stack: nextjs|react-native|python|etc
                description TEXT,
                status      TEXT DEFAULT 'active',   -- active|paused|done|archived
                health      INTEGER DEFAULT 100,      -- 0-100 score
                git_branch  TEXT,
                last_commit TEXT,
                last_commit_age_days REAL,
                todo_count  INTEGER DEFAULT 0,
                note        TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS prompts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                tags        TEXT,          -- comma-separated
                pinned      INTEGER DEFAULT 0,
                used_count  INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                detail      TEXT,
                priority    TEXT DEFAULT 'medium',  -- low|medium|high|urgent
                status      TEXT DEFAULT 'open',    -- open|in_progress|done|cancelled
                due_date    TEXT,
                reminded_at TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                event_type  TEXT NOT NULL,   -- scan|chat|reminder|digest|task_added|prompt_saved
                summary     TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                role        TEXT NOT NULL,   -- user|assistant
                content     TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            -- Encrypted secret vault
            CREATE TABLE IF NOT EXISTS vault_secrets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                category        TEXT DEFAULT 'general',  -- login|card|note|key|general
                username        TEXT DEFAULT '',
                password_enc    TEXT DEFAULT '',          -- AES-256-GCM encrypted
                url             TEXT DEFAULT '',
                notes_enc       TEXT DEFAULT '',          -- AES-256-GCM encrypted
                notes_preview   TEXT DEFAULT '',          -- unencrypted teaser (first 30 chars)
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            -- Default settings
            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('anthropic_api_key', ''),
                ('scan_interval_hours', '6'),
                ('morning_digest_hour', '8'),
                ('notify_desktop', 'true'),
                ('max_chat_history', '50'),
                ('projects_root', '~/Desktop'),
                ('ai_backend', 'ollama'),
                ('claude_cli_path', ''),
                ('vault_salt', ''),
                ('vault_pw_hash', ''),
                ('vault_totp_enc', ''),
                ('github_token', ''),
                ('slack_webhook_url', ''),
                ('webhook_urls', ''),
                ('webhook_secret', ''),
                ('azure_speech_key', ''),
                ('azure_speech_region', 'eastus');
        """)
        await db.commit()
    print(f"[Axon] Database initialised at {DB_PATH}")


# ─── Projects ────────────────────────────────────────────────────────────────

async def upsert_project(db: aiosqlite.Connection, data: dict) -> int:
    await db.execute("""
        INSERT INTO projects (name, path, stack, description, git_branch, last_commit,
                              last_commit_age_days, todo_count, health, updated_at)
        VALUES (:name, :path, :stack, :description, :git_branch, :last_commit,
                :last_commit_age_days, :todo_count, :health, datetime('now'))
        ON CONFLICT(name) DO UPDATE SET
            path                 = excluded.path,
            stack                = excluded.stack,
            git_branch           = excluded.git_branch,
            last_commit          = excluded.last_commit,
            last_commit_age_days = excluded.last_commit_age_days,
            todo_count           = excluded.todo_count,
            health               = excluded.health,
            updated_at           = datetime('now')
    """, data)
    await db.commit()
    cur = await db.execute("SELECT id FROM projects WHERE name = ?", (data["name"],))
    row = await cur.fetchone()
    return row["id"]


async def get_projects(db: aiosqlite.Connection, status: Optional[str] = None):
    if status:
        cur = await db.execute(
            "SELECT * FROM projects WHERE status = ? ORDER BY health ASC, name ASC", (status,)
        )
    else:
        cur = await db.execute("SELECT * FROM projects ORDER BY health ASC, name ASC")
    return await cur.fetchall()


async def get_project(db: aiosqlite.Connection, project_id: int):
    cur = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return await cur.fetchone()


async def update_project_note(db: aiosqlite.Connection, project_id: int, note: str):
    await db.execute(
        "UPDATE projects SET note = ?, updated_at = datetime('now') WHERE id = ?",
        (note, project_id)
    )
    await db.commit()


async def update_project_status(db: aiosqlite.Connection, project_id: int, status: str):
    await db.execute(
        "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, project_id)
    )
    await db.commit()


# ─── Prompts ─────────────────────────────────────────────────────────────────

async def save_prompt(db: aiosqlite.Connection, project_id: Optional[int], title: str,
                      content: str, tags: str = "") -> int:
    cur = await db.execute("""
        INSERT INTO prompts (project_id, title, content, tags)
        VALUES (?, ?, ?, ?)
    """, (project_id, title, content, tags))
    await db.commit()
    return cur.lastrowid


async def get_prompts(db: aiosqlite.Connection, project_id: Optional[int] = None):
    if project_id is not None:
        cur = await db.execute(
            "SELECT * FROM prompts WHERE project_id = ? ORDER BY pinned DESC, used_count DESC, created_at DESC",
            (project_id,)
        )
    else:
        cur = await db.execute(
            "SELECT p.*, pr.name as project_name FROM prompts p "
            "LEFT JOIN projects pr ON p.project_id = pr.id "
            "ORDER BY pinned DESC, used_count DESC, created_at DESC"
        )
    return await cur.fetchall()


async def increment_prompt_usage(db: aiosqlite.Connection, prompt_id: int):
    await db.execute(
        "UPDATE prompts SET used_count = used_count + 1, updated_at = datetime('now') WHERE id = ?",
        (prompt_id,)
    )
    await db.commit()


async def delete_prompt(db: aiosqlite.Connection, prompt_id: int):
    await db.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
    await db.commit()


# ─── Tasks ───────────────────────────────────────────────────────────────────

async def add_task(db: aiosqlite.Connection, project_id: Optional[int], title: str,
                   detail: str = "", priority: str = "medium", due_date: Optional[str] = None) -> int:
    cur = await db.execute("""
        INSERT INTO tasks (project_id, title, detail, priority, due_date)
        VALUES (?, ?, ?, ?, ?)
    """, (project_id, title, detail, priority, due_date))
    await db.commit()
    return cur.lastrowid


async def get_tasks(db: aiosqlite.Connection, project_id: Optional[int] = None,
                    status: Optional[str] = "open"):
    clauses = []
    params = []
    if project_id is not None:
        clauses.append("t.project_id = ?")
        params.append(project_id)
    if status:
        clauses.append("t.status = ?")
        params.append(status)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    cur = await db.execute(f"""
        SELECT t.*, pr.name as project_name FROM tasks t
        LEFT JOIN projects pr ON t.project_id = pr.id
        {where}
        ORDER BY
            CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2 ELSE 3 END,
            t.due_date ASC NULLS LAST,
            t.created_at ASC
    """, params)
    return await cur.fetchall()


async def update_task_status(db: aiosqlite.Connection, task_id: int, status: str):
    await db.execute(
        "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, task_id)
    )
    await db.commit()


# ─── Activity Log ─────────────────────────────────────────────────────────────

async def log_event(db: aiosqlite.Connection, event_type: str, summary: str,
                    project_id: Optional[int] = None):
    await db.execute(
        "INSERT INTO activity_log (project_id, event_type, summary) VALUES (?, ?, ?)",
        (project_id, event_type, summary)
    )
    await db.commit()


async def get_activity(db: aiosqlite.Connection, limit: int = 50):
    cur = await db.execute("""
        SELECT a.*, p.name as project_name FROM activity_log a
        LEFT JOIN projects p ON a.project_id = p.id
        ORDER BY a.created_at DESC LIMIT ?
    """, (limit,))
    return await cur.fetchall()


# ─── Chat History ─────────────────────────────────────────────────────────────

async def save_message(db: aiosqlite.Connection, role: str, content: str,
                       project_id: Optional[int] = None, tokens: int = 0):
    await db.execute("""
        INSERT INTO chat_history (project_id, role, content, tokens_used)
        VALUES (?, ?, ?, ?)
    """, (project_id, role, content, tokens))
    await db.commit()


async def get_chat_history(db: aiosqlite.Connection, project_id: Optional[int] = None,
                           limit: int = 20):
    if project_id is not None:
        cur = await db.execute(
            "SELECT * FROM chat_history WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        )
    else:
        cur = await db.execute(
            "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    rows = await cur.fetchall()
    return list(reversed(rows))  # oldest first for LLM context


async def clear_chat_history(db: aiosqlite.Connection, project_id: Optional[int] = None):
    if project_id is not None:
        await db.execute("DELETE FROM chat_history WHERE project_id = ?", (project_id,))
    else:
        await db.execute("DELETE FROM chat_history")
    await db.commit()


# ─── Settings ────────────────────────────────────────────────────────────────

async def get_setting(db: aiosqlite.Connection, key: str) -> Optional[str]:
    cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row else None


async def set_setting(db: aiosqlite.Connection, key: str, value: str):
    await db.execute("""
        INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
    """, (key, value))
    await db.commit()


async def get_all_settings(db: aiosqlite.Connection) -> dict:
    cur = await db.execute("SELECT key, value FROM settings")
    rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows}
