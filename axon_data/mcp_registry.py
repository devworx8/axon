from __future__ import annotations

import aiosqlite


async def upsert_mcp_server(
    db: aiosqlite.Connection,
    *,
    server_key: str,
    name: str,
    transport: str = "server_adapter",
    endpoint: str = "",
    auth_source: str = "",
    scope: str = "global",
    risk_tier: str = "observe",
    enabled: bool = True,
    status: str = "online",
    meta_json: str = "{}",
    last_seen_at: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO mcp_servers (
            server_key, name, transport, endpoint, auth_source, scope, risk_tier,
            enabled, status, meta_json, last_seen_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(server_key) DO UPDATE SET
            name = excluded.name,
            transport = excluded.transport,
            endpoint = excluded.endpoint,
            auth_source = excluded.auth_source,
            scope = excluded.scope,
            risk_tier = excluded.risk_tier,
            enabled = excluded.enabled,
            status = excluded.status,
            meta_json = excluded.meta_json,
            last_seen_at = COALESCE(excluded.last_seen_at, mcp_servers.last_seen_at),
            updated_at = datetime('now')
        """,
        (
            server_key,
            name,
            transport,
            endpoint,
            auth_source,
            scope,
            risk_tier,
            1 if enabled else 0,
            status,
            meta_json,
            last_seen_at,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM mcp_servers WHERE server_key = ?", (server_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_mcp_server(db: aiosqlite.Connection, server_id: int):
    cur = await db.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,))
    return await cur.fetchone()


async def get_mcp_server_by_key(db: aiosqlite.Connection, server_key: str):
    cur = await db.execute("SELECT * FROM mcp_servers WHERE server_key = ?", (server_key,))
    return await cur.fetchone()


async def list_mcp_servers(db: aiosqlite.Connection, *, enabled_only: bool = False, limit: int = 100):
    where = "WHERE enabled = 1" if enabled_only else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM mcp_servers
        {where}
        ORDER BY name ASC, server_key ASC
        LIMIT ?
        """,
        (limit,),
    )
    return await cur.fetchall()


async def upsert_mcp_capability(
    db: aiosqlite.Connection,
    *,
    capability_key: str,
    server_id: int | None = None,
    system_name: str,
    tool_name: str,
    action_type: str,
    scope: str = "global",
    risk_tier: str = "observe",
    cache_ttl_seconds: int = 0,
    mobile_direct_allowed: bool = False,
    available: bool = True,
    meta_json: str = "{}",
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO mcp_capabilities (
            capability_key, server_id, system_name, tool_name, action_type, scope,
            risk_tier, cache_ttl_seconds, mobile_direct_allowed, available, meta_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(capability_key) DO UPDATE SET
            server_id = excluded.server_id,
            system_name = excluded.system_name,
            tool_name = excluded.tool_name,
            action_type = excluded.action_type,
            scope = excluded.scope,
            risk_tier = excluded.risk_tier,
            cache_ttl_seconds = excluded.cache_ttl_seconds,
            mobile_direct_allowed = excluded.mobile_direct_allowed,
            available = excluded.available,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            capability_key,
            server_id,
            system_name,
            tool_name,
            action_type,
            scope,
            risk_tier,
            cache_ttl_seconds,
            1 if mobile_direct_allowed else 0,
            1 if available else 0,
            meta_json,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM mcp_capabilities WHERE capability_key = ?", (capability_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def list_mcp_capabilities(
    db: aiosqlite.Connection,
    *,
    server_id: int | None = None,
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if server_id is not None:
        clauses.append("server_id = ?")
        params.append(server_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM mcp_capabilities
        {where}
        ORDER BY system_name ASC, tool_name ASC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def upsert_mcp_session(
    db: aiosqlite.Connection,
    *,
    server_id: int,
    session_key: str,
    status: str = "online",
    detail: str = "",
    last_error: str = "",
    meta_json: str = "{}",
    last_seen_at: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO mcp_sessions (
            server_id, session_key, status, detail, last_error, meta_json,
            last_seen_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(session_key) DO UPDATE SET
            server_id = excluded.server_id,
            status = excluded.status,
            detail = excluded.detail,
            last_error = excluded.last_error,
            meta_json = excluded.meta_json,
            last_seen_at = COALESCE(excluded.last_seen_at, mcp_sessions.last_seen_at),
            updated_at = datetime('now')
        """,
        (
            server_id,
            session_key,
            status,
            detail,
            last_error,
            meta_json,
            last_seen_at,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM mcp_sessions WHERE session_key = ?", (session_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def list_mcp_sessions(
    db: aiosqlite.Connection,
    *,
    server_id: int | None = None,
    limit: int = 100,
):
    clauses = []
    params: list[object] = []
    if server_id is not None:
        clauses.append("server_id = ?")
        params.append(server_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT *
        FROM mcp_sessions
        {where}
        ORDER BY updated_at DESC, created_at DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def upsert_mcp_cache(
    db: aiosqlite.Connection,
    *,
    cache_key: str,
    server_key: str,
    capability_key: str,
    workspace_id: int | None = None,
    summary: str = "",
    payload_json: str = "{}",
    expires_at: str | None = None,
    commit: bool = True,
) -> int:
    await db.execute(
        """
        INSERT INTO mcp_cache (
            cache_key, server_key, capability_key, workspace_id, summary, payload_json,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(cache_key) DO UPDATE SET
            server_key = excluded.server_key,
            capability_key = excluded.capability_key,
            workspace_id = excluded.workspace_id,
            summary = excluded.summary,
            payload_json = excluded.payload_json,
            expires_at = excluded.expires_at,
            updated_at = datetime('now')
        """,
        (
            cache_key,
            server_key,
            capability_key,
            workspace_id,
            summary,
            payload_json,
            expires_at,
        ),
    )
    if commit:
        await db.commit()
    cur = await db.execute("SELECT id FROM mcp_cache WHERE cache_key = ?", (cache_key,))
    row = await cur.fetchone()
    return int(row["id"]) if row else 0


async def get_mcp_cache(db: aiosqlite.Connection, cache_key: str):
    cur = await db.execute("SELECT * FROM mcp_cache WHERE cache_key = ?", (cache_key,))
    return await cur.fetchone()

