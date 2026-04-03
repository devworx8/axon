"""Attention inbox query helpers."""

from __future__ import annotations

from typing import Any

from axon_data import list_attention_items, search_attention_items


_WAITING_STATUSES = {
    "approval_required",
    "awaiting_approval",
    "blocked",
    "needs_input",
    "needs_review",
    "waiting",
    "waiting_on_me",
}

_HIGH_SEVERITIES = {"critical", "fatal", "high"}


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def classify_attention_bucket(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "").strip().lower()
    severity = str(item.get("severity") or "").strip().lower()
    owner_kind = str(item.get("owner_kind") or "").strip().lower()
    source = str(item.get("source") or "").strip().lower()
    if status in {"resolved", "ignored", "dismissed"}:
        return "watch"
    if status in _WAITING_STATUSES or owner_kind in {"user", "operator", "human"}:
        return "waiting_on_me"
    if severity in _HIGH_SEVERITIES or source in {"runtime", "sentry", "github", "vercel", "browser"}:
        return "now"
    return "watch"


async def query_attention_inbox(
    db,
    *,
    workspace_id: int | None = None,
    query: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    rows = (
        await search_attention_items(db, query=query, workspace_id=workspace_id, limit=limit)
        if str(query or "").strip()
        else await list_attention_items(db, workspace_id=workspace_id, limit=limit)
    )
    grouped = {"now": [], "waiting_on_me": [], "watch": []}
    for row in rows:
      item = _row(row)
      if str(item.get("status") or "").lower() in {"resolved", "ignored"}:
          continue
      bucket = classify_attention_bucket(item)
      grouped[bucket].append(item)
    return {
        "counts": {bucket: len(items) for bucket, items in grouped.items()},
        "now": grouped["now"],
        "waiting_on_me": grouped["waiting_on_me"],
        "watch": grouped["watch"],
    }


async def attention_summary(db, *, workspace_id: int | None = None, limit: int = 20) -> dict[str, Any]:
    inbox = await query_attention_inbox(db, workspace_id=workspace_id, limit=limit)
    return {
        "counts": inbox["counts"],
        "top_now": inbox["now"][:5],
        "top_waiting_on_me": inbox["waiting_on_me"][:5],
        "top_watch": inbox["watch"][:5],
    }

