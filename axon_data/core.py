"""
Axon database core primitives and schema bootstrap.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from axon_data.aiosqlite_compat import ensure_aiosqlite_compat
from axon_data.core_migrations import apply_core_migrations
from axon_data.default_settings_seed import seed_default_settings

DB_PATH = Path.home() / ".devbrain" / "devbrain.db"

ensure_aiosqlite_compat()


def _db_connect_path() -> str:
    """Normalize the configured database path for sqlite connectors."""
    return str(DB_PATH)


class _DevBrainDB:
    """Async context manager that yields a configured aiosqlite connection."""

    async def __aenter__(self) -> aiosqlite.Connection:
        self._conn = await aiosqlite.connect(_db_connect_path())
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    async def __aexit__(self, *args):
        await self._conn.close()


def get_db() -> _DevBrainDB:
    """Return an aiosqlite context manager. Use as: async with get_db() as conn."""
    return _DevBrainDB()


async def init_db():
    """Create all tables on first run."""
    async with aiosqlite.connect(_db_connect_path()) as db:
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

            CREATE TABLE IF NOT EXISTS approval_grants (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                action_fingerprint  TEXT NOT NULL UNIQUE,
                action_type         TEXT NOT NULL,
                scope               TEXT NOT NULL DEFAULT 'persist',
                workspace_id        INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                repo_root           TEXT DEFAULT '',
                summary             TEXT DEFAULT '',
                command_preview     TEXT DEFAULT '',
                destructive         INTEGER DEFAULT 0,
                meta_json           TEXT DEFAULT '{}',
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now')),
                expires_at          TEXT
            );

            CREATE TABLE IF NOT EXISTS workspace_snapshots (
                workspace_id        INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                snapshot_key        TEXT NOT NULL,
                revision            TEXT NOT NULL,
                context_block       TEXT DEFAULT '',
                data_json           TEXT DEFAULT '{}',
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS thread_summaries (
                thread_key          TEXT PRIMARY KEY,
                workspace_id        INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                revision            TEXT NOT NULL,
                summary             TEXT NOT NULL,
                message_count       INTEGER DEFAULT 0,
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS external_fetch_cache (
                cache_key           TEXT PRIMARY KEY,
                url                 TEXT NOT NULL UNIQUE,
                title               TEXT DEFAULT '',
                content             TEXT DEFAULT '',
                summary             TEXT DEFAULT '',
                status_code         INTEGER DEFAULT 0,
                mime_type           TEXT DEFAULT '',
                workspace_id        INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                meta_json           TEXT DEFAULT '{}',
                fetched_at          TEXT DEFAULT (datetime('now')),
                expires_at          TEXT,
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS error_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source          TEXT NOT NULL DEFAULT 'sentry',
                event_id        TEXT NOT NULL DEFAULT '',
                title           TEXT NOT NULL DEFAULT '',
                level           TEXT NOT NULL DEFAULT 'error',
                fingerprint     TEXT DEFAULT '',
                occurrence_count INTEGER DEFAULT 1,
                first_seen_at   TEXT DEFAULT (datetime('now')),
                last_seen_at    TEXT DEFAULT (datetime('now')),
                status          TEXT DEFAULT 'new',
                fix_session_id  TEXT DEFAULT '',
                project_name    TEXT DEFAULT '',
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                meta_json       TEXT DEFAULT '{}',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(source, event_id)
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                backend         TEXT NOT NULL DEFAULT '',
                model           TEXT DEFAULT '',
                tokens_in       INTEGER DEFAULT 0,
                tokens_out      INTEGER DEFAULT 0,
                cost_usd        REAL DEFAULT 0.0,
                session_id      TEXT DEFAULT '',
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                tool_name       TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS attention_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_key       TEXT NOT NULL UNIQUE,
                source              TEXT NOT NULL DEFAULT '',
                source_event_id     TEXT DEFAULT '',
                item_type           TEXT DEFAULT '',
                title               TEXT NOT NULL DEFAULT '',
                summary             TEXT DEFAULT '',
                detail              TEXT DEFAULT '',
                workspace_id        INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                project_name        TEXT DEFAULT '',
                severity            TEXT DEFAULT 'medium',
                status              TEXT DEFAULT 'new',
                owner_kind          TEXT DEFAULT '',
                owner_id            INTEGER DEFAULT NULL,
                link_url            TEXT DEFAULT '',
                meta_json           TEXT DEFAULT '{}',
                occurrence_count    INTEGER DEFAULT 1,
                first_seen_at       TEXT DEFAULT (datetime('now')),
                last_seen_at        TEXT DEFAULT (datetime('now')),
                acknowledged_at     TEXT,
                resolved_at         TEXT,
                snoozed_until       TEXT,
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companion_devices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                device_key      TEXT NOT NULL UNIQUE,
                user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
                name            TEXT NOT NULL,
                kind            TEXT DEFAULT 'mobile',
                platform        TEXT DEFAULT '',
                model           TEXT DEFAULT '',
                os_version      TEXT DEFAULT '',
                status          TEXT DEFAULT 'active',
                meta_json       TEXT DEFAULT '{}',
                last_seen_at    TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companion_auth_sessions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id           INTEGER NOT NULL REFERENCES companion_devices(id) ON DELETE CASCADE,
                access_token_hash    TEXT NOT NULL UNIQUE,
                refresh_token_hash   TEXT DEFAULT '',
                expires_at          TEXT NOT NULL,
                revoked_at          TEXT,
                last_refreshed_at   TEXT,
                meta_json           TEXT DEFAULT '{}',
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companion_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key     TEXT NOT NULL UNIQUE,
                device_id       INTEGER REFERENCES companion_devices(id) ON DELETE CASCADE,
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                agent_session_id TEXT DEFAULT '',
                status          TEXT DEFAULT 'active',
                mode            TEXT DEFAULT 'companion',
                current_route   TEXT DEFAULT '',
                current_view    TEXT DEFAULT '',
                active_task     TEXT DEFAULT '',
                summary         TEXT DEFAULT '',
                last_seen_at    TEXT,
                started_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                meta_json       TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS companion_presence (
                device_id       INTEGER PRIMARY KEY REFERENCES companion_devices(id) ON DELETE CASCADE,
                session_id      INTEGER REFERENCES companion_sessions(id) ON DELETE SET NULL,
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                presence_state  TEXT DEFAULT 'online',
                voice_state     TEXT DEFAULT 'idle',
                app_state       TEXT DEFAULT 'foreground',
                active_route    TEXT DEFAULT '',
                last_seen_at    TEXT,
                meta_json       TEXT DEFAULT '{}',
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companion_voice_turns (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      INTEGER NOT NULL REFERENCES companion_sessions(id) ON DELETE CASCADE,
                workspace_id    INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                transcript      TEXT DEFAULT '',
                response_text   TEXT DEFAULT '',
                provider        TEXT DEFAULT '',
                voice_mode      TEXT DEFAULT '',
                language        TEXT DEFAULT '',
                audio_format    TEXT DEFAULT '',
                duration_ms     INTEGER DEFAULT 0,
                tokens_used     INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'recorded',
                meta_json       TEXT DEFAULT '{}',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companion_push_subscriptions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id       INTEGER NOT NULL REFERENCES companion_devices(id) ON DELETE CASCADE,
                provider        TEXT NOT NULL DEFAULT 'webpush',
                endpoint        TEXT NOT NULL UNIQUE,
                auth_json       TEXT DEFAULT '{}',
                p256dh          TEXT DEFAULT '',
                expiration_at   TEXT,
                status          TEXT DEFAULT 'active',
                meta_json       TEXT DEFAULT '{}',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS workspace_relationships (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                external_system     TEXT NOT NULL,
                relationship_type   TEXT DEFAULT 'primary',
                external_id         TEXT DEFAULT '',
                external_name       TEXT DEFAULT '',
                external_url        TEXT DEFAULT '',
                status              TEXT DEFAULT 'active',
                meta_json           TEXT DEFAULT '{}',
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now')),
                UNIQUE(workspace_id, external_system, external_id)
            );

            CREATE TABLE IF NOT EXISTS trusted_device_states (
                device_id            INTEGER PRIMARY KEY REFERENCES companion_devices(id) ON DELETE CASCADE,
                trust_state          TEXT DEFAULT 'paired',
                max_risk_tier        TEXT DEFAULT 'act',
                biometric_enabled    INTEGER DEFAULT 0,
                last_biometric_at    TEXT,
                elevated_until       TEXT,
                meta_json            TEXT DEFAULT '{}',
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mobile_elevation_sessions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id            INTEGER NOT NULL REFERENCES companion_devices(id) ON DELETE CASCADE,
                elevation_key        TEXT NOT NULL UNIQUE,
                risk_tier            TEXT DEFAULT 'destructive',
                granted_scopes_json  TEXT DEFAULT '[]',
                status               TEXT DEFAULT 'active',
                verified_via         TEXT DEFAULT '',
                verified_at          TEXT,
                expires_at           TEXT,
                meta_json            TEXT DEFAULT '{}',
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS risk_challenges (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_key        TEXT NOT NULL UNIQUE,
                device_id            INTEGER NOT NULL REFERENCES companion_devices(id) ON DELETE CASCADE,
                session_id           INTEGER REFERENCES companion_sessions(id) ON DELETE SET NULL,
                workspace_id         INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                action_type          TEXT NOT NULL DEFAULT '',
                risk_tier            TEXT DEFAULT 'destructive',
                title                TEXT NOT NULL DEFAULT '',
                summary              TEXT DEFAULT '',
                status               TEXT DEFAULT 'pending',
                requires_biometric   INTEGER DEFAULT 1,
                request_json         TEXT DEFAULT '{}',
                meta_json            TEXT DEFAULT '{}',
                expires_at           TEXT,
                confirmed_at         TEXT,
                rejected_at          TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS action_receipts (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_key          TEXT NOT NULL UNIQUE,
                device_id            INTEGER REFERENCES companion_devices(id) ON DELETE SET NULL,
                session_id           INTEGER REFERENCES companion_sessions(id) ON DELETE SET NULL,
                workspace_id         INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                challenge_id         INTEGER REFERENCES risk_challenges(id) ON DELETE SET NULL,
                action_type          TEXT NOT NULL DEFAULT '',
                risk_tier            TEXT DEFAULT 'observe',
                status               TEXT DEFAULT 'completed',
                outcome              TEXT DEFAULT '',
                title                TEXT DEFAULT '',
                summary              TEXT DEFAULT '',
                request_json         TEXT DEFAULT '{}',
                result_json          TEXT DEFAULT '{}',
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS control_capabilities (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type          TEXT NOT NULL UNIQUE,
                system_name          TEXT NOT NULL DEFAULT 'axon',
                scope                TEXT DEFAULT 'global',
                risk_tier            TEXT DEFAULT 'observe',
                mobile_direct_allowed INTEGER DEFAULT 0,
                destructive          INTEGER DEFAULT 0,
                available            INTEGER DEFAULT 1,
                description          TEXT DEFAULT '',
                meta_json            TEXT DEFAULT '{}',
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mcp_servers (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                server_key           TEXT NOT NULL UNIQUE,
                name                 TEXT NOT NULL DEFAULT '',
                transport            TEXT NOT NULL DEFAULT 'server_adapter',
                endpoint             TEXT DEFAULT '',
                auth_source          TEXT DEFAULT '',
                scope                TEXT DEFAULT 'global',
                risk_tier            TEXT DEFAULT 'observe',
                enabled              INTEGER DEFAULT 1,
                status               TEXT DEFAULT 'online',
                meta_json            TEXT DEFAULT '{}',
                last_seen_at         TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mcp_capabilities (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                capability_key       TEXT NOT NULL UNIQUE,
                server_id            INTEGER REFERENCES mcp_servers(id) ON DELETE CASCADE,
                system_name          TEXT NOT NULL DEFAULT '',
                tool_name            TEXT NOT NULL DEFAULT '',
                action_type          TEXT NOT NULL DEFAULT '',
                scope                TEXT DEFAULT 'global',
                risk_tier            TEXT DEFAULT 'observe',
                cache_ttl_seconds    INTEGER DEFAULT 0,
                mobile_direct_allowed INTEGER DEFAULT 0,
                available            INTEGER DEFAULT 1,
                meta_json            TEXT DEFAULT '{}',
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mcp_sessions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id            INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                session_key          TEXT NOT NULL UNIQUE,
                status               TEXT DEFAULT 'online',
                detail               TEXT DEFAULT '',
                last_error           TEXT DEFAULT '',
                meta_json            TEXT DEFAULT '{}',
                last_seen_at         TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mcp_cache (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key            TEXT NOT NULL UNIQUE,
                server_key           TEXT NOT NULL DEFAULT '',
                capability_key       TEXT NOT NULL DEFAULT '',
                workspace_id         INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                summary              TEXT DEFAULT '',
                payload_json         TEXT DEFAULT '{}',
                expires_at           TEXT,
                created_at           TEXT DEFAULT (datetime('now')),
                updated_at           TEXT DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
            USING fts5(title, summary, content, source, content='memory_items', content_rowid='id');

            CREATE VIRTUAL TABLE IF NOT EXISTS resource_chunks_fts
            USING fts5(text, content='resource_chunks', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS memory_items_ai AFTER INSERT ON memory_items BEGIN
                INSERT INTO memory_items_fts(rowid, title, summary, content, source)
                VALUES (new.id, new.title, new.summary, new.content, new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_items_ad AFTER DELETE ON memory_items BEGIN
                INSERT INTO memory_items_fts(memory_items_fts, rowid, title, summary, content, source)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.source);
            END;

            CREATE TRIGGER IF NOT EXISTS memory_items_au AFTER UPDATE ON memory_items BEGIN
                INSERT INTO memory_items_fts(memory_items_fts, rowid, title, summary, content, source)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.source);
                INSERT INTO memory_items_fts(rowid, title, summary, content, source)
                VALUES (new.id, new.title, new.summary, new.content, new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS resource_chunks_ai AFTER INSERT ON resource_chunks BEGIN
                INSERT INTO resource_chunks_fts(rowid, text)
                VALUES (new.id, COALESCE(new.content, new.text));
            END;

            CREATE TRIGGER IF NOT EXISTS resource_chunks_ad AFTER DELETE ON resource_chunks BEGIN
                INSERT INTO resource_chunks_fts(resource_chunks_fts, rowid, text)
                VALUES ('delete', old.id, COALESCE(old.content, old.text));
            END;

            CREATE TRIGGER IF NOT EXISTS resource_chunks_au AFTER UPDATE ON resource_chunks BEGIN
                INSERT INTO resource_chunks_fts(resource_chunks_fts, rowid, text)
                VALUES ('delete', old.id, COALESCE(old.content, old.text));
                INSERT INTO resource_chunks_fts(rowid, text)
                VALUES (new.id, COALESCE(new.content, new.text));
            END;

            CREATE INDEX IF NOT EXISTS idx_attention_items_workspace_status
                ON attention_items(workspace_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_attention_items_source
                ON attention_items(source, source_event_id);
            CREATE INDEX IF NOT EXISTS idx_companion_devices_user
                ON companion_devices(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_companion_sessions_workspace
                ON companion_sessions(workspace_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_companion_voice_turns_session
                ON companion_voice_turns(session_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_workspace_relationships_workspace
                ON workspace_relationships(workspace_id, external_system);
            CREATE INDEX IF NOT EXISTS idx_trusted_device_states_state
                ON trusted_device_states(trust_state, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mobile_elevation_sessions_device
                ON mobile_elevation_sessions(device_id, status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_risk_challenges_device
                ON risk_challenges(device_id, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_action_receipts_device
                ON action_receipts(device_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_control_capabilities_system
                ON control_capabilities(system_name, risk_tier);
            CREATE INDEX IF NOT EXISTS idx_mcp_servers_status
                ON mcp_servers(status, enabled);
            CREATE INDEX IF NOT EXISTS idx_mcp_capabilities_server
                ON mcp_capabilities(server_id, available);
            CREATE INDEX IF NOT EXISTS idx_mcp_sessions_server
                ON mcp_sessions(server_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mcp_cache_lookup
                ON mcp_cache(server_key, capability_key, workspace_id);

            """
        )
        await seed_default_settings(db)
        await apply_core_migrations(db)
        await db.commit()

    print(f"[Axon] Database initialised at {DB_PATH}")
