"""Bridge companion voice turns into Axon's local operator path."""

from __future__ import annotations

from typing import Any

import brain
from axon_api.services import companion_live
from axon_api.services.live_operator_state import set_live_operator


LOCAL_TOOLS_FALLBACK_PREFIX = "This request needs local tools."


def needs_local_operator_upgrade(response_text: str) -> bool:
    return str(response_text or "").strip().startswith(LOCAL_TOOLS_FALLBACK_PREFIX)


async def run_companion_agent_turn(
    *,
    user_message: str,
    history: list[dict[str, str]],
    context_block: str,
    project: dict[str, Any],
    ai: dict[str, Any],
    settings: dict[str, str],
    workspace_id: int | None = None,
) -> dict[str, Any]:
    response_chunks: list[str] = []
    approval_required: dict[str, Any] | None = None
    tool_events: list[dict[str, Any]] = []
    agent_session_id = ""

    set_live_operator(
        active=True,
        mode="agent",
        phase="observe",
        title="Inspecting the live voice request",
        detail=str(user_message or "").strip()[:180],
        workspace_id=int(project.get("id") or 0) or workspace_id,
    )

    async for event in brain.run_agent(
        user_message,
        history,
        context_block=context_block,
        project_name=str(project.get("name") or "").strip() or None,
        workspace_path=str(project.get("path") or "").strip(),
        backend=str(ai.get("backend") or settings.get("ai_backend") or "cli").strip(),
        api_key=str(ai.get("api_key") or "").strip(),
        api_provider=str(ai.get("api_provider") or "").strip(),
        api_base_url=str(ai.get("api_base_url") or "").strip(),
        api_model=str(ai.get("api_model") or "").strip(),
        cli_path=str(ai.get("cli_path") or "").strip(),
        cli_model=str(ai.get("cli_model") or "").strip(),
        cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
        ollama_url=str(ai.get("ollama_url") or "").strip(),
        ollama_model=str(ai.get("ollama_model") or "").strip(),
        workspace_id=workspace_id,
        autonomy_profile=str(settings.get("autonomy_profile") or "workspace_auto").strip(),
        runtime_permissions_mode=str(settings.get("runtime_permissions_mode") or "default").strip(),
        external_fetch_policy=str(settings.get("external_fetch_policy") or "cache_first").strip(),
        external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600").strip(),
        max_iterations=max(4, min(12, int(settings.get("max_agent_iterations") or "8"))),
        context_compact=True,
    ):
        event_type = str(event.get("type") or "").strip().lower()
        companion_live.apply_companion_agent_event(
            event,
            project=project,
            user_message=user_message,
            agent_session_id=agent_session_id,
        )
        if event_type == "text":
            chunk = str(event.get("chunk") or "")
            if chunk:
                response_chunks.append(chunk)
        elif event_type in {"tool_call", "tool_result"}:
            tool_events.append(event)
        elif event_type == "approval_required":
            approval_required = dict(event)
            approval_action = dict(event.get("approval_action") or {})
            agent_session_id = str(approval_action.get("session_id") or event.get("session_id") or "").strip()
            companion_live.apply_companion_agent_event(
                event,
                project=project,
                user_message=user_message,
                agent_session_id=agent_session_id,
            )
            message = str(event.get("message") or "").strip()
            if message:
                response_chunks.append(message)
            break
        elif event_type == "error":
            message = str(event.get("message") or "").strip()
            if message:
                response_chunks.append(message)
            break

    response_text = "".join(response_chunks).strip()
    if not response_text and approval_required:
        response_text = str(approval_required.get("message") or "").strip()
    if not response_text:
        response_text = "I ran the local operator, but it did not return any visible output."
    if not approval_required:
        set_live_operator(
            active=False,
            mode="agent",
            phase="verify",
            title="Live voice task complete",
            detail="Axon finished the local operator pass.",
            summary=response_text[:180],
            workspace_id=int(project.get("id") or 0) or workspace_id,
            auto_session_id=agent_session_id,
        )

    return {
        "response_text": response_text,
        "tokens_used": 0,
        "backend": "agent",
        "approval_required": approval_required,
        "agent_session_id": agent_session_id,
        "tool_events": tool_events,
    }
