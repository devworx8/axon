"""Hybrid MCP registry and built-in gateway helpers for Axon Online."""

from __future__ import annotations

import json
from typing import Any

from axon_api.services.attention_query import attention_summary
from axon_api.services.mobile_platform_snapshot import build_platform_snapshot
from axon_api.services.mobile_control_policy import risk_tier_at_least
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_data import (
    get_all_settings,
    get_project,
    get_setting,
    list_attention_items,
    list_mcp_capabilities,
    list_mcp_servers,
    list_mcp_sessions,
    upsert_mcp_capability,
    upsert_mcp_server,
    upsert_mcp_session,
)


BUILTIN_SERVERS: list[dict[str, Any]] = [
    {
        "server_key": "axon-core",
        "name": "Axon Core",
        "transport": "server_adapter",
        "auth_source": "companion_auth",
        "scope": "global",
        "risk_tier": "act",
        "status": "online",
        "meta": {"kind": "builtin"},
    },
    {
        "server_key": "github-native",
        "name": "GitHub Native Adapter",
        "transport": "server_adapter",
        "auth_source": "settings.github_token",
        "scope": "workspace",
        "risk_tier": "act",
        "status": "online",
        "meta": {"kind": "native_connector"},
    },
    {
        "server_key": "vercel-native",
        "name": "Vercel Native Adapter",
        "transport": "server_adapter",
        "auth_source": "settings.connector_credentials_json",
        "scope": "workspace",
        "risk_tier": "destructive",
        "status": "online",
        "meta": {"kind": "native_connector"},
    },
    {
        "server_key": "sentry-native",
        "name": "Sentry Native Adapter",
        "transport": "server_adapter",
        "auth_source": "settings.sentry_api_token",
        "scope": "workspace",
        "risk_tier": "act",
        "status": "online",
        "meta": {"kind": "native_connector"},
    },
]

BUILTIN_CAPABILITIES: list[dict[str, Any]] = [
    {
        "server_key": "axon-core",
        "capability_key": "axon-core:mission.snapshot",
        "system_name": "axon",
        "tool_name": "mission.snapshot",
        "action_type": "mission.snapshot",
        "scope": "global",
        "risk_tier": "observe",
        "cache_ttl_seconds": 5,
        "mobile_direct_allowed": False,
        "available": True,
        "meta": {"label": "Mission snapshot"},
    },
    {
        "server_key": "axon-core",
        "capability_key": "axon-core:attention.summary",
        "system_name": "attention",
        "tool_name": "attention.summary",
        "action_type": "attention.summary",
        "scope": "workspace",
        "risk_tier": "observe",
        "cache_ttl_seconds": 10,
        "mobile_direct_allowed": False,
        "available": True,
        "meta": {"label": "Attention summary"},
    },
    {
        "server_key": "github-native",
        "capability_key": "github-native:workspace.status",
        "system_name": "github",
        "tool_name": "workspace.status",
        "action_type": "github.workspace.status",
        "scope": "workspace",
        "risk_tier": "observe",
        "cache_ttl_seconds": 30,
        "mobile_direct_allowed": False,
        "available": True,
        "meta": {"label": "GitHub status"},
    },
    {
        "server_key": "vercel-native",
        "capability_key": "vercel-native:workspace.status",
        "system_name": "vercel",
        "tool_name": "workspace.status",
        "action_type": "vercel.workspace.status",
        "scope": "workspace",
        "risk_tier": "observe",
        "cache_ttl_seconds": 30,
        "mobile_direct_allowed": False,
        "available": True,
        "meta": {"label": "Vercel status"},
    },
    {
        "server_key": "sentry-native",
        "capability_key": "sentry-native:workspace.status",
        "system_name": "sentry",
        "tool_name": "workspace.status",
        "action_type": "sentry.workspace.status",
        "scope": "workspace",
        "risk_tier": "observe",
        "cache_ttl_seconds": 30,
        "mobile_direct_allowed": False,
        "available": True,
        "meta": {"label": "Sentry status"},
    },
]


def _json_meta(meta: dict[str, Any] | None) -> str:
    return "{}" if meta is None else json.dumps(meta, sort_keys=True, ensure_ascii=True)


async def seed_mcp_registry(db) -> dict[str, Any]:
    server_ids: dict[str, int] = {}
    for server in BUILTIN_SERVERS:
        server_id = await upsert_mcp_server(
            db,
            server_key=str(server["server_key"]),
            name=str(server["name"]),
            transport=str(server.get("transport") or "server_adapter"),
            endpoint=str(server.get("endpoint") or ""),
            auth_source=str(server.get("auth_source") or ""),
            scope=str(server.get("scope") or "global"),
            risk_tier=str(server.get("risk_tier") or "observe"),
            enabled=True,
            status=str(server.get("status") or "online"),
            meta_json=_json_meta(server.get("meta") if isinstance(server.get("meta"), dict) else {}),
            commit=False,
        )
        server_ids[str(server["server_key"])] = server_id
        await upsert_mcp_session(
            db,
            server_id=server_id,
            session_key=f"session:{server['server_key']}",
            status=str(server.get("status") or "online"),
            detail="Built-in adapter ready",
            meta_json=_json_meta({"source": "seed_mcp_registry"}),
            commit=False,
        )

    for capability in BUILTIN_CAPABILITIES:
        await upsert_mcp_capability(
            db,
            capability_key=str(capability["capability_key"]),
            server_id=server_ids.get(str(capability["server_key"])),
            system_name=str(capability["system_name"]),
            tool_name=str(capability["tool_name"]),
            action_type=str(capability["action_type"]),
            scope=str(capability.get("scope") or "global"),
            risk_tier=str(capability.get("risk_tier") or "observe"),
            cache_ttl_seconds=int(capability.get("cache_ttl_seconds") or 0),
            mobile_direct_allowed=bool(capability.get("mobile_direct_allowed")),
            available=bool(capability.get("available", True)),
            meta_json=_json_meta(capability.get("meta") if isinstance(capability.get("meta"), dict) else {}),
            commit=False,
        )
    await db.commit()
    return {
        "servers": [dict(row) for row in await list_mcp_servers(db, enabled_only=False, limit=100)],
        "sessions": [dict(row) for row in await list_mcp_sessions(db, limit=100)],
        "capabilities": [dict(row) for row in await list_mcp_capabilities(db, limit=250)],
    }


async def invoke_builtin_mcp_capability(
    db,
    *,
    device_id: int,
    workspace_id: int | None,
    capability_key: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = dict(arguments or {})
    if capability_key == "axon-core:mission.snapshot":
        snapshot = await build_platform_snapshot(
            db,
            device_id=device_id,
            session_id=args.get("session_id"),
            workspace_id=workspace_id or args.get("workspace_id"),
        )
        return {"capability_key": capability_key, "result": snapshot}

    if capability_key == "axon-core:attention.summary":
        summary = await attention_summary(db, workspace_id=workspace_id or args.get("workspace_id"), limit=20)
        return {"capability_key": capability_key, "result": summary}

    if capability_key == "github-native:workspace.status":
        rows = await list_attention_items(db, workspace_id=workspace_id, source="github", limit=10)
        relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, external_system="github", limit=10)
        return {
            "capability_key": capability_key,
            "result": {
                "workspace_id": workspace_id,
                "relationships": relationships,
                "attention": [dict(row) for row in rows],
            },
        }

    if capability_key == "vercel-native:workspace.status":
        rows = await list_attention_items(db, workspace_id=workspace_id, source="vercel", limit=10)
        relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, external_system="vercel", limit=10)
        return {
            "capability_key": capability_key,
            "result": {
                "workspace_id": workspace_id,
                "relationships": relationships,
                "attention": [dict(row) for row in rows],
            },
        }

    if capability_key == "sentry-native:workspace.status":
        rows = await list_attention_items(db, workspace_id=workspace_id, source="sentry", limit=10)
        relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, external_system="sentry", limit=10)
        return {
            "capability_key": capability_key,
            "result": {
                "workspace_id": workspace_id,
                "relationships": relationships,
                "attention": [dict(row) for row in rows],
            },
        }

    raise ValueError(f"Unsupported MCP capability: {capability_key}")


async def registry_health_summary(db) -> dict[str, Any]:
    seeded = await seed_mcp_registry(db)
    settings = await get_all_settings(db)
    return {
        "servers": seeded["servers"],
        "sessions": seeded["sessions"],
        "capabilities": seeded["capabilities"],
        "hybrid_enabled": True,
        "mobile_direct_allowed": [
            dict(item)
            for item in seeded["capabilities"]
            if bool(item.get("mobile_direct_allowed"))
        ],
        "break_glass_enabled": bool(int(settings.get("mobile_break_glass_enabled") or 0)),
    }
