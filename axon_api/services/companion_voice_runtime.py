"""Runtime selection and timeout helpers for companion voice replies."""

from __future__ import annotations

import asyncio
from typing import Any

import brain
import provider_registry
import vault
from axon_api.services import ai_runtime_helpers

DEFAULT_COMPANION_VOICE_TIMEOUT_SECONDS = 8.0
DEFAULT_COMPANION_VOICE_RUNTIME_MODE = "selected_runtime"
VOICE_API_PROVIDER_PRIORITY = ("anthropic", "deepseek", "gemini_gems")
API_QUICK_MODEL_BY_PROVIDER = {
    "anthropic": brain.FAST_MODEL,
    "deepseek": "deepseek-chat",
    "gemini_gems": "gemini-2.5-flash",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def companion_voice_timeout_seconds(settings: dict[str, Any]) -> float:
    raw_value = _clean(settings.get("companion_voice_timeout_seconds"))
    if not raw_value:
        return DEFAULT_COMPANION_VOICE_TIMEOUT_SECONDS
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_COMPANION_VOICE_TIMEOUT_SECONDS
    return max(4.0, min(20.0, parsed))


def companion_voice_runtime_mode(settings: dict[str, Any]) -> str:
    raw_value = _clean(settings.get("companion_voice_runtime_mode")).lower()
    if raw_value in {"selected_runtime", "follow_selected_runtime", "follow_runtime", "selected"}:
        return "selected_runtime"
    if raw_value in {"auto_fastest", "fastest", "auto"}:
        return "auto_fastest"
    return DEFAULT_COMPANION_VOICE_RUNTIME_MODE


def _resolved_backend(settings: dict[str, Any]) -> str:
    backend = _clean(settings.get("ai_backend")).lower()
    if backend:
        return backend
    cli_path = _clean(settings.get("cli_runtime_path") or settings.get("claude_cli_path"))
    return "cli" if cli_path else "api"


def _resolved_quick_model(settings: dict[str, Any], ai: dict[str, Any]) -> str:
    configured = ai_runtime_helpers.configured_budget_model(settings, "quick")
    if configured:
        return configured
    return ai_runtime_helpers.default_budget_model_for_ai(
        ai,
        settings,
        "quick",
        brain_module=brain,
    )


def _resolved_api_quick_model(settings: dict[str, Any], provider_id: str, default_model: str = "") -> str:
    configured = ai_runtime_helpers.configured_budget_model(settings, "quick")
    if configured:
        return configured
    provider_key = _clean(provider_id).lower()
    if provider_key in API_QUICK_MODEL_BY_PROVIDER:
        return API_QUICK_MODEL_BY_PROVIDER[provider_key]
    return _clean(default_model)


def _voice_api_provider_candidates(settings: dict[str, Any]) -> list[str]:
    selected = _clean(settings.get("api_provider") or provider_registry.selected_api_provider_id(settings)).lower()
    ordered: list[str] = []
    for provider_id in VOICE_API_PROVIDER_PRIORITY:
        if provider_id not in ordered:
            ordered.append(provider_id)
    if selected and selected not in ordered and selected in provider_registry.PROVIDER_BY_ID:
        ordered.append(selected)
    return ordered


def companion_voice_model_kwargs(settings: dict[str, Any]) -> dict[str, Any]:
    backend = _resolved_backend(settings)
    cli_path = _clean(settings.get("cli_runtime_path") or settings.get("claude_cli_path"))
    if backend == "cli":
        ai = {"backend": "cli", "cli_path": cli_path}
        quick_model = _resolved_quick_model(settings, ai)
        return {
            "backend": "cli",
            "cli_path": cli_path,
            "cli_model": quick_model or _clean(settings.get("cli_runtime_model") or settings.get("claude_cli_model") or "gpt-5.4"),
        }

    if backend == "ollama":
        ai = {"backend": "ollama"}
        quick_model = _resolved_quick_model(settings, ai)
        return {
            "backend": "ollama",
            "ollama_url": _clean(settings.get("ollama_url")),
            "ollama_model": quick_model or _clean(settings.get("ollama_model") or brain.OLLAMA_DEFAULT_MODEL),
        }

    api_runtime = provider_registry.runtime_api_config(settings)
    api_key = _clean(api_runtime.get("api_key"))
    if not api_key and cli_path:
        ai = {"backend": "cli", "cli_path": cli_path}
        quick_model = _resolved_quick_model(settings, ai)
        return {
            "backend": "cli",
            "cli_path": cli_path,
            "cli_model": quick_model or _clean(settings.get("cli_runtime_model") or settings.get("claude_cli_model") or "gpt-5.4"),
        }

    return {
        "backend": "api",
        "api_key": api_key,
        "api_provider": _clean(api_runtime.get("provider_id") or settings.get("api_provider") or "anthropic"),
        "api_base_url": _clean(api_runtime.get("api_base_url") or settings.get("api_base_url")),
        "api_model": _resolved_api_quick_model(
            settings,
            _clean(api_runtime.get("provider_id") or settings.get("api_provider") or "anthropic"),
            _clean(api_runtime.get("api_model") or settings.get("api_model")),
        ),
    }


async def _api_candidate_for_provider(
    db,
    settings: dict[str, Any],
    provider_id: str,
    *,
    allow_vault: bool,
) -> dict[str, Any] | None:
    normalized_provider_id = _clean(provider_id).lower()
    if normalized_provider_id not in provider_registry.PROVIDER_BY_ID:
        return None
    candidate_settings = dict(settings)
    candidate_settings["api_provider"] = normalized_provider_id
    api_runtime = provider_registry.runtime_api_config(candidate_settings)
    api_key = _clean(api_runtime.get("api_key"))
    if not api_key and allow_vault:
        api_key = _clean(await vault.vault_resolve_provider_key(db, normalized_provider_id))
    api_base_url = _clean(api_runtime.get("api_base_url") or candidate_settings.get("api_base_url"))
    if not api_key or not api_base_url:
        return None
    return {
        "backend": "api",
        "api_key": api_key,
        "api_provider": normalized_provider_id,
        "api_base_url": api_base_url,
        "api_model": _resolved_api_quick_model(
            candidate_settings,
            normalized_provider_id,
            _clean(api_runtime.get("api_model") or candidate_settings.get("api_model")),
        ),
    }


async def resolve_companion_voice_model_candidates(
    db,
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    resolved = companion_voice_model_kwargs(settings)
    backend = _resolved_backend(settings)
    if backend == "ollama":
        return [resolved]

    if companion_voice_runtime_mode(settings) == "selected_runtime":
        if backend == "api":
            provider_id = _clean(settings.get("api_provider") or provider_registry.selected_api_provider_id(settings))
            selected_candidate = await _api_candidate_for_provider(
                db,
                settings,
                provider_id,
                allow_vault=vault.VaultSession.is_unlocked(),
            )
            if selected_candidate:
                return [selected_candidate]
        return [resolved]

    vault_unlocked = vault.VaultSession.is_unlocked()
    candidates: list[dict[str, Any]] = []
    for provider_id in _voice_api_provider_candidates(settings):
        candidate = await _api_candidate_for_provider(
            db,
            settings,
            provider_id,
            allow_vault=vault_unlocked,
        )
        if candidate:
            candidates.append(candidate)

    if not any(candidate == resolved for candidate in candidates):
        candidates.append(resolved)
    return candidates


async def resolve_companion_voice_model_kwargs(
    db,
    settings: dict[str, Any],
) -> dict[str, Any]:
    candidates = await resolve_companion_voice_model_candidates(db, settings)
    return dict(candidates[0] if candidates else companion_voice_model_kwargs(settings))


def build_companion_voice_timeout_response(
    *,
    project: dict[str, Any] | None = None,
    attention: dict[str, Any] | None = None,
) -> str:
    project = dict(project or {})
    counts = dict((attention or {}).get("counts") or {})
    workspace_name = _clean(project.get("name")) or "the current workspace"
    branch = _clean(project.get("git_branch"))

    lines = [
        f"I could not finish that live voice reply within the quick-response budget for {workspace_name}.",
    ]
    if branch:
        lines.append(f"Branch: {branch}")
    if counts:
        lines.append(
            "Attention now: "
            f"{int(counts.get('now') or 0)}; "
            f"waiting on me: {int(counts.get('waiting_on_me') or 0)}; "
            f"watch: {int(counts.get('watch') or 0)}"
        )
    lines.append("For a near-instant answer, ask about attention, branch, workspace path, or linked systems.")
    return "\n".join(lines)


async def generate_direct_companion_voice_reply(
    *,
    user_message: str,
    history: list[dict[str, str]],
    context_block: str,
    project: dict[str, Any],
    attention: dict[str, Any] | None,
    ai: dict[str, Any],
    settings: dict[str, Any],
    ai_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = [dict(candidate) for candidate in (ai_candidates or [ai]) if isinstance(candidate, dict)]
    if not candidates:
        candidates = [dict(ai or {})]
    timeout_seconds = companion_voice_timeout_seconds(settings)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    errors: list[str] = []

    for candidate in candidates:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            response = await asyncio.wait_for(
                brain.chat(
                    user_message=user_message,
                    history=history,
                    context_block=context_block,
                    project_name=_clean(project.get("name")) or None,
                    backend=_clean(candidate.get("backend") or "cli"),
                    api_key=_clean(candidate.get("api_key")),
                    api_provider=_clean(candidate.get("api_provider")),
                    api_base_url=_clean(candidate.get("api_base_url")),
                    api_model=_clean(candidate.get("api_model")),
                    cli_path=_clean(candidate.get("cli_path")),
                    cli_model=_clean(candidate.get("cli_model")),
                    ollama_url=_clean(candidate.get("ollama_url")),
                    ollama_model=_clean(candidate.get("ollama_model")),
                ),
                timeout=remaining,
            )
        except TimeoutError:
            break
        except Exception as exc:
            errors.append(str(exc))
            continue

        return {
            "response_text": _clean(response.get("content")),
            "tokens_used": int(response.get("tokens") or 0),
            "backend": _clean(candidate.get("backend") or "cli"),
            "timed_out": False,
        }

    detail = build_companion_voice_timeout_response(project=project, attention=attention)
    if errors:
        detail = f"{detail}\nLast runtime error: {_clean(errors[-1])[:180]}"
    return {
        "response_text": detail,
        "tokens_used": 0,
        "backend": "local_timeout",
        "timed_out": True,
    }
