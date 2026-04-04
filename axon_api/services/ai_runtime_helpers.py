"""AI runtime selection helpers extracted from server.py."""
from __future__ import annotations

from fastapi import HTTPException

from axon_api.services import composer_runtime


async def ai_params(
    settings: dict,
    conn=None,
    *,
    allow_degraded_api: bool = False,
    provider_registry_module,
    resolved_api_runtime,
    selected_cli_path,
    selected_cli_model,
    cli_session_persistence_enabled,
    brain_module,
) -> dict:
    backend = settings.get("ai_backend", "api")
    selected_provider_id = provider_registry_module.selected_api_provider_id(settings)
    api_runtime, api_key = await resolved_api_runtime(settings, selected_provider_id, conn)
    provider_id = api_runtime.get("provider_id", selected_provider_id or "deepseek")

    if backend in {"cli", "ollama"} and not api_key:
        fallback_candidates = [
            spec.provider_id
            for spec in provider_registry_module.PROVIDERS
            if spec.runtime_capable and spec.provider_id != provider_id
        ]
        for candidate_id in fallback_candidates:
            candidate_runtime, candidate_key = await resolved_api_runtime(settings, candidate_id, conn)
            if candidate_key:
                api_runtime = candidate_runtime
                api_key = candidate_key
                provider_id = candidate_runtime.get("provider_id", candidate_id)
                break

    cli_path = selected_cli_path(settings)
    cli_model = selected_cli_model(settings)
    cli_session_persistence = cli_session_persistence_enabled(
        settings.get("claude_cli_session_persistence_enabled")
    )
    ollama_url = settings.get("ollama_url", "")
    ollama_model = settings.get("ollama_model", "")
    if backend == "api" and not api_key and not allow_degraded_api:
        provider_label = api_runtime.get("provider_label", "External API")
        raise HTTPException(400, f"{provider_label} key not set. Add it to the Secure Vault or Settings → Runtime.")
    if backend == "cli" and not cli_path and not brain_module._find_cli():
        raise HTTPException(400, "CLI agent not found. Set the path in Settings.")
    return {
        "api_key": api_key,
        "api_provider": provider_id,
        "api_base_url": api_runtime.get("api_base_url", ""),
        "api_model": api_runtime.get("api_model", ""),
        "backend": backend,
        "cli_path": cli_path,
        "cli_model": cli_model,
        "cli_session_persistence": cli_session_persistence,
        "ollama_url": ollama_url,
        "ollama_model": ollama_model,
    }


def configured_budget_model(settings: dict, budget: str) -> str:
    quick = str(settings.get("quick_model") or "").strip()
    standard = str(settings.get("standard_model") or "").strip()
    deep = str(settings.get("deep_model") or "").strip()
    if budget == "deep":
        return deep or standard or quick
    if budget == "quick":
        return quick or standard or deep
    return standard or quick or deep


def default_budget_model_for_ai(ai: dict, settings: dict, budget: str, *, brain_module) -> str:
    backend = str(ai.get("backend") or settings.get("ai_backend") or "api").strip().lower()
    if backend == "cli":
        cli_path = str(ai.get("cli_path") or composer_runtime.selected_cli_path(settings) or "").strip()
        family = brain_module._cli_runtime_family(cli_path)
        if family == "codex":
            return "gpt-5.1-codex-mini" if budget == "quick" else "gpt-5.4"
        if budget == "quick":
            return "haiku"
        if budget == "deep":
            return "opus"
        return "sonnet"
    if backend == "ollama":
        if budget == "quick":
            return brain_module.OLLAMA_FAST_MODEL
        return str(settings.get("ollama_model") or brain_module.OLLAMA_DEFAULT_MODEL).strip()
    return ""


def model_call_kwargs(ai: dict) -> dict:
    allowed_keys = {
        "backend",
        "api_key",
        "api_provider",
        "api_base_url",
        "api_model",
        "cli_path",
        "cli_model",
        "cli_session_persistence",
        "ollama_url",
        "ollama_model",
    }
    return {key: value for key, value in dict(ai or {}).items() if key in allowed_keys}


async def effective_ai_params(
    settings: dict,
    composer_options: dict,
    *,
    conn=None,
    agent_request: bool = False,
    requested_model: str = "",
    provider_registry_module,
    devvault_module,
    db_module,
    brain_module,
    runtime_manager_module,
    runtime_truth_service_module,
    resolve_model_for_role,
    runtime_truth_for_settings,
    family_cli_override_path,
    resolved_api_runtime,
    cli_session_persistence_enabled,
    ai_params_fn=None,
) -> dict:
    if ai_params_fn is not None:
        resolved_ai = await ai_params_fn(
            settings,
            conn,
            allow_degraded_api=True,
        )
    else:
        resolved_ai = await ai_params(
            settings,
            conn,
            allow_degraded_api=True,
            provider_registry_module=provider_registry_module,
            resolved_api_runtime=resolved_api_runtime,
            selected_cli_path=composer_runtime.selected_cli_path,
            selected_cli_model=composer_runtime.selected_cli_model,
            cli_session_persistence_enabled=cli_session_persistence_enabled,
            brain_module=brain_module,
        )
    ai = dict(resolved_ai)
    external_mode = str(composer_options.get("external_mode") or "local_first").lower()

    if not agent_request:
        if external_mode == "disable_external_calls" and ai.get("backend") != "ollama":
            ai["backend"] = "ollama"
        elif external_mode in {"cloud_assist", "external_agent"} and ai.get("backend") == "ollama":
            api_runtime = provider_registry_module.runtime_api_config(settings)
            provider_id = api_runtime.get("provider_id", "anthropic")
            api_key = api_runtime.get("api_key", "")
            if not api_key and devvault_module.VaultSession.is_unlocked():
                if conn:
                    api_key = await devvault_module.vault_resolve_provider_key(conn, provider_id)
                else:
                    async with db_module.get_db() as temp_conn:
                        api_key = await devvault_module.vault_resolve_provider_key(temp_conn, provider_id)
            if api_key:
                ai.update(
                    {
                        "backend": "api",
                        "api_key": api_key,
                        "api_provider": provider_id,
                        "api_base_url": api_runtime.get("api_base_url", ""),
                        "api_model": api_runtime.get("api_model", ""),
                    }
                )

    runtime_truth, runtime_status = await runtime_truth_for_settings(
        settings,
        conn,
        backend_override=str(ai.get("backend") or ""),
    )
    effective_runtime = str(runtime_truth.get("effective_runtime") or "").strip().lower()
    selected_runtime = str(runtime_truth.get("selected_runtime") or "").strip().lower()
    if effective_runtime == runtime_truth_service_module.SELF_HEAL_RUNTIME and selected_runtime != effective_runtime:
        codex_runtime = dict(runtime_status.get("codex_runtime") or {})
        codex_binary = str(
            codex_runtime.get("binary")
            or family_cli_override_path(settings, "codex")
            or brain_module._find_codex_cli()
        ).strip()
        if codex_binary:
            ai.update(
                {
                    "backend": "cli",
                    "cli_path": codex_binary,
                    "cli_model": runtime_truth_service_module.SELF_HEAL_MODEL,
                }
            )

    budget = composer_runtime.model_budget_for_request(composer_options, agent_request=agent_request)
    budget_model = configured_budget_model(settings, budget) or default_budget_model_for_ai(
        ai,
        settings,
        budget,
        brain_module=brain_module,
    )

    if ai.get("backend") == "ollama":
        if requested_model:
            ai["ollama_model"] = requested_model
            return ai
        available_models = await brain_module.ollama_list_models(settings.get("ollama_url", ""))
        route = resolve_model_for_role(
            composer_runtime.local_role_for_composer(composer_options, agent_request=agent_request),
            available_models,
            runtime_manager_module.build_router_config(settings),
        )
        if route.get("selected_model"):
            ai["ollama_model"] = route["selected_model"]
    elif ai.get("backend") == "api":
        if requested_model:
            ai["api_model"] = requested_model
            return ai
        role = composer_runtime.local_role_for_composer(composer_options, agent_request=agent_request)
        role_map = brain_module.API_MODEL_BY_ROLE.get(ai.get("api_provider", ""), {})
        if role in role_map:
            ai["api_model"] = role_map[role]
    else:
        if runtime_truth.get("self_heal_active") and effective_runtime == runtime_truth_service_module.SELF_HEAL_RUNTIME:
            ai["cli_model"] = runtime_truth_service_module.SELF_HEAL_MODEL
        elif requested_model:
            ai["cli_model"] = requested_model

    if not requested_model and budget_model:
        if ai.get("backend") == "api":
            ai["api_model"] = budget_model
        elif ai.get("backend") == "cli":
            selected_cli_path = str(ai.get("cli_path") or composer_runtime.selected_cli_path(settings) or "").strip()
            normalized_budget = brain_module.normalize_cli_model(selected_cli_path, budget_model)
            ai["cli_model"] = normalized_budget or budget_model
        elif ai.get("backend") == "ollama":
            ai["ollama_model"] = budget_model

    ai["budget_class"] = budget
    if ai.get("backend") == "api" and not ai.get("api_key"):
        provider_label = str(runtime_truth.get("selected_runtime_label") or "External API")
        raise HTTPException(400, f"{provider_label} key not set. Add it to the Secure Vault or Settings → Runtime.")
    return ai


def looks_like_image_generation_request(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    strong_markers = (
        "generate an image",
        "create an image",
        "make an image",
        "make me an image",
        "generate a logo",
        "create a logo",
        "generate an illustration",
        "create an illustration",
        "generate a poster",
        "create a poster",
        "generate concept art",
        "text to image",
    )
    if any(marker in text for marker in strong_markers):
        return True
    visual_nouns = ("image", "logo", "illustration", "poster", "sticker", "banner", "icon", "mockup", "render")
    visual_verbs = ("generate", "create", "make", "design", "draw")
    return any(verb in text for verb in visual_verbs) and any(noun in text for noun in visual_nouns)


async def auto_route_image_generation_runtime(
    conn,
    *,
    settings: dict,
    ai: dict,
    user_message: str,
    requested_model: str = "",
    agent_request: bool = False,
    provider_registry_module,
    devvault_module,
) -> tuple[dict, list[str]]:
    if not looks_like_image_generation_request(user_message):
        return ai, []
    warnings: list[str] = []
    if not agent_request:
        warnings.append("Image generation requests work best in Agent mode so Axon can call the generate_image tool automatically.")
        return ai, warnings
    if (requested_model or "").strip():
        warnings.append(f"Image generation request kept on explicitly selected model `{requested_model}`.")
        return ai, warnings

    routed = dict(ai)
    candidate_id = "gemini_gems"
    candidate = provider_registry_module.merged_provider_config(
        candidate_id,
        settings,
        {"model": settings.get("gemini_image_model") or "gemini-3.1-flash-image-preview"},
    )
    candidate_key = settings.get(candidate.get("key_setting", ""), "") or ""
    if not candidate_key and devvault_module.VaultSession.is_unlocked():
        candidate_key = await devvault_module.vault_resolve_provider_key(conn, candidate_id)
    if not candidate_key:
        warnings.append("Image generation was requested, but no Gemini key is configured. Axon can plan the image prompt, but cannot render it yet.")
        return routed, warnings

    routed.update(
        {
            "backend": "api",
            "api_provider": candidate_id,
            "api_key": candidate_key,
            "api_base_url": candidate.get("base_url", ""),
            "api_model": candidate.get("model", "gemini-3.1-flash-image-preview"),
        }
    )
    warnings.append(f"Image generation request — auto-routed to {candidate.get('label', candidate_id)} for image-capable tool use.")
    return routed, warnings
