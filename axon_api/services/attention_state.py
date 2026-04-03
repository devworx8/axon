"""Attention item state transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from axon_data import (
    acknowledge_attention_item,
    assign_attention_item,
    resolve_attention_item,
    snooze_attention_item,
    update_attention_item_state,
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def acknowledge(db, attention_id: int):
    await update_attention_item_state(
        db,
        attention_id,
        status="acknowledged",
        acknowledged_at=_now_iso(),
    )
    row = await acknowledge_attention_item(db, attention_id)
    return row


async def snooze(db, attention_id: int, snoozed_until: str):
    await snooze_attention_item(db, attention_id, snoozed_until)
    return True


async def assign(db, attention_id: int, *, owner_kind: str, owner_id: int | None = None):
    await assign_attention_item(db, attention_id, owner_kind=owner_kind, owner_id=owner_id)
    return True


async def resolve(db, attention_id: int):
    await update_attention_item_state(
        db,
        attention_id,
        status="resolved",
        resolved_at=_now_iso(),
    )
    row = await resolve_attention_item(db, attention_id)
    return row

