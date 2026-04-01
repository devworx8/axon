from __future__ import annotations

from typing import Awaitable, Callable, Optional

import provider_registry


ResolveProviderKey = Callable[[str], Awaitable[str]]


async def _resolve_candidate_key(
    candidate: dict,
    settings: dict,
    *,
    resolve_provider_key: Optional[ResolveProviderKey],
    vault_unlocked: bool,
) -> str:
    candidate_key = settings.get(candidate.get("key_setting", ""), "") or ""
    if candidate_key or not vault_unlocked or resolve_provider_key is None:
        return candidate_key
    return await resolve_provider_key(candidate.get("id", ""))


async def auto_route_vision_runtime(
    *,
    settings: dict,
    ai: dict,
    resource_bundle: dict,
    requested_model: str = "",
    resolve_provider_key: Optional[ResolveProviderKey] = None,
    vault_unlocked: bool = False,
) -> tuple[dict, list[str]]:
    if not resource_bundle.get("image_paths"):
        return ai, []

    routed = dict(ai)
    warnings: list[str] = []
    explicit_model = bool((requested_model or "").strip())
    backend = (routed.get("backend") or settings.get("ai_backend") or "api").strip().lower()

    if backend == "cli":
        return routed, warnings

    if backend == "api":
        provider_id = (routed.get("api_provider") or "").strip().lower()
        model_name = routed.get("api_model") or ""
        if provider_registry.model_supports_vision(provider_id, model_name):
            return routed, warnings
        if explicit_model:
            warnings.append(
                f"Attached image kept on explicitly selected model `{requested_model}`, but that model is not vision-capable. Axon will use image metadata only."
            )
            return routed, warnings

        for candidate_id in provider_registry.preferred_vision_provider_ids():
            candidate = provider_registry.merged_provider_config(candidate_id, settings)
            candidate["id"] = candidate_id
            candidate_key = await _resolve_candidate_key(
                candidate,
                settings,
                resolve_provider_key=resolve_provider_key,
                vault_unlocked=vault_unlocked,
            )
            if not candidate_key or not provider_registry.model_supports_vision(candidate_id, candidate.get("model", "")):
                continue
            routed.update(
                {
                    "backend": "api",
                    "api_provider": candidate_id,
                    "api_key": candidate_key,
                    "api_base_url": candidate.get("base_url", ""),
                    "api_model": candidate.get("model", ""),
                }
            )
            warnings.append(
                f"Image attached — auto-routed from {provider_id or 'current API model'} to {candidate.get('label', candidate_id)} for real vision."
            )
            return routed, warnings

        warnings.append("Image attached, but no configured vision-capable API provider is available. Axon will use image metadata only.")
        return routed, warnings

    ollama_model = routed.get("ollama_model") or settings.get("ollama_model") or ""
    if resource_bundle.get("vision_model"):
        routed["ollama_model"] = resource_bundle["vision_model"]
        warnings.append(f"Image attached — auto-switched Ollama to vision model `{resource_bundle['vision_model']}`.")
        return routed, warnings

    if explicit_model:
        warnings.append(
            f"Attached image kept on explicitly selected model `{requested_model}`, but that Ollama model is not vision-capable. Axon will use image metadata only."
        )
        return routed, warnings

    for candidate_id in provider_registry.preferred_vision_provider_ids():
        candidate = provider_registry.merged_provider_config(candidate_id, settings)
        candidate["id"] = candidate_id
        candidate_key = await _resolve_candidate_key(
            candidate,
            settings,
            resolve_provider_key=resolve_provider_key,
            vault_unlocked=vault_unlocked,
        )
        if not candidate_key or not provider_registry.model_supports_vision(candidate_id, candidate.get("model", "")):
            continue
        routed.update(
            {
                "backend": "api",
                "api_provider": candidate_id,
                "api_key": candidate_key,
                "api_base_url": candidate.get("base_url", ""),
                "api_model": candidate.get("model", ""),
            }
        )
        warnings.append(
            f"Image attached — auto-routed from local model `{ollama_model or 'current model'}` to {candidate.get('label', candidate_id)} for real vision."
        )
        return routed, warnings

    warnings.append("Image attached, but no vision-capable model is configured. Axon will use image metadata only.")
    return routed, warnings