"""Attention ingestion helpers for workspace and companion signals."""

from __future__ import annotations

import json
from typing import Any

from axon_data import (
    build_attention_key,
    get_attention_item,
    get_attention_item_by_key,
    upsert_attention_item,
)


def _meta_json(meta: Any) -> str:
    if isinstance(meta, str):
        return meta
    try:
        return json.dumps(meta or {}, ensure_ascii=True, sort_keys=True)
    except Exception:
        return "{}"


def normalize_attention_payload(payload: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if payload:
      data.update(payload)
    data.update(overrides)
    source = str(data.get("source") or data.get("external_system") or "system").strip()
    event_id = str(data.get("source_event_id") or data.get("event_id") or data.get("external_id") or "").strip()
    workspace_id = data.get("workspace_id")
    title = str(data.get("title") or data.get("summary") or source or "Attention item").strip()
    summary = str(data.get("summary") or "").strip()
    detail = str(data.get("detail") or data.get("message") or "").strip()
    item_type = str(data.get("item_type") or data.get("attention_type") or "").strip()
    external_system = str(data.get("external_system") or source).strip()
    external_id = str(data.get("external_id") or event_id).strip()
    attention_key = str(
        data.get("attention_key")
        or build_attention_key(
            source,
            event_id,
            workspace_id=workspace_id if workspace_id is not None else None,
            external_system=external_system,
            external_id=external_id,
            title=title,
        )
    )
    return {
        "attention_key": attention_key,
        "source": source,
        "source_event_id": event_id,
        "item_type": item_type,
        "title": title,
        "summary": summary,
        "detail": detail,
        "workspace_id": workspace_id,
        "project_name": str(data.get("project_name") or "").strip(),
        "severity": str(data.get("severity") or "medium").strip().lower() or "medium",
        "status": str(data.get("status") or "new").strip().lower() or "new",
        "owner_kind": str(data.get("owner_kind") or "").strip(),
        "owner_id": data.get("owner_id"),
        "link_url": str(data.get("link_url") or data.get("url") or "").strip(),
        "meta_json": _meta_json(data.get("meta_json") or data.get("meta") or {}),
        "occurrence_count": int(data.get("occurrence_count") or 1),
        "acknowledged_at": data.get("acknowledged_at"),
        "resolved_at": data.get("resolved_at"),
        "snoozed_until": data.get("snoozed_until"),
    }


async def ingest_attention_signal(
    db,
    payload: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    normalized = normalize_attention_payload(payload, **overrides)
    attention_id = await upsert_attention_item(db, **normalized)
    row = await get_attention_item(db, attention_id)
    if row:
        return dict(row)
    row = await get_attention_item_by_key(db, normalized["attention_key"])
    return dict(row) if row else normalized

