"""Special chat-intent handlers extracted from server.py."""
from __future__ import annotations

import asyncio
import json
import re
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from sse_starlette.sse import EventSourceResponse


_JSON_FENCE_PREFIX = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_JSON_FENCE_SUFFIX = re.compile(r"\s*```$", re.IGNORECASE)
_PPTX_TRIGGER = re.compile(
    r"\b(create|make|generate|build|produce|prepare)\b.{0,40}"
    r"\b(slides?|presentation|pptx|powerpoint|deck)\b",
    re.IGNORECASE,
)
_MISSION_TRIGGER = re.compile(
    r"\b(create|add|make|set\s*up|queue|schedule|track|start|turn|convert|break\s*down|organize|log|plan)\b"
    r".{0,60}"
    r"\b(missions?|tasks?|tracker)\b",
    re.IGNORECASE,
)
_PLAYBOOK_TRIGGER = re.compile(
    r"\b(create|add|make|save|build|write|generate|draft)\b"
    r".{0,60}"
    r"\b(playbooks?|prompts?|templates?|sops?|procedures?|checklists?)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ChatIntentContext:
    message: str
    project_id: int | None
    settings: dict[str, Any]
    merged_context_block: str
    history: list[dict[str, Any]]
    resource_bundle: dict[str, Any]
    chat_thread_mode: str


class ChatSpecialIntentService:
    def __init__(
        self,
        *,
        db_module: Any,
        provider_registry_module: Any,
        devvault_module: Any,
        set_live_operator: Callable[..., None],
        stored_chat_message: Callable[..., str],
    ) -> None:
        self._db = db_module
        self._provider_registry = provider_registry_module
        self._devvault = devvault_module
        self._set_live_operator = set_live_operator
        self._stored_chat_message = stored_chat_message

    async def maybe_handle_nonstreaming(self, conn: Any, context: ChatIntentContext) -> dict[str, Any] | None:
        return (
            await self._maybe_handle_pptx(conn, context, streaming=False)
            or await self._maybe_handle_missions(conn, context, streaming=False)
            or await self._maybe_handle_playbooks(conn, context, streaming=False)
        )

    async def maybe_handle_streaming(self, conn: Any, context: ChatIntentContext) -> EventSourceResponse | None:
        return (
            await self._maybe_handle_pptx(conn, context, streaming=True)
            or await self._maybe_handle_missions(conn, context, streaming=True)
            or await self._maybe_handle_playbooks(conn, context, streaming=True)
        )

    async def _resolve_api_runtime(self, conn: Any, settings: dict[str, Any]) -> dict[str, str]:
        api_cfg = self._provider_registry.runtime_api_config(settings)
        api_key = str(api_cfg.get("api_key") or "").strip()
        if not api_key and self._devvault.VaultSession.is_unlocked():
            api_key = str(
                await self._devvault.vault_resolve_provider_key(
                    conn,
                    api_cfg.get("provider_id", "deepseek"),
                )
                or ""
            ).strip()
        return {
            "api_key": api_key,
            "api_base_url": str(api_cfg.get("api_base_url") or "https://api.deepseek.com/").rstrip("/"),
            "api_model": str(api_cfg.get("api_model") or "deepseek-reasoner"),
        }

    def _history_context(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return ""
        lines = [
            f"{str(item.get('role') or 'assistant').upper()}: {str(item.get('content') or '')[:2000]}"
            for item in history[-6:]
        ]
        return "\n---\n".join(lines) + "\n---\n"

    async def _extract_json_array(
        self,
        conn: Any,
        *,
        settings: dict[str, Any],
        system_prompt: str,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> list[Any]:
        import httpx

        runtime = await self._resolve_api_runtime(conn, settings)
        full_message = self._history_context(history)
        if full_message:
            full_message += f"USER (current): {user_message}"
        else:
            full_message = user_message

        def _run_extract() -> Any:
            if runtime["api_key"]:
                response = httpx.post(
                    f"{runtime['api_base_url']}/chat/completions",
                    json={
                        "model": runtime["api_model"],
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_message},
                        ],
                        "temperature": 0.1,
                        "stream": False,
                    },
                    headers={
                        "Authorization": f"Bearer {runtime['api_key']}",
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
            else:
                response = httpx.post(
                    f"{str(settings.get('ollama_url') or 'http://localhost:11434').rstrip('/')}/api/chat",
                    json={
                        "model": str(settings.get("ollama_model") or "qwen2.5-coder:1.5b"),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_message},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=60,
                )
                response.raise_for_status()
                raw = response.json()["message"]["content"]

            cleaned = _JSON_FENCE_PREFIX.sub("", str(raw or "").strip())
            cleaned = _JSON_FENCE_SUFFIX.sub("", cleaned.strip())
            return json.loads(cleaned)

        extracted = await asyncio.to_thread(_run_extract)
        if isinstance(extracted, list):
            return extracted
        return [extracted]

    async def _active_projects(self, conn: Any) -> list[dict[str, Any]]:
        return [dict(row) for row in await self._db.get_projects(conn, status="active")]

    async def _save_chat_pair(self, conn: Any, context: ChatIntentContext, assistant_message: str, *, tokens: int = 0) -> None:
        await self._db.save_message(
            conn,
            "user",
            self._stored_chat_message(
                context.message,
                resources=context.resource_bundle["resources"],
                mode="chat",
                thread_mode=context.chat_thread_mode,
            ),
            project_id=context.project_id,
        )
        await self._db.save_message(
            conn,
            "assistant",
            self._stored_chat_message(
                assistant_message,
                mode="chat",
                thread_mode=context.chat_thread_mode,
            ),
            project_id=context.project_id,
            tokens=tokens,
        )

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

    async def _maybe_handle_pptx(
        self,
        conn: Any,
        context: ChatIntentContext,
        *,
        streaming: bool,
    ) -> dict[str, Any] | EventSourceResponse | None:
        if not _PPTX_TRIGGER.search(context.message):
            return None
        try:
            import httpx
            from pptx_engine import build_deck, deck_from_dict, prompt_to_deck_json

            settings = context.settings
            runtime = await self._resolve_api_runtime(conn, settings)
            pptx_model = (
                settings.get("reasoning_model")
                or settings.get("general_model")
                or settings.get("code_model")
                or settings.get("ollama_model")
                or "qwen2.5-coder:1.5b"
            )

            def _model_fn(system: str, user: str) -> str:
                if runtime["api_key"]:
                    response = httpx.post(
                        f"{runtime['api_base_url']}/chat/completions",
                        json={
                            "model": runtime["api_model"],
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            "temperature": 0.3,
                            "stream": False,
                        },
                        headers={
                            "Authorization": f"Bearer {runtime['api_key']}",
                            "Content-Type": "application/json",
                        },
                        timeout=120,
                    )
                    response.raise_for_status()
                    return response.json()["choices"][0]["message"]["content"]
                response = httpx.post(
                    f"{str(settings.get('ollama_url') or 'http://localhost:11434').rstrip('/')}/api/chat",
                    json={
                        "model": str(pptx_model),
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.3},
                    },
                    timeout=120,
                )
                response.raise_for_status()
                return response.json()["message"]["content"]

            self._set_live_operator(
                active=True,
                mode="chat",
                phase="execute",
                title="Generating slides…",
                detail=context.message[:120],
                workspace_id=context.project_id,
                preserve_started=streaming,
            )

            deck_json = prompt_to_deck_json(
                context.message,
                f"{context.merged_context_block}\n\nUser request: {context.message}",
                _model_fn,
            )
            spec = deck_from_dict(deck_json)
            out_path = build_deck(spec)
            slide_titles = [slide.title for slide in spec.slides if slide.title]
            reply = (
                f"✅ **Slides ready** — {len(spec.slides)} slides generated.\n\n"
                f"**Title:** {spec.title}\n"
                f"**Theme:** {spec.theme}\n"
                f"**Saved to:** `{out_path}`\n\n"
                f"**Slide outline:**\n"
                + "\n".join(f"  {index + 1}. {title}" for index, title in enumerate(slide_titles))
                + f"\n\n[Download slides](/api/generate/pptx/download?path={str(out_path)})\n\n"
                "Open with LibreOffice Impress or upload to Google Slides."
            )

            self._set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Slides ready",
                detail=f"{len(spec.slides)} slides · {out_path.name}",
                summary=reply[:180],
                workspace_id=context.project_id,
            )

            await self._save_chat_pair(conn, context, reply, tokens=0)
            await self._db.log_event(
                conn,
                "pptx_generate",
                context.message[:100],
                project_id=context.project_id,
            )
            await self._db.upsert_memory_item(
                conn,
                memory_key=f"mission:pptx:{out_path.stem}",
                layer="mission",
                title=f"Presentation: {spec.title}",
                content=(
                    f"Generated presentation: {spec.title}\n"
                    f"Slides: {len(spec.slides)}\n"
                    f"Outline: {', '.join(slide_titles)}\n"
                    f"Theme: {spec.theme}\n"
                    f"File: {out_path.name}\n"
                    f"User request: {context.message[:300]}"
                ),
                summary=f"Generated {len(spec.slides)}-slide deck: {spec.title}",
                source="pptx_generate",
                source_id=str(out_path),
                workspace_id=context.project_id,
                trust_level="high",
                relevance_score=0.8,
                meta_json=json.dumps(
                    {
                        "slide_count": len(spec.slides),
                        "theme": spec.theme,
                        "file_path": str(out_path),
                        "slide_titles": slide_titles,
                    }
                ),
            )

            if streaming:
                return self._single_reply_stream(reply, tokens=0)
            return {"response": reply, "tokens": 0}
        except Exception:
            traceback.print_exc()
            return None

    async def _maybe_handle_missions(
        self,
        conn: Any,
        context: ChatIntentContext,
        *,
        streaming: bool,
    ) -> dict[str, Any] | EventSourceResponse | None:
        if not _MISSION_TRIGGER.search(context.message):
            return None
        try:
            projects = await self._active_projects(conn)
            project_names = {str(project["id"]): project["name"] for project in projects}
            project_list = ", ".join(f"{project_id}: {name}" for project_id, name in project_names.items()) or "none"
            extracted = await self._extract_json_array(
                conn,
                settings=context.settings,
                system_prompt=(
                    "You are a JSON extractor. Extract mission(s) from the conversation.\n"
                    "The user is asking to create missions/tasks. Look at the FULL conversation history "
                    "(especially the last assistant message) to find all missions/tasks mentioned.\n"
                    "Return ONLY a JSON array of mission objects. Each object has:\n"
                    '  {"title": "string", "detail": "string", "priority": "low|medium|high|urgent", "project_id": null_or_int, "due_date": null_or_"YYYY-MM-DD"}\n'
                    f"Available projects: {project_list}\n"
                    "If the user mentions a project name, match it to the project_id.\n"
                    "If multiple missions are requested, return multiple objects.\n"
                    "Keep titles concise (under 80 chars). Put sub-tasks and details in the detail field.\n"
                    "Return ONLY valid JSON array, no markdown fences."
                ),
                user_message=context.message,
                history=context.history,
            )

            self._set_live_operator(
                active=True,
                mode="chat",
                phase="execute",
                title="Creating missions…",
                detail=context.message[:120],
                workspace_id=context.project_id,
                preserve_started=streaming,
            )

            created: list[dict[str, Any]] = []
            for item in extracted:
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                mission_id = await self._db.add_task(
                    conn,
                    item.get("project_id"),
                    str(item["title"]).strip(),
                    str(item.get("detail") or "").strip(),
                    str(item.get("priority") or "medium"),
                    item.get("due_date"),
                )
                await self._db.log_event(
                    conn,
                    "task_added",
                    f"Mission created via chat: {str(item['title']).strip()}",
                    project_id=item.get("project_id"),
                )
                created.append({"id": mission_id, **item})

            if not created:
                return None

            reply_lines = [f"✅ **{len(created)} mission(s) created:**\n"]
            priority_icons = {"urgent": "🔴", "high": "🟠", "medium": "🔵", "low": "⚪"}
            for item in created:
                priority = str(item.get("priority") or "medium")
                line = f"{priority_icons.get(priority, '🔵')} **{item['title']}** ({priority})"
                if item.get("detail"):
                    line += f"\n   {str(item['detail'])[:150]}"
                if item.get("due_date"):
                    line += f"\n   Due: {item['due_date']}"
                project_name = project_names.get(str(item.get("project_id")), "")
                if project_name:
                    line += f"\n   Workspace: {project_name}"
                reply_lines.append(line)
            reply_lines.append("\nView them in the **Missions** tab.")
            reply = "\n".join(reply_lines)

            self._set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Missions created",
                detail=f"{len(created)} mission(s)",
                summary=reply[:180],
                workspace_id=context.project_id,
            )

            await self._save_chat_pair(conn, context, reply, tokens=0)
            if streaming:
                return self._single_reply_stream(reply, tokens=0)
            return {"role": "assistant", "content": reply, "tokens": 0}
        except Exception:
            traceback.print_exc()
            return None

    async def _maybe_handle_playbooks(
        self,
        conn: Any,
        context: ChatIntentContext,
        *,
        streaming: bool,
    ) -> dict[str, Any] | EventSourceResponse | None:
        if not _PLAYBOOK_TRIGGER.search(context.message):
            return None
        try:
            projects = await self._active_projects(conn)
            project_names = {str(project["id"]): project["name"] for project in projects}
            project_list = ", ".join(f"{project_id}: {name}" for project_id, name in project_names.items()) or "none"
            extracted = await self._extract_json_array(
                conn,
                settings=context.settings,
                system_prompt=(
                    "You are a JSON extractor. Extract playbook(s)/prompt templates from the conversation.\n"
                    "The user wants to save reusable playbooks. Look at the FULL conversation history.\n"
                    "Return ONLY a JSON array of playbook objects. Each object has:\n"
                    '  {"title": "string", "content": "string (the full playbook/prompt text)", "tags": "comma,separated,tags", "project_id": null_or_int}\n'
                    f"Available projects: {project_list}\n"
                    "Content should be comprehensive and usable as a standalone reference.\n"
                    "Return ONLY valid JSON array, no markdown fences."
                ),
                user_message=context.message,
                history=context.history,
            )

            self._set_live_operator(
                active=True,
                mode="chat",
                phase="execute",
                title="Creating playbooks…",
                detail=context.message[:120],
                workspace_id=context.project_id,
                preserve_started=streaming,
            )

            created: list[dict[str, Any]] = []
            for item in extracted:
                if not isinstance(item, dict) or not item.get("title"):
                    continue
                playbook_id = await self._db.save_prompt(
                    conn,
                    item.get("project_id"),
                    str(item["title"]).strip(),
                    str(item.get("content") or "").strip(),
                    str(item.get("tags") or ""),
                )
                await self._db.log_event(
                    conn,
                    "prompt_saved",
                    f"Playbook created via chat: {str(item['title']).strip()}",
                    project_id=item.get("project_id"),
                )
                created.append({"id": playbook_id, **item})

            if not created:
                return None

            reply_lines = [f"📋 **{len(created)} playbook(s) saved:**\n"]
            for item in created:
                reply_lines.append(f"📝 **{item['title']}**")
                if item.get("tags"):
                    reply_lines.append(f"   Tags: {item['tags']}")
                if item.get("content"):
                    preview = str(item["content"])[:200].replace("\n", " ")
                    suffix = "…" if len(str(item.get("content") or "")) > 200 else ""
                    reply_lines.append(f"   {preview}{suffix}")
                project_name = project_names.get(str(item.get("project_id")), "")
                if project_name:
                    reply_lines.append(f"   Workspace: {project_name}")
            reply_lines.append("\nView them in the **Playbooks** tab.")
            reply = "\n".join(reply_lines)

            self._set_live_operator(
                active=False,
                mode="chat",
                phase="verify",
                title="Playbooks saved",
                detail=f"{len(created)} playbook(s)",
                summary=reply[:180],
                workspace_id=context.project_id,
            )

            await self._save_chat_pair(conn, context, reply, tokens=0)
            if streaming:
                return self._single_reply_stream(reply, tokens=0)
            return {"role": "assistant", "content": reply, "tokens": 0}
        except Exception:
            traceback.print_exc()
            return None
