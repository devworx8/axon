"""API routes for the DevOps monitoring dashboard — errors + usage + quota."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from axon_data import (
    get_db,
    get_setting,
    get_unresolved_errors,
    list_error_events,
    get_error_event,
    update_error_status,
    log_usage,
    get_usage_summary,
    get_daily_usage,
    get_usage_by_backend,
    get_quota_status,
    log_event,
)
from axon_api.services import npm_cli_extensions as npm_cli_extension_service

router = APIRouter(prefix="/api/devops", tags=["devops"])


# ── Error events ─────────────────────────────────────────────────────────────

@router.get("/errors")
async def errors_list(status: str = "", source: str = "", limit: int = 50):
    async with get_db() as db:
        if status:
            rows = await list_error_events(db, status=status, source=source, limit=limit)
        else:
            rows = await get_unresolved_errors(db, source=source, limit=limit)
    return {"errors": rows}


@router.get("/errors/{event_id}")
async def error_detail(event_id: int):
    async with get_db() as db:
        row = await get_error_event(db, event_id)
    if not row:
        raise HTTPException(404, "Error event not found")
    return row


class StatusUpdate(BaseModel):
    status: str
    fix_session_id: str = ""


@router.patch("/errors/{event_id}/status")
async def error_update_status(event_id: int, body: StatusUpdate):
    allowed = {"new", "triaging", "fixing", "fixed", "resolved", "ignored"}
    if body.status not in allowed:
        raise HTTPException(400, f"Invalid status. Allowed: {allowed}")
    async with get_db() as db:
        await update_error_status(db, event_id, body.status, fix_session_id=body.fix_session_id)
    return {"ok": True}


# ── Usage / quota ────────────────────────────────────────────────────────────

@router.get("/usage/summary")
async def usage_summary(days: int = 30):
    async with get_db() as db:
        data = await get_usage_summary(db, days=days)
    return data


@router.get("/usage/daily")
async def usage_daily(days: int = 30):
    async with get_db() as db:
        rows = await get_daily_usage(db, days=days)
    return {"days": rows}


@router.get("/usage/backends")
async def usage_backends(days: int = 30):
    async with get_db() as db:
        rows = await get_usage_by_backend(db, days=days)
    return {"backends": rows}


@router.get("/usage/quota")
async def usage_quota():
    async with get_db() as db:
        budget_tokens = int(await get_setting(db, "monthly_token_budget") or "0")
        budget_cost = float(await get_setting(db, "monthly_cost_budget_usd") or "0")
        data = await get_quota_status(
            db,
            monthly_token_budget=budget_tokens,
            monthly_cost_budget_usd=budget_cost,
        )
    return data


# ── Sentry webhook receiver ─────────────────────────────────────────────────

@router.post("/sentry/webhook")
async def sentry_webhook_receiver(payload: dict):
    from axon_api.services.sentry_bridge import handle_sentry_webhook
    result = await handle_sentry_webhook(payload)
    return result


# ── Manual poll trigger ──────────────────────────────────────────────────────

@router.post("/sentry/poll")
async def sentry_poll_trigger():
    from axon_api.services.sentry_bridge import poll_sentry_issues
    ingested = await poll_sentry_issues()
    return {"ingested": len(ingested), "issues": ingested}


# ── Local CLI installer ──────────────────────────────────────────────────────

class NpmCliExtensionInstallRequest(BaseModel):
    package_name: str
    binary_name: str = ""


@router.post("/cli-extensions/npm/install")
async def install_npm_cli_extension(body: NpmCliExtensionInstallRequest):
    try:
        result = await asyncio.to_thread(
            npm_cli_extension_service.install_npm_cli_extension,
            body.package_name,
            body.binary_name,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))

    async with get_db() as db:
        await log_event(db, "maintenance", f"CLI extension install requested: {body.package_name}")
    return result
