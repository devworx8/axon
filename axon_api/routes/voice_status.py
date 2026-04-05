"""Voice runtime status route extracted from the legacy server facade."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter


class VoiceStatusRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        local_voice_status: Callable[[dict[str, Any] | None], dict[str, Any]],
    ) -> None:
        self._db = db_module
        self._local_voice_status = local_voice_status

    async def voice_status(self):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
        return self._local_voice_status(dict(settings or {}))


def build_voice_status_router(**deps: Any) -> tuple[APIRouter, VoiceStatusRouteHandlers]:
    handlers = VoiceStatusRouteHandlers(**deps)
    router = APIRouter(tags=["voice-status"])
    router.add_api_route("/api/voice/status", handlers.voice_status, methods=["GET"])
    return router, handlers
