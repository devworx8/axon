"""Chat and chat-stream routes extracted from server.py."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from axon_api.services.chat_special_intents import ChatIntentContext, ChatSpecialIntentService


class ChatMessage(BaseModel):
    message: str
    project_id: Optional[int] = None
    model: Optional[str] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None


class ChatRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        brain_module: Any,
        devvault_module: Any,
        provider_registry_module: Any,
        load_chat_history_rows: Callable[..., Awaitable[list[Any]]],
        serialize_chat_history_row: Callable[[Any], dict[str, Any]],
        composer_options_dict: Callable[[Any], dict[str, Any]],
        thread_mode_from_composer_options: Callable[..., str],
        maybe_handle_chat_console_command: Callable[..., Awaitable[dict[str, Any] | None]],
        effective_ai_params: Callable[..., Awaitable[dict[str, Any]]],
        workspace_snapshot_bundle: Callable[..., Awaitable[dict[str, Any]]],
        chat_history_bundle: Callable[..., Awaitable[dict[str, Any]]],
        resource_bundle: Callable[..., Awaitable[dict[str, Any]]],
        auto_route_vision_runtime: Callable[..., Awaitable[tuple[dict[str, Any], list[str]]]],
        auto_route_image_generation_runtime: Callable[..., Awaitable[tuple[dict[str, Any], list[str]]]],
        memory_bundle: Callable[..., Awaitable[dict[str, Any]]],
        composer_instruction_block: Callable[[dict[str, Any]], str],
        maybe_local_fast_chat_response: Callable[..., Awaitable[dict[str, Any] | None]],
        persist_chat_reply: Callable[..., Awaitable[None]],
        set_live_operator: Callable[..., None],
        model_call_kwargs: Callable[[dict[str, Any]], dict[str, Any]],
        setting_int: Callable[..., int],
        stored_chat_message: Callable[..., str],
    ) -> None:
        self._db = db_module
        self._brain = brain_module
        self._devvault = devvault_module
        self._load_chat_history_rows = load_chat_history_rows
        self._serialize_chat_history_row = serialize_chat_history_row
        self._composer_options_dict = composer_options_dict
        self._thread_mode_from_composer_options = thread_mode_from_composer_options
        self._maybe_handle_chat_console_command = maybe_handle_chat_console_command
        self._effective_ai_params = effective_ai_params
        self._workspace_snapshot_bundle = workspace_snapshot_bundle
        self._chat_history_bundle = chat_history_bundle
        self._resource_bundle = resource_bundle
        self._auto_route_vision_runtime = auto_route_vision_runtime
        self._auto_route_image_generation_runtime = auto_route_image_generation_runtime
        self._memory_bundle = memory_bundle
        self._composer_instruction_block = composer_instruction_block
        self._maybe_local_fast_chat_response = maybe_local_fast_chat_response
        self._persist_chat_reply = persist_chat_reply
        self._set_live_operator = set_live_operator
        self._model_call_kwargs = model_call_kwargs
        self._setting_int = setting_int
        self._stored_chat_message = stored_chat_message
        self._special_intents = ChatSpecialIntentService(
            db_module=db_module,
            provider_registry_module=provider_registry_module,
            devvault_module=devvault_module,
            set_live_operator=set_live_operator,
            stored_chat_message=stored_chat_message,
        )

    async def _project_scope(self, conn: Any, project_id: int | None) -> tuple[str | None, str]:
        if not project_id:
            return None, ""
        project = await self._db.get_project(conn, project_id)
        if not project:
            return None, ""
        return project["name"], project["path"] or ""

    def _single_reply_stream(
        self,
        reply: str,
        *,
        tokens: int = 0,
        extra_done: dict[str, Any] | None = None,
    ) -> EventSourceResponse:
        async def generate():
            yield {"data": json.dumps({"chunk": reply})}
            done_payload = {"done": True, "tokens": tokens}
            if extra_done:
                done_payload.update(extra_done)
            yield {"data": json.dumps(done_payload)}

        return EventSourceResponse(generate())

    async def _build_request_context(
        self,
        conn: Any,
        body: ChatMessage,
        *,
        streaming: bool,
    ) -> dict[str, Any]:
        composer_options = self._composer_options_dict(body.composer_options)
        chat_thread_mode = self._thread_mode_from_composer_options(composer_options)
        console_command = await self._maybe_handle_chat_console_command(
            conn,
            project_id=body.project_id,
            user_message=body.message,
            thread_mode=chat_thread_mode,
        )
        if console_command:
            return {"console_command": console_command}

        requested_model = body.model or ""
        settings = await self._db.get_all_settings(conn)
        ai = await self._effective_ai_params(
            settings,
            composer_options,
            conn=conn,
            requested_model=requested_model,
        )
        backend = ai.get("backend", settings.get("ai_backend", "api"))
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
            backend=backend,
            history_rows=history_rows,
        )
        history = history_bundle["history"]
        project_name, workspace_path = await self._project_scope(conn, body.project_id)
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
            requested_model=requested_model,
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
            requested_model=requested_model,
            agent_request=False,
        )
        if image_warnings:
            resource_bundle["warnings"].extend(image_warnings)

        memory_settings = settings
        if streaming:
            memory_settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
            if ai.get("ollama_model"):
                memory_settings["ollama_model"] = ai["ollama_model"]
            backend = memory_settings.get("ai_backend", backend)

        memory_bundle = await self._memory_bundle(
            conn,
            user_message=body.message,
            project_id=body.project_id,
            resource_ids=body.resource_ids or [],
            settings=memory_settings,
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
        return {
            "body": body,
            "composer_options": composer_options,
            "chat_thread_mode": chat_thread_mode,
            "settings": settings,
            "stream_settings": memory_settings,
            "ai": ai,
            "backend": backend,
            "snapshot_bundle": snapshot_bundle,
            "history": history,
            "resource_bundle": resource_bundle,
            "memory_bundle": memory_bundle,
            "merged_context_block": merged_context_block,
            "project_name": project_name,
            "workspace_path": workspace_path,
        }

    async def chat(self, body: ChatMessage):
        async with self._db.get_db() as conn:
            context = await self._build_request_context(conn, body, streaming=False)
            if context.get("console_command"):
                return context["console_command"]

            fast_path = await self._maybe_local_fast_chat_response(
                conn,
                user_message=body.message,
                project_id=body.project_id,
                settings=context["settings"],
                snapshot_bundle=context["snapshot_bundle"],
                memory_bundle=context["memory_bundle"],
            )
            if fast_path:
                reply = str(fast_path.get("content") or "")
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="verify",
                    title="Answered from local context",
                    detail=str(fast_path.get("evidence_source") or "workspace"),
                    summary=reply[:180],
                    workspace_id=body.project_id,
                )
                await self._persist_chat_reply(
                    conn,
                    project_id=body.project_id,
                    user_message=body.message,
                    assistant_message=reply,
                    resources=context["resource_bundle"]["resources"],
                    thread_mode=context["chat_thread_mode"],
                    tokens=0,
                    model_label=str(fast_path.get("model_label") or ""),
                    event_name="chat_fast_path",
                    event_summary=f"{fast_path.get('evidence_source', 'local')}: {body.message[:100]}",
                )
                return {
                    "response": reply,
                    "tokens": 0,
                    "evidence_source": str(fast_path.get("evidence_source") or ""),
                    "fast_path": True,
                }

            special = await self._special_intents.maybe_handle_nonstreaming(
                conn,
                ChatIntentContext(
                    message=body.message,
                    project_id=body.project_id,
                    settings=context["settings"],
                    merged_context_block=context["merged_context_block"],
                    history=context["history"],
                    resource_bundle=context["resource_bundle"],
                    chat_thread_mode=context["chat_thread_mode"],
                ),
            )
            if special:
                return special

            try:
                self._set_live_operator(
                    active=True,
                    mode="chat",
                    phase="plan",
                    title="Preparing the reply",
                    detail=body.message[:180],
                    workspace_id=body.project_id,
                )
                result = await asyncio.wait_for(
                    self._brain.chat(
                        body.message,
                        context["history"],
                        context["merged_context_block"],
                        project_name=context["project_name"],
                        workspace_path=context["workspace_path"],
                        resource_context=context["resource_bundle"]["context_block"],
                        resource_image_paths=context["resource_bundle"]["image_paths"],
                        vision_model=context["resource_bundle"]["vision_model"],
                        **self._model_call_kwargs(context["ai"]),
                    ),
                    timeout=90.0,
                )
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="verify",
                    title="Reply complete",
                    detail="Axon finished the response.",
                    summary=result["content"][:180],
                    workspace_id=body.project_id,
                )
            except (asyncio.TimeoutError, TimeoutError, RuntimeError) as exc:
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="recover",
                    title="Reply interrupted",
                    detail=str(exc),
                    summary=body.message[:120],
                    workspace_id=body.project_id,
                )
                raise HTTPException(504, f"AI backend timed out — try a shorter message or check Ollama. ({exc})")

            await self._persist_chat_reply(
                conn,
                project_id=body.project_id,
                user_message=body.message,
                assistant_message=result["content"],
                resources=context["resource_bundle"]["resources"],
                thread_mode=context["chat_thread_mode"],
                tokens=result["tokens"],
                event_name="chat",
                event_summary=body.message[:100],
            )
            return {"response": result["content"], "tokens": result["tokens"]}

    async def get_chat_history(self, project_id: int | None = None, limit: int = 30):
        async with self._db.get_db() as conn:
            rows = await self._load_chat_history_rows(conn, project_id=project_id, limit=limit)
        return [self._serialize_chat_history_row(row) for row in rows]

    async def clear_history(self, project_id: int | None = None):
        async with self._db.get_db() as conn:
            await self._db.clear_chat_history(conn, project_id=project_id)
        return {"cleared": True}

    async def chat_stream(self, body: ChatMessage, request: Request):
        async with self._db.get_db() as conn:
            context = await self._build_request_context(conn, body, streaming=True)
            if context.get("console_command"):
                reply = str(context["console_command"].get("response") or "")
                return self._single_reply_stream(reply, extra_done=dict(context["console_command"]))

            fast_path = await self._maybe_local_fast_chat_response(
                conn,
                user_message=body.message,
                project_id=body.project_id,
                settings=context["settings"],
                snapshot_bundle=context["snapshot_bundle"],
                memory_bundle=context["memory_bundle"],
            )
            if fast_path:
                reply = str(fast_path.get("content") or "")
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="verify",
                    title="Answered from local context",
                    detail=str(fast_path.get("evidence_source") or "workspace"),
                    summary=reply[:180],
                    workspace_id=body.project_id,
                )
                await self._persist_chat_reply(
                    conn,
                    project_id=body.project_id,
                    user_message=body.message,
                    assistant_message=reply,
                    resources=context["resource_bundle"]["resources"],
                    thread_mode=context["chat_thread_mode"],
                    tokens=0,
                    model_label=str(fast_path.get("model_label") or ""),
                    event_name="chat_fast_path",
                    event_summary=f"{fast_path.get('evidence_source', 'local')}: {body.message[:100]}",
                )
                return self._single_reply_stream(
                    reply,
                    extra_done={
                        "fast_path": True,
                        "evidence_source": fast_path.get("evidence_source", ""),
                    },
                )

            self._set_live_operator(
                active=True,
                mode="chat",
                phase="observe",
                title="Understanding the request",
                detail=body.message[:180],
                workspace_id=body.project_id,
            )

            special = await self._special_intents.maybe_handle_streaming(
                conn,
                ChatIntentContext(
                    message=body.message,
                    project_id=body.project_id,
                    settings=context["settings"],
                    merged_context_block=context["merged_context_block"],
                    history=context["history"],
                    resource_bundle=context["resource_bundle"],
                    chat_thread_mode=context["chat_thread_mode"],
                ),
            )
            if special:
                return special

        async def generate():
            try:
                started_stream = False
                full_content: list[str] = []
                usage_sink: dict[str, object] = {}
                for warning in context["resource_bundle"]["warnings"]:
                    full_content.append(f"⚠️ {warning}\n\n")
                    yield {"data": json.dumps({"chunk": f"⚠️ {warning}\n\n"})}
                async for chunk in self._brain.stream_chat(
                    body.message,
                    context["history"],
                    context["merged_context_block"],
                    project_name=context["project_name"],
                    workspace_path=context["workspace_path"],
                    resource_context=context["resource_bundle"]["context_block"],
                    resource_image_paths=context["resource_bundle"]["image_paths"],
                    vision_model=context["resource_bundle"]["vision_model"],
                    backend=context["backend"],
                    api_key=context["ai"].get("api_key", ""),
                    api_provider=context["ai"].get("api_provider", ""),
                    api_base_url=context["ai"].get("api_base_url", ""),
                    api_model=context["ai"].get("api_model", ""),
                    cli_path=context["ai"].get("cli_path", ""),
                    cli_model=context["ai"].get("cli_model", ""),
                    cli_session_persistence=bool(context["ai"].get("cli_session_persistence", False)),
                    ollama_url=context["stream_settings"].get("ollama_url", ""),
                    ollama_model=context["stream_settings"].get("ollama_model", ""),
                    usage_sink=usage_sink,
                    settings=context.get("settings"),
                ):
                    if not started_stream:
                        self._set_live_operator(
                            active=True,
                            mode="chat",
                            phase="execute",
                            title="Writing the reply",
                            detail=(
                                "Axon is streaming the answer live."
                                if context["backend"] == "ollama"
                                else "Axon is streaming the external provider response live."
                            ),
                            workspace_id=body.project_id,
                            preserve_started=True,
                        )
                        started_stream = True
                    full_content.append(chunk)
                    if await request.is_disconnected():
                        return
                    yield {"data": json.dumps({"chunk": chunk})}

                async with self._db.get_db() as persist_conn:
                    await self._db.save_message(
                        persist_conn,
                        "user",
                        self._stored_chat_message(
                            body.message,
                            resources=context["resource_bundle"]["resources"],
                            mode="chat",
                            thread_mode=context["chat_thread_mode"],
                        ),
                        project_id=body.project_id,
                    )
                    await self._db.save_message(
                        persist_conn,
                        "assistant",
                        self._stored_chat_message(
                            "".join(full_content),
                            mode="chat",
                            thread_mode=context["chat_thread_mode"],
                        ),
                        project_id=body.project_id,
                        tokens=int(usage_sink.get("tokens") or 0),
                    )
                    await self._db.log_event(
                        persist_conn,
                        "chat",
                        body.message[:100],
                        project_id=body.project_id,
                    )
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="verify",
                    title="Reply complete",
                    detail="Axon finished streaming the answer.",
                    summary="".join(full_content)[:180],
                    workspace_id=body.project_id,
                )
                yield {"data": json.dumps({"done": True, "tokens": int(usage_sink.get("tokens") or 0)})}
            except Exception as exc:
                self._set_live_operator(
                    active=False,
                    mode="chat",
                    phase="recover",
                    title="Reply interrupted",
                    detail=str(exc),
                    summary=body.message[:120],
                    workspace_id=body.project_id,
                )
                yield {"data": json.dumps({"error": str(exc)})}

        return EventSourceResponse(generate())


def build_chat_router(**deps: Any) -> tuple[APIRouter, ChatRouteHandlers]:
    handlers = ChatRouteHandlers(**deps)
    router = APIRouter(tags=["chat"])
    router.add_api_route("/api/chat", handlers.chat, methods=["POST"])
    router.add_api_route("/api/chat/history", handlers.get_chat_history, methods=["GET"])
    router.add_api_route("/api/chat/history", handlers.clear_history, methods=["DELETE"])
    router.add_api_route("/api/chat/stream", handlers.chat_stream, methods=["POST"])
    return router, handlers
