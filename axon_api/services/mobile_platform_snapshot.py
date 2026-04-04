"""Mission Control snapshot assembly for Axon Online mobile surfaces."""

from __future__ import annotations

from typing import Any

from axon_api.services import live_preview_sessions as live_preview_service
from axon_api.services.attention_query import attention_summary, query_attention_inbox
from axon_api.services.companion_live import build_companion_live_snapshot
from axon_api.services.expo_control_actions import load_expo_overview
from axon_api.services.mobile_axon_mode import build_mobile_axon_snapshot
from axon_api.services.mobile_control_policy import capability_label, parse_meta, seed_control_capabilities
from axon_api.services.mobile_platform_sections import (
    build_system_strip,
    build_workspace_cards,
    project_payload,
    row_dict,
)
from axon_api.services.mobile_trust import get_trust_snapshot
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_api.services.workspace_sandbox_state import serialize_preview_session
from axon_data import (
    get_project,
    list_action_receipts,
    list_companion_sessions,
    list_companion_voice_turns,
    list_mcp_servers,
    list_mcp_sessions,
    list_risk_challenges,
)


def _mission_posture(
    *,
    attention_counts: dict[str, Any],
    pending_challenges: int,
    operator_active: bool,
) -> str:
    if int(attention_counts.get("now") or 0) > 0 or pending_challenges > 0:
        return "urgent"
    if int(attention_counts.get("waiting_on_me") or 0) > 0 or operator_active:
        return "degraded"
    return "healthy"


async def _workspace_cards(
    db,
    *,
    limit: int = 8,
    focus_workspace_id: int | None = None,
    focus_expo: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return await build_workspace_cards(
        db,
        limit=limit,
        focus_workspace_id=focus_workspace_id,
        focus_expo=focus_expo,
    )


async def _system_strip(
    db,
    *,
    workspace_id: int | None,
    live_snapshot: dict[str, Any],
    expo_overview: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return await build_system_strip(
        db,
        workspace_id=workspace_id,
        live_snapshot=live_snapshot,
        expo_overview=expo_overview,
    )


async def build_platform_snapshot(
    db,
    *,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
) -> dict[str, Any]:
    capabilities = await seed_control_capabilities(db)
    live_snapshot = await build_companion_live_snapshot(
        db,
        device_id=device_id,
        session_id=session_id,
        workspace_id=workspace_id,
    )
    focus = dict(live_snapshot.get("focus") or {})
    focus_workspace_id = int(focus.get("workspace_id") or 0) or workspace_id
    attention = await attention_summary(db, workspace_id=focus_workspace_id, limit=20)
    inbox = await query_attention_inbox(db, workspace_id=focus_workspace_id, limit=20)
    trust = await get_trust_snapshot(db, device_id=device_id)
    sessions = [dict(row) for row in await list_companion_sessions(db, device_id=device_id, limit=8)]
    pending_challenges = [
        dict(row)
        for row in await list_risk_challenges(db, device_id=device_id, status="pending", limit=10)
    ]
    receipts = [dict(row) for row in await list_action_receipts(db, device_id=device_id, limit=10)]
    mcp_servers = [dict(row) for row in await list_mcp_servers(db, enabled_only=False, limit=20)]
    mcp_sessions = [dict(row) for row in await list_mcp_sessions(db, limit=20)]
    focus_project = row_dict(await get_project(db, focus_workspace_id)) if focus_workspace_id else row_dict(focus.get("workspace"))
    relationships = (
        await list_workspace_relationships_for_workspace(db, workspace_id=focus_workspace_id, limit=20)
        if focus_workspace_id
        else []
    )
    expo_overview = (
        await load_expo_overview(db, workspace_id=focus_workspace_id, limit=1)
        if focus_workspace_id
        else {
            "project_count": 0,
            "build_count": 0,
            "projects": [],
            "status": "idle",
            "summary": "Focus a workspace to load Expo / EAS state.",
            "last_sync_at": "",
        }
    )
    expo_projects = list(dict(expo_overview or {}).get("projects") or [])
    focus_expo = dict(expo_projects[0] or {}) if expo_projects else {}
    axon_snapshot = await build_mobile_axon_snapshot(
        db,
        device_id=device_id,
        presence_row=dict(live_snapshot.get("presence") or {}),
    )
    voice_turns = (
        [dict(row) for row in await list_companion_voice_turns(db, session_id=session_id, limit=10)]
        if session_id
        else []
    )
    latest_voice = next(
        (
            turn
            for turn in sorted(voice_turns, key=lambda item: int(item.get("id") or 0), reverse=True)
            if str(turn.get("role") or "").strip().lower() == "assistant"
        ),
        None,
    )
    latest_receipt = receipts[0] if receipts else None
    quick_actions = []
    for capability in capabilities:
        meta = parse_meta(capability.get("meta_json"))
        if meta.get("quick_action"):
            quick_actions.append(
                {
                    "action_type": capability.get("action_type"),
                    "label": capability_label(capability),
                    "risk_tier": capability.get("risk_tier"),
                    "available": bool(capability.get("available")),
                    "planned": bool(meta.get("planned")),
                    "quick_action": meta.get("quick_action"),
                }
            )

    return {
        "at": live_snapshot.get("at"),
        "posture": _mission_posture(
            attention_counts=dict(attention.get("counts") or {}),
            pending_challenges=len(pending_challenges),
            operator_active=bool(dict(live_snapshot.get("operator") or {}).get("active")),
        ),
        "focus": {
            **focus,
            "workspace": project_payload(focus_project),
            "preview": serialize_preview_session(
                live_preview_service.get_preview_session(workspace_id=focus_workspace_id)
            ) if focus_workspace_id else None,
            "relationships": relationships,
            "expo": focus_expo or None,
        },
        "axon": axon_snapshot,
        "live": live_snapshot,
        "attention": {
            "summary": attention,
            "inbox": inbox,
        },
        "systems": await _system_strip(
            db,
            workspace_id=focus_workspace_id,
            live_snapshot=live_snapshot,
            expo_overview=expo_overview,
        ),
        "trust": trust,
        "quick_actions": quick_actions,
        "sessions": sessions,
        "latest_command_outcome": latest_receipt,
        "latest_voice_outcome": latest_voice,
        "next_required_action": pending_challenges[0] if pending_challenges else (
            (inbox.get("waiting_on_me") or [None])[0]
        ),
        "projects": await _workspace_cards(
            db,
            limit=8,
            focus_workspace_id=focus_workspace_id,
            focus_expo=focus_expo,
        ),
        "mcp": {
            "server_count": len(mcp_servers),
            "session_count": len(mcp_sessions),
            "servers": mcp_servers,
            "sessions": mcp_sessions,
        },
        "expo": {
            "project_count": int(expo_overview.get("project_count") or 0),
            "build_count": int(expo_overview.get("build_count") or 0),
            "last_sync_at": str(expo_overview.get("last_sync_at") or expo_overview.get("updated_at") or ""),
            "projects": expo_projects,
        },
    }
