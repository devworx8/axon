"""Workspace and project route extraction from the legacy server facade."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import brain
import runtime_manager
import scanner
import scheduler as sched_module
from axon_api.services import auto_sessions as auto_session_service
from axon_api.services import live_preview_sessions as live_preview_service


class WorkspacePreviewRequest(BaseModel):
    auto_session_id: str | None = None
    restart: bool = False
    attach_browser: bool = True


class ProjectUpdate(BaseModel):
    note: str | None = None
    status: str | None = None


class AddFolderBody(BaseModel):
    path: str
    persist_root: bool = True


class WorkspaceProjectRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        workspace_preview_target: Callable[[int, str], Awaitable[tuple[dict[str, Any], dict[str, Any] | None, str]]],
        serialize_preview_session: Callable[[dict[str, Any] | None], dict[str, Any] | None],
        attach_preview_browser: Callable[..., Awaitable[dict[str, Any]]],
        serialize_browser_action_state: Callable[[], dict[str, Any]],
        release_browser_preview_attachment: Callable[[dict[str, Any] | None], None],
        ai_params: Callable[..., Awaitable[dict[str, Any]]],
        model_call_kwargs: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._db = db_module
        self._workspace_preview_target = workspace_preview_target
        self._serialize_preview_session = serialize_preview_session
        self._attach_preview_browser = attach_preview_browser
        self._serialize_browser_action_state = serialize_browser_action_state
        self._release_browser_preview_attachment = release_browser_preview_attachment
        self._ai_params = ai_params
        self._model_call_kwargs = model_call_kwargs

    async def workspace_env(
        self,
        path: str = Query(default=""),
        project_id: int | None = Query(default=None),
        auto_session_id: str = Query(default=""),
    ):
        resolved_path = str(path or "").strip()
        if project_id and not resolved_path:
            async with self._db.get_db() as conn:
                project = await self._db.get_project(conn, int(project_id))
            if project:
                project_path = project["path"] if "path" in project.keys() else ""
                resolved_path = str(project_path or "").strip()
        if project_id and auto_session_id:
            auto_meta = auto_session_service.read_auto_session(auto_session_id)
            if auto_meta and int(auto_meta.get("workspace_id") or 0) == int(project_id):
                resolved_path = str(auto_meta.get("sandbox_path") or resolved_path).strip()

        payload = runtime_manager.env_snapshot(resolved_path or None)
        if resolved_path:
            payload.update(
                live_preview_service.workspace_env_snapshot(
                    resolved_path,
                    workspace_id=project_id,
                    auto_session_id=auto_session_id,
                )
            )
        return payload

    async def workspace_preview_status(self, project_id: int, auto_session_id: str = Query(default="")):
        workspace, auto_meta, _ = await self._workspace_preview_target(project_id, auto_session_id)
        preview = await asyncio.to_thread(
            lambda: live_preview_service.get_preview_session(
                workspace_id=int(workspace.get("id") or 0),
                auto_session_id=str((auto_meta or {}).get("session_id") or auto_session_id or ""),
            )
        )
        return {
            "workspace_id": workspace.get("id"),
            "workspace_name": workspace.get("name") or "",
            "auto_session_id": str((auto_meta or {}).get("session_id") or auto_session_id or ""),
            "preview": self._serialize_preview_session(preview),
        }

    async def start_workspace_preview(self, project_id: int, body: WorkspacePreviewRequest | None = None):
        payload = body or WorkspacePreviewRequest()
        workspace, auto_meta, target_path = await self._workspace_preview_target(project_id, payload.auto_session_id or "")
        title = str((auto_meta or {}).get("title") or workspace.get("name") or "")
        try:
            preview = await asyncio.to_thread(
                lambda: live_preview_service.ensure_preview_session(
                    workspace_id=int(workspace.get("id") or 0),
                    workspace_name=str(workspace.get("name") or ""),
                    source_path=target_path,
                    source_workspace_path=str(workspace.get("path") or ""),
                    auto_session_id=str((auto_meta or {}).get("session_id") or payload.auto_session_id or ""),
                    title=title,
                    restart=bool(payload.restart),
                )
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))

        attached = None
        if payload.attach_browser and preview and preview.get("url"):
            attached = await self._attach_preview_browser(
                str(preview.get("url") or ""),
                preview=preview,
                workspace=workspace,
                auto_meta=auto_meta,
            )
        if auto_meta and preview:
            auto_meta["preview_url"] = str(preview.get("url") or "")
            auto_meta["dev_url"] = str(preview.get("url") or "")
            auto_meta["preview_status"] = str(preview.get("status") or "")
            auto_session_service.write_auto_session(auto_meta)
        return {
            "workspace_id": workspace.get("id"),
            "workspace_name": workspace.get("name") or "",
            "preview": self._serialize_preview_session(preview),
            "browser": attached,
            "browser_actions": self._serialize_browser_action_state(),
        }

    async def stop_workspace_preview(self, project_id: int, auto_session_id: str = Query(default="")):
        workspace, auto_meta, _ = await self._workspace_preview_target(project_id, auto_session_id)
        try:
            preview = await asyncio.to_thread(
                lambda: live_preview_service.stop_preview_session(
                    workspace_id=int(workspace.get("id") or 0),
                    auto_session_id=str((auto_meta or {}).get("session_id") or auto_session_id or ""),
                )
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        self._release_browser_preview_attachment(preview)
        return {
            "stopped": True,
            "workspace_id": workspace.get("id"),
            "preview": self._serialize_preview_session(preview),
        }

    async def list_projects(self, status: str | None = None):
        async with self._db.get_db() as conn:
            rows = await self._db.get_projects(conn, status=status)
            return [dict(row) for row in rows]

    async def get_project(self, project_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_project(conn, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        return dict(row)

    async def delete_project(self, project_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_project(conn, project_id)
            if not row:
                raise HTTPException(404, "Project not found")
            payload = dict(row)
            await self._db.delete_project(conn, project_id)
            await self._db.log_event(conn, "workspace_deleted", f"Deleted workspace {payload.get('name') or project_id}")
        return {"deleted": True, "project": payload}

    async def update_project(self, project_id: int, body: ProjectUpdate):
        async with self._db.get_db() as conn:
            if body.note is not None:
                await self._db.update_project_note(conn, project_id, body.note)
            if body.status is not None:
                await self._db.update_project_status(conn, project_id, body.status)
            row = await self._db.get_project(conn, project_id)
        if not row:
            raise HTTPException(404, "Project not found")
        return dict(row)

    async def analyse_project(self, project_id: int):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            ai = await self._ai_params(settings, conn)
            project_row = await self._db.get_project(conn, project_id)
            if not project_row:
                raise HTTPException(404, "Project not found")
            project = dict(project_row)
            tasks = [dict(row) for row in await self._db.get_tasks(conn, project_id=project_id)]
            prompts = [dict(row) for row in await self._db.get_prompts(conn, project_id=project_id)]
            analysis = await brain.analyse_project(project, tasks, prompts, **self._model_call_kwargs(ai))
            await self._db.log_event(conn, "analysis", f"Analysed {project['name']}", project_id=project_id)
        return {"analysis": analysis}

    async def suggest_project_tasks(self, project_id: int):
        async with self._db.get_db() as conn:
            project = await self._db.get_project(conn, project_id)
            if not project:
                raise HTTPException(404, "Project not found")
            settings = await self._db.get_all_settings(conn)
            ai = await self._ai_params(settings, conn)
            open_tasks = [dict(row) for row in await self._db.get_tasks(conn, project_id=project_id, status="open")]
        try:
            suggestions = await brain.suggest_tasks_for_project(dict(project), open_tasks, **self._model_call_kwargs(ai))
        except Exception as exc:
            raise HTTPException(500, f"Suggestion failed: {exc}")
        return {"suggestions": suggestions, "project_name": project["name"]}

    async def run_scan(self):
        asyncio.create_task(sched_module.trigger_scan_now(trigger_type="manual"))
        return {"status": "scan started"}

    async def add_workspace_folder(self, body: AddFolderBody):
        folder = Path(os.path.realpath(os.path.expanduser(body.path)))
        if not folder.exists():
            raise HTTPException(400, f"Path does not exist: {folder}")
        if not folder.is_dir():
            raise HTTPException(400, f"Path is not a directory: {folder}")

        proj_data = await asyncio.get_running_loop().run_in_executor(None, scanner.scan_project, folder)
        async with self._db.get_db() as conn:
            project_id = await self._db.upsert_project(conn, proj_data)
            project_row = await self._db.get_project(conn, project_id)
            project = dict(project_row) if project_row else {"id": project_id}
            if body.persist_root:
                parent_str = str(folder.parent)
                folder_str = str(folder)
                existing = (await self._db.get_setting(conn, "projects_root")) or "~/Desktop"
                roots = [item.strip() for item in existing.split(",") if item.strip()]
                if folder_str not in roots and parent_str not in roots:
                    roots.append(folder_str)
                    await self._db.set_setting(conn, "projects_root", ",".join(roots))
            await self._db.log_event(conn, "scan", f"Manually added workspace: {proj_data['name']}")
        return {"project": project, "scanned": proj_data}


def build_workspace_project_router(**deps: Any) -> tuple[APIRouter, WorkspaceProjectRouteHandlers]:
    handlers = WorkspaceProjectRouteHandlers(**deps)
    router = APIRouter(tags=["workspace-projects"])
    router.add_api_route("/api/workspace/env", handlers.workspace_env, methods=["GET"])
    router.add_api_route("/api/workspaces/{project_id}/preview", handlers.workspace_preview_status, methods=["GET"])
    router.add_api_route("/api/workspaces/{project_id}/preview/start", handlers.start_workspace_preview, methods=["POST"])
    router.add_api_route("/api/workspaces/{project_id}/preview", handlers.stop_workspace_preview, methods=["DELETE"])
    router.add_api_route("/api/projects", handlers.list_projects, methods=["GET"])
    router.add_api_route("/api/projects/{project_id}", handlers.get_project, methods=["GET"])
    router.add_api_route("/api/projects/{project_id}", handlers.delete_project, methods=["DELETE"])
    router.add_api_route("/api/projects/{project_id}", handlers.update_project, methods=["PATCH"])
    router.add_api_route("/api/projects/{project_id}/analyse", handlers.analyse_project, methods=["POST"])
    router.add_api_route("/api/projects/{project_id}/suggest-tasks", handlers.suggest_project_tasks, methods=["POST"])
    router.add_api_route("/api/scan", handlers.run_scan, methods=["POST"])
    router.add_api_route("/api/workspaces/add-folder", handlers.add_workspace_folder, methods=["POST"])
    return router, handlers
