"""Agent approval and steering routes extracted from the legacy server facade."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ApproveActionBody(BaseModel):
    action: dict = {}
    scope: str = "once"
    session_id: str = ""


class AllowCommandBody(BaseModel):
    command: str = ""
    allow_all: bool = False
    persist: bool = False


class AllowEditBody(BaseModel):
    path: str = ""
    scope: str = "file"


class AgentControlRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        build_edit_approval_action: Callable[..., dict[str, Any]],
        build_command_approval_action: Callable[..., dict[str, Any]],
        agent_allow_action: Callable[..., None],
        agent_get_action_state: Callable[[], dict[str, Any]],
        agent_get_session_allowed: Callable[[], list[str]],
        allowed_cmds: set[str],
        enqueue_steer_message: Callable[..., int],
    ) -> None:
        self._db = db_module
        self._build_edit_approval_action = build_edit_approval_action
        self._build_command_approval_action = build_command_approval_action
        self._agent_allow_action = agent_allow_action
        self._agent_get_action_state = agent_get_action_state
        self._agent_get_session_allowed = agent_get_session_allowed
        self._allowed_cmds = allowed_cmds
        self._enqueue_steer_message = enqueue_steer_message

    def normalize_exact_approval_action(self, action: dict, *, workspace_root: str = "") -> dict:
        raw = dict(action or {})
        action_type = str(raw.get("action_type") or "").strip().lower()
        workspace_id = raw.get("workspace_id")
        session_id = str(raw.get("session_id") or "").strip()
        if action_type.startswith("file_"):
            operation = str(raw.get("operation") or action_type.removeprefix("file_") or "edit").strip().lower()
            path = str(raw.get("path") or "").strip()
            if not path:
                return {}
            return self._build_edit_approval_action(
                operation,
                path,
                workspace_id=workspace_id,
                session_id=session_id,
                workspace_root=workspace_root,
            )
        command_preview = str(raw.get("command_preview") or raw.get("full_command") or raw.get("command") or "").strip()
        if command_preview:
            return self._build_command_approval_action(
                command_preview,
                cwd=str(raw.get("repo_root") or ""),
                workspace_id=workspace_id,
                session_id=session_id,
            )
        return {}

    async def approval_workspace_root(self, workspace_id: object) -> str:
        try:
            workspace_int = int(workspace_id)
        except Exception:
            return ""
        if workspace_int <= 0:
            return ""
        async with self._db.get_db() as conn:
            project = await self._db.get_project(conn, workspace_int)
        if not project:
            return ""
        if isinstance(project, dict):
            return str(project.get("path") or "").strip()
        try:
            return str(project["path"] or "").strip()
        except Exception:
            return str(getattr(project, "path", "") or "").strip()

    async def approve_agent_action(
        self,
        body: ApproveActionBody,
        *,
        approval_workspace_root: Callable[[object], Awaitable[str]] | None = None,
        normalize_exact_approval_action: Callable[..., dict[str, Any]] | None = None,
    ):
        action = dict(body.action or {})
        scope = str(body.scope or "once").strip().lower()
        if scope not in {"once", "task", "session", "persist"}:
            raise HTTPException(400, "Invalid approval scope")
        if not action.get("action_fingerprint"):
            raise HTTPException(400, "approval action fingerprint is required")
        resolve_workspace_root = approval_workspace_root or self.approval_workspace_root
        normalize_action = normalize_exact_approval_action or self.normalize_exact_approval_action
        workspace_root = await resolve_workspace_root(action.get("workspace_id"))
        canonical_action = normalize_action(action, workspace_root=workspace_root)
        if not canonical_action:
            raise HTTPException(400, "approval action could not be validated")
        if canonical_action.get("action_fingerprint") != action.get("action_fingerprint"):
            raise HTTPException(400, "approval action fingerprint mismatch")
        action = canonical_action
        if scope == "persist" and (bool(action.get("destructive")) or not bool(action.get("persist_allowed", False))):
            raise HTTPException(400, "This action cannot be persisted")
        self._agent_allow_action(action, scope=scope, session_id=body.session_id or str(action.get("session_id") or ""))
        return {"ok": True, "scope": scope, "action": action, "state": self._agent_get_action_state()}

    async def allow_agent_command(self, body: AllowCommandBody):
        raise HTTPException(410, "Broad command grants are disabled. Use /api/agent/approve-action for the exact blocked action.")

    async def get_interrupted_session(self, project_id: int | None = None):
        from axon_core.session_store import SessionStore

        store = SessionStore(self._db.DB_PATH)
        workspace_path = ""
        project_name = None
        if project_id:
            async with self._db.get_db() as conn:
                proj = await self._db.get_project(conn, project_id)
                if proj:
                    project_name = proj["name"]
                    workspace_path = proj["path"] or ""
        session = store.get_interrupted(
            workspace_id=project_id,
            workspace_path=workspace_path,
            project_name=project_name,
            strict_workspace=project_id is not None,
        )
        if not session:
            return {"session": None}

        last_assistant_message = ""
        for message in reversed(session.messages or []):
            if str(message.get("role") or "") != "assistant":
                continue
            candidate = str(message.get("content") or "").strip()
            if candidate:
                last_assistant_message = candidate
                break

        metadata = dict(session.metadata or {})
        return {
            "session": {
                "session_id": session.session_id,
                "resume_target": session.session_id,
                "resume_reason": str(metadata.get("resume_reason") or session.status or "resume"),
                "task": session.task,
                "iteration": session.iteration,
                "status": session.status,
                "age_seconds": session.age_seconds(),
                "summary": session.summary(),
                "tool_count": len(session.tool_log),
                "project_name": session.project_name,
                "workspace_id": metadata.get("workspace_id"),
                "workspace_path": str(metadata.get("workspace_path") or "").strip(),
                "backend": session.backend,
                "updated_at": session.updated_at,
                "last_assistant_message": last_assistant_message,
                "error_message": str(metadata.get("error_message") or "").strip(),
                "approval": metadata if session.status == "approval_required" else None,
            }
        }

    async def allow_agent_edit(self, body: AllowEditBody):
        raise HTTPException(410, "Broad edit grants are disabled. Use /api/agent/approve-action for the exact blocked action.")

    async def steer_agent(self, body: dict):
        message = (body.get("message") or "").strip()
        if not message:
            return {"ok": False, "detail": "Empty steer message"}
        session_id = str(body.get("session_id") or "").strip()
        workspace_id = body.get("project_id")
        if workspace_id in ("", None):
            workspace_id = body.get("workspace_id")
        queued = self._enqueue_steer_message(
            message,
            session_id=session_id,
            workspace_id=workspace_id,
        )
        return {"ok": True, "queued": queued, "session_id": session_id, "workspace_id": workspace_id}

    async def get_allowed_commands(self):
        return {
            "deprecated": True,
            "detail": "Broad command grants are disabled. Use structured exact-action approvals instead.",
            "base": sorted(self._allowed_cmds),
            "session": self._agent_get_session_allowed(),
            "allow_all": False,
            "persistent_extra": [],
            "actions": self._agent_get_action_state(),
        }


def build_agent_control_router(**deps: Any) -> tuple[APIRouter, AgentControlRouteHandlers]:
    handlers = AgentControlRouteHandlers(**deps)
    router = APIRouter(tags=["agent-control"])
    router.add_api_route("/api/agent/approve-action", handlers.approve_agent_action, methods=["POST"])
    router.add_api_route("/api/agent/allow-command", handlers.allow_agent_command, methods=["POST"])
    router.add_api_route("/api/agent/sessions/interrupted", handlers.get_interrupted_session, methods=["GET"])
    router.add_api_route("/api/agent/allow-edit", handlers.allow_agent_edit, methods=["POST"])
    router.add_api_route("/api/agent/steer", handlers.steer_agent, methods=["POST"])
    router.add_api_route("/api/agent/allowed-commands", handlers.get_allowed_commands, methods=["GET"])
    return router, handlers
