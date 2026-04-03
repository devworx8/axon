"""Public runtime observability helpers for Axon."""

from __future__ import annotations

from typing import Any

import provider_registry

SELF_HEAL_RUNTIME = "codex_cli"
SELF_HEAL_RUNTIME_LABEL = "Codex CLI"
SELF_HEAL_MODEL = "gpt-5.4"


def _selected_backend(settings: dict[str, Any]) -> str:
    backend = str(settings.get("ai_backend") or "api").strip().lower()
    return backend if backend in {"api", "cli", "ollama"} else "api"


def _selected_cli_runtime(status: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    cli_runtime = dict(status.get("cli_runtime") or {})
    runtime_id = str(cli_runtime.get("runtime_id") or "claude").strip().lower()
    if runtime_id == "codex":
        return "codex_cli", "Codex CLI", dict(status.get("codex_runtime") or cli_runtime)
    return "claude_cli", "Claude CLI", cli_runtime


def _selected_api_runtime(status: dict[str, Any], settings: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    provider = dict(status.get("selected_api_provider") or provider_registry.public_runtime_api_config(settings))
    provider_id = str(provider.get("provider_id") or provider_registry.selected_api_provider_id(settings)).strip().lower()
    provider_label = str(provider.get("provider_label") or provider_id or "API").strip() or "API"
    return f"{provider_id}_api", provider_label, provider


def _api_runtime_ready(provider: dict[str, Any]) -> bool:
    return bool(provider.get("api_key_configured")) and bool(str(provider.get("api_base_url") or "").strip())


def _provider_error_message(provider: dict[str, Any]) -> str:
    label = str(provider.get("provider_label") or "API").strip() or "API"
    if not provider.get("api_key_configured"):
        return f"{label} is selected, but no API key is configured."
    if not str(provider.get("api_base_url") or "").strip():
        return f"{label} is selected, but no API base URL is configured."
    return ""


def _codex_self_heal_ready(codex_runtime: dict[str, Any]) -> bool:
    auth = dict(codex_runtime.get("auth") or {})
    return bool(codex_runtime.get("installed")) and bool(auth.get("logged_in"))


def build_runtime_truth(
    status: dict[str, Any],
    *,
    settings: dict[str, Any],
    ollama_running: bool = False,
) -> dict[str, Any]:
    backend = _selected_backend(settings)
    selected_runtime = ""
    selected_label = ""
    effective_runtime = ""
    effective_label = ""
    auth_method = ""
    subscription_type = ""
    cooldown_source = ""
    fallback_reason = ""
    provider_error = ""
    self_heal_active = False

    claude_runtime = dict(status.get("cli_runtime") or {})
    codex_runtime = dict(status.get("codex_runtime") or {})
    selected_api_runtime, selected_api_label, provider = _selected_api_runtime(status, settings)
    selected_cli_runtime, selected_cli_label, selected_cli_snapshot = _selected_cli_runtime(status)
    cooldown_seconds = float(status.get("cli_cooldown_remaining_seconds") or 0)
    ollama_label = "Local Ollama"
    self_heal_target_runtime = SELF_HEAL_RUNTIME if codex_runtime.get("installed") else ""
    self_heal_target_label = SELF_HEAL_RUNTIME_LABEL if codex_runtime.get("installed") else ""
    self_heal_target_model = SELF_HEAL_MODEL if codex_runtime.get("installed") else ""
    codex_self_heal_ready = _codex_self_heal_ready(codex_runtime)

    def _activate_codex_self_heal(reason: str) -> None:
        nonlocal effective_runtime, effective_label, auth_method, subscription_type, fallback_reason, self_heal_active
        auth = dict(codex_runtime.get("auth") or {})
        effective_runtime = SELF_HEAL_RUNTIME
        effective_label = SELF_HEAL_RUNTIME_LABEL
        auth_method = str(auth.get("auth_method") or "").strip()
        subscription_type = ""
        fallback_reason = reason
        self_heal_active = True

    if backend == "api":
        selected_runtime = selected_api_runtime
        selected_label = selected_api_label
        effective_runtime = selected_api_runtime
        effective_label = selected_api_label
        auth_method = "api_key" if provider.get("api_key_configured") else ""
        provider_error = _provider_error_message(provider)
        if provider_error and codex_self_heal_ready:
            _activate_codex_self_heal(
                f"{selected_api_label} is not ready, so Axon will use Codex CLI (`{SELF_HEAL_MODEL}`) until the selected runtime is healthy again."
            )
    elif backend == "ollama":
        selected_runtime = "ollama"
        selected_label = ollama_label
        effective_runtime = "ollama"
        effective_label = ollama_label
        auth_method = "local"
        if not ollama_running:
            provider_error = "Ollama is selected, but the local runtime is not currently running."
            if codex_self_heal_ready:
                _activate_codex_self_heal(
                    f"Local Ollama is unavailable, so Axon will use Codex CLI (`{SELF_HEAL_MODEL}`) until the selected runtime is healthy again."
                )
    else:
        selected_runtime = selected_cli_runtime
        selected_label = selected_cli_label
        effective_runtime = selected_cli_runtime
        effective_label = selected_cli_label

        cli_auth = dict(selected_cli_snapshot.get("auth") or {})
        auth_method = str(cli_auth.get("auth_method") or "").strip()
        subscription_type = str(cli_auth.get("subscription_type") or "").strip()
        if not bool(cli_auth.get("logged_in")):
            provider_error = str(cli_auth.get("message") or f"{selected_cli_label} is not signed in.").strip()
            if selected_cli_runtime == "claude_cli" and codex_self_heal_ready:
                _activate_codex_self_heal(
                    f"Claude CLI is not signed in, so Axon will use Codex CLI (`{SELF_HEAL_MODEL}`) until Claude is ready again."
                )

        if selected_cli_runtime == "claude_cli" and cooldown_seconds > 0:
            cooldown_source = "claude_cli_rate_limit"
            if codex_self_heal_ready:
                _activate_codex_self_heal(
                    f"Claude CLI is cooling down after a rate limit, so Axon will use Codex CLI (`{SELF_HEAL_MODEL}`) until the cooldown clears."
                )
            elif _api_runtime_ready(provider):
                effective_runtime = selected_api_runtime
                effective_label = selected_api_label
                auth_method = "api_key"
                subscription_type = ""
                fallback_reason = (
                    f"Claude CLI is cooling down after a rate limit, so Axon will use {selected_api_label} when a cloud fallback path is available."
                )
                provider_error = _provider_error_message(provider)
            elif ollama_running:
                effective_runtime = "ollama"
                effective_label = ollama_label
                auth_method = "local"
                subscription_type = ""
                fallback_reason = (
                    "Claude CLI is cooling down after a rate limit, so Axon will use Local Ollama when a local fallback path is available."
                )
                provider_error = ""
            else:
                fallback_reason = (
                    "Claude CLI is cooling down after a rate limit, and no fallback runtime is currently ready."
                )
                if not provider_error:
                    provider_error = fallback_reason

    return {
        "selected_runtime": selected_runtime,
        "selected_runtime_label": selected_label,
        "effective_runtime": effective_runtime,
        "effective_runtime_label": effective_label,
        "auth_method": auth_method,
        "subscription_type": subscription_type,
        "cooldown_source": cooldown_source,
        "fallback_reason": fallback_reason,
        "provider_error": provider_error,
        "self_heal_active": self_heal_active,
        "self_heal_target_runtime": self_heal_target_runtime,
        "self_heal_target_label": self_heal_target_label,
        "self_heal_target_model": self_heal_target_model,
    }
