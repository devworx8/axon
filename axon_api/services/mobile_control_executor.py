"""Typed action execution for the Axon Online mobile control plane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import brain
from axon_api.services import companion_runtime, companion_sessions as companion_sessions_service
from axon_api.services.connector_attention import sync_all_connector_attention, sync_workspace_connector_attention
from axon_api.services.mobile_action_preflight import preflight_typed_action
from axon_api.services.mobile_approval_actions import normalize_approval_action
from axon_api.services.mobile_control_audit import create_destructive_challenge, record_action_receipt
from axon_api.services.mobile_control_policy import capability_label, capability_requires_elevation, get_seeded_control_capability
from axon_api.services.expo_control_actions import (
    execute_expo_build_action,
    execute_expo_build_list_action,
    execute_expo_status_action,
    execute_expo_update_publish,
)
from axon_api.services.mobile_preview_actions import restart_workspace_preview, stop_workspace_preview
from axon_api.services.mobile_runtime_actions import log_runtime_restart_requested, queue_runtime_restart
from axon_api.services.mobile_trust import has_active_elevation
from axon_api.services.mobile_workspace_actions import (
    execute_workspace_connector_reconcile,
    execute_workspace_focus_set,
    execute_workspace_inspect,
)
from axon_api.services.mobile_vercel_actions import (
    execute_vercel_promote,
    execute_vercel_rollback,
)
from axon_data import (
    get_attention_item,
    resolve_attention_item,
    set_setting,
)

def _runtime_paths() -> tuple[Path, Path, Path]:
    base_dir = Path(getattr(brain, "DEVBRAIN_DIR", Path.home() / ".devbrain")).expanduser().resolve()
    log_path = Path(getattr(brain, "DEVBRAIN_LOG", base_dir / "devbrain.log")).expanduser().resolve()
    pid_path = Path(getattr(brain, "PIDFILE", base_dir / ".pid")).expanduser().resolve()
    return base_dir, log_path, pid_path


async def _execute_supported_action(
    db,
    *,
    device_id: int,
    session_id: int | None,
    workspace_id: int | None,
    action_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if action_type == "workspace.preview.restart":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0)
        if target_workspace_id <= 0:
            raise ValueError("workspace.preview.restart requires a workspace_id")
        return await restart_workspace_preview(
            db,
            workspace_id=target_workspace_id,
            restart=bool(payload.get("restart", True)),
        )

    if action_type == "workspace.preview.stop":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0)
        if target_workspace_id <= 0:
            raise ValueError("workspace.preview.stop requires a workspace_id")
        return await stop_workspace_preview(
            db,
            workspace_id=target_workspace_id,
        )

    if action_type == "workspace.inspect":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0)
        if target_workspace_id <= 0:
            raise ValueError("workspace.inspect requires a workspace_id")
        return await execute_workspace_inspect(db, workspace_id=target_workspace_id)

    if action_type == "workspace.focus.set":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0) or None
        return await execute_workspace_focus_set(db, workspace_id=target_workspace_id)

    if action_type == "workspace.connectors.reconcile":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0)
        if target_workspace_id <= 0:
            raise ValueError("workspace.connectors.reconcile requires a workspace_id")
        return await execute_workspace_connector_reconcile(
            db,
            workspace_id=target_workspace_id,
            allow_repo_writes=bool(payload.get("allow_repo_writes")),
        )

    if action_type == "workspace.run_agent":
        content = str(payload.get("prompt") or payload.get("content") or "").strip()
        if not content:
            raise ValueError("workspace.run_agent requires a prompt")
        return await companion_runtime.process_companion_voice_turn(
            db,
            device_id=device_id,
            session_id=session_id,
            workspace_id=workspace_id,
            content=content,
            transcript=str(payload.get("transcript") or content),
            voice_mode=str(payload.get("voice_mode") or "mobile_command"),
            meta={"surface": "mobile_control_action", "action_type": action_type},
        )

    if action_type == "attention.resolve":
        attention_id = int(payload.get("attention_id") or 0)
        if attention_id <= 0:
            raise ValueError("attention.resolve requires attention_id")
        await resolve_attention_item(db, attention_id)
        row = await get_attention_item(db, attention_id)
        return {"attention": dict(row) if row else {"id": attention_id}, "summary": "Attention item resolved."}

    if action_type == "attention.sync":
        target_workspace_id = int(payload.get("workspace_id") or workspace_id or 0) or None
        items = (
            await sync_workspace_connector_attention(db, workspace_id=target_workspace_id)
            if target_workspace_id
            else await sync_all_connector_attention(db, limit=int(payload.get("limit") or 25), max_workspaces=12)
        )
        return {"ingested": len(items), "items": items, "summary": f"Ingested {len(items)} signal(s)."}

    if action_type == "agent.approve":
        approval_action = dict(payload.get("approval_action") or payload.get("action") or {})
        scope = str(payload.get("scope") or "once").strip().lower()
        if scope not in {"once", "task", "session"}:
            raise ValueError("Unsupported approval scope")
        if not approval_action.get("action_fingerprint"):
            raise ValueError("approval_action.action_fingerprint is required")
        canonical = await normalize_approval_action(db, approval_action)
        if not canonical:
            raise ValueError("approval action could not be validated")
        if canonical.get("action_fingerprint") != approval_action.get("action_fingerprint"):
            raise ValueError("approval action fingerprint mismatch")
        brain.agent_allow_action(
            canonical,
            scope=scope,
            session_id=str(payload.get("agent_session_id") or payload.get("session_id") or canonical.get("session_id") or ""),
        )
        return {
            "approved": True,
            "action": canonical,
            "scope": scope,
            "state": brain.agent_get_action_state(),
            "summary": "Exact blocked action approved.",
        }

    if action_type == "session.resume":
        session_key = str(payload.get("session_key") or "").strip()
        if session_id and not session_key:
            current = await companion_sessions_service.ensure_companion_session(
                db,
                session_key=f"companion:{device_id}:{workspace_id or ''}:",
                device_id=device_id,
                workspace_id=workspace_id,
                status="active",
                mode="companion",
                summary="Mobile session refreshed",
                meta={"surface": "mobile_control_action"},
            )
            return {"session": current, "summary": "Session refreshed."}
        if not session_key:
            raise ValueError("session.resume requires session_key or active session")
        resumed = await companion_sessions_service.resume_companion_session(
            db,
            session_key=session_key,
            agent_session_id=str(payload.get("agent_session_id") or ""),
            status="active",
        )
        return {"session": resumed, "summary": "Session resumed."}

    if action_type == "session.stop":
        if not session_id:
            raise ValueError("session.stop requires an active session_id")
        await companion_sessions_service.close_companion_workspace_session(db, session_id=session_id)
        return {"session_id": session_id, "summary": "Mobile session closed."}

    if action_type == "runtime.permissions.set":
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"default", "ask_first", "full_access"}:
            raise ValueError("runtime.permissions.set requires mode: default, ask_first, or full_access")
        await set_setting(db, "runtime_permissions_mode", mode)
        return {"mode": mode, "summary": f"Runtime permissions set to {mode.replace('_', ' ')}."}

    if action_type == "runtime.restart":
        await log_runtime_restart_requested(db)
        devbrain_dir, devbrain_log, pidfile = _runtime_paths()
        return queue_runtime_restart(
            devbrain_dir=devbrain_dir,
            devbrain_log=devbrain_log,
            pidfile=pidfile,
        )

    if action_type == "expo.project.status":
        return await execute_expo_status_action(
            db,
            workspace_id=int(payload.get("workspace_id") or workspace_id or 0) or None,
            payload=payload,
        )

    if action_type == "expo.build.list":
        return await execute_expo_build_list_action(
            db,
            workspace_id=int(payload.get("workspace_id") or workspace_id or 0) or None,
            payload=payload,
        )

    if action_type in {"expo.build.android.dev", "expo.build.ios.dev"}:
        return await execute_expo_build_action(
            db,
            action_type=action_type,
            workspace_id=int(payload.get("workspace_id") or workspace_id or 0) or None,
            payload=payload,
        )

    if action_type == "expo.update.publish":
        return await execute_expo_update_publish(
            db,
            workspace_id=int(payload.get("workspace_id") or workspace_id or 0) or None,
            payload=payload,
        )

    if action_type == "vercel.deploy.promote":
        return await execute_vercel_promote(db, payload=payload)

    if action_type == "vercel.deploy.rollback":
        return await execute_vercel_rollback(db, payload=payload)

    raise ValueError(f"Unsupported action_type: {action_type}")


async def execute_typed_action(
    db,
    *,
    device_id: int,
    session_id: int | None,
    workspace_id: int | None,
    action_type: str,
    payload: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    payload = dict(payload or {})
    capability = await get_seeded_control_capability(db, action_type)
    if not capability:
        raise ValueError(f"Unknown action_type: {action_type}")

    risk_tier = str(capability.get("risk_tier") or "observe")
    title = capability_label(capability) or action_type
    if not bool(capability.get("available")):
        receipt = await record_action_receipt(
            db,
            device_id=device_id,
            session_id=session_id,
            workspace_id=workspace_id,
            action_type=action_type,
            risk_tier=risk_tier,
            status="blocked",
            outcome="unsupported",
            title=title,
            summary="This mobile action is planned but not executable yet.",
            request_payload=payload,
            result_payload={"available": False},
        )
        return {
            "status": "unsupported",
            "capability": capability,
            "receipt": receipt,
            "result": {"available": False, "message": "This action is not wired yet."},
        }

    preflight = await preflight_typed_action(
        db,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        action_type=action_type,
        payload=payload,
        risk_tier=risk_tier,
        title=title,
        capability=capability,
    )
    blocked_response = preflight.get("blocked_response")
    if blocked_response:
        return blocked_response
    payload = dict(preflight.get("payload") or payload)
    title = str(preflight.get("title") or title).strip() or title
    challenge_summary = str(preflight.get("challenge_summary") or "").strip()

    if capability_requires_elevation(capability) and not confirmed:
        challenge = await create_destructive_challenge(
            db,
            device_id=device_id,
            session_id=session_id,
            workspace_id=workspace_id,
            action_type=action_type,
            risk_tier=risk_tier,
            title=title,
            summary=challenge_summary,
            request_payload=payload,
            meta={"capability": capability},
        )
        receipt = await record_action_receipt(
            db,
            device_id=device_id,
            session_id=session_id,
            workspace_id=workspace_id,
            challenge_id=int(challenge.get("id") or 0) or None,
            action_type=action_type,
            risk_tier=risk_tier,
            status="challenge_required",
            outcome="pending_challenge",
            title=title,
            summary="High-risk action paused until the device confirms the challenge.",
            request_payload=payload,
            result_payload={"challenge_id": challenge.get("id")},
        )
        return {
            "status": "challenge_required",
            "capability": capability,
            "challenge": challenge,
            "receipt": receipt,
        }

    result = await _execute_supported_action(
        db,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        action_type=action_type,
        payload=payload,
    )
    receipt = await record_action_receipt(
        db,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
        action_type=action_type,
        risk_tier=risk_tier,
        status="completed",
        outcome="success",
        title=title,
        summary=str(result.get("summary") or title),
        request_payload=payload,
        result_payload=result,
    )
    return {
        "status": "completed",
        "capability": capability,
        "receipt": receipt,
        "result": result,
    }


async def confirm_destructive_action(
    db,
    *,
    device_id: int,
    session_id: int | None,
    workspace_id: int | None,
    challenge: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(challenge.get("action_type") or "").strip()
    request_payload = json.loads(str(challenge.get("request_json") or "{}") or "{}")
    risk_tier = str(challenge.get("risk_tier") or "destructive").strip().lower()
    if not await has_active_elevation(db, device_id=device_id, required_risk_tier=risk_tier):
        raise ValueError("A fresh mobile elevation session is required before confirming this action.")
    return await execute_typed_action(
        db,
        device_id=device_id,
        session_id=session_id or int(challenge.get("session_id") or 0) or None,
        workspace_id=workspace_id or int(challenge.get("workspace_id") or 0) or None,
        action_type=action_type,
        payload=request_payload,
        confirmed=True,
    )
