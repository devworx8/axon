"""Workspace preview and sandbox metadata helpers extracted from server.py."""
from __future__ import annotations

from typing import Any, Awaitable, Callable


def serialize_task_sandbox(meta: dict | None, *, include_report: bool = False) -> dict | None:
    if not meta:
        return None
    item = dict(meta)
    changed_files = list(item.get("changed_files") or [])
    item["changed_files"] = changed_files if include_report else changed_files[:10]
    item["changed_files_count"] = len(changed_files)
    item["has_report"] = bool(item.get("report_markdown"))
    if not include_report:
        item.pop("report_markdown", None)
    return item


def serialize_auto_session(
    meta: dict | None,
    *,
    include_report: bool = False,
    get_preview_session_fn: Callable[..., dict | None],
) -> dict | None:
    if not meta:
        return None
    item = dict(meta)
    changed_files = list(item.get("changed_files") or [])
    item["changed_files"] = changed_files if include_report else changed_files[:10]
    item["changed_files_count"] = len(changed_files)
    item["has_report"] = bool(item.get("report_markdown"))
    item["apply_allowed"] = bool(item.get("status") == "review_ready" and changed_files)
    item["resume_target"] = str(item.get("session_id") or "")
    item["resume_reason"] = str(item.get("resume_reason") or item.get("status") or "auto_session")
    preview = get_preview_session_fn(
        workspace_id=int(item.get("workspace_id") or 0) or None,
        auto_session_id=str(item.get("session_id") or ""),
    )
    if preview:
        item["preview_url"] = str(preview.get("url") or "")
        item["dev_url"] = str(preview.get("url") or "")
        item["preview_status"] = str(preview.get("status") or "")
    if not include_report:
        item.pop("report_markdown", None)
    return item


def auto_session_summary(
    meta: dict | None,
    *,
    serialize_auto_session_fn: Callable[[dict | None], dict | None],
) -> dict | None:
    item = serialize_auto_session_fn(meta)
    if not item:
        return None
    return {
        "session_id": item.get("session_id", ""),
        "workspace_id": item.get("workspace_id"),
        "workspace_name": item.get("workspace_name") or item.get("source_name") or "",
        "status": item.get("status") or "ready",
        "phase": "review" if item.get("status") == "review_ready" else item.get("status") or "ready",
        "title": item.get("title") or item.get("workspace_name") or "Auto session",
        "detail": item.get("last_error") or item.get("final_output") or "",
        "changed_files_count": item.get("changed_files_count") or 0,
        "apply_allowed": bool(item.get("apply_allowed")),
        "resume_target": item.get("resume_target") or "",
        "resume_reason": item.get("resume_reason") or "auto_session",
        "updated_at": item.get("updated_at") or item.get("created_at") or "",
        "runtime": item.get("resolved_runtime") or {},
        "preview_url": item.get("preview_url") or "",
        "preview_status": item.get("preview_status") or "",
    }


def serialize_preview_session(meta: dict | None) -> dict | None:
    if not meta:
        return None
    item = {
        "status": "",
        "healthy": False,
        "source_workspace_path": "",
        "last_error": "",
        "log_tail": "",
        **dict(meta),
    }
    item["url"] = str(item.get("url") or "")
    item["healthy"] = bool(item.get("healthy"))
    item["running"] = str(item.get("status") or "") in {"running", "starting"}
    item["source_workspace_path"] = str(item.get("source_workspace_path") or "")
    item["last_error"] = str(item.get("last_error") or "")
    item["log_tail"] = str(item.get("log_tail") or "")
    return item


async def workspace_preview_target(
    project_id: int,
    auto_session_id: str = "",
    *,
    db_module: Any,
    auto_session_service: Any,
    http_exception_cls,
) -> tuple[dict, dict | None, str]:
    async with db_module.get_db() as conn:
        workspace = await db_module.get_project(conn, int(project_id))
    if not workspace:
        raise http_exception_cls(404, "Workspace not found")
    workspace_dict = dict(workspace)
    auto_meta = None
    target_path = str(workspace_dict.get("path") or "")
    auto_session_id = str(auto_session_id or "").strip()
    if auto_session_id:
        auto_meta = auto_session_service.read_auto_session(auto_session_id)
        if not auto_meta:
            raise http_exception_cls(404, "Auto session not found.")
        if int(auto_meta.get("workspace_id") or 0) != int(project_id):
            raise http_exception_cls(400, "Auto session does not belong to this workspace.")
        target_path = str(auto_meta.get("sandbox_path") or target_path)
    return workspace_dict, auto_meta, target_path


async def get_task_with_project(conn, task_id: int):
    cur = await conn.execute(
        """
        SELECT t.*, pr.name AS project_name
        FROM tasks t
        LEFT JOIN projects pr ON pr.id = t.project_id
        WHERE t.id = ?
        """,
        (task_id,),
    )
    return await cur.fetchone()


def task_sandbox_runtime_override(payload, *, provider_registry_module) -> dict[str, str]:
    if not payload:
        return {}
    backend = str(payload.backend or "").strip().lower()
    override: dict[str, str] = {}
    if backend in {"api", "cli", "ollama"}:
        override["backend"] = backend
    provider_id = str(payload.api_provider or "").strip().lower()
    if provider_id in provider_registry_module.PROVIDER_BY_ID:
        override["api_provider"] = provider_id
    if payload.api_model:
        override["api_model"] = str(payload.api_model).strip()
    if payload.cli_path:
        override["cli_path"] = str(payload.cli_path).strip()
    if payload.cli_model:
        override["cli_model"] = str(payload.cli_model).strip()
    if payload.cli_session_persistence_enabled is not None:
        override["cli_session_persistence_enabled"] = bool(payload.cli_session_persistence_enabled)
    if payload.ollama_model:
        override["ollama_model"] = str(payload.ollama_model).strip()
    return override


async def task_sandbox_ai_params(
    settings: dict,
    *,
    conn,
    runtime_override: dict[str, str] | None = None,
    provider_registry_module,
    effective_ai_params_fn: Callable[..., Awaitable[dict]],
) -> dict:
    merged = dict(settings)
    runtime_override = runtime_override or {}
    backend = str(runtime_override.get("backend") or merged.get("ai_backend") or "api").strip().lower()
    if backend not in {"api", "cli", "ollama"}:
        backend = str(merged.get("ai_backend") or "api").strip().lower() or "api"
    merged["ai_backend"] = backend

    if backend == "api":
        provider_id = str(runtime_override.get("api_provider") or provider_registry_module.selected_api_provider_id(merged)).strip().lower()
        if provider_id not in provider_registry_module.PROVIDER_BY_ID:
            provider_id = provider_registry_module.selected_api_provider_id(merged)
        spec = provider_registry_module.PROVIDER_BY_ID[provider_id]
        merged["api_provider"] = provider_id
        if "api_model" in runtime_override:
            merged[spec.model_setting] = runtime_override.get("api_model", "")
    elif backend == "cli":
        if "cli_path" in runtime_override:
            merged["cli_runtime_path"] = runtime_override.get("cli_path", "")
        if "cli_model" in runtime_override:
            merged["cli_runtime_model"] = runtime_override.get("cli_model", "")
        if "cli_session_persistence_enabled" in runtime_override:
            merged["claude_cli_session_persistence_enabled"] = "1" if runtime_override.get("cli_session_persistence_enabled") else "0"
    elif backend == "ollama":
        if "ollama_model" in runtime_override:
            merged["ollama_model"] = runtime_override.get("ollama_model", "")

    requested_model = ""
    if backend == "api":
        requested_model = runtime_override.get("api_model", "")
    elif backend == "cli":
        requested_model = runtime_override.get("cli_model", "")
    elif backend == "ollama":
        requested_model = runtime_override.get("ollama_model", "")

    return await effective_ai_params_fn(
        merged,
        {},
        conn=conn,
        agent_request=True,
        requested_model=requested_model,
    )


def task_sandbox_prompt(task: dict, sandbox_meta: dict) -> str:
    title = str(task.get("title") or f"Mission {task.get('id')}")
    detail = str(task.get("detail") or "").strip()
    lines = [
        f"Complete this mission inside the current sandbox workspace: {title}",
        "",
        "You are in Axon Auto mode inside an isolated git worktree sandbox.",
        f"Sandbox path: {sandbox_meta.get('sandbox_path')}",
        f"Source workspace: {sandbox_meta.get('source_path')}",
        "",
        "Rules:",
        "- Only inspect and edit files inside the sandbox path.",
        "- Do not merge, rebase, push, or modify the source workspace.",
        "- Work autonomously until the mission is complete or clearly blocked.",
        "- Treat edits and local shell work inside the sandbox as pre-approved. Do not stop to ask for routine permission.",
        "- Do not stop at a plan or commentary. The mission is only complete once the requested repo change or concrete diagnostic output exists in the sandbox and has been verified.",
        "- Run concrete checks that fit the workspace before stopping.",
        "- Ask the user only if the mission itself is ambiguous, required credentials are missing, or external access beyond the sandbox is required.",
        "- End with a concise handoff covering what changed, what still remains, and what should be reviewed before merge.",
    ]
    if detail:
        lines.extend(["", "Mission details:", detail])
    return "\n".join(lines).strip()
