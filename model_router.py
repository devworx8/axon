"""
Axon model routing primitives.

Local models are available by default. Set AXON_LOCAL_MODELS=0 to disable
Ollama-based routing explicitly on machines where local inference is unwanted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

# ── Local model gate ─────────────────────────────────────────────────────────
# Local Ollama stays available unless it is explicitly disabled. This keeps
# the runtime aligned with Axon's local-first posture while still allowing
# lower-capability machines to opt out.
def _local_models_enabled_from_env() -> bool:
    raw = os.environ.get("AXON_LOCAL_MODELS")
    if raw is None:
        return True
    value = str(raw).strip().lower()
    if not value:
        return True
    return value in {"1", "true", "yes", "on"}


LOCAL_MODELS_ENABLED: bool = _local_models_enabled_from_env()


class ModelRole(str, Enum):
    CODE = "code"
    GENERAL = "general"
    REASONING = "reasoning"
    EMBEDDINGS = "embeddings"
    VISION = "vision"


@dataclass(frozen=True)
class ModelRoute:
    role: ModelRole
    label: str
    description: str
    default_family: str
    preferred_runtime: str = "ollama"
    fallbacks: tuple[str, ...] = ()


@dataclass(frozen=True)
class CloudAdapter:
    adapter_id: str
    label: str
    description: str
    enabled: bool = False
    external: bool = True


@dataclass
class ModelRouterConfig:
    selected_models: dict[str, str] = field(default_factory=dict)
    preferred_runtime: str = "api"
    allow_cloud: bool = True
    adapter_enabled: dict[str, bool] = field(default_factory=dict)


LOCAL_MODEL_ROUTES: tuple[ModelRoute, ...] = (
    ModelRoute(
        role=ModelRole.CODE,
        label="Code",
        description="Primary coding and code-edit execution model.",
        default_family="qwen2.5-coder",
        fallbacks=("codegemma", "starcoder2", "codellama"),
    ),
    ModelRoute(
        role=ModelRole.GENERAL,
        label="General",
        description="Balanced local model for operator chat and summaries.",
        default_family="qwen3",
        fallbacks=("llama3.2", "phi4-mini"),
    ),
    ModelRoute(
        role=ModelRole.REASONING,
        label="Reasoning",
        description="Deeper planning and recovery model.",
        default_family="deepseek-r1",
        fallbacks=("qwen3", "llama3.2"),
    ),
    ModelRoute(
        role=ModelRole.EMBEDDINGS,
        label="Embeddings",
        description="Semantic search and retrieval model.",
        default_family="nomic-embed-text",
        fallbacks=("mxbai-embed-large",),
    ),
    ModelRoute(
        role=ModelRole.VISION,
        label="Vision",
        description="Optional visual inspection route for screenshots and assets.",
        default_family="llava",
        fallbacks=("bakllava",),
    ),
)


CLOUD_ADAPTERS: tuple[CloudAdapter, ...] = (
    CloudAdapter(
        adapter_id="openai_gpts",
        label="OpenAI GPTs",
        description="External cloud adapter for GPT-based specialist flows.",
    ),
    CloudAdapter(
        adapter_id="gemini_gems",
        label="Gemini Gems",
        description="Fallback cloud adapter for Gemini Gem specialist flows.",
    ),
)


def local_model_cards(config: ModelRouterConfig | None = None) -> list[dict]:
    if not LOCAL_MODELS_ENABLED:
        return []
    config = config or ModelRouterConfig()
    cards: list[dict] = []
    for route in LOCAL_MODEL_ROUTES:
        selected = config.selected_models.get(route.role.value, "")
        cards.append(
            {
                "role": route.role.value,
                "label": route.label,
                "description": route.description,
                "default_family": route.default_family,
                "selected_model": selected or "",
                "preferred_runtime": route.preferred_runtime,
                "fallbacks": list(route.fallbacks),
            }
        )
    return cards


def cloud_adapter_cards(config: ModelRouterConfig | None = None) -> list[dict]:
    config = config or ModelRouterConfig()
    return [
        {
            "id": adapter.adapter_id,
            "label": adapter.label,
            "description": adapter.description,
            "enabled": bool(config.allow_cloud and config.adapter_enabled.get(adapter.adapter_id, adapter.enabled)),
            "external": adapter.external,
        }
        for adapter in CLOUD_ADAPTERS
    ]


def resolve_model_for_role(
    role: str | ModelRole,
    available_models: Iterable[str],
    config: ModelRouterConfig | None = None,
) -> dict:
    if not LOCAL_MODELS_ENABLED:
        role_value = role.value if isinstance(role, ModelRole) else str(role)
        return {
            "role": role_value,
            "runtime": "api",
            "selected_model": "",
            "matched": False,
            "source": "local_models_disabled",
        }
    config = config or ModelRouterConfig()
    role_value = role.value if isinstance(role, ModelRole) else str(role)
    normalized = [name.lower() for name in available_models]

    route = next((item for item in LOCAL_MODEL_ROUTES if item.role.value == role_value), None)
    if not route:
        return {
            "role": role_value,
            "runtime": config.preferred_runtime,
            "selected_model": "",
            "matched": False,
        }

    preferred = config.selected_models.get(role_value, "")
    preferred_lower = preferred.lower()
    if preferred and preferred_lower in normalized:
        return {
            "role": role_value,
            "runtime": route.preferred_runtime,
            "selected_model": preferred,
            "matched": True,
            "source": "configured",
        }

    families = (route.default_family, *route.fallbacks)
    match = next((name for name in available_models if any(name.lower().startswith(fam) for fam in families)), "")
    return {
        "role": role_value,
        "runtime": route.preferred_runtime,
        "selected_model": match,
        "matched": bool(match),
        "source": "discovered" if match else "default",
        "default_family": route.default_family,
    }
