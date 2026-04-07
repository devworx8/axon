"""Auto-session handlers extracted from server.py."""
from __future__ import annotations
import asyncio
import time
from typing import Any, Awaitable, Callable, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from axon_api.routes.task_sandbox_routes import TaskSandboxRunRequest
from axon_api.services.auto_session_route_support import (
    auto_resume_prompt,
    auto_session_title,
    refresh_listed_auto_sessions,
    stopped_auto_session_meta,
)
class AutoSessionStartRequest(TaskSandboxRunRequest):
    message: str
    project_id: Optional[int] = None
    resource_ids: Optional[list[int]] = None
    composer_options: Optional[dict] = None
class AutoSessionHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        brain_module: Any,
        devvault_module: Any,
        auto_session_service: Any,
        auto_session_runs: dict[str, asyncio.Task],
        now_iso: Callable[[], str],
        set_live_operator: Callable[..., None],
        serialize_auto_session: Callable[..., dict | None],
        task_sandbox_ai_params: Callable[..., Awaitable[dict]],
        load_chat_history_rows: Callable[..., Awaitable[list[Any]]],
        history_messages_from_rows: Callable[[list[Any]], list[dict]],
        resource_bundle: Callable[..., Awaitable[dict]],
        auto_route_vision_runtime: Callable[..., Awaitable[tuple[dict, list[str]]]],
        auto_route_image_generation_runtime: Callable[..., Awaitable[tuple[dict, list[str]]]],
        memory_bundle: Callable[..., Awaitable[dict]],
        composer_instruction_block: Callable[[dict], str],
        auto_session_prompt: Callable[[str, dict], str],
        auto_runtime_summary: Callable[[dict], dict],
        normalized_autonomy_profile: Callable[..., str],
        normalized_runtime_permissions_mode: Callable[..., str],
        effective_agent_runtime_permissions_mode: Callable[..., str],
        normalized_external_fetch_policy: Callable[[str], str],
        auto_tool_command: Callable[[str, dict], tuple[str, str, str]],
        auto_receipt_summary: Callable[[str], str],
        is_verification_command: Callable[[str, dict], bool],
        auto_session_live_operator: Callable[[dict, dict], None],
        composer_options_dict: Callable[[dict | None], dict],
        task_sandbox_runtime_override: Callable[[TaskSandboxRunRequest | None], dict[str, str]],
    ) -> None:
        self._db = db_module
        self._brain = brain_module
        self._devvault = devvault_module
        self._auto_session_service = auto_session_service
        self._auto_session_runs = auto_session_runs
        self._now_iso = now_iso
        self._set_live_operator = set_live_operator
        self._serialize_auto_session = serialize_auto_session
        self._task_sandbox_ai_params = task_sandbox_ai_params
        self._load_chat_history_rows = load_chat_history_rows
        self._history_messages_from_rows = history_messages_from_rows
        self._resource_bundle = resource_bundle
        self._auto_route_vision_runtime = auto_route_vision_runtime
        self._auto_route_image_generation_runtime = auto_route_image_generation_runtime
        self._memory_bundle = memory_bundle
        self._composer_instruction_block = composer_instruction_block
        self._auto_session_prompt = auto_session_prompt
        self._auto_runtime_summary = auto_runtime_summary
        self._normalized_autonomy_profile = normalized_autonomy_profile
        self._normalized_runtime_permissions_mode = normalized_runtime_permissions_mode
        self._effective_agent_runtime_permissions_mode = effective_agent_runtime_permissions_mode
        self._normalized_external_fetch_policy = normalized_external_fetch_policy
        self._auto_tool_command = auto_tool_command
        self._auto_receipt_summary = auto_receipt_summary
        self._is_verification_command = is_verification_command
        self._auto_session_live_operator = auto_session_live_operator
        self._composer_options_dict = composer_options_dict
        self._task_sandbox_runtime_override = task_sandbox_runtime_override
    async def cancel_auto_session_run(self, session_id: str) -> bool:
        task = self._auto_session_runs.get(session_id)
        if not task or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True
    async def run_auto_session_background(
        self,
        workspace: dict,
        session_meta: dict,
        *,
        resume: bool = False,
        resume_message: str = "",
        runtime_override: dict[str, str] | None = None,
        composer_options: dict | None = None,
    ):
        session_id = str(session_meta.get("session_id") or "")
        workspace_id = int(workspace["id"])
        workspace_name = str(workspace.get("name") or "")
        sandbox_path = str(session_meta.get("sandbox_path") or "")
        start_prompt = str(session_meta.get("start_prompt") or "")
        prompt = auto_resume_prompt(session_meta, resume_message) if resume else self._auto_session_prompt(start_prompt, session_meta)
        final_output_parts: list[str] = []
        approval_message = ""
        run_error = ""
        command_receipts = list(session_meta.get("command_receipts") or [])
        verification_receipts = list(session_meta.get("verification_receipts") or [])
        pending_tool_calls: list[dict] = []
        permission_state = self._brain.agent_capture_permission_state()
        autonomous_shell_cmds = ("rm", "chmod", "ln")

        try:
            async with self._db.get_db() as conn:
                settings = await self._db.get_all_settings(conn)
                runtime_override = runtime_override or dict(session_meta.get("runtime_override") or {})
                composer_options = self._composer_options_dict(composer_options or session_meta.get("composer_options") or {})
                composer_options.update({"agent_role": "auto", "safe_mode": True, "require_approval": False})
                composer_options["external_mode"] = composer_options.get("external_mode") or "local_first"
                ai = await self._task_sandbox_ai_params(settings, conn=conn, runtime_override=runtime_override)
                projects = [dict(r) for r in await self._db.get_projects(conn, status="active")]
                tasks = [dict(r) for r in await self._db.get_tasks(conn, status="open")]
                prompts_list = [dict(r) for r in await self._db.get_prompts(conn)]
                context_block = self._brain._build_context_block(projects, tasks, prompts_list)
                history_rows = await self._load_chat_history_rows(conn, project_id=workspace_id, degrade_to_empty=True)
                history = self._history_messages_from_rows(history_rows)
                resource_ids = list(session_meta.get("resource_ids") or [])
                resource_bundle = await self._resource_bundle(conn, resource_ids=resource_ids, user_message=start_prompt, settings=settings)
                ai, vision_warnings = await self._auto_route_vision_runtime(
                    settings=settings,
                    ai=ai,
                    resource_bundle=resource_bundle,
                    requested_model="",
                    resolve_provider_key=lambda provider_id: self._devvault.vault_resolve_provider_key(conn, provider_id),
                    vault_unlocked=self._devvault.VaultSession.is_unlocked(),
                )
                if vision_warnings:
                    resource_bundle["warnings"].extend(vision_warnings)
                ai, image_warnings = await self._auto_route_image_generation_runtime(
                    conn,
                    settings=settings,
                    ai=ai,
                    user_message=start_prompt,
                    requested_model="",
                    agent_request=True,
                )
                if image_warnings:
                    resource_bundle["warnings"].extend(image_warnings)
                settings = {**settings, "ai_backend": ai.get("backend", settings.get("ai_backend", "api"))}
                autonomy_profile = self._normalized_autonomy_profile(settings.get("autonomy_profile") or "branch_auto")
                runtime_permissions_mode = self._effective_agent_runtime_permissions_mode(
                    settings,
                    backend=ai.get("backend", settings.get("ai_backend", "api")),
                    cli_path=ai.get("cli_path", ""),
                    autonomy_profile=autonomy_profile,
                    isolated_workspace=True,
                )
                memory_bundle = await self._memory_bundle(
                    conn,
                    user_message=start_prompt,
                    project_id=workspace_id,
                    resource_ids=resource_ids,
                    settings=settings,
                    composer_options=composer_options,
                )
                merged_context_block = "\n\n".join(
                    block for block in (context_block, memory_bundle["context_block"], self._composer_instruction_block(composer_options)) if block
                )
                max_iterations = max(10, min(200, int(settings.get("max_agent_iterations") or "75")))
                context_compact = str(settings.get("context_compact_enabled", "1")).strip().lower() in {"1", "true", "yes", "on"}
                session_meta["resolved_runtime"] = self._auto_runtime_summary(ai)

            session_meta = self._auto_session_service.ensure_auto_session(
                session_id,
                workspace,
                title=str(session_meta.get("title") or workspace_name or "Auto session"),
                detail=str(session_meta.get("detail") or ""),
                runtime_override=runtime_override,
                start_prompt=start_prompt,
                mode="auto",
                metadata={
                    "status": "running",
                    "last_error": "",
                    "last_run_started_at": self._now_iso(),
                    "runtime_override": runtime_override,
                    "resolved_runtime": session_meta.get("resolved_runtime") or {},
                    "resource_ids": list(session_meta.get("resource_ids") or []),
                    "composer_options": dict(composer_options or {}),
                    "command_receipts": command_receipts,
                    "verification_receipts": verification_receipts,
                    "inferred_notes": list(session_meta.get("inferred_notes") or []),
                },
            )

            self._brain.agent_allow_edit(sandbox_path, scope="repo")
            for cmd_name in autonomous_shell_cmds:
                self._brain.agent_allow_command(cmd_name)

            self._set_live_operator(
                active=True,
                mode="auto",
                phase="execute",
                title="Running Auto session",
                detail=start_prompt[:180],
                summary=str(session_meta.get("title") or "")[:120],
                workspace_id=workspace_id,
                auto_session_id=session_id,
                changed_files_count=0,
            )

            for warning in resource_bundle["warnings"]:
                final_output_parts.append(f"⚠️ {warning}\n\n")

            async for event in self._brain.run_agent(
                prompt,
                history,
                merged_context_block,
                project_name=workspace_name,
                workspace_path=sandbox_path,
                resource_context=resource_bundle["context_block"],
                resource_image_paths=resource_bundle["image_paths"],
                vision_model=resource_bundle["vision_model"],
                ollama_url=ai.get("ollama_url", ""),
                ollama_model=ai.get("ollama_model", ""),
                max_iterations=max_iterations,
                context_compact=context_compact,
                force_tool_mode=True,
                api_key=ai.get("api_key", ""),
                api_base_url=ai.get("api_base_url", ""),
                api_model=ai.get("api_model", ""),
                api_provider=ai.get("api_provider", ""),
                cli_path=ai.get("cli_path", ""),
                cli_model=ai.get("cli_model", ""),
                cli_session_persistence=bool(ai.get("cli_session_persistence", False)),
                backend=ai.get("backend", ""),
                workspace_id=workspace_id,
                autonomy_profile=autonomy_profile,
                runtime_permissions_mode=runtime_permissions_mode,
                external_fetch_policy=self._normalized_external_fetch_policy(settings.get("external_fetch_policy") or "cache_first"),
                external_fetch_cache_ttl_seconds=str(settings.get("external_fetch_cache_ttl_seconds") or "21600"),
            ):
                if event.get("type") == "tool_call":
                    tool_name = str(event.get("name") or "")
                    tool_args = dict(event.get("args") or {})
                    command, cwd, label = self._auto_tool_command(tool_name, tool_args)
                    pending_tool_calls.append({"tool": tool_name, "args": tool_args, "command": command, "cwd": cwd, "label": label, "recorded_at": self._now_iso()})
                elif event.get("type") == "tool_result":
                    tool_name = str(event.get("name") or "")
                    result = str(event.get("result") or "")
                    pending = None
                    for index in range(len(pending_tool_calls) - 1, -1, -1):
                        if pending_tool_calls[index].get("tool") == tool_name:
                            pending = pending_tool_calls.pop(index)
                            break
                    receipt = {
                        **(pending or {"tool": tool_name, "args": dict(event.get("args") or {}), "label": tool_name, "recorded_at": self._now_iso()}),
                        "summary": self._auto_receipt_summary(result),
                        "result_preview": result[:500],
                        "success": not result.startswith("ERROR:"),
                    }
                    command_receipts.append(receipt)
                    if self._is_verification_command(tool_name, receipt.get("args") or {}):
                        verification_receipts.append(receipt)
                elif event.get("type") == "text":
                    final_output_parts.append(str(event.get("chunk") or ""))
                elif event.get("type") == "approval_required":
                    approval_message = str(event.get("message") or "Approval required to continue the Auto session.")
                    break
                elif event.get("type") == "error":
                    run_error = str(event.get("message") or "Auto session failed.")
                    break
                self._auto_session_live_operator(session_meta, event)

            session_meta = dict(session_meta or {})
            session_meta.update(
                {
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "source_name": workspace_name,
                    "source_path": workspace.get("path") or "",
                    "resolved_runtime": session_meta.get("resolved_runtime") or self._auto_runtime_summary(ai),
                    "resource_ids": list(session_meta.get("resource_ids") or []),
                    "composer_options": dict(composer_options or {}),
                    "command_receipts": command_receipts,
                    "verification_receipts": verification_receipts,
                    "final_output": "".join(final_output_parts).strip(),
                    "last_run_completed_at": self._now_iso(),
                }
            )
            session_meta["status"] = "approval_required" if approval_message else "error" if run_error else "completed"
            session_meta["last_error"] = approval_message or run_error or ""
            self._auto_session_service.write_auto_session(session_meta)
            refreshed = self._auto_session_service.refresh_auto_session(session_id) or session_meta

            if not approval_message and not run_error:
                start_snapshot = dict(refreshed.get("start_snapshot") or {})
                start_commit = str(start_snapshot.get("latest_commit") or "")
                end_commit = str(refreshed.get("latest_commit") or "")
                changed_files = list(refreshed.get("changed_files") or [])
                commit_changed = bool(start_commit and end_commit and end_commit != start_commit)
                concrete_blocker = bool(refreshed.get("last_error"))
                if not changed_files and not verification_receipts and not commit_changed and not concrete_blocker:
                    refreshed["status"] = "error"
                    refreshed["last_error"] = "Auto session finished without repository changes, verification receipts, or a concrete blocker. Axon did not produce a reviewable handoff."
                    self._auto_session_service.write_auto_session(refreshed)
                    refreshed = self._auto_session_service.refresh_auto_session(session_id) or refreshed

            current_status = str(refreshed.get("status") or "")
            changed_files_count = len(refreshed.get("changed_files") or [])
            if current_status == "review_ready":
                self._set_live_operator(active=False, mode="auto", phase="verify", title="Auto session ready for review", detail="Axon finished the sandbox pass and prepared a reviewable handoff.", summary=str(refreshed.get("title") or "")[:120], workspace_id=workspace_id, auto_session_id=session_id, changed_files_count=changed_files_count, apply_allowed=bool(changed_files_count))
            elif current_status == "approval_required":
                self._set_live_operator(active=False, mode="auto", phase="recover", title="Auto session awaiting approval", detail=str(refreshed.get("last_error") or approval_message or "")[:180], summary=str(refreshed.get("title") or "")[:120], workspace_id=workspace_id, auto_session_id=session_id, changed_files_count=changed_files_count)
            else:
                self._set_live_operator(active=False, mode="auto", phase="recover" if current_status == "error" else "verify", title="Auto session needs attention" if current_status == "error" else "Auto session updated", detail=str(refreshed.get("last_error") or refreshed.get("final_output") or "")[:180], summary=str(refreshed.get("title") or "")[:120], workspace_id=workspace_id, auto_session_id=session_id, changed_files_count=changed_files_count)
        except asyncio.CancelledError:
            meta = stopped_auto_session_meta(session_meta, self._now_iso)
            meta.update(
                {
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "source_name": workspace_name,
                    "source_path": workspace.get("path") or "",
                    "resolved_runtime": session_meta.get("resolved_runtime") or {},
                    "resource_ids": list(session_meta.get("resource_ids") or []),
                    "composer_options": dict(composer_options or {}),
                    "command_receipts": command_receipts,
                    "verification_receipts": verification_receipts,
                }
            )
            self._auto_session_service.write_auto_session(meta)
            self._auto_session_service.refresh_auto_session(session_id)
            self._set_live_operator(active=False, mode="auto", phase="recover", title="Auto session stopped", detail="Stopped by user."[:180], summary=str(session_meta.get("title") or "")[:120], workspace_id=workspace_id, auto_session_id=session_id, changed_files_count=len(meta.get("changed_files") or []))
        except Exception as exc:
            meta = dict(session_meta or {})
            meta.update({"status": "error", "last_error": str(exc), "final_output": "".join(final_output_parts).strip(), "last_run_completed_at": self._now_iso(), "command_receipts": command_receipts, "verification_receipts": verification_receipts})
            self._auto_session_service.write_auto_session(meta)
            self._auto_session_service.refresh_auto_session(session_id)
            self._set_live_operator(active=False, mode="auto", phase="recover", title="Auto session needs attention", detail=str(exc)[:180], summary=str(session_meta.get("title") or "")[:120], workspace_id=workspace_id)
        finally:
            self._brain.agent_restore_permission_state(permission_state)
            self._auto_session_runs.pop(session_id, None)

    async def queue_auto_session_run(
        self,
        body: AutoSessionStartRequest,
        *,
        resume: bool = False,
        session_id: str = "",
        run_auto_session_background: Callable[..., Awaitable[None]] | None = None,
    ):
        if run_auto_session_background is None:
            run_auto_session_background = self.run_auto_session_background
        resume_message = str(body.message or "").strip()
        existing_session = None
        project_id = body.project_id
        if resume and session_id:
            existing_session = self._auto_session_service.refresh_auto_session(session_id)
            project_id = project_id or int(existing_session.get("workspace_id") or 0) if existing_session else project_id
        if not project_id:
            raise HTTPException(400, "Select a workspace before starting Auto mode.")

        async with self._db.get_db() as conn:
            workspace = await self._db.get_project(conn, int(project_id))
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        workspace_dict = dict(workspace)

        normalized_options = self._composer_options_dict(body.composer_options)
        normalized_options.update({"agent_role": "auto", "require_approval": False, "safe_mode": True})
        normalized_options["external_mode"] = normalized_options.get("external_mode") or "local_first"
        runtime_override = self._task_sandbox_runtime_override(body)

        existing = self._auto_session_service.find_workspace_auto_session(int(project_id), active_only=True)
        if existing:
            existing = self._auto_session_service.refresh_auto_session(str(existing.get("session_id") or "")) or existing

        if resume:
            target_id = session_id or str((existing or {}).get("session_id") or "").strip()
            if not target_id:
                raise HTTPException(404, "No Auto session to continue for this workspace.")
            session_meta = existing_session if existing_session and str(existing_session.get("session_id") or "") == target_id else self._auto_session_service.refresh_auto_session(target_id)
            if not session_meta:
                raise HTTPException(404, "Auto session not found.")
            if not runtime_override:
                runtime_override = dict(session_meta.get("runtime_override") or {})
            current = self._auto_session_runs.get(target_id)
            if current and not current.done():
                return {"started": False, "already_running": True, "session": self._serialize_auto_session(session_meta, include_report=True)}
            session_meta = self._auto_session_service.write_auto_session(
                {
                    **dict(session_meta or {}),
                    "status": "running",
                    "detail": resume_message[:300] or str(session_meta.get("detail") or "")[:300],
                    "last_error": "",
                    "last_run_started_at": self._now_iso(),
                    "runtime_override": runtime_override,
                    "composer_options": dict(normalized_options),
                }
            )
        else:
            if existing and str(existing.get("status") or "") not in {"applied", "discarded"}:
                current = self._auto_session_runs.get(str(existing.get("session_id") or ""))
                return {"started": False, "already_running": bool(current and not current.done()), "requires_resolution": True, "session": self._serialize_auto_session(existing, include_report=True)}
            target_id = f"{int(time.time() * 1000)}-{workspace_dict['id']}"
            session_meta = self._auto_session_service.ensure_auto_session(
                target_id,
                workspace_dict,
                title=auto_session_title(body.message, str(workspace_dict.get("name") or "")),
                detail=str(body.message or "").strip()[:300],
                runtime_override=runtime_override,
                start_prompt=str(body.message or "").strip(),
                mode="auto",
                metadata={
                    "resource_ids": list(body.resource_ids or []),
                    "composer_options": dict(normalized_options),
                    "status": "running",
                    "last_error": "",
                    "last_run_started_at": self._now_iso(),
                },
            )

        run_task = asyncio.create_task(
            run_auto_session_background(
                workspace_dict,
                session_meta,
                resume=resume,
                resume_message=resume_message,
                runtime_override=runtime_override,
                composer_options=normalized_options,
            )
        )
        self._auto_session_runs[target_id] = run_task
        return {"started": True, "resume": resume, "session": self._serialize_auto_session(session_meta, include_report=True)}
    async def start_auto_session(self, body: AutoSessionStartRequest):
        return await self.queue_auto_session_run(body, resume=False)
    async def list_auto_sessions(self):
        refreshed_rows = refresh_listed_auto_sessions(
            self._auto_session_service.list_auto_sessions(),
            self._auto_session_service.refresh_auto_session,
        )
        return {"sessions": [self._serialize_auto_session(item) for item in refreshed_rows]}
    async def get_auto_session(self, session_id: str):
        session = self._auto_session_service.refresh_auto_session(session_id)
        if not session:
            raise HTTPException(404, "Auto session not found.")
        return {"session": self._serialize_auto_session(session, include_report=True)}
    async def continue_auto_session(self, session_id: str, body: AutoSessionStartRequest | None = None):
        payload = body or AutoSessionStartRequest(message="please continue")
        return await self.queue_auto_session_run(payload, resume=True, session_id=session_id)
    async def stop_auto_session(self, session_id: str):
        session = self._auto_session_service.refresh_auto_session(session_id)
        if not session:
            raise HTTPException(404, "Auto session not found.")
        await self.cancel_auto_session_run(session_id)
        refreshed = self._auto_session_service.refresh_auto_session(session_id) or session
        if str(refreshed.get("status") or "").strip().lower() in {"running", "approval_required"}:
            refreshed = self._auto_session_service.write_auto_session(stopped_auto_session_meta(refreshed, self._now_iso))
            refreshed = self._auto_session_service.refresh_auto_session(session_id) or refreshed
        self._set_live_operator(active=False, mode="auto", phase="recover", title="Auto session stopped", detail=str(refreshed.get("last_error") or "Stopped by user.")[:180], summary=str(refreshed.get("title") or "")[:120], workspace_id=int(refreshed.get("workspace_id") or 0) or None, auto_session_id=session_id, changed_files_count=len(refreshed.get("changed_files") or []))
        return {"stopped": True, "session": self._serialize_auto_session(refreshed, include_report=True)}
    async def apply_auto_session(self, session_id: str):
        try:
            result = self._auto_session_service.apply_auto_session(session_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        session = self._auto_session_service.refresh_auto_session(session_id)
        return {"applied": True, "summary": result.get("summary", ""), "session": self._serialize_auto_session(session, include_report=True)}
    async def discard_auto_session(self, session_id: str):
        try:
            await self.cancel_auto_session_run(session_id)
            return self._auto_session_service.discard_auto_session(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
def build_auto_session_router(**deps: Any) -> tuple[APIRouter, AutoSessionHandlers]:
    handlers = AutoSessionHandlers(**deps)
    router = APIRouter(tags=["auto-session"])
    router.add_api_route("/api/auto/sessions", handlers.list_auto_sessions, methods=["GET"])
    router.add_api_route("/api/auto/start", handlers.start_auto_session, methods=["POST"])
    router.add_api_route("/api/auto/{session_id}", handlers.get_auto_session, methods=["GET"])
    router.add_api_route("/api/auto/{session_id}/continue", handlers.continue_auto_session, methods=["POST"])
    router.add_api_route("/api/auto/{session_id}/stop", handlers.stop_auto_session, methods=["POST"])
    router.add_api_route("/api/auto/{session_id}/apply", handlers.apply_auto_session, methods=["POST"])
    router.add_api_route("/api/auto/{session_id}", handlers.discard_auto_session, methods=["DELETE"])
    return router, handlers
