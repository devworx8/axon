"""Composer and runtime-selection helpers extracted from server.py."""
from __future__ import annotations

from typing import Any

import brain
from fastapi import HTTPException


def selected_cli_path(settings: dict) -> str:
    return str(settings.get("cli_runtime_path") or settings.get("claude_cli_path") or "").strip()


def selected_cli_model(settings: dict) -> str:
    return str(settings.get("cli_runtime_model") or settings.get("claude_cli_model") or "").strip()


def selected_cli_family(settings: dict) -> str:
    cli_path = selected_cli_path(settings)
    if not cli_path:
        return "claude"
    return brain._cli_runtime_family(cli_path) or "claude"


def family_cli_override_path(settings: dict, family: str) -> str:
    family_name = str(family or "").strip().lower()
    cli_path = selected_cli_path(settings)
    if not cli_path:
        return ""
    return cli_path if selected_cli_family(settings) == family_name else ""


def apply_cli_runtime_settings(data: dict, current_settings: dict) -> None:
    selected_path = str(
        data.get(
            "cli_runtime_path",
            data.get("claude_cli_path", selected_cli_path(current_settings)),
        )
        or ""
    ).strip()
    requested_model = str(
        data.get(
            "cli_runtime_model",
            data.get("claude_cli_model", selected_cli_model(current_settings)),
        )
        or ""
    ).strip()
    normalized_model = brain.normalize_cli_model(selected_path, requested_model)
    selected_family = brain._cli_runtime_family(selected_path) if selected_path else "claude"
    data["cli_runtime_path"] = selected_path
    data["cli_runtime_model"] = normalized_model
    data["claude_cli_path"] = selected_path if selected_family == "claude" else ""
    data["claude_cli_model"] = normalized_model if selected_family == "claude" else ""


def composer_options_dict(composer_options) -> dict:
    if composer_options is None:
        return {}
    if isinstance(composer_options, dict):
        return {key: value for key, value in composer_options.items() if value not in (None, "", [], {})}
    if hasattr(composer_options, "model_dump"):
        dumped = composer_options.model_dump(exclude_none=True)
        return {key: value for key, value in dumped.items() if value not in (None, "", [], {})}
    return {}


def composer_instruction_block(options: dict, *, terminal_mode_value) -> str:
    if not options:
        return ""
    lines = ["## Composer Directives"]
    intelligence = options.get("intelligence_mode") or "ask"
    action = options.get("action_mode") or ""
    agent_role = options.get("agent_role") or ""
    external_mode = options.get("external_mode") or "local_first"
    external_provider_hint = options.get("external_provider_hint") or ""
    research_pack_title = options.get("research_pack_title") or ""
    terminal_mode = terminal_mode_value(options.get("terminal_mode"), "read_only") if options.get("terminal_mode") else ""

    lines.append(f"- Intelligence mode: {str(intelligence).replace('_', ' ').title()}")
    if action:
        lines.append(f"- Action mode: {str(action).replace('_', ' ').title()}")
    if agent_role:
        lowered = str(agent_role).lower()
        if lowered == "multi_agent":
            lines.append("- Agent mode: Multi-Agent orchestration is preferred for planning, execution, and verification.")
        elif lowered == "auto":
            lines.append("- Agent mode: Autonomous workspace execution is active.")
            lines.append("- Keep working inside the selected workspace until the request is complete or clearly blocked.")
            lines.append("- Do not stop at a plan, commentary, or partial diagnosis when you can execute and verify the next step.")
            lines.append("- Ask the user only if the request is materially ambiguous, credentials are missing, or a risky action truly needs confirmation.")
        else:
            lines.append(f"- Agent role: {str(agent_role).replace('_', ' ').title()} Agent")
    if options.get("use_workspace_memory", True):
        lines.append("- Use workspace memory when it is relevant.")
    if options.get("include_timeline_history"):
        lines.append("- Include mission and timeline history when it helps.")
    if options.get("require_approval"):
        lines.append("- Require approval before risky actions or destructive changes.")
    if options.get("safe_mode", True):
        lines.append("- Safe mode is on: avoid destructive or high-risk actions.")
    if options.get("simulation_mode"):
        lines.append("- Simulation mode is on: plan and simulate, do not make changes.")
    if research_pack_title:
        lines.append(f"- Use the selected Research Pack: {research_pack_title}.")
    if options.get("live_desktop_feed"):
        lines.append("- Keep the live desktop and operator feed updated with visible progress while working.")
    if terminal_mode == "read_only":
        lines.append("- Terminal mode is read-only. Limit commands to safe inspection, logs, tests, and status checks.")
    elif terminal_mode == "approval_required":
        lines.append("- Terminal mode requires approval before executing commands that change the system.")
    elif terminal_mode == "simulation":
        lines.append("- Terminal mode is simulation-only. Explain the command plan instead of running it.")
    if external_mode == "disable_external_calls":
        lines.append("- Do not use cloud or external services. Stay fully local-first.")
    elif external_mode == "cloud_assist":
        lines.append("- Cloud assist is allowed when it materially improves the answer.")
    elif external_mode == "external_agent":
        lines.append("- External specialist agents are allowed if enabled, but local-first remains preferred.")
    if external_provider_hint:
        lines.append(f"- If cloud help is needed, prefer this provider family: {str(external_provider_hint).replace('_', ' ').title()}.")
    if intelligence == "deep_research":
        lines.append("- Perform multi-step retrieval and synthesis. Return summary, key findings, supporting context, and gaps.")
        lines.append("- Search local memory first, then attached resources, then workspace memory, and only use cloud help if allowed and truly necessary.")
    elif intelligence == "summarize":
        lines.append("- Compress the input and memory into a concise summary with minimal repetition.")
    elif intelligence == "explain":
        lines.append("- Explain clearly and simply, like a calm operator teaching a beginner.")
    elif intelligence == "compare":
        lines.append("- Compare options with pros, trade-offs, and a recommendation.")
    elif intelligence == "analyze":
        lines.append("- Inspect the available context carefully before concluding.")
    elif intelligence == "build_brief":
        lines.append("- Produce a structured brief with a clear summary, core goals, supporting context, and next actions.")
    return "\n".join(lines)


def composer_memory_layers(options: dict, *, has_attached_resources: bool = False) -> list[str]:
    intelligence = str(options.get("intelligence_mode") or "ask").lower()
    layers: list[str] = []
    if options.get("use_workspace_memory", True):
        layers.append("workspace")
    if intelligence == "deep_research" or options.get("select_research_pack") or options.get("research_pack_id"):
        layers.append("resource")
    if options.get("include_timeline_history") or intelligence in {"deep_research", "analyze"}:
        layers.append("mission")
    layers.append("user")
    if has_attached_resources and "resource" not in layers:
        layers.append("resource")
    deduped: list[str] = []
    for layer in layers:
        if layer not in deduped:
            deduped.append(layer)
    return deduped


def loads_json_object(value: str | None, *, json_module) -> dict:
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        parsed = json_module.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def local_role_for_composer(options: dict, *, agent_request: bool = False) -> str:
    agent_role = str(options.get("agent_role") or "").lower()
    intelligence = str(options.get("intelligence_mode") or "ask").lower()
    action = str(options.get("action_mode") or "").lower()
    if agent_role in {"planner", "reviewer", "repair"}:
        return "reasoning"
    if agent_role in {"auto", "coder"}:
        return "code"
    if agent_role == "scanner":
        return "general"
    if action in {"fix_repair", "optimize", "refactor"}:
        return "code"
    if intelligence in {"deep_research", "compare"}:
        return "reasoning"
    if intelligence in {"summarize", "explain", "generate"}:
        return "general"
    if agent_request:
        return "code"
    return "general"


def normalized_autonomy_profile(value: str, *, reject_elevated: bool = False) -> str:
    profile = str(value or "workspace_auto").strip().lower() or "workspace_auto"
    if profile == "manual":
        return "manual"
    if profile in {"branch_auto", "pr_auto", "merge_auto", "deploy_auto"}:
        if reject_elevated:
            raise HTTPException(400, "Elevated autonomy profiles are disabled in this hardening phase.")
        return "workspace_auto"
    return "workspace_auto"


def normalized_runtime_permissions_mode(value: str, *, fallback: str = "default") -> str:
    mode = str(value or "").strip().lower()
    if mode in {"default", "ask_first", "full_access"}:
        return mode
    return fallback


def effective_agent_runtime_permissions_mode(
    settings: dict,
    *,
    override: str = "",
    backend: str = "",
    cli_path: str = "",
    autonomy_profile: str = "",
    cli_runtime_family,
) -> str:
    normalized_autonomy = normalized_autonomy_profile(
        autonomy_profile or settings.get("autonomy_profile") or "workspace_auto"
    )
    default_fallback = "ask_first" if normalized_autonomy == "manual" else "default"
    current_mode = normalized_runtime_permissions_mode(
        settings.get("runtime_permissions_mode") or "",
        fallback=default_fallback,
    )
    requested_mode = normalized_runtime_permissions_mode(override or "", fallback=current_mode)
    if requested_mode != "full_access":
        return requested_mode
    if str(backend or "").strip().lower() != "cli":
        return current_mode
    if cli_runtime_family(str(cli_path or "")) != "codex":
        return current_mode
    return "full_access"


def normalized_external_fetch_policy(value: str) -> str:
    policy = str(value or "cache_first").strip().lower()
    if policy in {"", "memory_first", "cache_first"}:
        return "cache_first"
    if policy == "live_first":
        return "live_first"
    return "cache_first"


def normalized_max_history_turns(settings_or_payload: dict, *, setting_int, key: str = "max_history_turns") -> str:
    raw = str((settings_or_payload or {}).get(key) or "").strip()
    if raw in {"", "12"}:
        return "10"
    return str(setting_int(settings_or_payload, key, 10, minimum=6, maximum=60))


def model_budget_for_request(composer_options: dict, *, agent_request: bool = False) -> str:
    options = composer_options_dict(composer_options)
    intelligence = str(options.get("intelligence_mode") or "ask").strip().lower()
    action = str(options.get("action_mode") or "").strip().lower()
    agent_role = str(options.get("agent_role") or "").strip().lower()
    if intelligence in {"deep_research", "compare"} or agent_role in {"planner", "reviewer", "repair"}:
        return "deep"
    if agent_request or agent_role in {"auto", "coder"} or action in {"fix_repair", "optimize", "refactor"}:
        return "standard"
    return "quick"
