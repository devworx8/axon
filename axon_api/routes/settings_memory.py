"""Settings, cloud-provider, and memory routes extracted from the legacy server facade."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from axon_api.settings_models import SettingsUpdate


class CloudProviderTestRequest(BaseModel):
    provider_id: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class MemoryUpdate(BaseModel):
    pinned: bool | None = None
    trust_level: str | None = None


class SettingsMemoryRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        memory_engine_module: Any,
        provider_registry_module: Any,
        devvault_module: Any,
        normalized_autonomy_profile: Callable[..., str],
        normalized_runtime_permissions_mode: Callable[..., str],
        normalized_external_fetch_policy: Callable[[str], str],
        normalized_max_history_turns: Callable[[dict, str], str],
        selected_cli_path: Callable[[dict], str],
        selected_cli_model: Callable[[dict], str],
        stored_ollama_runtime_mode: Callable[[dict], str],
        apply_cli_runtime_settings: Callable[[dict, dict], None],
        setting_int: Callable[..., int],
        ensure_memory_layers_synced: Callable[..., Awaitable[dict[str, Any]]],
        serialize_memory_item: Callable[[Any], dict[str, Any]],
    ) -> None:
        self._db = db_module
        self._memory_engine = memory_engine_module
        self._provider_registry = provider_registry_module
        self._devvault = devvault_module
        self._normalized_autonomy_profile = normalized_autonomy_profile
        self._normalized_runtime_permissions_mode = normalized_runtime_permissions_mode
        self._normalized_external_fetch_policy = normalized_external_fetch_policy
        self._normalized_max_history_turns = normalized_max_history_turns
        self._selected_cli_path = selected_cli_path
        self._selected_cli_model = selected_cli_model
        self._stored_ollama_runtime_mode = stored_ollama_runtime_mode
        self._apply_cli_runtime_settings = apply_cli_runtime_settings
        self._setting_int = setting_int
        self._ensure_memory_layers_synced = ensure_memory_layers_synced
        self._serialize_memory_item = serialize_memory_item

    async def get_settings(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            settings.pop("extra_allowed_cmds", None)
            settings["autonomy_profile"] = self._normalized_autonomy_profile(
                settings.get("autonomy_profile") or "workspace_auto"
            )
            settings["runtime_permissions_mode"] = self._normalized_runtime_permissions_mode(
                settings.get("runtime_permissions_mode") or "",
                fallback="ask_first" if settings["autonomy_profile"] == "manual" else "default",
            )
            settings["external_fetch_policy"] = self._normalized_external_fetch_policy(
                settings.get("external_fetch_policy") or "cache_first"
            )
            settings["max_history_turns"] = self._normalized_max_history_turns(settings)
            settings["ai_backend"] = settings.get("ai_backend") or "api"
            settings["api_provider"] = self._provider_registry.selected_api_provider_id(settings)
            settings["cli_runtime_path"] = self._selected_cli_path(settings)
            settings["cli_runtime_model"] = self._selected_cli_model(settings)
            settings["ollama_runtime_mode"] = self._stored_ollama_runtime_mode(settings)
            for key in (
                "cloud_agents_enabled",
                "openai_gpts_enabled",
                "gemini_gems_enabled",
                "resource_url_import_enabled",
                "claude_cli_session_persistence_enabled",
                "live_feed_enabled",
                "stable_domain_enabled",
                "alerts_enabled",
                "alerts_desktop",
                "alerts_mobile",
                "alerts_missions",
                "alerts_runtime",
                "alerts_morning_brief",
                "alerts_tunnel",
                "dash_bridge_enabled",
            ):
                settings[key] = str(settings.get(key, "")).strip().lower() in {"1", "true", "yes", "on"}
            for key_name in (
                "anthropic_api_key",
                "gemini_api_key",
                "deepseek_api_key",
                "azure_speech_key",
                "cloudflare_tunnel_token",
                "vercel_api_token",
                "sentry_api_token",
            ):
                raw = settings.get(key_name, "")
                settings[f"{key_name}_set"] = bool(raw)
                settings[key_name] = self._provider_registry.mask_secret(raw) if raw else ""
            settings["api_key_set"] = settings.get("deepseek_api_key_set", False)
            if settings.get("github_token"):
                token = settings["github_token"]
                settings["github_token"] = token[:4] + "..." + token[-4:] if len(token) > 10 else "set"
                settings["github_token_set"] = True
            else:
                settings["github_token_set"] = False
            if settings.get("dash_bridge_token"):
                token = settings["dash_bridge_token"]
                settings["dash_bridge_token"] = self._provider_registry.mask_secret(token)
                settings["dash_bridge_token_set"] = True
            else:
                settings["dash_bridge_token_set"] = False
        return settings

    async def update_settings(self, body: SettingsUpdate):
        async with self._db.get_db() as conn:
            data = body.model_dump(exclude_none=True)
            current_settings = await self._db.get_all_settings(conn)
            current_runtime_permissions_mode = self._normalized_runtime_permissions_mode(
                current_settings.get("runtime_permissions_mode") or "",
                fallback="ask_first"
                if self._normalized_autonomy_profile(current_settings.get("autonomy_profile") or "workspace_auto") == "manual"
                else "default",
            )
            if "runtime_permissions_mode" in data:
                data["runtime_permissions_mode"] = self._normalized_runtime_permissions_mode(
                    data.get("runtime_permissions_mode") or "",
                    fallback=current_runtime_permissions_mode,
                )
                if "autonomy_profile" not in data:
                    data["autonomy_profile"] = "manual" if data["runtime_permissions_mode"] == "ask_first" else "workspace_auto"
            if "autonomy_profile" in data:
                data["autonomy_profile"] = self._normalized_autonomy_profile(
                    data.get("autonomy_profile") or "workspace_auto",
                    reject_elevated=True,
                )
                if "runtime_permissions_mode" not in data:
                    data["runtime_permissions_mode"] = "ask_first" if data["autonomy_profile"] == "manual" else "default"
            if "external_fetch_policy" in data:
                data["external_fetch_policy"] = self._normalized_external_fetch_policy(
                    data.get("external_fetch_policy") or "cache_first"
                )
            if "max_history_turns" in data:
                data["max_history_turns"] = self._normalized_max_history_turns(data)
            for ttl_key, ttl_default in (
                ("workspace_snapshot_ttl_seconds", 120),
                ("memory_query_cache_ttl_seconds", 60),
                ("external_fetch_cache_ttl_seconds", 21600),
            ):
                if ttl_key in data:
                    data[ttl_key] = str(self._setting_int(data, ttl_key, ttl_default, minimum=30, maximum=86400))
            for spec in self._provider_registry.PROVIDERS:
                key_name = spec.base_url_setting
                if key_name in data:
                    raw_value = str(data.get(key_name, "") or "").strip()
                    if raw_value:
                        merged = self._provider_registry.merged_provider_config(
                            spec.provider_id,
                            current_settings,
                            {"base_url": raw_value},
                        )
                        data[key_name] = merged.get("base_url", raw_value)
                    else:
                        data[key_name] = ""
            if any(key in data for key in ("cli_runtime_model", "cli_runtime_path", "claude_cli_model", "claude_cli_path")):
                self._apply_cli_runtime_settings(data, current_settings)
            for key, value in data.items():
                if isinstance(value, bool):
                    await self._db.set_setting(conn, key, "1" if value else "0")
                else:
                    await self._db.set_setting(conn, key, str(value))
        return {"updated": list(data.keys())}

    async def list_cloud_providers(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            vault_keys = await self._devvault.vault_resolve_all_provider_keys(conn)
            for provider_id, api_key in vault_keys.items():
                spec = self._provider_registry.PROVIDER_BY_ID.get(provider_id)
                if spec and api_key and not settings.get(spec.key_setting):
                    settings = {**settings, spec.key_setting: api_key}
        return {
            "selected": self._provider_registry.runtime_api_config(settings),
            "providers": self._provider_registry.api_provider_cards(settings),
            "adapters": self._provider_registry.cloud_adapter_cards(settings),
        }

    async def test_cloud_provider(self, body: CloudProviderTestRequest):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            api_key = body.api_key
            if not api_key and body.provider_id:
                api_key = await self._devvault.vault_resolve_provider_key(conn, body.provider_id) or ""
        return await self._provider_registry.test_provider_connection(
            body.provider_id,
            settings,
            overrides={
                "api_key": api_key,
                "base_url": body.base_url,
                "model": body.model,
            },
        )

    async def sync_memory(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            overview = await self._ensure_memory_layers_synced(conn, settings, force=True)
        return {"synced": True, "overview": overview}

    async def memory_overview(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            overview = await self._ensure_memory_layers_synced(conn, settings)
        return overview

    async def memory_search(
        self,
        q: str = Query("", alias="q"),
        project_id: int | None = None,
        layers: str = "",
        limit: int = Query(6, ge=1, le=20),
    ):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            await self._ensure_memory_layers_synced(conn, settings)
            selected_layers = [item.strip() for item in layers.split(",") if item.strip()]
            results = await self._memory_engine.search_memory(
                conn,
                query=q,
                settings=settings,
                workspace_id=project_id,
                layers=selected_layers or None,
                limit=limit,
            )
        return {
            "items": [
                {
                    "id": item["id"],
                    "layer": item["layer"],
                    "title": item["title"],
                    "summary": item.get("summary", ""),
                    "source": item.get("source", ""),
                    "trust_level": item.get("trust_level", "medium"),
                    "workspace_id": item.get("workspace_id"),
                    "score": item.get("score", 0),
                }
                for item in results
            ]
        }

    async def list_memory_items(
        self,
        q: str = Query("", alias="q"),
        layer: str = "",
        trust_level: str = "",
        pinned: bool | None = None,
        project_id: int | None = None,
        limit: int = Query(120, ge=1, le=300),
    ):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            await self._ensure_memory_layers_synced(conn, settings)
            rows = await self._db.list_memory_items_filtered(
                conn,
                search=q,
                layer=layer,
                trust_level=trust_level,
                pinned=pinned,
                workspace_id=project_id,
                limit=limit,
            )
        return {"items": [self._serialize_memory_item(row) for row in rows]}

    async def update_memory_item(self, memory_id: int, body: MemoryUpdate):
        if body.trust_level not in (None, "high", "medium", "low"):
            raise HTTPException(400, "Invalid trust level")
        async with self._db.get_db() as conn:
            row = await self._db.get_memory_item(conn, memory_id)
            if not row:
                raise HTTPException(404, "Memory item not found")
            await self._db.update_memory_item_state(
                conn,
                memory_id,
                pinned=body.pinned,
                trust_level=body.trust_level,
            )
            updated = await self._db.get_memory_item(conn, memory_id)
        return self._serialize_memory_item(updated)


def build_settings_memory_router(**deps: Any) -> tuple[APIRouter, SettingsMemoryRouteHandlers]:
    handlers = SettingsMemoryRouteHandlers(**deps)
    router = APIRouter(tags=["settings-memory"])
    router.add_api_route("/api/settings", handlers.get_settings, methods=["GET"])
    router.add_api_route("/api/settings", handlers.update_settings, methods=["POST"])
    router.add_api_route("/api/cloud/providers", handlers.list_cloud_providers, methods=["GET"])
    router.add_api_route("/api/cloud/providers/test", handlers.test_cloud_provider, methods=["POST"])
    router.add_api_route("/api/memory/sync", handlers.sync_memory, methods=["POST"])
    router.add_api_route("/api/memory/overview", handlers.memory_overview, methods=["GET"])
    router.add_api_route("/api/memory/search", handlers.memory_search, methods=["GET"])
    router.add_api_route("/api/memory/items", handlers.list_memory_items, methods=["GET"])
    router.add_api_route("/api/memory/items/{memory_id}", handlers.update_memory_item, methods=["PATCH"])
    return router, handlers
