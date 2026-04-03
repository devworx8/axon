"""
Runtime snapshot helpers for Axon.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from model_router import LOCAL_MODELS_ENABLED, ModelRouterConfig, local_model_cards, resolve_model_for_role
from agent_registry import active_agents_count, lifecycle_phases, registered_agents
from permissions_guard import default_permission_cards
import gpu_guard
import provider_registry
import brain as _brain
from axon_api.services import claude_cli_runtime as _claude_cli_runtime
from axon_api.services import codex_cli_runtime as _codex_cli_runtime
from axon_core.cli_pacing import current_cli_cooldown


# Ollama model families that support vision natively
_VISION_CAPABLE_OLLAMA_FAMILIES = (
    "llava", "llava-phi", "bakllava", "moondream", "cogvlm",
    "minicpm-v", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "internvl", "phi3-vision", "phi-3-vision",
)


def _build_vision_status(settings: dict) -> dict:
    """Determine vision readiness across all backends."""
    explicit_model = (settings.get("vision_model") or "").strip()
    if explicit_model:
        return {"model": explicit_model, "ready": True, "runtime_label": "Local Ollama"}

    backend = (settings.get("ai_backend") or "ollama").lower()

    if backend == "api":
        api_model = (settings.get("api_model") or "").strip()
        provider = (settings.get("api_provider") or "").lower()
        label = provider.capitalize() if provider else "API"
        vision_ready = provider_registry.model_supports_vision(provider, api_model)
        return {
            "model": api_model or label,
            "ready": vision_ready,
            "runtime_label": f"{label} (built-in vision)" if vision_ready else "API — vision unknown",
        }

    if backend == "cli":
        return {
            "model": "Claude CLI",
            "ready": True,
            "runtime_label": "Claude CLI with forwarded image attachments",
        }

    # Ollama: check if the active model name contains a vision family keyword
    ollama_model = (settings.get("ollama_model") or "").strip().lower()
    vision_via_ollama = any(fam in ollama_model for fam in _VISION_CAPABLE_OLLAMA_FAMILIES)
    if vision_via_ollama:
        return {
            "model": ollama_model,
            "ready": True,
            "runtime_label": "Local Ollama (vision-capable model)",
        }
    return {"model": "", "ready": False, "runtime_label": "Not configured"}


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
        preferred_runtime=(settings.get("ai_backend") or "api"),
        allow_cloud=True,
        adapter_enabled={
            "openai_gpts": _setting_enabled(settings.get("openai_gpts_enabled")),
            "gemini_gems": _setting_enabled(settings.get("gemini_gems_enabled")),
        },
    )


def env_snapshot(workspace_path: str | None = None) -> dict:
    """Return environment info for a workspace path (or the server root)."""
    if workspace_path:
        probe = Path(workspace_path).expanduser().resolve()
    else:
        probe = Path(__file__).resolve().parent
    work_dir = probe.name
    # Detect virtualenv inside the workspace
    venv_name = ""
    if workspace_path:
        for candidate in (".venv", "venv", ".env"):
            vdir = probe / candidate
            if (vdir / "bin" / "python").is_file() or (vdir / "Scripts" / "python.exe").is_file():
                venv_name = candidate
                break
    else:
        venv = os.environ.get("VIRTUAL_ENV") or ""
        venv_name = Path(venv).name if venv else ""
        if not venv_name and sys.prefix != sys.base_prefix:
            venv_name = Path(sys.prefix).name
    # Git branch
    git_branch = ""
    try:
        git_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(probe), stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
    except Exception:
        pass
    return {
        "venv": venv_name,
        "git_branch": git_branch,
        "work_dir": work_dir,
    }


def build_runtime_status(
    *,
    settings: dict,
    available_models: list[str],
    ollama_running: bool,
    vault_unlocked: bool,
    workspace_count: int,
    resource_count: int = 0,
    memory_overview: dict | None = None,
    usage: dict | None = None,
) -> dict:
    usage = usage or {}
    memory_overview = memory_overview or {"total": 0, "layers": {}}
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
    selected_cli_override = str(settings.get("cli_runtime_path", settings.get("claude_cli_path", "")) or "")
    selected_cli_family = _brain._cli_runtime_family(selected_cli_override) if selected_cli_override else "claude"
    claude_runtime = {
        **_claude_cli_runtime.build_cli_runtime_snapshot(selected_cli_override if selected_cli_family == "claude" else ""),
        "runtime_id": "claude",
        "runtime_name": "Claude CLI",
    }
    codex_runtime = {
        **_codex_cli_runtime.build_codex_runtime_snapshot(selected_cli_override if selected_cli_family == "codex" else ""),
        "runtime_id": "codex",
        "runtime_name": "Codex CLI",
    }
    cli_runtime = codex_runtime if selected_cli_family == "codex" else claude_runtime
    selected_cli_path = str(cli_runtime.get("binary") or (_brain._resolve_selected_cli_binary(selected_cli_override) or ""))
    cli_environments = [dict(env) for env in (_brain.discover_cli_environments() or [])]

    backend = settings.get("ai_backend") or "api"
    cli_models = _brain.available_cli_models(selected_cli_path)
    normalized_cli_model = _brain.normalize_cli_model(
        selected_cli_path,
        settings.get("cli_runtime_model", settings.get("claude_cli_model", "")),
    )

    if backend == "api":
        api_cfg = provider_registry.runtime_api_config(settings)
        active_model = api_cfg.get("api_model") or "deepseek-reasoner"
        runtime_state = "active"
        runtime_label = "Cloud API"
    elif backend == "cli":
        active_model = normalized_cli_model or ("Codex default" if selected_cli_family == "codex" else "Claude default")
        runtime_state = "active"
        runtime_label = str(cli_runtime.get("runtime_name") or ("Codex CLI" if selected_cli_family == "codex" else "Claude CLI"))
    elif ollama_running:
        active_model = (
            settings.get("code_model")
            or settings.get("ollama_model")
            or code_route.get("selected_model")
            or code_route.get("default_family")
            or "qwen2.5-coder:1.5b"
        )
        runtime_state = "active"
        runtime_label = "Local Ollama"
    else:
        active_model = settings.get("code_model") or settings.get("ollama_model") or "Saved default"
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
        "local_models_enabled": LOCAL_MODELS_ENABLED,
        "cloud_agents": provider_registry.cloud_adapter_cards(settings),
        "api_providers": provider_registry.api_provider_cards(settings),
        "selected_api_provider": provider_registry.public_runtime_api_config(settings),
        "cli_environments": cli_environments,
        "cli_binary": selected_cli_path,
        "cli_model": normalized_cli_model,
        "cli_session_persistence_enabled": _setting_enabled(settings.get("claude_cli_session_persistence_enabled")),
        "cli_cooldown_remaining_seconds": float(
            current_cli_cooldown(key=_brain._cli_runtime_key(selected_cli_path)).get("remaining_seconds") or 0
        ),
        "cli_models": cli_models,
        "cli_runtime": cli_runtime,
        "codex_runtime": codex_runtime,
        "local_extensions": [
            {
                "id": "claude_cli",
                "label": "Claude CLI",
                "description": "Axon's supported local CLI bridge for console and agent work.",
                "runtime": claude_runtime,
                "installed": bool(claude_runtime.get("installed")),
            },
            {
                "id": "codex_cli",
                "label": "Codex CLI",
                "description": "Installable local extension for Codex workflows and non-interactive exec runs.",
                "runtime": codex_runtime,
                "installed": bool(codex_runtime.get("installed")),
            },
        ],
        "permissions": default_permission_cards(),
        "gpu_guard": gpu_profile,
        "vision_status": _build_vision_status(settings),
        "resource_bank": {
            "count": resource_count,
            "storage_path": settings.get("resource_storage_path", "~/.devbrain/resources") or "~/.devbrain/resources",
            "upload_max_mb": settings.get("resource_upload_max_mb", "20") or "20",
            "url_import_enabled": _setting_enabled(settings.get("resource_url_import_enabled", "1")),
        },
        "memory_overview": memory_overview,
        "env": env_snapshot(),
    }
