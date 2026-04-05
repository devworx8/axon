"""Companion runtime orchestration for authenticated voice turns."""

from __future__ import annotations

from typing import Any

import brain
import provider_registry
from axon_api.services import companion_agent_bridge, companion_fast_path, companion_live
from axon_api.services import companion_sessions as companion_sessions_service
from axon_api.services import companion_voice as companion_voice_service
from axon_api.services.attention_query import attention_summary
from axon_api.services.live_operator_state import set_live_operator
from axon_api.services.workspace_relationships import list_workspace_relationships_for_workspace
from axon_data import get_all_settings, get_companion_session, get_project


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


def _voice_history(rows: list[dict[str, Any]], current_turn_id: int) -> list[dict[str, str]]:
    ordered = sorted((row for row in rows if int(row.get("id") or 0) != current_turn_id), key=lambda row: int(row.get("id") or 0))
    history: list[dict[str, str]] = []
    for row in ordered[-8:]:
        role = str(row.get("role") or "").strip().lower()
        content = str(row.get("response_text") or row.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content})
    return history


def _companion_model_kwargs(settings: dict[str, str]) -> dict[str, Any]:
    backend = str(settings.get("ai_backend") or "").strip().lower()
    if not backend:
        backend = "cli" if str(settings.get("cli_runtime_path") or settings.get("claude_cli_path") or "").strip() else "api"

    quick_model = str(settings.get("quick_model") or "").strip()
    if backend == "cli":
        return {
            "backend": "cli",
            "cli_path": str(settings.get("cli_runtime_path") or settings.get("claude_cli_path") or "").strip(),
            "cli_model": quick_model or str(settings.get("cli_runtime_model") or settings.get("claude_cli_model") or "gpt-5.4").strip(),
        }
    if backend == "ollama":
        return {
            "backend": "ollama",
            "ollama_url": str(settings.get("ollama_url") or "").strip(),
            "ollama_model": quick_model or str(settings.get("ollama_model") or brain.OLLAMA_DEFAULT_MODEL).strip(),
        }

    api_runtime = provider_registry.runtime_api_config(settings)
    api_key = str(api_runtime.get("api_key") or "").strip()
    if not api_key and str(settings.get("cli_runtime_path") or settings.get("claude_cli_path") or "").strip():
        return {
            "backend": "cli",
            "cli_path": str(settings.get("cli_runtime_path") or settings.get("claude_cli_path") or "").strip(),
            "cli_model": quick_model or str(settings.get("cli_runtime_model") or settings.get("claude_cli_model") or "gpt-5.4").strip(),
        }
    return {
        "backend": "api",
        "api_key": api_key,
        "api_provider": str(api_runtime.get("provider_id") or settings.get("api_provider") or "anthropic").strip(),
        "api_base_url": str(api_runtime.get("api_base_url") or settings.get("api_base_url") or "").strip(),
        "api_model": quick_model or str(api_runtime.get("api_model") or settings.get("api_model") or "").strip(),
    }


async def ensure_voice_session(
    db,
    *,
    device_id: int,
    workspace_id: int | None = None,
    session_id: int | None = None,
) -> dict[str, Any]:
    if session_id:
        existing = await get_companion_session(db, session_id)
        if existing:
            return dict(existing)
    session_key = companion_sessions_service.companion_session_key(device_id, workspace_id)
    return await companion_sessions_service.ensure_companion_session(
        db,
        session_key=session_key,
        device_id=device_id,
        workspace_id=workspace_id,
        status="active",
        mode="voice",
        current_route="/voice",
        current_view="voice",
        active_task="Voice request",
        summary="Listening for the next turn.",
        meta={"surface": "companion_voice"},
    )


async def _voice_context_block(db, *, workspace_id: int | None = None) -> tuple[str, dict[str, Any]]:
    if not workspace_id:
        return (
            "This is an authenticated Axon companion voice turn. Reply clearly, briefly, and actionably.",
            {},
        )

    project = _row(await get_project(db, workspace_id))
    workspace_name = str(project.get("name") or "").strip()
    workspace_path = str(project.get("path") or "").strip()
    relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, limit=10)
    attention = await attention_summary(db, workspace_id=workspace_id, limit=10)
    lines = [
        "This is an authenticated Axon companion voice turn.",
        "Reply clearly, briefly, and actionably.",
    ]
    if workspace_name:
        lines.append(f"Focused workspace: {workspace_name}")
    if workspace_path:
        lines.append(f"Workspace path: {workspace_path}")
    if relationships:
        linked = ", ".join(sorted({str(rel.get('external_system') or '').strip() for rel in relationships if str(rel.get('external_system') or '').strip()}))
        if linked:
            lines.append(f"Linked systems: {linked}")
    counts = dict(attention.get("counts") or {})
    if counts:
        lines.append(
            "Attention summary: "
            f"now={int(counts.get('now') or 0)}, "
            f"waiting={int(counts.get('waiting_on_me') or 0)}, "
            f"watch={int(counts.get('watch') or 0)}"
        )
    return ("\n".join(lines), project)


async def _voice_context_data(
    db,
    *,
    workspace_id: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not workspace_id:
        return {}, [], {"counts": {"now": 0, "waiting_on_me": 0, "watch": 0}}
    project = _row(await get_project(db, workspace_id))
    relationships = await list_workspace_relationships_for_workspace(db, workspace_id=workspace_id, limit=10)
    attention = await attention_summary(db, workspace_id=workspace_id, limit=10)
    return project, relationships, attention


async def process_companion_voice_turn(
    db,
    *,
    device_id: int,
    session_id: int | None = None,
    workspace_id: int | None = None,
    content: str,
    transcript: str = "",
    provider: str = "",
    voice_mode: str = "",
    language: str = "",
    audio_format: str = "",
    duration_ms: int = 0,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = await ensure_voice_session(db, device_id=device_id, workspace_id=workspace_id, session_id=session_id)
    resolved_workspace_id = workspace_id if workspace_id is not None else session.get("workspace_id")
    context_block, project = await _voice_context_block(db, workspace_id=resolved_workspace_id)
    context_project, relationships, attention = await _voice_context_data(db, workspace_id=resolved_workspace_id)
    if context_project:
        project = context_project

    user_turn = await companion_voice_service.record_companion_voice_turn(
        db,
        session_id=int(session["id"]),
        workspace_id=resolved_workspace_id,
        role="user",
        content=content,
        transcript=transcript or content,
        provider=provider,
        voice_mode=voice_mode,
        language=language,
        audio_format=audio_format,
        duration_ms=duration_ms,
        status="received",
        meta=meta or {"surface": "companion_voice"},
    )

    history_rows = await companion_voice_service.list_recent_companion_voice_turns(
        db,
        session_id=int(session["id"]),
        workspace_id=resolved_workspace_id,
        limit=12,
    )
    history = _voice_history(history_rows, int(user_turn.get("id") or 0))

    settings = await get_all_settings(db)
    ai = _companion_model_kwargs(settings)
    response_text = ""
    tokens_used = 0
    response_backend = str(ai.get("backend") or settings.get("ai_backend") or "").strip()
    approval_required: dict[str, Any] | None = None
    tool_events: list[dict[str, Any]] = []
    agent_session_id = ""
    assistant_meta: dict[str, Any] = {"surface": "companion_voice_reply", "budget_class": "quick"}

    set_live_operator(
        active=True,
        mode="agent",
        phase="observe",
        title="Listening on Axon Online",
        detail=str(content or "").strip()[:180],
        workspace_id=resolved_workspace_id,
    )

    fast_path = companion_fast_path.maybe_build_fast_voice_response(
        content,
        project=project,
        relationships=relationships,
        attention=attention,
    )
    if fast_path:
        response_text = str(fast_path.get("content") or "").strip()
        tokens_used = int(fast_path.get("tokens_used") or 0)
        response_backend = str(fast_path.get("backend") or "local").strip()
        assistant_meta = {
            "surface": "companion_voice_fast_path",
            "budget_class": "quick",
            "evidence_source": str(fast_path.get("evidence_source") or "workspace_snapshot"),
            "fast_path": True,
        }
        set_live_operator(
            active=False,
            mode="agent",
            phase="verify",
            title="Live voice reply ready",
            detail="Answered from local Axon context without a model call.",
            summary=response_text[:180],
            workspace_id=resolved_workspace_id,
        )
    else:
        workspace_path = str(project.get("path") or "").strip()
        needs_operator = bool(
            resolved_workspace_id
            and workspace_path
            and brain._requires_local_operator_execution(content)
        )
        if needs_operator:
            agent_result = await companion_agent_bridge.run_companion_agent_turn(
                user_message=content,
                history=history,
                context_block=context_block,
                project=project,
                ai=ai,
                settings=settings,
                workspace_id=resolved_workspace_id,
            )
            response_text = str(agent_result.get("response_text") or "").strip()
            tokens_used = int(agent_result.get("tokens_used") or 0)
            response_backend = str(agent_result.get("backend") or "agent").strip()
            approval_required = agent_result.get("approval_required")
            tool_events = list(agent_result.get("tool_events") or [])
            agent_session_id = str(agent_result.get("agent_session_id") or "").strip()
            assistant_meta = {
                "surface": "companion_voice_agent",
                "budget_class": "quick",
                "tool_event_count": len(tool_events),
            }
            if approval_required:
                set_live_operator(
                    active=False,
                    mode="agent",
                    phase="recover",
                    title="Live voice paused for approval",
                    detail=str(approval_required.get("message") or "Axon needs approval before it can continue.")[:180],
                    summary=response_text[:180],
                    workspace_id=resolved_workspace_id,
                    auto_session_id=agent_session_id,
                )
            else:
                set_live_operator(
                    active=False,
                    mode="agent",
                    phase="verify",
                    title="Live voice reply ready",
                    detail="Axon finished the operator-backed response.",
                    summary=response_text[:180],
                    workspace_id=resolved_workspace_id,
                    auto_session_id=agent_session_id,
                )
        else:
            set_live_operator(
                active=True,
                mode="agent",
                phase="plan",
                title="Reasoning through the live voice request",
                detail="Axon is preparing a direct reply.",
                workspace_id=resolved_workspace_id,
                preserve_started=True,
            )
            response = await brain.chat(
                user_message=content,
                history=history,
                context_block=context_block,
                project_name=str(project.get("name") or "").strip() or None,
                backend=str(ai.get("backend") or "cli"),
                api_key=str(ai.get("api_key") or "").strip(),
                api_provider=str(ai.get("api_provider") or "").strip(),
                api_base_url=str(ai.get("api_base_url") or "").strip(),
                api_model=str(ai.get("api_model") or "").strip(),
                cli_path=str(ai.get("cli_path") or "").strip(),
                cli_model=str(ai.get("cli_model") or "").strip(),
                ollama_url=str(ai.get("ollama_url") or "").strip(),
                ollama_model=str(ai.get("ollama_model") or "").strip(),
            )
            response_text = str(response.get("content") or "").strip()
            tokens_used = int(response.get("tokens") or 0)
            if resolved_workspace_id and companion_agent_bridge.needs_local_operator_upgrade(response_text):
                agent_result = await companion_agent_bridge.run_companion_agent_turn(
                    user_message=content,
                    history=history,
                    context_block=context_block,
                    project=project,
                    ai=ai,
                    settings=settings,
                    workspace_id=resolved_workspace_id,
                )
                response_text = str(agent_result.get("response_text") or "").strip()
                tokens_used = int(agent_result.get("tokens_used") or 0)
                response_backend = str(agent_result.get("backend") or "agent").strip()
                approval_required = agent_result.get("approval_required")
                tool_events = list(agent_result.get("tool_events") or [])
                agent_session_id = str(agent_result.get("agent_session_id") or "").strip()
                assistant_meta = {
                    "surface": "companion_voice_agent",
                    "budget_class": "quick",
                    "tool_event_count": len(tool_events),
                }
                if approval_required:
                    set_live_operator(
                        active=False,
                        mode="agent",
                        phase="recover",
                        title="Live voice paused for approval",
                        detail=str(approval_required.get("message") or "Axon needs approval before it can continue.")[:180],
                        summary=response_text[:180],
                        workspace_id=resolved_workspace_id,
                        auto_session_id=agent_session_id,
                    )
                else:
                    set_live_operator(
                        active=False,
                        mode="agent",
                        phase="verify",
                        title="Live voice reply ready",
                        detail="Axon finished the operator-backed response.",
                        summary=response_text[:180],
                        workspace_id=resolved_workspace_id,
                        auto_session_id=agent_session_id,
                    )
            else:
                set_live_operator(
                    active=False,
                    mode="agent",
                    phase="verify",
                    title="Live voice reply ready",
                    detail="Axon finished the direct response.",
                    summary=response_text[:180],
                    workspace_id=resolved_workspace_id,
                )

    assistant_turn = await companion_voice_service.record_companion_voice_turn(
        db,
        session_id=int(session["id"]),
        workspace_id=resolved_workspace_id,
        role="assistant",
        content=response_text,
        transcript=response_text,
        response_text=response_text,
        provider=response_backend,
        voice_mode=voice_mode,
        language=language,
        audio_format=audio_format,
        tokens_used=tokens_used,
        status="completed",
        meta=assistant_meta,
    )

    await companion_sessions_service.touch_companion_session(
        db,
        session_id=int(session["id"]),
        status="awaiting_approval" if approval_required else "active",
        agent_session_id=agent_session_id or None,
        current_route="/voice",
        current_view="voice",
        active_task=content[:160],
        summary=response_text[:220] or "Voice reply ready.",
    )
    refreshed_session = await get_companion_session(db, int(session["id"]))
    session_payload = dict(refreshed_session) if refreshed_session else dict(session)
    live_snapshot = await companion_live.build_companion_live_snapshot(
        db,
        device_id=device_id,
        session_id=int(session["id"]),
        workspace_id=resolved_workspace_id,
        session_row=session_payload,
        presence_row={},
        operator_project_row=project,
        focus_project_row=project,
    )
    return {
        "session": session_payload,
        "user_turn": user_turn,
        "assistant_turn": assistant_turn,
        "response_text": response_text,
        "tokens_used": tokens_used,
        "backend": response_backend,
        "voice_mode": voice_mode,
        "approval_required": approval_required,
        "tool_events": tool_events,
        "live": live_snapshot,
    }
