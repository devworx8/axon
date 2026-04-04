"""Post-schema migrations and settings normalization for the core database."""

from __future__ import annotations

_LEGACY_SETTING_KEYS = {
    "extra_allowed_cmds",
}


async def apply_core_migrations(db) -> None:
    async def ensure_column(table: str, column: str, definition: str):
        cur = await db.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        existing = {row["name"] for row in rows}
        if column not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    async def get_setting_value(key: str) -> str | None:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return str(row["value"] or "") if row else None

    async def put_setting_value(key: str, value: str):
        await db.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )

    async def delete_setting_value(key: str):
        await db.execute("DELETE FROM settings WHERE key = ?", (key,))

    def normalize_autonomy_profile(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized == "manual" else "workspace_auto"

    def normalize_runtime_permissions_mode(value: str | None, *, autonomy_profile: str | None = None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"default", "ask_first", "full_access"}:
            return normalized
        return "ask_first" if normalize_autonomy_profile(autonomy_profile) == "manual" else "default"

    def normalize_external_fetch_policy(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        return "live_first" if normalized == "live_first" else "cache_first"

    def normalize_history_turns(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw or raw == "12":
            return "10"
        try:
            parsed = int(raw)
        except Exception:
            return "10"
        return str(max(6, min(60, parsed)))

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
    await ensure_column("approval_grants", "destructive", "INTEGER DEFAULT 0")
    await ensure_column("approval_grants", "meta_json", "TEXT DEFAULT '{}'")
    await ensure_column("external_fetch_cache", "summary", "TEXT DEFAULT ''")
    for legacy_key in _LEGACY_SETTING_KEYS:
        await delete_setting_value(legacy_key)

    current_autonomy = await get_setting_value("autonomy_profile")
    normalized_autonomy = normalize_autonomy_profile(current_autonomy)
    if current_autonomy != normalized_autonomy:
        await put_setting_value("autonomy_profile", normalized_autonomy)

    current_runtime_permissions = await get_setting_value("runtime_permissions_mode")
    normalized_runtime_permissions = normalize_runtime_permissions_mode(
        current_runtime_permissions,
        autonomy_profile=normalized_autonomy,
    )
    if current_runtime_permissions != normalized_runtime_permissions:
        await put_setting_value("runtime_permissions_mode", normalized_runtime_permissions)

    current_fetch_policy = await get_setting_value("external_fetch_policy")
    normalized_fetch_policy = normalize_external_fetch_policy(current_fetch_policy)
    if current_fetch_policy != normalized_fetch_policy:
        await put_setting_value("external_fetch_policy", normalized_fetch_policy)

    current_history_turns = await get_setting_value("max_history_turns")
    normalized_history_turns = normalize_history_turns(current_history_turns)
    if current_history_turns != normalized_history_turns:
        await put_setting_value("max_history_turns", normalized_history_turns)
    await db.execute("INSERT INTO memory_items_fts(memory_items_fts) VALUES ('rebuild')")
    await db.execute("INSERT INTO resource_chunks_fts(resource_chunks_fts) VALUES ('rebuild')")
