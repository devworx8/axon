"""Prompt and task routes extracted from the legacy server facade."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import brain
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class PromptCreate(BaseModel):
    project_id: int | None = None
    title: str
    content: str
    tags: str = ""
    meta: dict | None = None


class PromptUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: str | None = None
    project_id: int | None = None
    meta: dict | None = None


class EnhanceRequest(BaseModel):
    content: str
    project_context: str | None = None


class TaskCreate(BaseModel):
    project_id: int | None = None
    title: str
    detail: str = ""
    priority: str = "medium"
    due_date: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    detail: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: str | None = None
    project_id: int | None = None


class PromptTaskRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        json_dumps: Callable[[Any], str],
        serialize_prompt: Callable[[Any], dict[str, Any]],
        ai_params: Callable[..., Awaitable[dict[str, Any]]],
        model_call_kwargs: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._db = db_module
        self._json_dumps = json_dumps
        self._serialize_prompt = serialize_prompt
        self._ai_params = ai_params
        self._model_call_kwargs = model_call_kwargs

    async def list_prompts(self, project_id: int | None = None):
        async with self._db.get_db() as conn:
            rows = await self._db.get_prompts(conn, project_id=project_id)
        return [self._serialize_prompt(row) for row in rows]

    async def create_prompt(self, body: PromptCreate):
        async with self._db.get_db() as conn:
            prompt_id = await self._db.save_prompt(
                conn,
                body.project_id,
                body.title,
                body.content,
                body.tags,
                meta_json=self._json_dumps(body.meta or {}),
            )
            await self._db.log_event(
                conn,
                "prompt_saved",
                f"Saved prompt: {body.title}",
                project_id=body.project_id,
            )
            row = await self._db.get_prompt(conn, prompt_id)
        return self._serialize_prompt(row)

    async def delete_prompt(self, prompt_id: int):
        async with self._db.get_db() as conn:
            await self._db.delete_prompt(conn, prompt_id)
        return {"deleted": True}

    async def update_prompt(self, prompt_id: int, body: PromptUpdate):
        async with self._db.get_db() as conn:
            fields = {key: value for key, value in body.dict().items() if value is not None}
            if "meta" in fields:
                fields["meta_json"] = self._json_dumps(fields.pop("meta") or {})
            if not fields:
                raise HTTPException(400, "Nothing to update")
            set_clauses = ", ".join(f"{key} = ?" for key in fields)
            values = list(fields.values()) + [prompt_id]
            await conn.execute(
                f"UPDATE prompts SET {set_clauses}, updated_at = datetime('now') WHERE id = ?",
                values,
            )
            await conn.commit()
            row = await self._db.get_prompt(conn, prompt_id)
        return self._serialize_prompt(row)

    async def toggle_pin(self, prompt_id: int):
        async with self._db.get_db() as conn:
            cur = await conn.execute("SELECT id FROM prompts WHERE id = ?", (prompt_id,))
            if not await cur.fetchone():
                raise HTTPException(404, "Prompt not found")
            await conn.execute(
                "UPDATE prompts SET pinned = CASE WHEN pinned = 1 THEN 0 ELSE 1 END, "
                "updated_at = datetime('now') WHERE id = ?",
                (prompt_id,),
            )
            await conn.commit()
            cur = await conn.execute("SELECT pinned FROM prompts WHERE id = ?", (prompt_id,))
            row = await cur.fetchone()
        return {"pinned": bool(row["pinned"])}

    async def use_prompt(self, prompt_id: int):
        async with self._db.get_db() as conn:
            await self._db.increment_prompt_usage(conn, prompt_id)
        return {"ok": True}

    async def enhance_prompt(self, body: EnhanceRequest):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            ai = await self._ai_params(settings, conn)
            enhanced = await brain.enhance_prompt(
                body.content,
                body.project_context,
                **self._model_call_kwargs(ai),
            )
        return {"enhanced": enhanced}

    async def list_tasks(self, project_id: int | None = None, status: str | None = "open"):
        async with self._db.get_db() as conn:
            rows = await self._db.get_tasks(conn, project_id=project_id, status=status)
        return [dict(row) for row in rows]

    async def create_task(self, body: TaskCreate):
        async with self._db.get_db() as conn:
            task_id = await self._db.add_task(
                conn,
                body.project_id,
                body.title,
                body.detail,
                body.priority,
                body.due_date,
            )
            await self._db.log_event(
                conn,
                "task_added",
                f"Task added: {body.title}",
                project_id=body.project_id,
            )
        return {"id": task_id, "title": body.title}

    async def update_task(self, task_id: int, body: TaskUpdate):
        async with self._db.get_db() as conn:
            fields = body.model_dump(exclude_none=True)
            if not fields:
                raise HTTPException(400, "No fields to update")
            if "status" in fields and len(fields) == 1:
                await self._db.update_task_status(conn, task_id, fields["status"])
            else:
                await self._db.update_task(conn, task_id, **fields)
        return {"updated": True}

    async def delete_task(self, task_id: int):
        async with self._db.get_db() as conn:
            await self._db.delete_task(conn, task_id)
        return {"deleted": True}

    async def suggest_tasks(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            ai = await self._ai_params(settings, conn)
            projects = [dict(row) for row in await self._db.get_projects(conn)]
            tasks = [dict(row) for row in await self._db.get_tasks(conn, status="open")]
            suggestions = await brain.suggest_tasks(
                projects,
                tasks,
                **self._model_call_kwargs(ai),
            )
        return {"suggestions": suggestions}


def build_prompt_task_router(**deps: Any) -> tuple[APIRouter, PromptTaskRouteHandlers]:
    handlers = PromptTaskRouteHandlers(**deps)
    router = APIRouter(tags=["prompt-tasks"])
    router.add_api_route("/api/prompts", handlers.list_prompts, methods=["GET"])
    router.add_api_route("/api/prompts", handlers.create_prompt, methods=["POST"])
    router.add_api_route("/api/prompts/{prompt_id}", handlers.delete_prompt, methods=["DELETE"])
    router.add_api_route("/api/prompts/{prompt_id}", handlers.update_prompt, methods=["PATCH"])
    router.add_api_route("/api/prompts/{prompt_id}/pin", handlers.toggle_pin, methods=["POST"])
    router.add_api_route("/api/prompts/{prompt_id}/use", handlers.use_prompt, methods=["POST"])
    router.add_api_route("/api/prompts/enhance", handlers.enhance_prompt, methods=["POST"])
    router.add_api_route("/api/tasks", handlers.list_tasks, methods=["GET"])
    router.add_api_route("/api/tasks", handlers.create_task, methods=["POST"])
    router.add_api_route("/api/tasks/{task_id}", handlers.update_task, methods=["PATCH"])
    router.add_api_route("/api/tasks/{task_id}", handlers.delete_task, methods=["DELETE"])
    router.add_api_route("/api/tasks/suggest", handlers.suggest_tasks, methods=["POST"])
    return router, handlers
