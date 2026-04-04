"""Task sandbox handlers extracted from server.py."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class TaskSandboxRunRequest(BaseModel):
    backend: Optional[str] = None
    api_provider: Optional[str] = None
    api_model: Optional[str] = None
    cli_path: Optional[str] = None
    cli_model: Optional[str] = None
    cli_session_persistence_enabled: Optional[bool] = None
    ollama_model: Optional[str] = None


class TaskSandboxHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        brain_module: Any,
        task_sandbox_service: Any,
        task_sandbox_runs: dict[int, asyncio.Task],
        now_iso: Callable[[], str],
        set_live_operator: Callable[..., None],
        serialize_task_sandbox: Callable[..., dict | None],
        get_task_with_project: Callable[..., Awaitable[Any]],
        task_sandbox_prompt: Callable[[dict, dict], str],
        task_sandbox_ai_params: Callable[..., Awaitable[dict]],
        task_sandbox_live_operator: Callable[[dict, dict], None],
        normalized_autonomy_profile: Callable[..., str],
        normalized_runtime_permissions_mode: Callable[..., str],
        normalized_external_fetch_policy: Callable[[str], str],
        task_sandbox_runtime_override: Callable[[TaskSandboxRunRequest | None], dict[str, str]],
    ) -> None:
        self._db = db_module
        self._brain = brain_module
        self._task_sandbox_service = task_sandbox_service
        self._task_sandbox_runs = task_sandbox_runs
        self._now_iso = now_iso
        self._set_live_operator = set_live_operator
        self._serialize_task_sandbox = serialize_task_sandbox
        self._get_task_with_project = get_task_with_project
        self._task_sandbox_prompt = task_sandbox_prompt
        self._task_sandbox_ai_params = task_sandbox_ai_params
        self._task_sandbox_live_operator = task_sandbox_live_operator
        self._normalized_autonomy_profile = normalized_autonomy_profile
        self._normalized_runtime_permissions_mode = normalized_runtime_permissions_mode
        self._normalized_external_fetch_policy = normalized_external_fetch_policy
        self._task_sandbox_runtime_override = task_sandbox_runtime_override

    async def run_task_sandbox_background(
        self,
        task: dict,
        project: dict,
        sandbox_meta: dict,
        *,
        resume: bool = False,
        runtime_override: dict[str, str] | None = None,
    ):
        task_id = int(task["id"])
        task_title = str(task.get("title") or "")
        prompt = "please continue" if resume else self._task_sandbox_prompt(task, sandbox_meta)
        final_output_parts: list[str] = []
        approval_message = ""
        run_error = ""
        starting_commit = ""
        permission_state = self._brain.agent_capture_permission_state()
        autonomous_shell_cmds = ("rm", "chmod", "ln")

        try:
            async with self._db.get_db() as conn:
                settings = await self._db.get_all_settings(conn)
                ai = await self._task_sandbox_ai_params(settings, conn=conn, runtime_override=runtime_override)
                projects = [dict(r) for r in await self._db.get_projects(conn, status="active")]
                tasks = [dict(r) for r in await self._db.get_tasks(conn, status="open")]
                prompts_list = [dict(r) for r in await self._db.get_prompts(conn)]
                context_block = self._brain._build_context_block(projects, tasks, prompts_list)
                max_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
                context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {"1", "true", "yes", "on"}
                if str(task.get("status") or "").lower() == "open":
                    await self._db.update_task_status(conn, task_id, "in_progress")

            sandbox_meta = await asyncio.to_thread(self._task_sandbox_service.ensure_task_sandbox, task, project)
            sandbox_meta = await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, task_title) or sandbox_meta
            starting_commit = str(sandbox_meta.get("latest_commit") or "")
            sandbox_meta.update(
                {
                    "mode": "auto",
                    "autonomous": True,
                    "status": "running",
                    "last_error": "",
                    "last_run_started_at": self._now_iso(),
                    "run_prompt": prompt,
                }
            )
            await asyncio.to_thread(self._task_sandbox_service.write_task_sandbox, sandbox_meta)

            self._brain.agent_allow_edit(sandbox_meta["sandbox_path"], scope="repo")
            for cmd_name in autonomous_shell_cmds:
                self._brain.agent_allow_command(cmd_name)

            self._set_live_operator(
                active=True,
                mode="agent",
                phase="execute",
                title="Running mission sandbox",
                detail=str(task.get("title") or "Mission")[:180],
                summary=str(task.get("title") or "")[:120],
                workspace_id=task.get("project_id"),
            )

            async for event in self._brain.run_agent(
                prompt,
                [],
                context_block,
                project_name=project.get("name"),
                workspace_path=sandbox_meta["sandbox_path"],
                ollama_url=ai.get("ollama_url", ""),
                ollama_model=ai.get("ollama_model", ""),
                max_iterations=max_iterations,
                context_compact=context_compact,
                api_key=ai.get("api_key", ""),
                api_base_url=ai.get("api_base_url", ""),
                api_model=ai.get("api_model", ""),
                api_provider=ai.get("api_provider", ""),
                cli_path=ai.get("cli_path", ""),
                cli_model=ai.get("cli_model", ""),
                cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
                backend=ai.get("backend", ""),
                force_tool_mode=True,
                autonomy_profile=self._normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto"),
                runtime_permissions_mode=self._normalized_runtime_permissions_mode(
                    settings.get("runtime_permissions_mode") or "",
                    fallback="ask_first" if self._normalized_autonomy_profile(settings.get("autonomy_profile") or "workspace_auto") == "manual" else "default",
                ),
                external_fetch_policy=self._normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first"),
                external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600"),
            ):
                self._task_sandbox_live_operator(task, event)
                if event.get("type") == "text":
                    final_output_parts.append(str(event.get("chunk") or ""))
                elif event.get("type") == "approval_required":
                    approval_message = str(event.get("message") or "Approval required to continue the sandbox run.")
                    break
                elif event.get("type") == "error":
                    run_error = str(event.get("message") or "Sandbox run failed.")
                    break

            sandbox_meta = await asyncio.to_thread(self._task_sandbox_service.read_task_sandbox, task_id, task_title) or {}
            sandbox_meta.update(
                {
                    "task_id": task_id,
                    "task_title": task_title,
                    "project_id": task.get("project_id"),
                    "project_name": project.get("name") or "",
                    "final_output": "".join(final_output_parts).strip(),
                    "last_run_completed_at": self._now_iso(),
                }
            )
            if approval_message:
                sandbox_meta["status"] = "approval_required"
                sandbox_meta["last_error"] = approval_message
                self._set_live_operator(active=False, mode="agent", phase="recover", title="Sandbox awaiting approval", detail=approval_message[:180], summary=str(task.get("title") or "")[:120], workspace_id=task.get("project_id"))
            elif run_error:
                sandbox_meta["status"] = "error"
                sandbox_meta["last_error"] = run_error
                self._set_live_operator(active=False, mode="agent", phase="recover", title="Sandbox needs attention", detail=run_error[:180], summary=str(task.get("title") or "")[:120], workspace_id=task.get("project_id"))
            else:
                sandbox_meta["status"] = "completed"
                sandbox_meta["last_error"] = ""
                self._set_live_operator(active=False, mode="agent", phase="verify", title="Sandbox report ready", detail="Axon finished the isolated mission run and prepared a review handoff.", summary=str(task.get("title") or "")[:120], workspace_id=task.get("project_id"))
            await asyncio.to_thread(self._task_sandbox_service.write_task_sandbox, sandbox_meta)
            refreshed_meta = await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, task_title)
            if not approval_message and not run_error:
                refreshed_meta = refreshed_meta or await asyncio.to_thread(self._task_sandbox_service.read_task_sandbox, task_id, task_title) or {}
                ending_commit = str(refreshed_meta.get("latest_commit") or "")
                final_output = str(refreshed_meta.get("final_output") or "").strip()
                changed_files = list(refreshed_meta.get("changed_files") or [])
                commit_changed = bool(starting_commit and ending_commit and ending_commit != starting_commit)
                meaningful_completion = bool(final_output or changed_files or commit_changed)
                if final_output.startswith("ERROR:"):
                    refreshed_meta["status"] = "error"
                    refreshed_meta["last_error"] = final_output
                    await asyncio.to_thread(self._task_sandbox_service.write_task_sandbox, refreshed_meta)
                    await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, task_title)
                    self._set_live_operator(active=False, mode="agent", phase="recover", title="Sandbox needs attention", detail=final_output[:180], summary=task_title[:120], workspace_id=task.get("project_id"))
                elif not meaningful_completion:
                    refreshed_meta["status"] = "error"
                    refreshed_meta["last_error"] = "Sandbox run finished without producing repository changes, a new commit, or a reviewable handoff."
                    await asyncio.to_thread(self._task_sandbox_service.write_task_sandbox, refreshed_meta)
                    await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, task_title)
                    self._set_live_operator(active=False, mode="agent", phase="recover", title="Sandbox needs attention", detail=str(refreshed_meta["last_error"])[:180], summary=task_title[:120], workspace_id=task.get("project_id"))
        except Exception as exc:
            meta = await asyncio.to_thread(self._task_sandbox_service.read_task_sandbox, task_id, task_title)
            meta = meta or {
                "task_id": task_id,
                "task_title": task_title,
                "project_id": task.get("project_id"),
                "project_name": project.get("name") or "",
                "source_path": project.get("path") or "",
                "sandbox_path": sandbox_meta.get("sandbox_path") or "",
                "branch_name": sandbox_meta.get("branch_name") or "",
                "base_branch": sandbox_meta.get("base_branch") or "",
                "created_at": self._now_iso(),
            }
            meta.update({"status": "error", "final_output": "".join(final_output_parts).strip(), "last_error": str(exc), "last_run_completed_at": self._now_iso()})
            await asyncio.to_thread(self._task_sandbox_service.write_task_sandbox, meta)
            self._set_live_operator(active=False, mode="agent", phase="recover", title="Sandbox needs attention", detail=str(exc)[:180], summary=str(task.get("title") or "")[:120], workspace_id=task.get("project_id"))
        finally:
            self._brain.agent_restore_permission_state(permission_state)
            self._task_sandbox_runs.pop(task_id, None)

    async def queue_task_sandbox_run(
        self,
        task_id: int,
        *,
        resume: bool = False,
        runtime_override: dict[str, str] | None = None,
        run_task_sandbox_background: Callable[..., Awaitable[None]] | None = None,
    ):
        if run_task_sandbox_background is None:
            run_task_sandbox_background = self.run_task_sandbox_background
        async with self._db.get_db() as conn:
            row = await self._get_task_with_project(conn, task_id)
            if not row:
                raise HTTPException(404, "Mission not found")
            task = dict(row)
            if not task.get("project_id"):
                raise HTTPException(400, "Attach this mission to a workspace before using an isolated sandbox.")
            project = await self._db.get_project(conn, int(task["project_id"]))
            if not project:
                raise HTTPException(400, "Workspace not found for this mission.")
            project_dict = dict(project)

        sandbox_meta = await asyncio.to_thread(self._task_sandbox_service.ensure_task_sandbox, task, project_dict)
        current = self._task_sandbox_runs.get(task_id)
        if current and not current.done():
            return {"started": False, "already_running": True, "sandbox": self._serialize_task_sandbox(sandbox_meta)}

        run_task = asyncio.create_task(
            run_task_sandbox_background(task, project_dict, sandbox_meta, resume=resume, runtime_override=runtime_override)
        )
        self._task_sandbox_runs[task_id] = run_task
        return {"started": True, "resume": resume, "sandbox": self._serialize_task_sandbox(sandbox_meta)}

    async def run_task_sandbox(self, task_id: int, body: TaskSandboxRunRequest | None = None):
        return await self.queue_task_sandbox_run(
            task_id,
            resume=False,
            runtime_override=self._task_sandbox_runtime_override(body),
        )

    async def continue_task_sandbox(self, task_id: int, body: TaskSandboxRunRequest | None = None):
        return await self.queue_task_sandbox_run(
            task_id,
            resume=True,
            runtime_override=self._task_sandbox_runtime_override(body),
        )

    async def list_task_sandboxes(self):
        rows = await asyncio.to_thread(self._task_sandbox_service.list_task_sandboxes)
        return {"sandboxes": [self._serialize_task_sandbox(item) for item in rows]}

    async def get_task_sandbox(self, task_id: int):
        async with self._db.get_db() as conn:
            row = await self._get_task_with_project(conn, task_id)
        if not row:
            raise HTTPException(404, "Mission not found")
        sandbox = await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, str(row["title"]))
        if not sandbox:
            raise HTTPException(404, "Sandbox not created yet for this mission.")
        return {"sandbox": self._serialize_task_sandbox(sandbox, include_report=True)}

    async def apply_task_sandbox(self, task_id: int):
        async with self._db.get_db() as conn:
            row = await self._get_task_with_project(conn, task_id)
        if not row:
            raise HTTPException(404, "Mission not found")
        result = await asyncio.to_thread(self._task_sandbox_service.apply_task_sandbox, task_id, str(row["title"]))
        sandbox = await asyncio.to_thread(self._task_sandbox_service.refresh_task_sandbox, task_id, str(row["title"]))
        return {"applied": True, "summary": result.get("summary", ""), "sandbox": self._serialize_task_sandbox(sandbox, include_report=True)}

    async def discard_task_sandbox(self, task_id: int):
        async with self._db.get_db() as conn:
            row = await self._get_task_with_project(conn, task_id)
        if not row:
            raise HTTPException(404, "Mission not found")
        return await asyncio.to_thread(self._task_sandbox_service.discard_task_sandbox, task_id, str(row["title"]))


def build_task_sandbox_router(**deps: Any) -> tuple[APIRouter, TaskSandboxHandlers]:
    handlers = TaskSandboxHandlers(**deps)
    router = APIRouter(tags=["task-sandbox"])
    router.add_api_route("/api/tasks/sandboxes", handlers.list_task_sandboxes, methods=["GET"])
    router.add_api_route("/api/tasks/{task_id}/sandbox", handlers.get_task_sandbox, methods=["GET"])
    router.add_api_route("/api/tasks/{task_id}/sandbox/run", handlers.run_task_sandbox, methods=["POST"])
    router.add_api_route("/api/tasks/{task_id}/sandbox/continue", handlers.continue_task_sandbox, methods=["POST"])
    router.add_api_route("/api/tasks/{task_id}/sandbox/apply", handlers.apply_task_sandbox, methods=["POST"])
    router.add_api_route("/api/tasks/{task_id}/sandbox", handlers.discard_task_sandbox, methods=["DELETE"])
    return router, handlers
