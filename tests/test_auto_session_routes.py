from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from axon_api.routes.auto_session_routes import AutoSessionHandlers, AutoSessionStartRequest


class AutoSessionRouteTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    def _build_handlers(self, workspace: dict, auto_service, run_registry: dict[str, asyncio.Task]):
        db = SimpleNamespace(
            get_db=self._fake_db,
            get_project=AsyncMock(return_value=workspace),
        )
        return AutoSessionHandlers(
            db_module=db,
            brain_module=SimpleNamespace(),
            devvault_module=SimpleNamespace(),
            auto_session_service=auto_service,
            auto_session_runs=run_registry,
            now_iso=lambda: "2026-04-06T00:00:00Z",
            set_live_operator=lambda **kwargs: None,
            serialize_auto_session=lambda meta, include_report=False: dict(meta or {}),
            task_sandbox_ai_params=AsyncMock(return_value={}),
            load_chat_history_rows=AsyncMock(return_value=[]),
            history_messages_from_rows=lambda rows: [],
            resource_bundle=AsyncMock(return_value={"warnings": [], "context_block": "", "image_paths": [], "vision_model": ""}),
            auto_route_vision_runtime=AsyncMock(return_value=({}, [])),
            auto_route_image_generation_runtime=AsyncMock(return_value=({}, [])),
            memory_bundle=AsyncMock(return_value={"context_block": ""}),
            composer_instruction_block=lambda options: "",
            auto_session_prompt=lambda message, session: message,
            auto_runtime_summary=lambda ai: {},
            normalized_autonomy_profile=lambda value: value,
            normalized_runtime_permissions_mode=lambda *args, **kwargs: "default",
            effective_agent_runtime_permissions_mode=lambda *args, **kwargs: "default",
            normalized_external_fetch_policy=lambda value: value,
            auto_tool_command=lambda name, args: ("", "", name),
            auto_receipt_summary=lambda result: result,
            is_verification_command=lambda name, args: False,
            auto_session_live_operator=lambda session, event: None,
            composer_options_dict=lambda options: dict(options or {}),
            task_sandbox_runtime_override=lambda body: {},
        )

    async def test_start_returns_running_session_immediately(self):
        workspace = {"id": 42, "name": "Hope", "path": "/tmp/hope"}
        captured = {}
        run_registry: dict[str, asyncio.Task] = {}

        async def fake_background(_workspace, session_meta, **_kwargs):
            captured["background_session"] = dict(session_meta)

        def fake_ensure(session_id, workspace_dict, **kwargs):
            metadata = dict(kwargs.get("metadata") or {})
            return {
                "session_id": session_id,
                "workspace_id": workspace_dict["id"],
                "workspace_name": workspace_dict["name"],
                "title": kwargs["title"],
                "detail": kwargs["detail"],
                "runtime_override": dict(kwargs.get("runtime_override") or {}),
                "composer_options": dict(metadata.get("composer_options") or {}),
                "status": metadata.get("status"),
                "last_error": metadata.get("last_error", ""),
                "last_run_started_at": metadata.get("last_run_started_at", ""),
            }

        auto_service = SimpleNamespace(
            refresh_auto_session=Mock(return_value=None),
            find_workspace_auto_session=Mock(return_value=None),
            ensure_auto_session=Mock(side_effect=fake_ensure),
            write_auto_session=Mock(side_effect=lambda meta: dict(meta)),
        )
        handlers = self._build_handlers(workspace, auto_service, run_registry)

        result = await handlers.queue_auto_session_run(
            AutoSessionStartRequest(message="Inspect the repo and repair the shell.", project_id=42),
            run_auto_session_background=fake_background,
        )
        await asyncio.sleep(0)

        self.assertTrue(result["started"])
        self.assertEqual(result["session"]["status"], "running")
        self.assertEqual(result["session"]["last_error"], "")
        self.assertEqual(result["session"]["last_run_started_at"], "2026-04-06T00:00:00Z")
        self.assertEqual(captured["background_session"]["status"], "running")

    async def test_resume_marks_existing_session_running_before_background(self):
        workspace = {"id": 42, "name": "Hope", "path": "/tmp/hope"}
        existing = {
            "session_id": "auto-42",
            "workspace_id": 42,
            "workspace_name": "Hope",
            "status": "error",
            "detail": "Previous blocker",
            "runtime_override": {},
        }
        captured = {}
        run_registry: dict[str, asyncio.Task] = {}

        async def fake_background(_workspace, session_meta, **_kwargs):
            captured["background_session"] = dict(session_meta)

        def fake_write(meta):
            captured["written_meta"] = dict(meta)
            return dict(meta)

        auto_service = SimpleNamespace(
            refresh_auto_session=Mock(return_value=dict(existing)),
            find_workspace_auto_session=Mock(return_value=dict(existing)),
            ensure_auto_session=Mock(side_effect=AssertionError("resume path should not create a new session")),
            write_auto_session=Mock(side_effect=fake_write),
        )
        handlers = self._build_handlers(workspace, auto_service, run_registry)

        result = await handlers.queue_auto_session_run(
            AutoSessionStartRequest(message="please continue"),
            resume=True,
            session_id="auto-42",
            run_auto_session_background=fake_background,
        )
        await asyncio.sleep(0)

        self.assertTrue(result["started"])
        self.assertTrue(result["resume"])
        self.assertEqual(result["session"]["status"], "running")
        self.assertEqual(result["session"]["detail"], "please continue")
        self.assertEqual(captured["written_meta"]["status"], "running")
        self.assertEqual(captured["background_session"]["status"], "running")

    async def test_stop_cancels_running_auto_session_and_marks_it_stopped(self):
        workspace = {"id": 42, "name": "Hope", "path": "/tmp/hope"}
        existing = {
            "session_id": "auto-42",
            "workspace_id": 42,
            "workspace_name": "Hope",
            "status": "running",
            "title": "Deploy the build",
            "detail": "Axon is still running.",
        }
        stored = dict(existing)
        run_registry: dict[str, asyncio.Task] = {}

        def fake_refresh(_session_id):
            return dict(stored)

        def fake_write(meta):
            stored.update(dict(meta))
            return dict(stored)

        auto_service = SimpleNamespace(
            refresh_auto_session=Mock(side_effect=fake_refresh),
            write_auto_session=Mock(side_effect=fake_write),
            discard_auto_session=Mock(),
            list_auto_sessions=Mock(return_value=[]),
        )
        handlers = self._build_handlers(workspace, auto_service, run_registry)

        async def fake_running_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(fake_running_task())
        run_registry["auto-42"] = task
        result = await handlers.stop_auto_session("auto-42")

        self.assertTrue(result["stopped"])
        self.assertTrue(task.cancelled())
        self.assertEqual(result["session"]["status"], "error")
        self.assertEqual(result["session"]["last_error"], "Stopped by user.")


if __name__ == "__main__":
    unittest.main()
