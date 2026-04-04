"""Runtime status and CLI login routes extracted from the legacy server facade."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class ClaudeCliLoginRequest(BaseModel):
    mode: str | None = None
    email: str | None = None


class RuntimeLoginStartRequest(BaseModel):
    mode: str | None = None
    email: str | None = None


class RuntimeCliRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        devbrain_log: Path,
        provider_registry_module: Any,
        build_runtime_status: Callable[..., dict[str, Any]],
        runtime_truth_builder: Callable[..., dict[str, Any]],
        vault_resolve_all_provider_keys: Callable[[Any], Awaitable[dict[str, str]]],
        vault_unlocked: Callable[[], bool],
        ensure_memory_layers_synced: Callable[[Any, dict], Awaitable[dict[str, Any]]],
        ollama_list_models: Callable[[str], Awaitable[list[Any]]],
        ollama_service_status: Callable[[], dict[str, Any]],
        stored_ollama_runtime_mode: Callable[[dict], str],
        connection_snapshot: Callable[[], dict[str, Any]],
        serialize_browser_action_state: Callable[[], dict[str, Any]],
        selected_cli_model: Callable[[dict], str],
        family_cli_override_path: Callable[[dict, str], str],
        runtime_login_start_session: Callable[..., dict[str, Any]],
        runtime_login_refresh_session: Callable[[str, str], dict[str, Any] | None],
        runtime_login_cancel_session: Callable[[str, str], dict[str, Any]],
        claude_cli_build_snapshot: Callable[[str], dict[str, Any]],
        claude_cli_install: Callable[[str], dict[str, Any]],
        claude_cli_logout: Callable[[str], dict[str, Any]],
        codex_cli_build_snapshot: Callable[[str], dict[str, Any]],
        codex_cli_install: Callable[[str], dict[str, Any]],
        codex_cli_logout: Callable[[str], dict[str, Any]],
        get_session_usage: Callable[[], dict[str, Any]],
        live_operator_snapshot: dict[str, Any],
        terminal_processes: dict[int, Any],
    ) -> None:
        self._db = db_module
        self._devbrain_log = devbrain_log
        self._provider_registry = provider_registry_module
        self._build_runtime_status = build_runtime_status
        self._runtime_truth_builder = runtime_truth_builder
        self._vault_resolve_all_provider_keys = vault_resolve_all_provider_keys
        self._vault_unlocked = vault_unlocked
        self._ensure_memory_layers_synced = ensure_memory_layers_synced
        self._ollama_list_models = ollama_list_models
        self._ollama_service_status = ollama_service_status
        self._stored_ollama_runtime_mode = stored_ollama_runtime_mode
        self._connection_snapshot = connection_snapshot
        self._serialize_browser_action_state = serialize_browser_action_state
        self._selected_cli_model = selected_cli_model
        self._family_cli_override_path = family_cli_override_path
        self._runtime_login_start_session = runtime_login_start_session
        self._runtime_login_refresh_session = runtime_login_refresh_session
        self._runtime_login_cancel_session = runtime_login_cancel_session
        self._claude_cli_build_snapshot = claude_cli_build_snapshot
        self._claude_cli_install = claude_cli_install
        self._claude_cli_logout = claude_cli_logout
        self._codex_cli_build_snapshot = codex_cli_build_snapshot
        self._codex_cli_install = codex_cli_install
        self._codex_cli_logout = codex_cli_logout
        self._get_session_usage = get_session_usage
        self._live_operator_snapshot = live_operator_snapshot
        self._terminal_processes = terminal_processes

    async def runtime_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            vault_keys = await self._vault_resolve_all_provider_keys(conn)
            for provider_id, api_key in vault_keys.items():
                spec = self._provider_registry.PROVIDER_BY_ID.get(provider_id)
                if spec and api_key and not settings.get(spec.key_setting):
                    settings = {**settings, spec.key_setting: api_key}
            projects = await self._db.get_projects(conn, status="active")
            resources = await self._db.list_resources(conn)
            try:
                memory_overview = await self._ensure_memory_layers_synced(conn, settings)
            except Exception as exc:
                print(f"[Axon] Runtime status memory sync degraded: {exc}")
                memory_overview = {
                    "total": 0,
                    "layers": {},
                    "state": "degraded",
                    "warning": "Memory sync is temporarily unavailable.",
                }
            terminal_sessions = await self._db.list_terminal_sessions(conn, limit=6)

        available_models = await self._ollama_list_models(settings.get("ollama_url", ""))
        ollama_service = self._ollama_service_status()
        status = self._build_runtime_status(
            settings=settings,
            available_models=available_models,
            ollama_running=bool(ollama_service.get("running")),
            vault_unlocked=self._vault_unlocked(),
            workspace_count=len(projects),
            resource_count=len(resources),
            memory_overview=memory_overview,
            usage=self._get_session_usage(),
        )
        status["ollama_service"] = ollama_service
        status["ollama_runtime_mode"] = self._stored_ollama_runtime_mode(settings)
        status["connection"] = self._connection_snapshot()
        status["live_operator"] = dict(self._live_operator_snapshot)
        status["terminal"] = {
            "active_session_id": next((row["id"] for row in terminal_sessions if row["id"] in self._terminal_processes), None),
            "session_count": len(terminal_sessions),
            "running_count": sum(1 for row in terminal_sessions if row["id"] in self._terminal_processes),
        }
        status.update(
            self._runtime_truth_builder(
                status,
                settings=settings,
                ollama_running=bool(ollama_service.get("running")),
            )
        )
        status["browser_actions"] = self._serialize_browser_action_state()
        return status

    def _normalize_runtime_login_family(self, family: str) -> str:
        text = str(family or "").strip().lower()
        if text in {"cli", "claude"}:
            return "claude"
        if text == "codex":
            return "codex"
        raise HTTPException(404, "Runtime family not found.")

    async def _runtime_login_start(self, family: str, body: RuntimeLoginStartRequest | None = None):
        family_name = self._normalize_runtime_login_family(family)
        payload = body or RuntimeLoginStartRequest()
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            override_path = self._family_cli_override_path(settings, family_name)
            result = self._runtime_login_start_session(
                family_name,
                override_path=override_path,
                mode=payload.mode or "claudeai",
                email=payload.email or "",
            )
            await self._db.log_event(conn, "maintenance", f"{family_name.title()} CLI guided login started")
        return {"session": result}

    async def _runtime_login_refresh(self, family: str, session_id: str):
        family_name = self._normalize_runtime_login_family(family)
        session = self._runtime_login_refresh_session(family_name, session_id)
        if not session:
            raise HTTPException(404, "Runtime login session not found.")
        return {"session": session}

    async def _runtime_login_cancel(self, family: str, session_id: str):
        family_name = self._normalize_runtime_login_family(family)
        async with self._db.get_db() as conn:
            try:
                session = self._runtime_login_cancel_session(family_name, session_id)
            except ValueError as exc:
                raise HTTPException(404, str(exc))
            await self._db.log_event(conn, "maintenance", f"{family_name.title()} CLI login cancelled")
        return {"session": session}

    async def runtime_cli_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        return self._claude_cli_build_snapshot(self._family_cli_override_path(settings, "claude"))

    async def runtime_cli_install(self):
        import asyncio

        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            result = await asyncio.to_thread(
                self._claude_cli_install,
                self._family_cli_override_path(settings, "claude"),
            )
            await self._db.log_event(conn, "maintenance", "Claude CLI install action requested")
        return result

    async def runtime_cli_login(self, body: ClaudeCliLoginRequest):
        return await self._runtime_login_start("claude", RuntimeLoginStartRequest(mode=body.mode, email=body.email))

    async def runtime_claude_login_start(self, body: RuntimeLoginStartRequest | None = None):
        return await self._runtime_login_start("claude", body)

    async def runtime_claude_login_status(self, session_id: str):
        return await self._runtime_login_refresh("claude", session_id)

    async def runtime_claude_login_cancel(self, session_id: str):
        return await self._runtime_login_cancel("claude", session_id)

    async def runtime_cli_logout(self):
        import asyncio

        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            result = await asyncio.to_thread(
                self._claude_cli_logout,
                self._family_cli_override_path(settings, "claude"),
            )
            await self._db.log_event(conn, "maintenance", "Claude CLI sign-out requested")
        return result

    async def runtime_codex_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        return self._codex_cli_build_snapshot(self._family_cli_override_path(settings, "codex"))

    async def runtime_codex_install(self):
        import asyncio

        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            result = await asyncio.to_thread(
                self._codex_cli_install,
                self._family_cli_override_path(settings, "codex"),
            )
            await self._db.log_event(conn, "maintenance", "Codex CLI install action requested")
        return result

    async def runtime_codex_login(self):
        return await self._runtime_login_start("codex")

    async def runtime_codex_login_start(self, body: RuntimeLoginStartRequest | None = None):
        return await self._runtime_login_start("codex", body)

    async def runtime_codex_login_status(self, session_id: str):
        return await self._runtime_login_refresh("codex", session_id)

    async def runtime_codex_login_cancel(self, session_id: str):
        return await self._runtime_login_cancel("codex", session_id)

    async def runtime_codex_logout(self):
        import asyncio

        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            result = await asyncio.to_thread(
                self._codex_cli_logout,
                self._family_cli_override_path(settings, "codex"),
            )
            await self._db.log_event(conn, "maintenance", "Codex CLI sign-out requested")
        return result

    async def server_logs(self, tail: int = 200):
        line_limit = max(20, min(int(tail), 2000))
        if not self._devbrain_log.exists():
            return {"path": str(self._devbrain_log), "lines": [], "text": "", "available": False}
        try:
            with self._devbrain_log.open("r", encoding="utf-8", errors="replace") as handle:
                lines = list(deque((line.rstrip("\n") for line in handle), maxlen=line_limit))
        except Exception as exc:
            raise HTTPException(500, f"Unable to read server log: {exc}")
        return {
            "path": str(self._devbrain_log),
            "lines": lines,
            "text": "\n".join(lines),
            "available": True,
        }


def build_runtime_cli_router(**deps: Any) -> tuple[APIRouter, RuntimeCliRouteHandlers]:
    handlers = RuntimeCliRouteHandlers(**deps)
    router = APIRouter(tags=["runtime-cli"])
    router.add_api_route("/api/runtime/status", handlers.runtime_status, methods=["GET"])
    router.add_api_route("/api/runtime/cli/status", handlers.runtime_cli_status, methods=["GET"])
    router.add_api_route("/api/runtime/cli/install", handlers.runtime_cli_install, methods=["POST"])
    router.add_api_route("/api/runtime/cli/login", handlers.runtime_cli_login, methods=["POST"])
    router.add_api_route("/api/runtime/claude/login/start", handlers.runtime_claude_login_start, methods=["POST"])
    router.add_api_route("/api/runtime/claude/login/{session_id}", handlers.runtime_claude_login_status, methods=["GET"])
    router.add_api_route("/api/runtime/claude/login/{session_id}/cancel", handlers.runtime_claude_login_cancel, methods=["POST"])
    router.add_api_route("/api/runtime/cli/logout", handlers.runtime_cli_logout, methods=["POST"])
    router.add_api_route("/api/runtime/codex/status", handlers.runtime_codex_status, methods=["GET"])
    router.add_api_route("/api/runtime/codex/install", handlers.runtime_codex_install, methods=["POST"])
    router.add_api_route("/api/runtime/codex/login", handlers.runtime_codex_login, methods=["POST"])
    router.add_api_route("/api/runtime/codex/login/start", handlers.runtime_codex_login_start, methods=["POST"])
    router.add_api_route("/api/runtime/codex/login/{session_id}", handlers.runtime_codex_login_status, methods=["GET"])
    router.add_api_route("/api/runtime/codex/login/{session_id}/cancel", handlers.runtime_codex_login_cancel, methods=["POST"])
    router.add_api_route("/api/runtime/codex/logout", handlers.runtime_codex_logout, methods=["POST"])
    router.add_api_route("/api/server/logs", handlers.server_logs, methods=["GET"])
    return router, handlers
