from __future__ import annotations

import hashlib
import inspect
import json
import re
from typing import Optional

import aiosqlite


def _hash_key(value: str) -> str:
    return hashlib.sha1((value or "").encode("utf-8")).hexdigest()


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip().lower())


def _fts_query(query: str) -> str:
    terms = [token for token in re.findall(r"[A-Za-z0-9_./:-]{2,}", _normalize_query(query)) if token]
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _row_value(row, key: str, default: str = "") -> str:
    if not row:
        return default
    try:
        return str(row[key] or default)
    except Exception:
        try:
            return str(dict(row).get(key) or default)
        except Exception:
            return default


async def _fetchone_compat(cursor):
    if cursor is None:
        return None
    fetchone = getattr(cursor, "fetchone", None)
    if fetchone is not None:
        result = fetchone()
        if inspect.isawaitable(result):
            return await result
        return result
    raw_cursor = getattr(cursor, "_cursor", None)
    if raw_cursor is not None:
        try:
            return raw_cursor.fetchone()
        except Exception:
            return None
    return None


async def _execute_fetchone_compat(db, sql: str, params=()):
    if not isinstance(db, aiosqlite.Connection):
        raw_conn = getattr(db, "_conn", None)
        if raw_conn is not None:
            cursor = raw_conn.execute(sql, params)
            try:
                return cursor.fetchone()
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
    cursor = await db.execute(sql, params)
    return await _fetchone_compat(cursor)


async def compute_workspace_revision(db: aiosqlite.Connection, workspace_id: int | None) -> str:
    if workspace_id is None:
        return "global"
    project_row = await _execute_fetchone_compat(
        db,
        "SELECT COALESCE(updated_at, created_at, '') AS stamp FROM projects WHERE id = ?",
        (workspace_id,),
    )
    prompt_row = await _execute_fetchone_compat(
        db,
        "SELECT COALESCE(MAX(updated_at), MAX(created_at), '') AS stamp FROM prompts WHERE project_id = ?",
        (workspace_id,),
    )
    task_row = await _execute_fetchone_compat(
        db,
        "SELECT COALESCE(MAX(updated_at), MAX(created_at), '') AS stamp FROM tasks WHERE project_id = ?",
        (workspace_id,),
    )
    resource_row = await _execute_fetchone_compat(
        db,
        "SELECT COALESCE(MAX(updated_at), MAX(created_at), '') AS stamp FROM resources WHERE workspace_id = ?",
        (workspace_id,),
    )
    memory_row = await _execute_fetchone_compat(
        db,
        "SELECT COALESCE(MAX(updated_at), MAX(created_at), '') AS stamp FROM memory_items WHERE workspace_id = ? OR workspace_id IS NULL",
        (workspace_id,),
    )
    payload = "|".join(
        _row_value(item, "stamp")
        for item in (
            project_row,
            prompt_row,
            task_row,
            resource_row,
            memory_row,
        )
    )
    return _hash_key(payload)


async def get_workspace_snapshot(
    db: aiosqlite.Connection,
    *,
    workspace_id: int,
    snapshot_key: str,
):
    cur = await db.execute(
        """
        SELECT * FROM workspace_snapshots
        WHERE workspace_id = ? AND snapshot_key = ?
        """,
        (workspace_id, snapshot_key),
    )
    return await cur.fetchone()


async def upsert_workspace_snapshot(
    db: aiosqlite.Connection,
    *,
    workspace_id: int,
    snapshot_key: str,
    revision: str,
    context_block: str,
    data_json: str,
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO workspace_snapshots (
            workspace_id, snapshot_key, revision, context_block, data_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(workspace_id) DO UPDATE SET
            snapshot_key = excluded.snapshot_key,
            revision = excluded.revision,
            context_block = excluded.context_block,
            data_json = excluded.data_json,
            updated_at = datetime('now')
        """,
        (workspace_id, snapshot_key, revision, context_block, data_json),
    )
    if commit:
        await db.commit()


async def get_thread_summary(db: aiosqlite.Connection, thread_key: str):
    cur = await db.execute(
        "SELECT * FROM thread_summaries WHERE thread_key = ?",
        (thread_key,),
    )
    return await cur.fetchone()


async def upsert_thread_summary(
    db: aiosqlite.Connection,
    *,
    thread_key: str,
    workspace_id: int | None,
    revision: str,
    summary: str,
    message_count: int,
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO thread_summaries (
            thread_key, workspace_id, revision, summary, message_count, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(thread_key) DO UPDATE SET
            workspace_id = excluded.workspace_id,
            revision = excluded.revision,
            summary = excluded.summary,
            message_count = excluded.message_count,
            updated_at = datetime('now')
        """,
        (thread_key, workspace_id, revision, summary, message_count),
    )
    if commit:
        await db.commit()


async def get_external_fetch_cache(db: aiosqlite.Connection, url: str):
    cur = await db.execute(
        """
        SELECT * FROM external_fetch_cache
        WHERE url = ?
          AND (expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now'))
        """,
        (url,),
    )
    return await cur.fetchone()


async def upsert_external_fetch_cache(
    db: aiosqlite.Connection,
    *,
    url: str,
    title: str,
    content: str,
    summary: str,
    status_code: int,
    mime_type: str = "",
    workspace_id: int | None = None,
    ttl_seconds: int = 21600,
    meta_json: str = "{}",
    commit: bool = True,
):
    cache_key = _hash_key(url)
    ttl_seconds = max(60, int(ttl_seconds or 21600))
    await db.execute(
        """
        INSERT INTO external_fetch_cache (
            cache_key, url, title, content, summary, status_code, mime_type,
            workspace_id, meta_json, fetched_at, expires_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'),
            datetime('now', '+' || ? || ' seconds'),
            datetime('now')
        )
        ON CONFLICT(cache_key) DO UPDATE SET
            url = excluded.url,
            title = excluded.title,
            content = excluded.content,
            summary = excluded.summary,
            status_code = excluded.status_code,
            mime_type = excluded.mime_type,
            workspace_id = excluded.workspace_id,
            meta_json = excluded.meta_json,
            fetched_at = datetime('now'),
            expires_at = datetime('now', '+' || ? || ' seconds'),
            updated_at = datetime('now')
        """,
        (
            cache_key,
            url,
            title,
            content,
            summary,
            int(status_code or 0),
            mime_type,
            workspace_id,
            meta_json,
            ttl_seconds,
            ttl_seconds,
        ),
    )
    if commit:
        await db.commit()


async def prune_expired_external_fetch_cache(db: aiosqlite.Connection, *, commit: bool = True):
    await db.execute(
        """
        DELETE FROM external_fetch_cache
        WHERE expires_at IS NOT NULL AND expires_at != '' AND expires_at <= datetime('now')
        """
    )
    if commit:
        await db.commit()


async def upsert_approval_grant(
    db: aiosqlite.Connection,
    *,
    action_fingerprint: str,
    action_type: str,
    workspace_id: int | None = None,
    repo_root: str = "",
    summary: str = "",
    command_preview: str = "",
    destructive: bool = False,
    meta_json: str = "{}",
    scope: str = "persist",
    commit: bool = True,
):
    await db.execute(
        """
        INSERT INTO approval_grants (
            action_fingerprint, action_type, scope, workspace_id, repo_root,
            summary, command_preview, destructive, meta_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(action_fingerprint) DO UPDATE SET
            action_type = excluded.action_type,
            scope = excluded.scope,
            workspace_id = excluded.workspace_id,
            repo_root = excluded.repo_root,
            summary = excluded.summary,
            command_preview = excluded.command_preview,
            destructive = excluded.destructive,
            meta_json = excluded.meta_json,
            updated_at = datetime('now')
        """,
        (
            action_fingerprint,
            action_type,
            scope,
            workspace_id,
            repo_root,
            summary,
            command_preview,
            1 if destructive else 0,
            meta_json,
        ),
    )
    if commit:
        await db.commit()


async def get_approval_grant(db: aiosqlite.Connection, action_fingerprint: str):
    cur = await db.execute(
        """
        SELECT * FROM approval_grants
        WHERE action_fingerprint = ?
          AND (expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now'))
        """,
        (action_fingerprint,),
    )
    return await cur.fetchone()


async def list_approval_grants(
    db: aiosqlite.Connection,
    *,
    scope: str = "",
    workspace_id: int | None = None,
):
    clauses: list[str] = []
    params: list[object] = []
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if workspace_id is not None:
        clauses.append("(workspace_id = ? OR workspace_id IS NULL)")
        params.append(workspace_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(
        f"""
        SELECT * FROM approval_grants
        {where}
        ORDER BY updated_at DESC
        """,
        params,
    )
    return await cur.fetchall()


async def delete_approval_grant(db: aiosqlite.Connection, action_fingerprint: str, *, commit: bool = True):
    await db.execute(
        "DELETE FROM approval_grants WHERE action_fingerprint = ?",
        (action_fingerprint,),
    )
    if commit:
        await db.commit()


async def search_memory_items_fts(
    db: aiosqlite.Connection,
    *,
    query: str,
    workspace_id: int | None = None,
    layers: list[str] | None = None,
    limit: int = 80,
):
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    clauses = ["memory_items_fts MATCH ?"]
    params: list[object] = [fts_query]
    if workspace_id is not None:
        clauses.append("(mi.workspace_id = ? OR mi.workspace_id IS NULL)")
        params.append(workspace_id)
    if layers:
        placeholders = ",".join("?" for _ in layers)
        clauses.append(f"mi.layer IN ({placeholders})")
        params.extend(list(layers))
    cur = await db.execute(
        f"""
        SELECT mi.*, bm25(memory_items_fts) AS fts_rank
        FROM memory_items_fts
        JOIN memory_items mi ON mi.id = memory_items_fts.rowid
        WHERE {' AND '.join(clauses)}
        ORDER BY fts_rank ASC, COALESCE(mi.last_accessed_at, mi.updated_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return await cur.fetchall()


async def search_resource_chunks_fts(
    db: aiosqlite.Connection,
    *,
    query: str,
    limit: int = 40,
):
    fts_query = _fts_query(query)
    if not fts_query:
        return []
    cur = await db.execute(
        """
        SELECT rc.*, r.title AS resource_title, r.workspace_id, bm25(resource_chunks_fts) AS fts_rank
        FROM resource_chunks_fts
        JOIN resource_chunks rc ON rc.id = resource_chunks_fts.rowid
        LEFT JOIN resources r ON r.id = rc.resource_id
        WHERE resource_chunks_fts MATCH ?
        ORDER BY fts_rank ASC, rc.chunk_index ASC
        LIMIT ?
        """,
        (fts_query, limit),
    )
    return await cur.fetchall()
