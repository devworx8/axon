"""Preflight preparation for typed mobile control actions."""

from __future__ import annotations

from typing import Any

from axon_api.services.expo_control_actions import ExpoControlError, prepare_expo_action_request
from axon_api.services.mobile_control_audit import record_action_receipt
from axon_api.services.mobile_vercel_actions import MobileVercelActionError, prepare_vercel_action_request


async def preflight_typed_action(
    db,
    *,
    device_id: int,
    session_id: int | None,
    workspace_id: int | None,
    action_type: str,
    payload: dict[str, Any],
    risk_tier: str,
    title: str,
    capability: dict[str, Any],
    record_action_receipt_fn=None,
) -> dict[str, Any]:
    record_receipt = record_action_receipt_fn or record_action_receipt
    challenge_summary = f"{title} needs explicit confirmation on a trusted mobile device."

    if action_type.startswith("expo."):
        try:
            prepared = await prepare_expo_action_request(
                db,
                action_type=action_type,
                workspace_id=int(payload.get("workspace_id") or workspace_id or 0) or None,
                payload=payload,
            )
        except ExpoControlError as exc:
            receipt = await record_receipt(
                db,
                device_id=device_id,
                session_id=session_id,
                workspace_id=workspace_id,
                action_type=action_type,
                risk_tier=risk_tier,
                status="blocked",
                outcome=exc.outcome,
                title=title,
                summary=exc.summary,
                request_payload=payload,
                result_payload=exc.result_payload,
            )
            return {
                "blocked_response": {
                    "status": "blocked",
                    "capability": capability,
                    "receipt": receipt,
                    "result": exc.result_payload | {"message": exc.summary},
                }
            }
        payload = dict(prepared.get("payload") or payload)
        title = str(prepared.get("title") or title).strip() or title
        challenge_summary = str(prepared.get("summary") or challenge_summary).strip() or challenge_summary

    if action_type in {"vercel.deploy.promote", "vercel.deploy.rollback"}:
        try:
            prepared = await prepare_vercel_action_request(
                db,
                action_type=action_type,
                workspace_id=int(payload.get("workspace_id") or workspace_id or 0),
                payload=payload,
            )
        except MobileVercelActionError as exc:
            receipt = await record_receipt(
                db,
                device_id=device_id,
                session_id=session_id,
                workspace_id=workspace_id,
                action_type=action_type,
                risk_tier=risk_tier,
                status="blocked",
                outcome=exc.outcome,
                title=title,
                summary=exc.summary,
                request_payload=payload,
                result_payload=exc.result_payload,
            )
            return {
                "blocked_response": {
                    "status": "blocked",
                    "capability": capability,
                    "receipt": receipt,
                    "result": exc.result_payload | {"message": exc.summary},
                }
            }
        payload = dict(prepared.get("payload") or payload)
        title = str(prepared.get("title") or title).strip() or title
        challenge_summary = str(prepared.get("summary") or challenge_summary).strip() or challenge_summary

    return {
        "blocked_response": None,
        "payload": payload,
        "title": title,
        "challenge_summary": challenge_summary,
    }
