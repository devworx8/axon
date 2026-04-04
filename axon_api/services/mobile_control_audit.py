"""Audit, challenge, and receipt helpers for mobile control actions."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from axon_data import (
    create_action_receipt,
    create_risk_challenge,
    get_action_receipt,
    get_risk_challenge,
)


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def expires_after(minutes: int) -> str:
    return (_now_utc() + timedelta(minutes=max(1, int(minutes)))).isoformat().replace("+00:00", "Z")


def _json_payload(payload: dict[str, Any] | None) -> str:
    return "{}" if payload is None else json.dumps(payload, sort_keys=True, ensure_ascii=True)


def new_receipt_key(action_type: str) -> str:
    return f"receipt:{action_type}:{secrets.token_urlsafe(8)}"


def new_challenge_key(action_type: str) -> str:
    return f"challenge:{action_type}:{secrets.token_urlsafe(8)}"


async def record_action_receipt(
    db,
    *,
    device_id: int | None = None,
    session_id: int | None = None,
    workspace_id: int | None = None,
    challenge_id: int | None = None,
    action_type: str,
    risk_tier: str,
    status: str,
    outcome: str,
    title: str,
    summary: str,
    request_payload: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_key = new_receipt_key(action_type)
    receipt_id = await create_action_receipt(
        db,
        receipt_key=receipt_key,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        challenge_id=challenge_id,
        action_type=action_type,
        risk_tier=risk_tier,
        status=status,
        outcome=outcome,
        title=title,
        summary=summary,
        request_json=_json_payload(request_payload),
        result_json=_json_payload(result_payload),
        commit=False,
    )
    row = await get_action_receipt(db, receipt_id)
    return dict(row) if row else {
        "id": receipt_id,
        "receipt_key": receipt_key,
        "action_type": action_type,
        "status": status,
        "outcome": outcome,
    }


async def create_destructive_challenge(
    db,
    *,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
    action_type: str,
    risk_tier: str,
    title: str,
    summary: str,
    request_payload: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    expires_minutes: int = 10,
) -> dict[str, Any]:
    challenge_key = new_challenge_key(action_type)
    challenge_id = await create_risk_challenge(
        db,
        challenge_key=challenge_key,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        action_type=action_type,
        risk_tier=risk_tier,
        title=title,
        summary=summary,
        request_json=_json_payload(request_payload),
        meta_json=_json_payload(meta),
        expires_at=expires_after(expires_minutes),
        commit=False,
    )
    row = await get_risk_challenge(db, challenge_id)
    return dict(row) if row else {
        "id": challenge_id,
        "challenge_key": challenge_key,
        "action_type": action_type,
        "status": "pending",
    }
