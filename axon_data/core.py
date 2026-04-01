"""
Axon database core primitives and schema bootstrap.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite


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
    """Return an aiosqlite context manager. Use as: async with get_db() as conn."""
    return _DevBrainDB()


async def init_db():
    """Create all tables on first run."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                path        TEXT NOT NULL,
                stack       TEXT,
                description TEXT,
                status      TEXT DEFAULT 'active',
                health      INTEGER DEFAULT 100,
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
                tags        TEXT,
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
                priority    TEXT DEFAULT 'medium',
                status      TEXT DEFAULT 'open',
                due_date    TEXT,
                reminded_at TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                event_type  TEXT NOT NULL,
                summary     TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                tokens_used INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS vault_secrets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                category        TEXT DEFAULT 'general',
                username        TEXT DEFAULT '',
                password_enc    TEXT DEFAULT '',
                url             TEXT DEFAULT '',
                notes_enc       TEXT DEFAULT '',
                notes_preview   TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS resources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                kind            TEXT NOT NULL DEFAULT 'document',
                source_type     TEXT NOT NULL DEFAULT 'upload',
                source_url      TEXT DEFAULT '',
                local_path      TEXT NOT NULL,
                file_path       TEXT DEFAULT '',
                mime_type       TEXT DEFAULT '',
                size_bytes      INTEGER DEFAULT 0,
                sha256          TEXT DEFAULT '',
                status          TEXT DEFAULT 'pending',
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
                layer           TEXT NOT NULL,
                memory_type     TEXT DEFAULT '',
                title           TEXT NOT NULL,
                content         TEXT NOT NULL,
                summary         TEXT DEFAULT '',
                source          TEXT DEFAULT '',
                source_id       TEXT DEFAULT '',
                source_ref      TEXT DEFAULT '',
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                mission_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                trust_level     TEXT DEFAULT 'medium',
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
                status              TEXT DEFAULT 'idle',
                mode                TEXT DEFAULT 'read_only',
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
                event_type      TEXT NOT NULL,
                content         TEXT DEFAULT '',
                exit_code       INTEGER,
                created_at      TEXT DEFAULT (datetime('now'))
            );

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

            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                email           TEXT DEFAULT '',
                username        TEXT DEFAULT '',
                avatar_url      TEXT DEFAULT '',
                role            TEXT DEFAULT 'operator',
                status          TEXT DEFAULT 'active',
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
                role            TEXT DEFAULT 'member',
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(team_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS workspace_members (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role            TEXT DEFAULT 'member',
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(workspace_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS devices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
                name            TEXT NOT NULL,
                kind            TEXT DEFAULT 'desktop',
                host            TEXT DEFAULT '',
                runtime_state   TEXT DEFAULT 'unknown',
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

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('anthropic_api_key', ''),
                ('scan_interval_hours', '6'),
                ('morning_digest_hour', '8'),
                ('notify_desktop', 'true'),
                ('max_chat_history', '50'),
                ('projects_root', '~/Desktop'),
                ('ai_backend', 'ollama'),
                ('claude_cli_path', ''),
                ('claude_cli_session_persistence_enabled', '0'),
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
            """
        )

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
        await ensure_column(
            "resources",
            "workspace_id",
            "INTEGER REFERENCES projects(id) ON DELETE SET NULL",
        )
        await ensure_column("resource_chunks", "content", "TEXT DEFAULT ''")
        await ensure_column("resource_chunks", "token_estimate", "INTEGER DEFAULT 0")
        await ensure_column("resource_chunks", "embedding_model", "TEXT DEFAULT ''")
        await ensure_column("resource_chunks", "embedding_vector", "TEXT DEFAULT ''")
        await ensure_column("memory_items", "memory_type", "TEXT DEFAULT ''")
        await ensure_column("memory_items", "source_ref", "TEXT DEFAULT ''")
        await ensure_column(
            "memory_items",
            "mission_id",
            "INTEGER REFERENCES tasks(id) ON DELETE SET NULL",
        )
        await ensure_column("memory_items", "last_used_at", "TEXT")
        await ensure_column(
            "research_packs",
            "workspace_id",
            "INTEGER REFERENCES projects(id) ON DELETE SET NULL",
        )
        await ensure_column(
            "projects",
            "owner_user_id",
            "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        )
        await ensure_column(
            "projects",
            "team_id",
            "INTEGER REFERENCES teams(id) ON DELETE SET NULL",
        )
        await ensure_column("projects", "visibility", "TEXT DEFAULT 'personal'")
        await ensure_column(
            "tasks",
            "assigned_user_id",
            "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        )
        await ensure_column(
            "tasks",
            "created_by_user_id",
            "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        )
        await ensure_column(
            "tasks",
            "owner_user_id",
            "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        )
        await ensure_column("tasks", "due_at", "TEXT")
        await db.commit()

    print(f"[Axon] Database initialised at {DB_PATH}")
