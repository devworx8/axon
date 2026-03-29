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
                meta_json   TEXT DEFAULT '{}',
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
                event_type  TEXT NOT NULL,   -- scan|chat|reminder|digest|task_added|prompt_saved|resource_added|resource_processed|resource_used|resource_failed
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

            CREATE TABLE IF NOT EXISTS resources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                kind            TEXT NOT NULL DEFAULT 'document', -- document|image
                source_type     TEXT NOT NULL DEFAULT 'upload',   -- upload|url
                source_url      TEXT DEFAULT '',
                local_path      TEXT NOT NULL,
                file_path       TEXT DEFAULT '',
                mime_type       TEXT DEFAULT '',
                size_bytes      INTEGER DEFAULT 0,
                sha256          TEXT DEFAULT '',
                status          TEXT DEFAULT 'pending',           -- pending|ready|processed|failed
                summary         TEXT DEFAULT '',
                preview_text    TEXT DEFAULT '',
                trust_level     TEXT DEFAULT 'medium',
                pinned          INTEGER DEFAULT 0,
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                meta_json       TEXT DEFAULT '{}',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                last_used_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS resource_chunks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id     INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                chunk_index     INTEGER NOT NULL,
                text            TEXT NOT NULL,
                content         TEXT DEFAULT '',
                token_estimate  INTEGER DEFAULT 0,
                embedding_model TEXT DEFAULT '',
                embedding_json  TEXT DEFAULT '',
                embedding_vector TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key      TEXT NOT NULL UNIQUE,
                layer           TEXT NOT NULL,                  -- resource|workspace|user|mission
                memory_type     TEXT DEFAULT '',
                title           TEXT NOT NULL,
                content         TEXT NOT NULL,
                summary         TEXT DEFAULT '',
                source          TEXT DEFAULT '',
                source_id       TEXT DEFAULT '',
                source_ref      TEXT DEFAULT '',
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                mission_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                trust_level     TEXT DEFAULT 'medium',         -- high|medium|low
                relevance_score REAL DEFAULT 0,
                embedding_json  TEXT DEFAULT '',
                meta_json       TEXT DEFAULT '{}',
                pinned          INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                last_accessed_at TEXT,
                last_used_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS research_packs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                description     TEXT DEFAULT '',
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                pinned          INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS research_pack_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pack_id         INTEGER NOT NULL REFERENCES research_packs(id) ON DELETE CASCADE,
                resource_id     INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(pack_id, resource_id)
            );

            CREATE TABLE IF NOT EXISTS memory_links (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                from_memory_id  INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                to_memory_id    INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                link_type       TEXT NOT NULL DEFAULT 'related',
                weight          REAL DEFAULT 1.0,
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(from_memory_id, to_memory_id, link_type)
            );

            CREATE TABLE IF NOT EXISTS terminal_sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                title               TEXT NOT NULL,
                workspace_id        INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                status              TEXT DEFAULT 'idle',     -- idle|pending_approval|running|completed|failed|stopped
                mode                TEXT DEFAULT 'read_only', -- read_only|approval_required|simulation
                cwd                 TEXT DEFAULT '',
                pending_command     TEXT DEFAULT '',
                active_command      TEXT DEFAULT '',
                pid                 INTEGER DEFAULT 0,
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now')),
                last_output_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS terminal_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES terminal_sessions(id) ON DELETE CASCADE,
                event_type      TEXT NOT NULL,   -- command|output|status|approval|error
                content         TEXT DEFAULT '',
                exit_code       INTEGER,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            -- ── Webhook retry queue ─────────────────────────────────────
            CREATE TABLE IF NOT EXISTS webhook_jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_url     TEXT NOT NULL,
                event           TEXT NOT NULL,
                payload_json    TEXT NOT NULL,
                secret          TEXT DEFAULT '',
                status          TEXT DEFAULT 'pending',
                attempt_count   INTEGER DEFAULT 0,
                max_attempts    INTEGER DEFAULT 3,
                next_retry_at   TEXT DEFAULT (datetime('now')),
                last_error      TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            -- ── User / Account foundations ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT DEFAULT '',
                username        TEXT DEFAULT '',
                avatar_url      TEXT DEFAULT '',
                role            TEXT DEFAULT 'operator',  -- operator|admin|viewer
                status          TEXT DEFAULT 'active',    -- active|inactive|suspended
                is_active       INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                display_name         TEXT DEFAULT '',
                bio                  TEXT DEFAULT '',
                preferences_json     TEXT DEFAULT '{}',
                timezone             TEXT DEFAULT 'UTC',
                default_workspace_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS teams (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                slug            TEXT DEFAULT '',
                description     TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS team_members (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id         INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role            TEXT DEFAULT 'member',  -- owner|admin|member
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(team_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS workspace_members (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role            TEXT DEFAULT 'member',  -- owner|editor|viewer
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(workspace_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS devices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
                name            TEXT NOT NULL,
                kind            TEXT DEFAULT 'desktop',  -- desktop|laptop|server|mobile
                host            TEXT DEFAULT '',
                runtime_state   TEXT DEFAULT 'unknown',  -- online|offline|unknown
                last_seen_at    TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                token_hash      TEXT NOT NULL,
                device_id       INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                expires_at      TEXT NOT NULL,
                created_at      TEXT DEFAULT (datetime('now'))
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
                ('azure_speech_region', 'eastus'),
                ('resource_storage_path', '~/.devbrain/resources'),
                ('resource_upload_max_mb', '20'),
                ('resource_url_import_enabled', '1'),
                ('live_feed_enabled', '1'),
                ('terminal_default_mode', 'read_only'),
                ('terminal_command_timeout_seconds', '25');
        """)
        async def ensure_column(table: str, column: str, definition: str):
            cur = await db.execute(f"PRAGMA table_info({table})")
            rows = await cur.fetchall()
            existing = {row["name"] for row in rows}
            if column not in existing:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        await ensure_column("prompts", "meta_json", "TEXT DEFAULT '{}'")
        await ensure_column("memory_items", "pinned", "INTEGER DEFAULT 0")
        await ensure_column("resources", "file_path", "TEXT DEFAULT ''")
        await ensure_column("resources", "trust_level", "TEXT DEFAULT 'medium'")
        await ensure_column("resources", "pinned", "INTEGER DEFAULT 0")
        await ensure_column("resources", "workspace_id", "INTEGER REFERENCES projects(id) ON DELETE SET NULL")
        await ensure_column("resource_chunks", "content", "TEXT DEFAULT ''")
        await ensure_column("resource_chunks", "token_estimate", "INTEGER DEFAULT 0")
        await ensure_column("resource_chunks", "embedding_model", "TEXT DEFAULT ''")
        await ensure_column("resource_chunks", "embedding_vector", "TEXT DEFAULT ''")
        await ensure_column("memory_items", "memory_type", "TEXT DEFAULT ''")
        await ensure_column("memory_items", "source_ref", "TEXT DEFAULT ''")
        await ensure_column("memory_items", "mission_id", "INTEGER REFERENCES tasks(id) ON DELETE SET NULL")
        await ensure_column("memory_items", "last_used_at", "TEXT")
        await ensure_column("research_packs", "workspace_id", "INTEGER REFERENCES projects(id) ON DELETE SET NULL")
        # User/account extension columns on existing tables
        await ensure_column("projects", "owner_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
        await ensure_column("projects", "team_id", "INTEGER REFERENCES teams(id) ON DELETE SET NULL")
        await ensure_column("projects", "visibility", "TEXT DEFAULT 'personal'")  # personal|shared|team
        await ensure_column("tasks", "assigned_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
        await ensure_column("tasks", "created_by_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
        await ensure_column("tasks", "owner_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
        await ensure_column("tasks", "due_at", "TEXT")
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
                      content: str, tags: str = "", meta_json: str = "{}") -> int:
    cur = await db.execute("""
        INSERT INTO prompts (project_id, title, content, tags, meta_json)
        VALUES (?, ?, ?, ?, ?)
    """, (project_id, title, content, tags, meta_json))
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


async def get_prompt(db: aiosqlite.Connection, prompt_id: int):
    cur = await db.execute(
        "SELECT p.*, pr.name as project_name FROM prompts p LEFT JOIN projects pr ON p.project_id = pr.id WHERE p.id = ?",
        (prompt_id,),
    )
    return await cur.fetchone()


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


async def update_task(db: aiosqlite.Connection, task_id: int, **fields):
    allowed = {"title", "detail", "priority", "status", "due_date", "project_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [task_id]
    await db.execute(
        f"UPDATE tasks SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
        params
    )
    await db.commit()


async def delete_task(db: aiosqlite.Connection, task_id: int):
    await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
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


# ─── Resources ───────────────────────────────────────────────────────────────

async def add_resource(
    db: aiosqlite.Connection,
    *,
    title: str,
    kind: str,
    source_type: str,
    source_url: str,
    local_path: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
    status: str = "pending",
    summary: str = "",
    preview_text: str = "",
    trust_level: str = "medium",
    pinned: bool = False,
    workspace_id: Optional[int] = None,
    meta_json: str = "{}",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO resources (
            title, kind, source_type, source_url, local_path, file_path, mime_type,
            size_bytes, sha256, status, summary, preview_text, trust_level, pinned, workspace_id, meta_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title, kind, source_type, source_url, local_path, local_path, mime_type,
            size_bytes, sha256, status, summary, preview_text,
            trust_level, 1 if pinned else 0, workspace_id, meta_json,
        ),
    )
    await db.commit()
    return cur.lastrowid


async def update_resource(db: aiosqlite.Connection, resource_id: int, **fields):
    if not fields:
        return
    if "local_path" in fields and "file_path" not in fields:
        fields["file_path"] = fields["local_path"]
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values())
    values.append(resource_id)
    await db.execute(
        f"UPDATE resources SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def list_resources(
    db: aiosqlite.Connection,
    *,
    search: str = "",
    kind: str = "",
    source_type: str = "",
    status: str = "",
    limit: int = 200,
):
    clauses = []
    params = []
    if search.strip():
        clauses.append("(title LIKE ? OR preview_text LIKE ? OR source_url LIKE ?)")
        token = f"%{search.strip()}%"
        params.extend([token, token, token])
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    cur = await db.execute(
        f"""
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        {where}
        ORDER BY r.pinned DESC, COALESCE(r.last_used_at, r.updated_at) DESC, r.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_resource(db: aiosqlite.Connection, resource_id: int):
    cur = await db.execute(
        """
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        WHERE r.id = ?
        """,
        (resource_id,),
    )
    return await cur.fetchone()


async def get_resources_by_ids(db: aiosqlite.Connection, resource_ids: list[int]):
    if not resource_ids:
        return []
    placeholders = ",".join("?" for _ in resource_ids)
    cur = await db.execute(
        f"""
        SELECT r.*, p.name AS workspace_name
        FROM resources r
        LEFT JOIN projects p ON p.id = r.workspace_id
        WHERE r.id IN ({placeholders})
        ORDER BY r.created_at ASC
        """,
        resource_ids,
    )
    return await cur.fetchall()


async def delete_resource(db: aiosqlite.Connection, resource_id: int):
    await db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    await db.commit()


async def replace_resource_chunks(
    db: aiosqlite.Connection,
    resource_id: int,
    chunks: list[dict],
    *,
    embedding_model: str = "",
):
    await db.execute("DELETE FROM resource_chunks WHERE resource_id = ?", (resource_id,))
    for chunk in chunks:
        text = chunk.get("text") or chunk.get("content") or ""
        embedding_json = chunk.get("embedding_json", "") or chunk.get("embedding_vector", "")
        await db.execute(
            """
            INSERT INTO resource_chunks (
                resource_id, chunk_index, text, content, token_estimate,
                embedding_model, embedding_json, embedding_vector
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resource_id,
                chunk.get("chunk_index", 0),
                text,
                text,
                chunk.get("token_estimate", max(1, len(text) // 4) if text else 0),
                chunk.get("embedding_model", embedding_model),
                embedding_json,
                embedding_json,
            ),
        )
    await db.commit()


async def get_resource_chunks(db: aiosqlite.Connection, resource_id: int):
    cur = await db.execute(
        "SELECT * FROM resource_chunks WHERE resource_id = ? ORDER BY chunk_index ASC",
        (resource_id,),
    )
    return await cur.fetchall()


async def touch_resource_used(db: aiosqlite.Connection, resource_id: int):
    await db.execute(
        "UPDATE resources SET last_used_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (resource_id,),
    )
    await db.commit()


# ─── Memory Engine ───────────────────────────────────────────────────────────

async def upsert_memory_item(
    db: aiosqlite.Connection,
    *,
    memory_key: str,
    layer: str,
    title: str,
    content: str,
    summary: str = "",
    source: str = "",
    source_id: str = "",
    workspace_id: Optional[int] = None,
    mission_id: Optional[int] = None,
    trust_level: str = "medium",
    relevance_score: float = 0.0,
    embedding_json: str = "",
    meta_json: str = "{}",
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO memory_items (
            memory_key, layer, memory_type, title, content, summary, source, source_id, source_ref,
            workspace_id, mission_id, trust_level, relevance_score, embedding_json, meta_json,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(memory_key) DO UPDATE SET
            layer = excluded.layer,
            memory_type = excluded.memory_type,
            title = excluded.title,
            content = excluded.content,
            summary = excluded.summary,
            source = excluded.source,
            source_id = excluded.source_id,
            source_ref = excluded.source_ref,
            workspace_id = excluded.workspace_id,
            mission_id = excluded.mission_id,
            trust_level = excluded.trust_level,
            relevance_score = excluded.relevance_score,
            embedding_json = excluded.embedding_json,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            memory_key,
            layer,
            layer,
            title,
            content,
            summary,
            source,
            source_id,
            source or source_id,
            workspace_id,
            mission_id,
            trust_level,
            relevance_score,
            embedding_json,
            meta_json,
        ),
    )
    if commit:
        await db.commit()


async def get_memory_item(db: aiosqlite.Connection, memory_id: int):
    cur = await db.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,))
    return await cur.fetchone()


async def get_memory_item_by_key(db: aiosqlite.Connection, memory_key: str):
    cur = await db.execute("SELECT * FROM memory_items WHERE memory_key = ?", (memory_key,))
    return await cur.fetchone()


async def list_memory_items(
    db: aiosqlite.Connection,
    *,
    layer: str = "",
    workspace_id: Optional[int] = None,
    limit: int = 500,
):
    clauses = []
    params: list[object] = []
    if layer:
        clauses.append("layer = ?")
        params.append(layer)
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT * FROM memory_items
        {where}
        ORDER BY COALESCE(last_accessed_at, updated_at) DESC, updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def delete_stale_memory_items(
    db: aiosqlite.Connection,
    *,
    layer: str,
    keep_keys: list[str],
    commit: bool = True,
):
    if keep_keys:
        placeholders = ",".join("?" for _ in keep_keys)
        await db.execute(
            f"DELETE FROM memory_items WHERE layer = ? AND memory_key NOT IN ({placeholders})",
            (layer, *keep_keys),
        )
    else:
        await db.execute("DELETE FROM memory_items WHERE layer = ?", (layer,))
    if commit:
        await db.commit()


async def touch_memory_item(db: aiosqlite.Connection, memory_id: int):
    await db.execute(
        "UPDATE memory_items SET last_accessed_at = datetime('now'), last_used_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (memory_id,),
    )
    await db.commit()


async def count_memory_items_by_layer(db: aiosqlite.Connection) -> dict[str, int]:
    cur = await db.execute(
        "SELECT layer, COUNT(*) AS total FROM memory_items GROUP BY layer"
    )
    rows = await cur.fetchall()
    return {row["layer"]: row["total"] for row in rows}


async def update_memory_item_state(
    db: aiosqlite.Connection,
    memory_id: int,
    *,
    pinned: Optional[bool] = None,
    trust_level: Optional[str] = None,
):
    fields = []
    values: list[object] = []
    if pinned is not None:
        fields.append("pinned = ?")
        values.append(1 if pinned else 0)
    if trust_level is not None:
        fields.append("trust_level = ?")
        values.append(trust_level)
    if not fields:
        return
    values.append(memory_id)
    await db.execute(
        f"UPDATE memory_items SET {', '.join(fields)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def list_memory_items_filtered(
    db: aiosqlite.Connection,
    *,
    search: str = "",
    layer: str = "",
    trust_level: str = "",
    pinned: Optional[bool] = None,
    workspace_id: Optional[int] = None,
    limit: int = 200,
):
    clauses = []
    params: list[object] = []
    if search.strip():
        token = f"%{search.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR content LIKE ? OR source LIKE ?)")
        params.extend([token, token, token, token])
    if layer:
        clauses.append("layer = ?")
        params.append(layer)
    if trust_level:
        clauses.append("trust_level = ?")
        params.append(trust_level)
    if pinned is not None:
        clauses.append("pinned = ?")
        params.append(1 if pinned else 0)
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT mi.*, p.name as workspace_name
        FROM memory_items mi
        LEFT JOIN projects p ON mi.workspace_id = p.id
        {where}
        ORDER BY mi.pinned DESC,
                 COALESCE(mi.last_accessed_at, mi.updated_at) DESC,
                 mi.updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


# ─── Research packs ──────────────────────────────────────────────────────────

async def create_research_pack(
    db: aiosqlite.Connection,
    *,
    title: str,
    description: str = "",
    workspace_id: Optional[int] = None,
    pinned: bool = False,
) -> int:
    cur = await db.execute(
        """
        INSERT INTO research_packs (title, description, workspace_id, pinned)
        VALUES (?, ?, ?, ?)
        """,
        (title, description, workspace_id, 1 if pinned else 0),
    )
    await db.commit()
    return cur.lastrowid


async def list_research_packs(db: aiosqlite.Connection, *, search: str = "", limit: int = 100):
    clauses = []
    params: list[object] = []
    if search.strip():
        token = f"%{search.strip()}%"
        clauses.append("(rp.title LIKE ? OR rp.description LIKE ?)")
        params.extend([token, token])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT
            rp.*,
            p.name AS workspace_name,
            COUNT(rpi.resource_id) AS resource_count
        FROM research_packs rp
        LEFT JOIN projects p ON p.id = rp.workspace_id
        LEFT JOIN research_pack_items rpi ON rpi.pack_id = rp.id
        {where}
        GROUP BY rp.id
        ORDER BY rp.pinned DESC, rp.updated_at DESC, rp.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_research_pack(db: aiosqlite.Connection, pack_id: int):
    cur = await db.execute(
        """
        SELECT
            rp.*,
            p.name AS workspace_name,
            COUNT(rpi.resource_id) AS resource_count
        FROM research_packs rp
        LEFT JOIN projects p ON p.id = rp.workspace_id
        LEFT JOIN research_pack_items rpi ON rpi.pack_id = rp.id
        WHERE rp.id = ?
        GROUP BY rp.id
        """,
        (pack_id,),
    )
    return await cur.fetchone()


async def update_research_pack(db: aiosqlite.Connection, pack_id: int, **fields):
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values()) + [pack_id]
    await db.execute(
        f"UPDATE research_packs SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def delete_research_pack(db: aiosqlite.Connection, pack_id: int):
    await db.execute("DELETE FROM research_packs WHERE id = ?", (pack_id,))
    await db.commit()


async def add_research_pack_items(db: aiosqlite.Connection, pack_id: int, resource_ids: list[int]):
    for resource_id in resource_ids:
        await db.execute(
            """
            INSERT OR IGNORE INTO research_pack_items (pack_id, resource_id)
            VALUES (?, ?)
            """,
            (pack_id, resource_id),
        )
    await db.execute(
        "UPDATE research_packs SET updated_at = datetime('now') WHERE id = ?",
        (pack_id,),
    )
    await db.commit()


async def remove_research_pack_item(db: aiosqlite.Connection, pack_id: int, resource_id: int):
    await db.execute(
        "DELETE FROM research_pack_items WHERE pack_id = ? AND resource_id = ?",
        (pack_id, resource_id),
    )
    await db.execute(
        "UPDATE research_packs SET updated_at = datetime('now') WHERE id = ?",
        (pack_id,),
    )
    await db.commit()


async def get_research_pack_items(db: aiosqlite.Connection, pack_id: int):
    cur = await db.execute(
        """
        SELECT
            rpi.pack_id,
            r.id,
            r.title,
            r.kind,
            r.source_type,
            r.source_url,
            r.local_path,
            r.mime_type,
            r.size_bytes,
            r.sha256,
            r.status,
            r.summary,
            r.preview_text,
            r.trust_level,
            r.pinned,
            r.workspace_id,
            r.meta_json,
            r.created_at,
            r.updated_at,
            r.last_used_at
        FROM research_pack_items rpi
        JOIN resources r ON r.id = rpi.resource_id
        WHERE rpi.pack_id = ?
        ORDER BY rpi.created_at ASC, r.created_at ASC
        """,
        (pack_id,),
    )
    return await cur.fetchall()


# ─── Memory links ────────────────────────────────────────────────────────────

async def upsert_memory_link(
    db: aiosqlite.Connection,
    *,
    from_memory_id: int,
    to_memory_id: int,
    link_type: str = "related",
    weight: float = 1.0,
):
    await db.execute(
        """
        INSERT INTO memory_links (from_memory_id, to_memory_id, link_type, weight)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(from_memory_id, to_memory_id, link_type)
        DO UPDATE SET weight = excluded.weight
        """,
        (from_memory_id, to_memory_id, link_type, weight),
    )
    await db.commit()


async def list_memory_links(db: aiosqlite.Connection, memory_id: int, *, limit: int = 50):
    cur = await db.execute(
        """
        SELECT ml.*, src.title AS from_title, dst.title AS to_title
        FROM memory_links ml
        LEFT JOIN memory_items src ON src.id = ml.from_memory_id
        LEFT JOIN memory_items dst ON dst.id = ml.to_memory_id
        WHERE ml.from_memory_id = ? OR ml.to_memory_id = ?
        ORDER BY ml.weight DESC, ml.created_at DESC
        LIMIT ?
        """,
        (memory_id, memory_id, limit),
    )
    return await cur.fetchall()


# ─── Terminal sessions ──────────────────────────────────────────────────────

async def create_terminal_session(
    db: aiosqlite.Connection,
    *,
    title: str,
    workspace_id: Optional[int] = None,
    mode: str = "read_only",
    cwd: str = "",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO terminal_sessions (title, workspace_id, status, mode, cwd)
        VALUES (?, ?, 'idle', ?, ?)
        """,
        (title, workspace_id, mode, cwd),
    )
    await db.commit()
    return cur.lastrowid


async def list_terminal_sessions(db: aiosqlite.Connection, *, workspace_id: Optional[int] = None, limit: int = 30):
    clauses = []
    params: list[object] = []
    if workspace_id is not None:
        clauses.append("ts.workspace_id = ?")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT ts.*, p.name AS workspace_name,
               (SELECT COUNT(*) FROM terminal_events te WHERE te.session_id = ts.id) AS event_count
        FROM terminal_sessions ts
        LEFT JOIN projects p ON p.id = ts.workspace_id
        {where}
        ORDER BY ts.updated_at DESC, ts.created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def get_terminal_session(db: aiosqlite.Connection, session_id: int):
    cur = await db.execute(
        """
        SELECT ts.*, p.name AS workspace_name,
               (SELECT COUNT(*) FROM terminal_events te WHERE te.session_id = ts.id) AS event_count
        FROM terminal_sessions ts
        LEFT JOIN projects p ON p.id = ts.workspace_id
        WHERE ts.id = ?
        """,
        (session_id,),
    )
    return await cur.fetchone()


async def update_terminal_session(db: aiosqlite.Connection, session_id: int, **fields):
    if not fields:
        return
    set_clauses = [f"{key} = ?" for key in fields]
    values = list(fields.values()) + [session_id]
    await db.execute(
        f"UPDATE terminal_sessions SET {', '.join(set_clauses)}, updated_at = datetime('now') WHERE id = ?",
        values,
    )
    await db.commit()


async def add_terminal_event(
    db: aiosqlite.Connection,
    *,
    session_id: int,
    event_type: str,
    content: str = "",
    exit_code: Optional[int] = None,
):
    await db.execute(
        """
        INSERT INTO terminal_events (session_id, event_type, content, exit_code)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, event_type, content, exit_code),
    )
    await db.execute(
        """
        UPDATE terminal_sessions
        SET last_output_at = datetime('now'), updated_at = datetime('now')
        WHERE id = ?
        """,
        (session_id,),
    )
    await db.commit()


async def list_terminal_events(db: aiosqlite.Connection, session_id: int, *, limit: int = 200):
    cur = await db.execute(
        """
        SELECT * FROM terminal_events
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = await cur.fetchall()
    return list(reversed(rows))


# ─── Webhook Job Queue ────────────────────────────────────────────────────────

async def enqueue_webhook(db: aiosqlite.Connection, url: str, event: str,
                          payload_json: str, secret: str = "") -> int:
    cur = await db.execute(
        """INSERT INTO webhook_jobs (webhook_url, event, payload_json, secret)
           VALUES (?, ?, ?, ?)""",
        (url, event, payload_json, secret),
    )
    await db.commit()
    return cur.lastrowid


async def get_pending_webhooks(db: aiosqlite.Connection, limit: int = 20):
    cur = await db.execute(
        """SELECT * FROM webhook_jobs
           WHERE status = 'pending' AND next_retry_at <= datetime('now')
           ORDER BY created_at ASC LIMIT ?""",
        (limit,),
    )
    return await cur.fetchall()


async def mark_webhook_sent(db: aiosqlite.Connection, job_id: int):
    await db.execute(
        """UPDATE webhook_jobs SET status = 'sent', updated_at = datetime('now')
           WHERE id = ?""",
        (job_id,),
    )
    await db.commit()


async def mark_webhook_failed(db: aiosqlite.Connection, job_id: int,
                               error: str, backoff_seconds: int):
    await db.execute(
        """UPDATE webhook_jobs
           SET attempt_count = attempt_count + 1,
               last_error = ?,
               next_retry_at = datetime('now', '+' || ? || ' seconds'),
               status = CASE WHEN attempt_count + 1 >= max_attempts
                             THEN 'abandoned' ELSE 'pending' END,
               updated_at = datetime('now')
           WHERE id = ?""",
        (error, backoff_seconds, job_id),
    )
    await db.commit()