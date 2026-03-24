"""
Runtime snapshot helpers for Axon.
"""

from __future__ import annotations

from model_router import ModelRouterConfig, cloud_adapter_cards, local_model_cards, resolve_model_for_role
from agent_registry import active_agents_count, lifecycle_phases, registered_agents
from permissions_guard import default_permission_cards
import gpu_guard


def build_router_config(settings: dict) -> ModelRouterConfig:
    selected = {
        "code": settings.get("ollama_model", "") or "",
        "general": settings.get("general_model", "") or "",
        "reasoning": settings.get("reasoning_model", "") or "",
        "embeddings": settings.get("embeddings_model", "") or "",
        "vision": settings.get("vision_model", "") or "",
    }
    return ModelRouterConfig(
        selected_models=selected,
        preferred_runtime="ollama",
        allow_cloud=bool(settings.get("cloud_agents_enabled")),
    )


def build_runtime_status(
    *,
    settings: dict,
    available_models: list[str],
    ollama_running: bool,
    vault_unlocked: bool,
    workspace_count: int,
    usage: dict | None = None,
) -> dict:
    usage = usage or {}
    config = build_router_config(settings)
    code_route = resolve_model_for_role("code", available_models, config)
    gpu_profile = gpu_guard.detect_display_gpu_state()
    runtime_ready = ollama_running or settings.get("ai_backend") in {"api", "cli"}
    active_model = (
        settings.get("ollama_model")
        or code_route.get("selected_model")
        or settings.get("ollama_model")
        or "Saved default"
    )

    if ollama_running:
        runtime_state = "active"
        runtime_label = "Local Ollama"
    elif settings.get("ai_backend") == "cli":
        runtime_state = "warning"
        runtime_label = "Claude CLI"
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
        "local_models": local_model_cards(config),
        "cloud_agents": cloud_adapter_cards(config),
        "permissions": default_permission_cards(),
        "gpu_guard": gpu_profile,
    }
