"""
Provider registry for Axon's external/cloud runtimes.

This keeps outward-facing provider names and configuration fields in one place
without breaking the existing local-first runtime paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
import httpx


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def mask_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 10:
        return "set"
    return f"{raw[:4]}...{raw[-4:]}"


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    description: str
    transport: str
    key_setting: str
    base_url_setting: str
    model_setting: str
    default_base_url: str
    default_model: str
    external: bool = True
    adapter_setting: str = ""
    runtime_capable: bool = True
    model_placeholder: str = ""


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider_id="deepseek",
        label="DeepSeek",
        description="Default runtime — high-capability code and reasoning via OpenAI-compatible API.",
        transport="openai_compatible",
        key_setting="deepseek_api_key",
        base_url_setting="deepseek_base_url",
        model_setting="deepseek_api_model",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-reasoner",
        model_placeholder="deepseek-reasoner",
    ),
    ProviderSpec(
        provider_id="anthropic",
        label="Anthropic",
        description="Claude models — premium runtime for complex agentic and reasoning tasks.",
        transport="anthropic",
        key_setting="anthropic_api_key",
        base_url_setting="anthropic_base_url",
        model_setting="anthropic_api_model",
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-5",
        model_placeholder="claude-sonnet-4-5",
    ),
    ProviderSpec(
        provider_id="gemini_gems",
        label="Gemini",
        description="Gemini models — fallback runtime and specialist flows.",
        transport="gemini",
        key_setting="gemini_api_key",
        base_url_setting="gemini_base_url",
        model_setting="gemini_api_model",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.5-pro",
        adapter_setting="gemini_gems_enabled",
        model_placeholder="gemini-2.5-pro",
    ),
)

PROVIDER_BY_ID = {spec.provider_id: spec for spec in PROVIDERS}


def _normalized_base_url(spec: ProviderSpec, base_url: str) -> str:
    url = (base_url or spec.default_base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if spec.provider_id == "deepseek":
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = (parsed.netloc or parsed.path or "").strip().lower()
        if "platform.deepseek.com" in host:
            return (spec.default_base_url or "https://api.deepseek.com/v1").rstrip("/")
        if host == "api.deepseek.com":
            path = parsed.path.rstrip("/")
            if not path or path == "":
                return "https://api.deepseek.com/v1"
            if path == "/chat/completions":
                return "https://api.deepseek.com/v1"
    if spec.transport == "anthropic" and not url.endswith("/v1"):
        if url.endswith("/"):
            url = url[:-1]
        if not url.endswith("/v1"):
            url = f"{url}/v1"
    if spec.transport == "openai_compatible" and url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return url


def provider_state(spec: ProviderSpec, settings: dict, *, selected_api_provider: str = "") -> dict:
    key = settings.get(spec.key_setting, "") or ""
    base_url = _normalized_base_url(spec, settings.get(spec.base_url_setting, "") or "")
    model = (settings.get(spec.model_setting, "") or spec.default_model or "").strip()
    enabled = truthy(settings.get(spec.adapter_setting)) if spec.adapter_setting else selected_api_provider == spec.provider_id
    configured = bool(key.strip()) and (bool(base_url) if spec.transport != "gemini" or spec.default_base_url else True)
    return {
        "id": spec.provider_id,
        "label": spec.label,
        "description": spec.description,
        "transport": spec.transport,
        "external": spec.external,
        "enabled": enabled,
        "configured": configured,
        "selected": selected_api_provider == spec.provider_id,
        "key_setting": spec.key_setting,
        "base_url_setting": spec.base_url_setting,
        "model_setting": spec.model_setting,
        "base_url": base_url or spec.default_base_url,
        "default_base_url": spec.default_base_url,
        "default_model": spec.default_model,
        "model": model,
        "model_placeholder": spec.model_placeholder or spec.default_model,
        "key_hint": mask_secret(key),
        "adapter_setting": spec.adapter_setting,
    }


def selected_api_provider_id(settings: dict) -> str:
    provider_id = (settings.get("api_provider") or "deepseek").strip()
    return provider_id if provider_id in PROVIDER_BY_ID else "deepseek"


def api_provider_cards(settings: dict) -> list[dict]:
    selected = selected_api_provider_id(settings)
    return [provider_state(spec, settings, selected_api_provider=selected) for spec in PROVIDERS if spec.runtime_capable]


def cloud_adapter_cards(settings: dict) -> list[dict]:
    selected = selected_api_provider_id(settings)
    return [
        provider_state(spec, settings, selected_api_provider=selected)
        for spec in PROVIDERS
        if spec.adapter_setting
    ]


def runtime_api_config(settings: dict) -> dict:
    spec = PROVIDER_BY_ID[selected_api_provider_id(settings)]
    state = provider_state(spec, settings, selected_api_provider=spec.provider_id)
    return {
        "provider_id": spec.provider_id,
        "provider_label": spec.label,
        "transport": spec.transport,
        "api_key": settings.get(spec.key_setting, "") or "",
        "api_base_url": state["base_url"],
        "api_model": state["model"] or spec.default_model,
    }


def model_supports_vision(provider_id: str, model: str = "") -> bool:
    provider = (provider_id or "").strip().lower()
    model_name = (model or "").strip().lower()
    if provider == "anthropic":
        return True
    if provider == "gemini_gems":
        return True
    if provider == "deepseek":
        return any(token in model_name for token in ("vl", "vision"))
    return any(token in model_name for token in ("vision", "image", "vl"))


def model_supports_image_generation(provider_id: str, model: str = "") -> bool:
    provider = (provider_id or "").strip().lower()
    model_name = (model or "").strip().lower()
    if provider == "gemini_gems":
        return (not model_name) or any(
            token in model_name
            for token in ("flash-image", "image-preview", "pro-image", "imagen")
        )
    return False


def preferred_vision_provider_ids() -> tuple[str, ...]:
    return ("anthropic", "gemini_gems")


def preferred_image_generation_provider_ids() -> tuple[str, ...]:
    return ("gemini_gems",)


def merged_provider_config(provider_id: str, settings: dict, overrides: dict | None = None) -> dict:
    spec = PROVIDER_BY_ID[provider_id]
    merged = dict(settings)
    overrides = overrides or {}
    if overrides.get("api_key") is not None:
        merged[spec.key_setting] = overrides.get("api_key", "")
    if overrides.get("base_url") is not None:
        merged[spec.base_url_setting] = overrides.get("base_url", "")
    if overrides.get("model") is not None:
        merged[spec.model_setting] = overrides.get("model", "")
    return provider_state(spec, merged, selected_api_provider=provider_id)


async def test_provider_connection(provider_id: str, settings: dict, overrides: dict | None = None) -> dict:
    if provider_id not in PROVIDER_BY_ID:
        return {"ok": False, "message": "Unknown provider."}

    spec = PROVIDER_BY_ID[provider_id]
    state = merged_provider_config(provider_id, settings, overrides)
    api_key = (overrides or {}).get("api_key")
    if api_key is None:
        api_key = settings.get(spec.key_setting, "") or ""

    if not api_key.strip():
        return {"ok": False, "message": f"{spec.label} needs an API key before it can be tested.", "provider": state}

    base_url = state["base_url"] or spec.default_base_url
    if not base_url:
        return {"ok": False, "message": f"{spec.label} needs a base URL before it can be tested.", "provider": state}

    try:
        timeout = httpx.Timeout(12.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if spec.transport == "anthropic":
                resp = await client.get(
                    f"{base_url}/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
            elif spec.transport == "gemini":
                resp = await client.get(
                    f"{base_url}/models",
                    params={"key": api_key},
                )
            else:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )

        if 200 <= resp.status_code < 300:
            return {
                "ok": True,
                "message": f"{spec.label} responded successfully.",
                "provider": state,
                "status_code": resp.status_code,
            }
        detail = resp.text[:200].strip() or resp.reason_phrase
        return {
            "ok": False,
            "message": f"{spec.label} returned HTTP {resp.status_code}. {detail}",
            "provider": state,
            "status_code": resp.status_code,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"{spec.label} test failed: {exc}",
            "provider": state,
        }
