"""
Axon memory engine.

This module maintains a curated memory layer on top of existing runtime data so
Axon can retrieve compact, high-value context across:
- Resource Bank
- Workspace Memory
- User Memory
- Mission Memory
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Iterable, Optional

import db as devdb
import resource_bank


LAYER_ORDER = ("workspace", "resource", "mission", "user")
LAYER_LABELS = {
    "workspace": "Workspace Memory",
    "resource": "Resource Bank",
    "mission": "Mission Memory",
    "user": "User Memory",
}
TRUST_WEIGHTS = {"high": 1.0, "medium": 0.72, "low": 0.45}
LAYER_BONUS = {"workspace": 0.2, "resource": 0.12, "mission": 0.1, "user": 0.08}
PREFERENCE_KEYS = (
    "projects_root",
    "scan_interval_hours",
    "morning_digest_hour",
    "ai_backend",
    "api_provider",
    "ollama_url",
    "ollama_model",
    "code_model",
    "general_model",
    "reasoning_model",
    "embeddings_model",
    "vision_model",
    "azure_speech_region",
    "azure_voice",
    "resource_storage_path",
    "resource_upload_max_mb",
    "resource_url_import_enabled",
)
_SEARCH_CACHE: dict[tuple[str, str, str, int, str], dict[str, object]] = {}


def _normalized_query_key(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip().lower())


def _clean_text(value: str, *, limit: int = 4000) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:limit]


def _summary(title: str, text: str, *, limit: int = 220) -> str:
    cleaned = _clean_text(text, limit=4000)
    if not cleaned:
        return f"{title} is available in Axon memory."
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")


def _stable_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=True)


def _parse_when(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(raw.replace(" ", "T")).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _recency_score(value: str | None) -> float:
    moment = _parse_when(value)
    if not moment:
        return 0.25
    age_hours = max((datetime.now(timezone.utc) - moment).total_seconds() / 3600.0, 0.0)
    return max(0.08, 1.0 - min(age_hours / (24 * 30), 0.92))


def _semantic_similarity(query_vec: list[float] | None, row_vec: list[float] | None) -> float:
    if not query_vec or not row_vec:
        return 0.0
    try:
        return max(0.0, resource_bank.cosine_similarity(query_vec, row_vec))
    except Exception:
        return 0.0


def _keyword_score(query: str, row_text: str) -> float:
    raw = resource_bank.score_chunk(query, row_text)
    return min(raw / 8.0, 1.0)


def _item_row(
    *,
    memory_key: str,
    layer: str,
    title: str,
    content: str,
    source: str,
    source_id: str,
    workspace_id: Optional[int] = None,
    trust_level: str = "medium",
    relevance_score: float = 0.0,
    meta: Optional[dict] = None,
) -> dict:
    text = _clean_text(content)
    return {
        "memory_key": memory_key,
        "layer": layer,
        "title": title,
        "content": text,
        "summary": _summary(title, text),
        "source": source,
        "source_id": source_id,
        "workspace_id": workspace_id,
        "trust_level": trust_level,
        "relevance_score": relevance_score,
        "meta_json": _stable_json(meta or {}),
    }


def _sanitize_memory_refs(
    item: dict,
    *,
    valid_workspace_ids: set[int],
    valid_mission_ids: set[int],
) -> dict:
    sanitized = dict(item)

    workspace_id = sanitized.get("workspace_id")
    if workspace_id is not None:
        try:
            workspace_value = int(workspace_id)
        except Exception:
            workspace_value = None
        sanitized["workspace_id"] = workspace_value if workspace_value in valid_workspace_ids else None

    mission_id = sanitized.get("mission_id")
    if mission_id is not None:
        try:
            mission_value = int(mission_id)
        except Exception:
            mission_value = None
        sanitized["mission_id"] = mission_value if mission_value in valid_mission_ids else None

    return sanitized


async def sync_memory_layers(conn, settings: dict) -> dict:
    """
    Rebuild curated memory items from the current Axon runtime.

    The sync intentionally favors high-value summaries over raw logs so retrieval
    stays compact and useful.
    """
    projects = [dict(row) for row in await devdb.get_projects(conn)]
    tasks = [dict(row) for row in await devdb.get_tasks(conn, status=None)]
    resources = [resource_bank.serialize_resource(row) for row in await devdb.list_resources(conn, limit=500)]
    activity = [dict(row) for row in await devdb.get_activity(conn, limit=80)]
    existing_rows = await devdb.list_memory_items(conn, limit=2000)
    existing_map = {row["memory_key"]: dict(row) for row in existing_rows}
    valid_workspace_ids = {int(project["id"]) for project in projects if project.get("id") is not None}
    valid_mission_ids = {int(task["id"]) for task in tasks if task.get("id") is not None}

    items: list[dict] = []

    for project in projects:
        details = [
            f"Path: {project.get('path', '')}",
            f"Stack: {project.get('stack') or 'unknown'}",
            f"Health: {project.get('health', 100)}",
            f"Open TODOs: {project.get('todo_count', 0)}",
            f"Branch: {project.get('git_branch') or 'unknown'}",
            f"Last commit age: {project.get('last_commit_age_days') or 'unknown'}",
        ]
        if project.get("description"):
            details.append(f"Description: {project['description']}")
        if project.get("note"):
            details.append(f"Operator note: {project['note']}")
        items.append(
            _item_row(
                memory_key=f"workspace:{project['id']}",
                layer="workspace",
                title=project.get("name", f"Workspace {project['id']}"),
                content="\n".join(details),
                source="workspace_scan",
                source_id=str(project["id"]),
                workspace_id=project["id"],
                trust_level="high",
                relevance_score=float(project.get("health") or 0) / 100.0,
                meta={
                    "status": project.get("status", "active"),
                    "path": project.get("path", ""),
                    "stack": project.get("stack", ""),
                },
            )
        )

    for resource in resources:
        parts = [
            resource.get("summary") or "",
            resource.get("preview_text") or "",
        ]
        if resource.get("source_url"):
            parts.append(f"Source URL: {resource['source_url']}")
        if resource.get("mime_type"):
            parts.append(f"Type: {resource['mime_type']}")
        items.append(
            _item_row(
                memory_key=f"resource:{resource['id']}",
                layer="resource",
                title=resource.get("title", f"Resource {resource['id']}"),
                content="\n".join(part for part in parts if part),
                source="resource_bank",
                source_id=str(resource["id"]),
                trust_level="high" if resource.get("source_type") == "upload" else "medium",
                relevance_score=1.0 if resource.get("status") == "ready" else 0.5,
                meta={
                    "kind": resource.get("kind", "document"),
                    "source_type": resource.get("source_type", "upload"),
                    "status": resource.get("status", "ready"),
                },
            )
        )

    for task in tasks:
        content = "\n".join(
            part for part in (
                f"Workspace: {task.get('project_name') or 'general'}",
                f"Priority: {task.get('priority', 'medium')}",
                f"Status: {task.get('status', 'open')}",
                f"Due date: {task.get('due_date') or 'none'}",
                task.get("detail") or "",
            )
            if part
        )
        items.append(
            _item_row(
                memory_key=f"mission:task:{task['id']}",
                layer="mission",
                title=task.get("title", f"Mission {task['id']}"),
                content=content,
                source="mission_task",
                source_id=str(task["id"]),
                workspace_id=task.get("project_id"),
                trust_level="high",
                relevance_score={"urgent": 1.0, "high": 0.85, "medium": 0.65, "low": 0.4}.get(task.get("priority"), 0.5),
                meta={
                    "status": task.get("status", "open"),
                    "priority": task.get("priority", "medium"),
                    "workspace_name": task.get("project_name"),
                },
            )
        )

    for event in activity:
        if event.get("event_type") in {"chat"}:
            continue
        summary = _clean_text(event.get("summary", ""), limit=1200)
        if not summary:
            continue
        items.append(
            _item_row(
                memory_key=f"mission:event:{event['id']}",
                layer="mission",
                title=f"{event.get('event_type', 'system').replace('_', ' ').title()}",
                content=summary,
                source="activity_log",
                source_id=str(event["id"]),
                workspace_id=event.get("project_id"),
                trust_level="medium" if event.get("event_type") != "resource_failed" else "high",
                relevance_score=0.55,
                meta={
                    "event_type": event.get("event_type", "system"),
                    "created_at": event.get("created_at"),
                    "project_name": event.get("project_name"),
                },
            )
        )

    pref_lines = []
    for key in PREFERENCE_KEYS:
        value = settings.get(key)
        if value in (None, "", "0"):
            continue
        if "key" in key or "token" in key or "secret" in key:
            continue
        pref_lines.append(f"{key}: {value}")
    if pref_lines:
        items.append(
            _item_row(
                memory_key="user:preferences",
                layer="user",
                title="Operator preferences",
                content="\n".join(pref_lines),
                source="settings",
                source_id="preferences",
                trust_level="high",
                relevance_score=0.6,
                meta={"preference_keys": [line.split(":", 1)[0] for line in pref_lines]},
            )
        )

    texts_to_embed: list[str] = []
    embed_keys: list[str] = []
    prepared_items: list[dict] = []
    for item in items:
        existing = existing_map.get(item["memory_key"])
        if (
            existing
            and existing.get("content") == item["content"]
            and existing.get("summary") == item["summary"]
            and existing.get("embedding_json")
        ):
            item["embedding_json"] = existing.get("embedding_json", "")
        else:
            item["embedding_json"] = ""
            texts_to_embed.append(item["summary"] or item["content"][:1400])
            embed_keys.append(item["memory_key"])
        prepared_items.append(item)

    if texts_to_embed and (settings.get("embeddings_model") or "").strip():
        vectors = await resource_bank.embed_texts(texts_to_embed, settings)
        for idx, key in enumerate(embed_keys):
            if idx < len(vectors):
                vector = vectors[idx]
                for item in prepared_items:
                    if item["memory_key"] == key:
                        item["embedding_json"] = json.dumps(vector)
                        break

    keys_by_layer: dict[str, list[str]] = {layer: [] for layer in LAYER_ORDER}
    for item in prepared_items:
        sanitized_item = _sanitize_memory_refs(
            item,
            valid_workspace_ids=valid_workspace_ids,
            valid_mission_ids=valid_mission_ids,
        )
        await devdb.upsert_memory_item(conn, **sanitized_item, commit=False)
        keys_by_layer.setdefault(sanitized_item["layer"], []).append(sanitized_item["memory_key"])

    for layer in LAYER_ORDER:
        await devdb.delete_stale_memory_items(conn, layer=layer, keep_keys=keys_by_layer.get(layer, []), commit=False)

    await conn.commit()

    return await build_memory_overview(conn)


async def build_memory_overview(conn) -> dict:
    counts = await devdb.count_memory_items_by_layer(conn)
    total = sum(counts.values())
    return {
        "total": total,
        "layers": {layer: int(counts.get(layer, 0)) for layer in LAYER_ORDER},
        "labels": {layer: LAYER_LABELS[layer] for layer in LAYER_ORDER},
    }


async def search_memory(
    conn,
    *,
    query: str,
    settings: dict,
    workspace_id: Optional[int] = None,
    layers: Optional[list[str]] = None,
    limit: int = 6,
    snapshot_revision: str = "",
) -> list[dict]:
    normalized_query = _normalized_query_key(query)
    cache_ttl = max(5, int(settings.get("memory_query_cache_ttl_seconds") or 45))
    cache_key = (
        normalized_query,
        str(workspace_id or ""),
        ",".join(sorted(layers or [])),
        int(limit or 0),
        str(snapshot_revision or ""),
    )
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and (time.time() - float(cached.get("cached_at") or 0.0)) < cache_ttl:
        return [dict(row) for row in (cached.get("results") or [])]

    if query.strip():
        fts_rows = await devdb.search_memory_items_fts(
            conn,
            query=query,
            workspace_id=workspace_id,
            layers=list(layers or []),
            limit=max(40, limit * 12),
        )
        candidates = [dict(row) for row in fts_rows]
        if not candidates:
            rows = await devdb.search_memory_items(
                conn,
                query=query,
                workspace_id=workspace_id,
                layers=list(layers or []),
                limit=max(120, limit * 20),
            )
            candidates = [dict(row) for row in rows]
    else:
        rows = await devdb.list_memory_items(conn, workspace_id=workspace_id, limit=max(120, limit * 20))
        candidates = [dict(row) for row in rows]
        if layers:
            allowed = set(layers)
            candidates = [row for row in candidates if row.get("layer") in allowed]

    if not query.strip():
        top = candidates[:limit]
        _SEARCH_CACHE[cache_key] = {"cached_at": time.time(), "results": [dict(row) for row in top]}
        return top

    query_vec: list[float] | None = None
    if (settings.get("embeddings_model") or "").strip():
        vectors = await resource_bank.embed_texts([query], settings)
        if vectors:
            query_vec = vectors[0]

    ranked: list[tuple[float, dict]] = []
    for row in candidates:
        text = " ".join(
            part for part in (
                row.get("title", ""),
                row.get("summary", ""),
                row.get("content", ""),
            )
            if part
        )
        keyword = _keyword_score(query, text)
        try:
            row_vec = json.loads(row.get("embedding_json") or "[]") if row.get("embedding_json") else None
        except Exception:
            row_vec = None
        semantic = _semantic_similarity(query_vec, row_vec)
        trust = TRUST_WEIGHTS.get(str(row.get("trust_level", "medium")).lower(), 0.6)
        recency = _recency_score(row.get("last_accessed_at") or row.get("updated_at"))
        layer_bonus = LAYER_BONUS.get(row.get("layer", ""), 0.05)
        workspace_bonus = 0.18 if workspace_id and row.get("workspace_id") == workspace_id else 0.0
        score = (
            semantic * 0.55
            + keyword * 0.4
            + trust * 0.18
            + recency * 0.12
            + layer_bonus
            + workspace_bonus
            + float(row.get("relevance_score") or 0.0) * 0.1
        )
        if score <= 0.12:
            continue
        row["score"] = round(score, 4)
        ranked.append((score, row))

    ranked.sort(key=lambda item: item[0], reverse=True)
    top_rows = [item[1] for item in ranked[:limit]]
    touch_ids = [row.get("id") for row in top_rows if row.get("id")]
    if touch_ids:
        try:
            await devdb.touch_memory_items(conn, touch_ids, commit=False)
            await conn.commit()
        except Exception:
            pass
    _SEARCH_CACHE[cache_key] = {"cached_at": time.time(), "results": [dict(row) for row in top_rows]}
    return top_rows


def build_memory_context(results: list[dict], *, limit_chars: int = 3600) -> str:
    if not results:
        return ""
    grouped: dict[str, list[dict]] = {}
    for row in results:
        grouped.setdefault(row.get("layer", "user"), []).append(row)

    lines = ["## Memory Context"]
    for layer in LAYER_ORDER:
        rows = grouped.get(layer) or []
        if not rows:
            continue
        lines.append(f"### {LAYER_LABELS.get(layer, layer.title())}")
        for row in rows[:3]:
            trust = str(row.get("trust_level", "medium")).lower()
            snippet = _clean_text(row.get("summary") or row.get("content") or "", limit=220)
            source = row.get("source", "")
            lines.append(
                f"- [{trust} trust] {row.get('title', 'Memory item')}: {snippet}"
                + (f" (source: {source})" if source else "")
            )
    return "\n".join(lines)[:limit_chars]
