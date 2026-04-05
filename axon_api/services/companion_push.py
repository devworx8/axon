"""Companion push subscription helpers."""

from __future__ import annotations

import json
from typing import Any

from axon_data import (
    disable_companion_push_subscription,
    get_companion_push_subscription,
    list_companion_push_subscriptions,
    upsert_companion_push_subscription,
)


async def register_companion_push_subscription(
    db,
    *,
    device_id: int,
    endpoint: str,
    provider: str = "webpush",
    auth: dict[str, Any] | None = None,
    p256dh: str = "",
    expiration_at: str | None = None,
    status: str = "active",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sub_id = await upsert_companion_push_subscription(
        db,
        device_id=device_id,
        endpoint=endpoint,
        provider=provider,
        auth_json="{}" if auth is None else json.dumps(auth, sort_keys=True, ensure_ascii=True),
        p256dh=p256dh,
        expiration_at=expiration_at,
        status=status,
        meta_json="{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True),
    )
    row = await get_companion_push_subscription(db, sub_id)
    return dict(row) if row else {"id": sub_id, "device_id": device_id, "endpoint": endpoint}


async def list_companion_push_targets(
    db,
    *,
    device_id: int | None = None,
    status: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = await list_companion_push_subscriptions(db, device_id=device_id, status=status, limit=limit)
    return [dict(row) for row in rows]


async def disable_companion_push_target(db, *, subscription_id: int) -> bool:
    await disable_companion_push_subscription(db, subscription_id)
    return True

