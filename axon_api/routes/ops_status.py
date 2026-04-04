"""Digest, activity, usage, and live-status routes extracted from the legacy server facade."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse


class OpsStatusRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        trigger_digest_now: Callable[[], Awaitable[None]] | Callable[[], Any],
        get_session_usage: Callable[[], dict[str, Any]],
        reset_session_usage: Callable[[], None],
        now_iso: Callable[[], str],
        connection_snapshot: Callable[[], dict[str, Any]],
        auto_session_list: Callable[[], list[dict[str, Any]]],
        auto_session_summary: Callable[[dict[str, Any] | None], dict[str, Any] | None],
        serialize_terminal_session: Callable[[Any], dict[str, Any]],
        serialize_browser_action_state: Callable[[], dict[str, Any]],
        selected_cli_model: Callable[[dict], str],
        live_operator_snapshot: dict[str, Any],
        terminal_processes: dict[int, Any],
    ) -> None:
        self._db = db_module
        self._trigger_digest_now = trigger_digest_now
        self._get_session_usage = get_session_usage
        self._reset_session_usage = reset_session_usage
        self._now_iso = now_iso
        self._connection_snapshot = connection_snapshot
        self._auto_session_list = auto_session_list
        self._auto_session_summary = auto_session_summary
        self._serialize_terminal_session = serialize_terminal_session
        self._serialize_browser_action_state = serialize_browser_action_state
        self._selected_cli_model = selected_cli_model
        self._live_operator_snapshot = live_operator_snapshot
        self._terminal_processes = terminal_processes

    async def run_digest(self):
        asyncio.create_task(self._trigger_digest_now())
        return {"status": "digest started"}

    async def get_latest_digest(self):
        async with self._db.get_db() as conn:
            cur = await conn.execute(
                "SELECT * FROM activity_log WHERE event_type = 'digest' ORDER BY created_at DESC LIMIT 1"
            )
            row = await cur.fetchone()
        if not row:
            return {"digest": None}
        item = dict(row)
        return {"digest": item["summary"], "created_at": item["created_at"]}

    async def get_activity(self, limit: int = 30):
        async with self._db.get_db() as conn:
            rows = await self._db.get_activity(conn, limit=limit)
        return [dict(row) for row in rows]

    async def get_usage(self):
        return self._get_session_usage()

    async def reset_usage(self):
        self._reset_session_usage()
        return {"reset": True}

    async def build_live_snapshot(self) -> dict:
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            terminal_rows = await self._db.list_terminal_sessions(conn, limit=6)
            activity_rows = await self._db.get_activity(conn, limit=6)
        auto_rows = self._auto_session_list()
        running_session_id = next((row["id"] for row in terminal_rows if row["id"] in self._terminal_processes), None)
        connection = self._connection_snapshot()
        return {
            "type": "snapshot",
            "at": self._now_iso(),
            "connection": connection,
            "operator": dict(self._live_operator_snapshot),
            "runtime": {
                "runtime_label": (
                    "Local Ollama"
                    if settings.get("ai_backend", "api") == "ollama"
                    else "External API"
                    if settings.get("ai_backend") == "api"
                    else "CLI Agent"
                    if settings.get("ai_backend") == "cli"
                    else "Runtime offline"
                ),
                "active_model": (
                    settings.get("api_model")
                    or "deepseek-reasoner"
                    if settings.get("ai_backend") == "api"
                    else (self._selected_cli_model(settings) or "CLI default")
                    if settings.get("ai_backend") == "cli"
                    else settings.get("code_model") or settings.get("ollama_model") or settings.get("general_model") or "Saved default"
                ),
            },
            "terminal": {
                "active_session_id": running_session_id,
                "sessions": [
                    self._serialize_terminal_session(row, running=row["id"] in self._terminal_processes)
                    for row in terminal_rows
                ],
            },
            "auto_sessions": [item for item in (self._auto_session_summary(row) for row in auto_rows[:12]) if item],
            "browser_actions": self._serialize_browser_action_state(),
            "activity": [dict(row) for row in activity_rows],
        }

    async def connection_status(self):
        return self._connection_snapshot()

    async def live_feed(self, request: Request, build_live_snapshot: Callable[[], Awaitable[dict[str, Any]]] | None = None):
        snapshot_builder = build_live_snapshot or self.build_live_snapshot

        async def generate():
            tick = 0
            while True:
                if await request.is_disconnected():
                    return
                try:
                    snapshot = await snapshot_builder()
                    yield {"data": __import__("json").dumps(snapshot)}
                except Exception:
                    yield {"data": __import__("json").dumps({"type": "heartbeat", "at": self._now_iso()})}
                await asyncio.sleep(4)
                tick += 1
                if tick % 2 == 1:
                    if await request.is_disconnected():
                        return
                    yield {"data": __import__("json").dumps({"type": "heartbeat", "at": self._now_iso()})}
                    await asyncio.sleep(4)

        return EventSourceResponse(generate())


def build_ops_status_router(**deps: Any) -> tuple[APIRouter, OpsStatusRouteHandlers]:
    handlers = OpsStatusRouteHandlers(**deps)
    router = APIRouter(tags=["ops-status"])
    router.add_api_route("/api/digest", handlers.run_digest, methods=["POST"])
    router.add_api_route("/api/digest/latest", handlers.get_latest_digest, methods=["GET"])
    router.add_api_route("/api/activity", handlers.get_activity, methods=["GET"])
    router.add_api_route("/api/usage", handlers.get_usage, methods=["GET"])
    router.add_api_route("/api/usage/reset", handlers.reset_usage, methods=["POST"])
    router.add_api_route("/api/connection/status", handlers.connection_status, methods=["GET"])
    return router, handlers
