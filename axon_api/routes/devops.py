"""API routes for the DevOps monitoring dashboard — errors + usage + quota."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
    list_action_receipts,
    list_risk_challenges,
)
from axon_api.services.expo_control_actions import (
    ExpoControlError,
    execute_expo_build_action,
    execute_expo_build_list_action,
    execute_expo_status_action,
    execute_expo_update_publish,
    load_expo_overview,
)
from axon_api.services import npm_cli_extensions as npm_cli_extension_service

router = APIRouter(prefix="/api/devops", tags=["devops"])


class ExpoActionRequest(BaseModel):
    action_type: str
    workspace_id: int | None = None
    payload: dict = Field(default_factory=dict)
    confirm: bool = False


# ── Error events ─────────────────────────────────────────────────────────────

@router.get("/errors")
async def errors_list(status: str = "", source: str = "", limit: int = Query(default=50, ge=1, le=500)):
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


# ── Expo / EAS control ───────────────────────────────────────────────────────


@router.get("/expo/overview")
async def expo_overview(workspace_id: int | None = None, limit: int = 6, force_refresh: bool = False):
    async with get_db() as db:
        overview = await load_expo_overview(
            db,
            workspace_id=workspace_id,
            limit=max(1, min(limit, 12)),
            force_refresh=force_refresh,
        )
    return overview


@router.get("/delivery/activity")
async def delivery_activity(limit: int = 8, force_refresh: bool = False):
    async with get_db() as db:
        overview = await load_expo_overview(
            db,
            workspace_id=None,
            limit=max(1, min(limit, 12)),
            force_refresh=force_refresh,
        )
        receipt_rows = [dict(row) for row in await list_action_receipts(db, limit=50)]
        challenge_rows = [dict(row) for row in await list_risk_challenges(db, status="pending", limit=25)]

    expo_active = list(overview.get("active_builds") or [])[: max(1, min(limit, 10))]
    expo_recent = list(overview.get("builds") or [])[: max(1, min(limit, 10))]
    vercel_pending = [
        row for row in challenge_rows
        if str(row.get("action_type") or "").startswith("vercel.deploy.")
    ][: max(1, min(limit, 10))]
    vercel_recent_candidates = [
        row for row in receipt_rows
        if str(row.get("action_type") or "").startswith("vercel.deploy.")
    ]
    vercel_recent_candidates.sort(
        key=lambda row: (
            str(row.get("updated_at") or row.get("created_at") or ""),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )
    vercel_recent: list[dict] = []
    seen_vercel_keys: set[tuple[str, str]] = set()
    for row in vercel_recent_candidates:
        dedupe_key = (
            str(row.get("action_type") or "").strip(),
            str(row.get("workspace_id") or "").strip(),
        )
        if dedupe_key in seen_vercel_keys:
            continue
        seen_vercel_keys.add(dedupe_key)
        vercel_recent.append(row)
        if len(vercel_recent) >= max(1, min(limit, 10)):
            break

    items: list[dict] = []
    seen_expo_ids: set[str] = set()
    for build in expo_active:
        build_id = str(build.get("id") or "")
        if build_id:
            seen_expo_ids.add(build_id)
        items.append({
            "kind": "expo_build",
            "action_type": "expo.build",
            "title": str(build.get("name") or build.get("platform") or "Expo build"),
            "summary": str(build.get("message") or "").strip() or f"{str(build.get('platform') or 'Build').upper()} {str(build.get('status') or '').replace('_', ' ').strip()}",
            "status": str(build.get("status") or "").strip().lower() or "queued",
            "created_at": str(build.get("created_at") or ""),
            "updated_at": str(build.get("updated_at") or build.get("created_at") or ""),
            "url": str(build.get("url") or build.get("artifact_url") or ""),
            "meta": {
                "platform": build.get("platform"),
                "profile": dict(build.get("meta") or {}).get("profile"),
                "runtime_version": build.get("runtime_version"),
                "channel": dict(build.get("meta") or {}).get("channel"),
            },
        })
    for build in expo_recent:
        build_id = str(build.get("id") or "")
        if build_id and build_id in seen_expo_ids:
            continue
        items.append({
            "kind": "expo_build",
            "action_type": "expo.build",
            "title": str(build.get("name") or build.get("platform") or "Expo build"),
            "summary": str(build.get("message") or "").strip() or f"{str(build.get('platform') or 'Build').upper()} {str(build.get('status') or '').replace('_', ' ').strip()}",
            "status": str(build.get("status") or "").strip().lower() or "completed",
            "created_at": str(build.get("created_at") or ""),
            "updated_at": str(build.get("updated_at") or build.get("created_at") or ""),
            "url": str(build.get("artifact_url") or build.get("url") or ""),
            "meta": {
                "platform": build.get("platform"),
                "profile": dict(build.get("meta") or {}).get("profile"),
                "runtime_version": build.get("runtime_version"),
                "channel": dict(build.get("meta") or {}).get("channel"),
            },
        })
    for challenge in vercel_pending:
        items.append({
            "kind": "vercel_challenge",
            "action_type": challenge.get("action_type"),
            "title": str(challenge.get("title") or "Vercel deploy challenge"),
            "summary": str(challenge.get("summary") or "").strip() or "Awaiting confirmation.",
            "status": str(challenge.get("status") or "pending").strip().lower(),
            "created_at": str(challenge.get("created_at") or ""),
            "updated_at": str(challenge.get("updated_at") or challenge.get("created_at") or ""),
            "url": "",
            "meta": {
                "workspace_id": challenge.get("workspace_id"),
                "risk_tier": challenge.get("risk_tier"),
            },
        })
    for receipt in vercel_recent:
        items.append({
            "kind": "vercel_action",
            "action_type": receipt.get("action_type"),
            "title": str(receipt.get("title") or "Vercel deploy"),
            "summary": str(receipt.get("summary") or "").strip() or "Recent Vercel deploy action.",
            "status": str(receipt.get("status") or receipt.get("outcome") or "completed").strip().lower(),
            "created_at": str(receipt.get("created_at") or ""),
            "updated_at": str(receipt.get("created_at") or ""),
            "url": "",
            "meta": {
                "workspace_id": receipt.get("workspace_id"),
                "outcome": receipt.get("outcome"),
            },
        })

    items.sort(key=lambda item: (str(item.get("updated_at") or item.get("created_at") or ""), str(item.get("title") or "")), reverse=True)
    return {
        "updated_at": overview.get("updated_at"),
        "expo_active_builds": expo_active,
        "expo_recent_builds": expo_recent,
        "vercel_pending_actions": vercel_pending,
        "vercel_recent_actions": vercel_recent,
        "items": items[: max(1, min(limit, 12))],
    }


@router.get("/expo/projects/{workspace_id}/status")
async def expo_project_status(workspace_id: int):
    try:
        async with get_db() as db:
            result = await execute_expo_status_action(
                db,
                workspace_id=workspace_id,
                payload={"workspace_id": workspace_id},
            )
    except ExpoControlError as exc:
        raise HTTPException(400, exc.summary)
    return result


@router.get("/expo/projects/{workspace_id}/builds")
async def expo_project_builds(workspace_id: int, limit: int = 10):
    try:
        async with get_db() as db:
            result = await execute_expo_build_list_action(
                db,
                workspace_id=workspace_id,
                payload={"workspace_id": workspace_id, "limit": max(1, min(limit, 20))},
            )
    except ExpoControlError as exc:
        raise HTTPException(400, exc.summary)
    return result


@router.post("/expo/actions")
async def expo_actions(body: ExpoActionRequest):
    payload = dict(body.payload or {})
    workspace_id = body.workspace_id or int(payload.get("workspace_id") or 0) or None
    payload.setdefault("workspace_id", workspace_id)
    action_type = str(body.action_type or "").strip()
    if not action_type.startswith("expo."):
        raise HTTPException(400, "Unsupported Expo action type")

    if action_type == "expo.update.publish" and not body.confirm:
        return {
            "status": "confirm_required",
            "action_type": action_type,
            "summary": "Publishing an Expo update will push the latest mobile bundle immediately. Confirm to continue.",
        }

    try:
        async with get_db() as db:
            if action_type == "expo.project.status":
                result = await execute_expo_status_action(db, workspace_id=workspace_id, payload=payload)
            elif action_type == "expo.build.list":
                result = await execute_expo_build_list_action(db, workspace_id=workspace_id, payload=payload)
            elif action_type in {"expo.build.android.dev", "expo.build.ios.dev"}:
                result = await execute_expo_build_action(
                    db,
                    action_type=action_type,
                    workspace_id=workspace_id,
                    payload=payload,
                )
            elif action_type == "expo.update.publish":
                result = await execute_expo_update_publish(
                    db,
                    workspace_id=workspace_id,
                    payload=payload,
                )
            else:
                raise HTTPException(400, "Unsupported Expo action type")
            await log_event(db, "maintenance", f"Expo action requested: {action_type}")
            await db.commit()
    except ExpoControlError as exc:
        raise HTTPException(400, exc.summary)
    return {"status": "completed", "action_type": action_type, **result}
