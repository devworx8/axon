"""Trusted-device, typed action, and challenge routes for Axon Online mobile control."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from axon_api.routes.mobile_axon import router as mobile_axon_router
from axon_api.services.companion_request_auth import require_companion_context
from axon_api.services.mobile_control_executor import confirm_destructive_action, execute_typed_action
from axon_api.services.mobile_control_policy import seed_control_capabilities
from axon_api.services.mobile_trust import create_elevation, get_trust_snapshot
from axon_data import (
    get_db,
    get_risk_challenge,
    list_action_receipts,
    list_risk_challenges,
    update_risk_challenge,
)

router = APIRouter(tags=["mobile-control"])
router.include_router(mobile_axon_router)


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _expires_at_passed(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except Exception:
        return False
    return expiry <= datetime.now(timezone.utc)


class ElevationRequest(BaseModel):
    target_risk_tier: str = "destructive"
    verified_via: str = "biometric_local"
    ttl_minutes: int = 15
    meta: dict[str, Any] | None = Field(default=None)


class TypedActionRequest(BaseModel):
    action_type: str
    session_id: int | None = None
    workspace_id: int | None = None
    payload: dict[str, Any] | None = Field(default=None)


@router.get("/api/mobile/control/trust")
async def mobile_control_trust(request: Request):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        trust = await get_trust_snapshot(db, device_id=int(device_row["id"]))
        receipts = [dict(row) for row in await list_action_receipts(db, device_id=int(device_row["id"]), limit=10)]
    return {"device": device_row, "trust": trust, "receipts": receipts}


@router.post("/api/mobile/control/elevate")
async def mobile_control_elevate(request: Request, body: ElevationRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        result = await create_elevation(
            db,
            device_id=int(device_row["id"]),
            target_risk_tier=body.target_risk_tier,
            verified_via=body.verified_via,
            ttl_minutes=max(1, int(body.ttl_minutes or 15)),
            meta=body.meta or {},
        )
        await db.commit()
        trust = await get_trust_snapshot(db, device_id=int(device_row["id"]))
    return {"device": device_row, "trust": trust, **result}


@router.get("/api/mobile/actions/capabilities")
async def mobile_action_capabilities(request: Request):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        capabilities = await seed_control_capabilities(db)
        trust = await get_trust_snapshot(db, device_id=int(device_row["id"]))
    return {"capabilities": capabilities, "trust": trust}


@router.post("/api/mobile/actions/execute")
async def mobile_action_execute(request: Request, body: TypedActionRequest):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        try:
            result = await execute_typed_action(
                db,
                device_id=int(device_row["id"]),
                session_id=body.session_id,
                workspace_id=body.workspace_id,
                action_type=body.action_type,
                payload=body.payload or {},
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await db.commit()
    return result


@router.get("/api/mobile/actions/receipts")
async def mobile_action_receipts(request: Request, limit: int = 20):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        rows = await list_action_receipts(db, device_id=int(device_row["id"]), limit=max(1, min(100, limit)))
    return {"receipts": [dict(row) for row in rows]}


@router.get("/api/mobile/challenges")
async def mobile_challenges(request: Request, status: str = "pending", limit: int = 20):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        rows = await list_risk_challenges(db, device_id=int(device_row["id"]), status=status, limit=max(1, min(100, limit)))
    return {"challenges": [dict(row) for row in rows]}


@router.get("/api/mobile/challenges/{challenge_id}")
async def mobile_challenge_detail(request: Request, challenge_id: int):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        challenge = await get_risk_challenge(db, challenge_id)
    if not challenge or int(dict(challenge).get("device_id") or 0) != int(device_row["id"]):
        raise HTTPException(404, "Challenge not found")
    return {"challenge": dict(challenge)}


@router.post("/api/mobile/challenges/{challenge_id}/confirm")
async def mobile_challenge_confirm(request: Request, challenge_id: int):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        challenge_row = await get_risk_challenge(db, challenge_id)
        challenge = _row(challenge_row)
        if not challenge or int(challenge.get("device_id") or 0) != int(device_row["id"]):
            raise HTTPException(404, "Challenge not found")
        if str(challenge.get("status") or "").strip().lower() != "pending":
            raise HTTPException(400, "Challenge is no longer pending")
        if _expires_at_passed(str(challenge.get("expires_at") or "")):
            await update_risk_challenge(db, challenge_id, status="expired", commit=False)
            await db.commit()
            raise HTTPException(400, "Challenge expired")
        try:
            result = await confirm_destructive_action(
                db,
                device_id=int(device_row["id"]),
                session_id=int(challenge.get("session_id") or 0) or None,
                workspace_id=int(challenge.get("workspace_id") or 0) or None,
                challenge=challenge,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await update_risk_challenge(
            db,
            challenge_id,
            status="confirmed",
            confirmed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            commit=False,
        )
        await db.commit()
        updated = await get_risk_challenge(db, challenge_id)
    return {"challenge": _row(updated), "result": result}


@router.post("/api/mobile/challenges/{challenge_id}/reject")
async def mobile_challenge_reject(request: Request, challenge_id: int):
    _, _, device_row = await require_companion_context(request)
    async with get_db() as db:
        challenge_row = await get_risk_challenge(db, challenge_id)
        challenge = _row(challenge_row)
        if not challenge or int(challenge.get("device_id") or 0) != int(device_row["id"]):
            raise HTTPException(404, "Challenge not found")
        await update_risk_challenge(
            db,
            challenge_id,
            status="rejected",
            rejected_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            commit=False,
        )
        await db.commit()
        updated = await get_risk_challenge(db, challenge_id)
    return {"challenge": _row(updated)}
