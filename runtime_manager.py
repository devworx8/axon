"""
Runtime snapshot helpers for Axon.
"""

from __future__ import annotations

from model_router import ModelRouterConfig, local_model_cards, resolve_model_for_role
from agent_registry import active_agents_count, lifecycle_phases, registered_agents
from permissions_guard import default_permission_cards
import gpu_guard
import provider_registry


def _setting_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_router_config(settings: dict) -> ModelRouterConfig:
    selected = {
        "code": settings.get("code_model", "") or settings.get("ollama_model", "") or "",
        "general": settings.get("general_model", "") or "",
        "reasoning": settings.get("reasoning_model", "") or "",
        "embeddings": settings.get("embeddings_model", "") or "",
        "vision": settings.get("vision_model", "") or "",
    }
    return ModelRouterConfig(
        selected_models=selected,
        preferred_runtime=(settings.get("ai_backend") or "ollama"),
        allow_cloud=_setting_enabled(settings.get("cloud_agents_enabled")),
        adapter_enabled={
            "openai_gpts": _setting_enabled(settings.get("openai_gpts_enabled")),
            "gemini_gems": _setting_enabled(settings.get("gemini_gems_enabled")),
            "generic_api": _setting_enabled(settings.get("generic_api_enabled")),
        },
    )


def build_runtime_status(
    *,
    settings: dict,
    available_models: list[str],
    ollama_running: bool,
    vault_unlocked: bool,
    workspace_count: int,
    resource_count: int = 0,
    usage: dict | None = None,
) -> dict:
    usage = usage or {}
    config = build_router_config(settings)
    code_route = resolve_model_for_role("code", available_models, config)
    gpu_profile = gpu_guard.detect_display_gpu_state()
    local_models = local_model_cards(config)
    for card in local_models:
        resolved = resolve_model_for_role(card["role"], available_models, config)
        families = [card["default_family"], *(card.get("fallbacks") or [])]
        family_matches = [
            name for name in available_models
            if any(name.lower().startswith(str(fam).lower()) for fam in families if fam)
        ]
        safety = gpu_guard.ollama_model_safety(resolved.get("selected_model", ""), gpu_profile) if resolved.get("selected_model") else {}
        card["resolved_model"] = resolved.get("selected_model", "")
        card["route_source"] = resolved.get("source", "default")
        card["selection_mode"] = "configured" if card.get("selected_model") else "auto"
        card["match_count"] = len(family_matches)
        card["family_matches"] = family_matches[:4]
        card["runtime_label"] = "Local Ollama"
        card["status_label"] = "Ready" if resolved.get("matched") else "Awaiting install"
        card["safety_warning"] = safety.get("warning", "")
        card["preferred_num_ctx"] = safety.get("preferred_num_ctx")
    runtime_ready = ollama_running or settings.get("ai_backend") in {"api", "cli"}
    active_model = (
        settings.get("code_model")
        or settings.get("ollama_model")
        or code_route.get("selected_model")
        or code_route.get("default_family")
        or "Saved default"
    )

    if ollama_running:
        runtime_state = "active"
        runtime_label = "Local Ollama"
    elif settings.get("ai_backend") == "cli":
        runtime_state = "warning"
        runtime_label = "CLI Agent"
    elif settings.get("ai_backend") == "api":
        runtime_state = "warning"
        runtime_label = "External API"
    else:
        runtime_state = "degraded"
        runtime_label = "Runtime offline"

    return {
        "runtime_state": runtime_state,
        "runtime_label": runtime_label,
        "active_model": active_model,
        "vault_state": "Ready" if vault_unlocked else "Locked",
        "memory_state": "Guarded" if gpu_profile.get("warning") else "Ready",
        "active_agents_count": active_agents_count(runtime_ready),
        "workspace_count": workspace_count,
        "usage_calls": usage.get("calls", 0),
        "phases": lifecycle_phases(),
        "agents": registered_agents(),
        "local_models": local_models,
        "cloud_agents": provider_registry.cloud_adapter_cards(settings),
        "api_providers": provider_registry.api_provider_cards(settings),
        "selected_api_provider": provider_registry.runtime_api_config(settings),
        "permissions": default_permission_cards(),
        "gpu_guard": gpu_profile,
        "vision_status": {
            "model": settings.get("vision_model", "") or "",
            "ready": bool(settings.get("vision_model", "")),
            "runtime_label": "Local Ollama" if settings.get("vision_model") else "Not configured",
        },
        "resource_bank": {
            "count": resource_count,
            "storage_path": settings.get("resource_storage_path", "~/.devbrain/resources") or "~/.devbrain/resources",
            "upload_max_mb": settings.get("resource_upload_max_mb", "20") or "20",
            "url_import_enabled": _setting_enabled(settings.get("resource_url_import_enabled", "1")),
        },
    }
