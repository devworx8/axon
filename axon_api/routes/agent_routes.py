"""Agent SSE route extracted from server.py."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


class AgentRequest(BaseModel):
    message: str
    project_id: Optional[int] = None
    tools: Optional[list[str]] = None
    model: Optional[str] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None
    resume_session_id: Optional[str] = None
    resume_reason: Optional[str] = None
    continue_task: Optional[str] = None
    runtime_permissions_mode_override: Optional[str] = None


class AgentRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        brain_module: Any,
        agent_fast_path_module: Any,
        devvault_module: Any,
        set_live_operator: Callable[..., None],
        composer_options_dict: Callable[[Any], dict[str, Any]],
        thread_mode_from_composer_options: Callable[..., str],
        effective_ai_params: Callable[..., Awaitable[dict[str, Any]]],
        effective_agent_runtime_permissions_mode: Callable[..., str],
        setting_int: Callable[..., int],
        workspace_snapshot_bundle: Callable[..., Awaitable[dict[str, Any]]],
        load_chat_history_rows: Callable[..., Awaitable[list[Any]]],
        chat_history_bundle: Callable[..., Awaitable[dict[str, Any]]],
        resource_bundle: Callable[..., Awaitable[dict[str, Any]]],
        auto_route_vision_runtime: Callable[..., Awaitable[tuple[dict[str, Any], list[str]]]],
        auto_route_image_generation_runtime: Callable[..., Awaitable[tuple[dict[str, Any], list[str]]]],
        memory_bundle: Callable[..., Awaitable[dict[str, Any]]],
        composer_instruction_block: Callable[[dict[str, Any]], str],
        normalized_autonomy_profile: Callable[..., str],
        normalized_external_fetch_policy: Callable[[str], str],
        stored_chat_message: Callable[..., str],
    ) -> None:
        self._db = db_module
        self._brain = brain_module
        self._agent_fast_path = agent_fast_path_module
        self._devvault = devvault_module
        self._set_live_operator = set_live_operator
        self._composer_options_dict = composer_options_dict
        self._thread_mode_from_composer_options = thread_mode_from_composer_options
        self._effective_ai_params = effective_ai_params
        self._effective_agent_runtime_permissions_mode = effective_agent_runtime_permissions_mode
        self._setting_int = setting_int
        self._workspace_snapshot_bundle = workspace_snapshot_bundle
        self._load_chat_history_rows = load_chat_history_rows
        self._chat_history_bundle = chat_history_bundle
        self._resource_bundle = resource_bundle
        self._auto_route_vision_runtime = auto_route_vision_runtime
        self._auto_route_image_generation_runtime = auto_route_image_generation_runtime
        self._memory_bundle = memory_bundle
        self._composer_instruction_block = composer_instruction_block
        self._normalized_autonomy_profile = normalized_autonomy_profile
        self._normalized_external_fetch_policy = normalized_external_fetch_policy
        self._stored_chat_message = stored_chat_message

    async def _project_scope(self, conn: Any, project_id: int | None) -> tuple[str | None, str]:
        if not project_id:
            return None, ""
        project = await self._db.get_project(conn, project_id)
        if not project:
            return None, ""
        return project["name"], project["path"] or ""

    async def agent_endpoint(self, body: AgentRequest, request: Request):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            composer_options = self._composer_options_dict(body.composer_options)
            agent_thread_mode = self._thread_mode_from_composer_options(
                composer_options,
                agent_request=True,
            )
            project_name, workspace_path = await self._project_scope(conn, body.project_id)
            fast_path = self._agent_fast_path.maybe_run_fast_commit_path(
                body.message,
                deps=self._brain._agent_runtime_deps(),
                workspace_path=workspace_path,
                project_name=project_name,
                workspace_id=body.project_id,
                resource_ids=body.resource_ids or [],
                resume_session_id=body.resume_session_id or "",
                continue_task=body.continue_task or "",
                composer_options=composer_options,
            )
            if fast_path:
                collected_text: list[str] = []
                self._set_live_operator(
                    active=True,
                    mode="agent",
                    phase="execute",
                    title="Preparing commit",
                    detail=body.message[:180],
                    workspace_id=body.project_id,
                )

                async def generate_fast():
                    try:
                        for event in fast_path.events:
                            event_type = str(event.get("type") or "").strip().lower()
                            if event_type == "tool_call":
                                self._set_live_operator(
                                    active=True,
                                    mode="agent",
                                    phase="execute",
                                    title=f"Running {str(event.get('name') or 'tool').replace('_', ' ')}",
                                    detail=json.dumps(event.get("args") or {})[:180],
                                    tool=event.get("name", ""),
                                    workspace_id=body.project_id,
                                    preserve_started=True,
                                )
                            elif event_type == "tool_result":
                                self._set_live_operator(
                                    active=True,
                                    mode="agent",
                                    phase="verify",
                                    title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
                                    detail=str(event.get("result") or "")[:180],
                                    tool=event.get("name", ""),
                                    workspace_id=body.project_id,
                                    preserve_started=True,
                                )
                            elif event_type == "text":
                                collected_text.append(str(event.get("chunk") or ""))
                                self._set_live_operator(
                                    active=True,
                                    mode="agent",
                                    phase="verify",
                                    title="Commit step complete",
                                    detail=str(event.get("chunk") or "")[:180],
                                    workspace_id=body.project_id,
                                    preserve_started=True,
                                )
                            elif event_type == "approval_required":
                                self._set_live_operator(
                                    active=False,
                                    mode="agent",
                                    phase="recover",
                                    title="Awaiting approval",
                                    detail=str(event.get("message") or "Axon paused until you approve or deny the blocked action.")[:180],
                                    summary=body.message[:120],
                                    workspace_id=body.project_id,
                                )
                            elif event_type == "done":
                                self._set_live_operator(
                                    active=False,
                                    mode="agent",
                                    phase="verify",
                                    title="Task complete",
                                    detail="Axon finished the fast local action.",
                                    summary="".join(collected_text)[:180],
                                    workspace_id=body.project_id,
                                )
                            elif event_type == "error":
                                self._set_live_operator(
                                    active=False,
                                    mode="agent",
                                    phase="recover",
                                    title="Needs attention",
                                    detail=str(event.get("message") or "Axon hit an error and stopped safely.")[:180],
                                    summary=body.message[:120],
                                    workspace_id=body.project_id,
                                )
                            if await request.is_disconnected():
                                return
                            yield {"data": json.dumps(event)}

                        if fast_path.final_text:
                            async with self._db.get_db() as persist_conn:
                                await self._db.save_message(
                                    persist_conn,
                                    "user",
                                    self._stored_chat_message(
                                        body.message,
                                        resources=[],
                                        mode="agent",
                                        thread_mode=agent_thread_mode,
                                    ),
                                    project_id=body.project_id,
                                )
                                await self._db.save_message(
                                    persist_conn,
                                    "assistant",
                                    self._stored_chat_message(
                                        fast_path.final_text,
                                        mode="agent",
                                        thread_mode=agent_thread_mode,
                                    ),
                                    project_id=body.project_id,
                                    tokens=0,
                                )
                                await self._db.log_event(
                                    persist_conn,
                                    "agent",
                                    body.message[:100],
                                    project_id=body.project_id,
                                )
                    except Exception as exc:
                        self._set_live_operator(
                            active=False,
                            mode="agent",
                            phase="recover",
                            title="Needs attention",
                            detail=str(exc)[:180],
                            summary=body.message[:120],
                            workspace_id=body.project_id,
                        )
                        yield {"data": json.dumps({"type": "error", "message": str(exc)})}

                return EventSourceResponse(generate_fast())

            ai = await self._effective_ai_params(
                settings,
                composer_options,
                conn=conn,
                agent_request=True,
                requested_model=body.model or "",
            )
            settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
            agent_runtime_permissions_mode = self._effective_agent_runtime_permissions_mode(
                settings,
                override=body.runtime_permissions_mode_override or "",
                backend=ai.get("backend", settings.get("ai_backend", "api")),
                cli_path=ai.get("cli_path", ""),
                autonomy_profile=settings.get("autonomy_profile") or "workspace_auto",
            )
            max_agent_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
            context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            snapshot_bundle = await self._workspace_snapshot_bundle(
                conn,
                project_id=body.project_id,
                settings=settings,
            )
            history_rows = await self._load_chat_history_rows(
                conn,
                project_id=body.project_id,
                limit=max(self._setting_int(settings, "max_history_turns", 10, minimum=6, maximum=60) * 4, 40),
                degrade_to_empty=True,
            )
            history_bundle = await self._chat_history_bundle(
                conn,
                project_id=body.project_id,
                settings=settings,
                backend=settings.get("ai_backend", "api"),
                history_rows=history_rows,
            )
            history = history_bundle["history"]
            resource_bundle = await self._resource_bundle(
                conn,
                resource_ids=body.resource_ids or [],
                user_message=body.message,
                settings=settings,
            )
            ai, vision_warnings = await self._auto_route_vision_runtime(
                settings=settings,
                ai=ai,
                resource_bundle=resource_bundle,
                requested_model=body.model or "",
                resolve_provider_key=lambda provider_id: self._devvault.vault_resolve_provider_key(conn, provider_id),
                vault_unlocked=self._devvault.VaultSession.is_unlocked(),
            )
            if vision_warnings:
                resource_bundle["warnings"].extend(vision_warnings)
            ai, image_warnings = await self._auto_route_image_generation_runtime(
                conn,
                settings=settings,
                ai=ai,
                user_message=body.message,
                requested_model=body.model or "",
                agent_request=True,
            )
            if image_warnings:
                resource_bundle["warnings"].extend(image_warnings)
            settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
            memory_bundle = await self._memory_bundle(
                conn,
                user_message=body.message,
                project_id=body.project_id,
                resource_ids=body.resource_ids or [],
                settings=settings,
                composer_options=composer_options,
                snapshot_revision=snapshot_bundle["revision"],
            )
            merged_context_block = "\n\n".join(
                block
                for block in (
                    snapshot_bundle["context_block"],
                    history_bundle["summary_block"],
                    memory_bundle["context_block"],
                    self._composer_instruction_block(composer_options),
                )
                if block
            )
            backend = settings.get("ai_backend", "api")
            agent_api_key = ai.get("api_key", "")
            agent_api_base = ai.get("api_base_url", "")
            agent_api_model = ai.get("api_model", "")
            agent_api_provider = ai.get("api_provider", "")
            if backend == "api" and not agent_api_key:
                raise HTTPException(
                    400,
                    "Agent mode with API backend requires a configured API key. Check Settings or Vault.",
                )

        ollama_url = ai.get("ollama_url", settings.get("ollama_url", ""))
        ollama_model = ai.get("ollama_model") or resource_bundle["vision_model"] or settings.get("ollama_model", "")
        min_sizes = {"qwen2.5-coder": "7b", "llama3.2": "3b", "phi4-mini": "latest"}
        model_lower = ollama_model.lower()
        for family, min_tag in min_sizes.items():
            if model_lower.startswith(family) and min_tag not in model_lower:
                available = await self._brain.ollama_list_models(ollama_url)
                upgrade = next(
                    (model for model in available if model.lower().startswith(family) and min_tag in model.lower()),
                    None,
                )
                if upgrade:
                    ollama_model = upgrade
                break

        collected_text: list[str] = []
        self._set_live_operator(
            active=True,
            mode="agent",
            phase="observe",
            title="Inspecting the task",
            detail=body.message[:180],
            workspace_id=body.project_id,
        )

        async def generate():
            try:
                for warning in resource_bundle["warnings"]:
                    collected_text.append(f"⚠️ {warning}\n\n")
                    yield {"data": json.dumps({"type": "text", "chunk": f"⚠️ {warning}\n\n"})}
                kickoff = {
                    "type": "thinking",
                    "chunk": "Axon is analysing the request and forming a plan.",
                }
                self._set_live_operator(
                    active=True,
                    mode="agent",
                    phase="plan",
                    title="Thinking through the task",
                    detail=str(kickoff["chunk"])[:180],
                    workspace_id=body.project_id,
                    preserve_started=True,
                )
                yield {"data": json.dumps(kickoff)}
                async for event in self._brain.run_agent(
                    body.message,
                    history,
                    merged_context_block,
                    project_name=project_name,
                    workspace_path=workspace_path,
                    resource_context=resource_bundle["context_block"],
                    resource_image_paths=resource_bundle["image_paths"],
                    vision_model=resource_bundle["vision_model"],
                    tools=body.tools,
                    ollama_url=ollama_url,
                    ollama_model=ollama_model,
                    max_iterations=max_agent_iterations,
                    context_compact=context_compact,
                    force_tool_mode=bool(
                        composer_options.get("action_mode") or composer_options.get("agent_role")
                    ),
                    api_key=agent_api_key,
                    api_base_url=agent_api_base,
                    api_model=agent_api_model,
                    api_provider=agent_api_provider,
                    cli_path=ai.get("cli_path", ""),
                    cli_model=ai.get("cli_model", ""),
                    cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
                    backend=backend,
                    workspace_id=body.project_id,
                    autonomy_profile=self._normalized_autonomy_profile(
                        settings.get("autonomy_profile") or "workspace_auto"
                    ),
                    runtime_permissions_mode=agent_runtime_permissions_mode,
                    external_fetch_policy=self._normalized_external_fetch_policy(
                        settings.get("external_fetch_policy") or "cache_first"
                    ),
                    external_fetch_cache_ttl_seconds=str(
                        settings.get("external_fetch_cache_ttl_seconds") or "21600"
                    ),
                    resume_session_id=body.resume_session_id or "",
                    resume_reason=body.resume_reason or "",
                    continue_task=body.continue_task or "",
                ):
                    event_type = event.get("type")
                    if event_type == "text":
                        chunk = str(event.get("chunk") or "")
                        collected_text.append(chunk)
                        self._set_live_operator(
                            active=True,
                            mode="agent",
                            phase="verify",
                            title="Writing the result",
                            detail=chunk[:180] or "Axon is drafting the answer now.",
                            workspace_id=body.project_id,
                            preserve_started=True,
                        )
                    elif event_type == "thinking":
                        self._set_live_operator(
                            active=True,
                            mode="agent",
                            phase="plan",
                            title="Thinking through the task",
                            detail=str(event.get("chunk") or "Axon is reasoning through the task.")[:180],
                            workspace_id=body.project_id,
                            preserve_started=True,
                        )
                    elif event_type == "tool_call":
                        self._set_live_operator(
                            active=True,
                            mode="agent",
                            phase="execute",
                            title=f"Running {str(event.get('name') or 'tool').replace('_', ' ')}",
                            detail=json.dumps(event.get("args") or {})[:180],
                            tool=event.get("name", ""),
                            workspace_id=body.project_id,
                            preserve_started=True,
                        )
                    elif event_type == "tool_result":
                        self._set_live_operator(
                            active=True,
                            mode="agent",
                            phase="verify",
                            title=f"Checking {str(event.get('name') or 'tool').replace('_', ' ')}",
                            detail=str(event.get("result") or "Axon is reviewing the tool output.")[:180],
                            tool=event.get("name", ""),
                            workspace_id=body.project_id,
                            preserve_started=True,
                        )
                    elif event_type == "approval_required":
                        self._set_live_operator(
                            active=False,
                            mode="agent",
                            phase="recover",
                            title="Awaiting approval",
                            detail=str(event.get("message") or "Axon paused until you approve or deny the blocked action.")[:180],
                            summary=body.message[:120],
                            workspace_id=body.project_id,
                        )
                    elif event_type == "done":
                        self._set_live_operator(
                            active=False,
                            mode="agent",
                            phase="verify",
                            title="Task complete",
                            detail="Axon finished the operator pass.",
                            summary="".join(collected_text)[:180],
                            workspace_id=body.project_id,
                        )
                    elif event_type == "error":
                        self._set_live_operator(
                            active=False,
                            mode="agent",
                            phase="recover",
                            title="Needs attention",
                            detail=str(event.get("message") or "Axon hit an error and stopped safely.")[:180],
                            summary=body.message[:120],
                            workspace_id=body.project_id,
                        )
                    if await request.is_disconnected():
                        return
                    yield {"data": json.dumps(event)}

                final_text = "".join(collected_text)
                if final_text:
                    async with self._db.get_db() as persist_conn:
                        await self._db.save_message(
                            persist_conn,
                            "user",
                            self._stored_chat_message(
                                body.message,
                                resources=resource_bundle["resources"],
                                mode="agent",
                                thread_mode=agent_thread_mode,
                            ),
                            project_id=body.project_id,
                        )
                        await self._db.save_message(
                            persist_conn,
                            "assistant",
                            self._stored_chat_message(
                                final_text,
                                mode="agent",
                                thread_mode=agent_thread_mode,
                            ),
                            project_id=body.project_id,
                            tokens=0,
                        )
                        await self._db.log_event(
                            persist_conn,
                            "agent",
                            body.message[:100],
                            project_id=body.project_id,
                        )
            except Exception as exc:
                self._set_live_operator(
                    active=False,
                    mode="agent",
                    phase="recover",
                    title="Needs attention",
                    detail=str(exc),
                    summary=body.message[:120],
                    workspace_id=body.project_id,
                )
                yield {"data": json.dumps({"type": "error", "message": str(exc)})}

        return EventSourceResponse(generate())


def build_agent_router(**deps: Any) -> tuple[APIRouter, AgentRouteHandlers]:
    handlers = AgentRouteHandlers(**deps)
    router = APIRouter(tags=["agent"])
    router.add_api_route("/api/agent", handlers.agent_endpoint, methods=["POST"])
    return router, handlers
