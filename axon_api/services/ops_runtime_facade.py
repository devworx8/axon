"""Facade bindings for browser, connection, and live-operator runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable, Optional

from axon_api.services import browser_runtime_state, connection_runtime_state, live_operator_state


class OpsRuntimeFacade:
    def __init__(
        self,
        *,
        live_operator_snapshot: dict[str, Any],
        browser_action_state: dict[str, Any],
        connection_config_fn: Callable[[], dict[str, Any]],
        read_tunnel_url_fn: Callable[[dict[str, Any] | None], str],
        domain_probe_cache: dict[str, Any],
        time_module,
        urlrequest_module,
        urlerror_module,
        json_module,
    ) -> None:
        self._live_operator_snapshot = live_operator_snapshot
        self._browser_action_state = browser_action_state
        self._connection_config_fn = connection_config_fn
        self._read_tunnel_url_fn = read_tunnel_url_fn
        self._domain_probe_cache = domain_probe_cache
        self._time_module = time_module
        self._urlrequest_module = urlrequest_module
        self._urlerror_module = urlerror_module
        self._json_module = json_module

    def set_live_operator(
        self,
        *,
        active: bool,
        mode: str,
        phase: str,
        title: str,
        detail: str = "",
        tool: str = "",
        summary: str = "",
        workspace_id: Optional[int] = None,
        auto_session_id: str = "",
        changed_files_count: int = 0,
        apply_allowed: bool = False,
        preserve_started: bool = False,
    ) -> None:
        live_operator_state.set_live_operator(
            active=active,
            mode=mode,
            phase=phase,
            title=title,
            detail=detail,
            tool=tool,
            summary=summary,
            workspace_id=workspace_id,
            auto_session_id=auto_session_id,
            changed_files_count=changed_files_count,
            apply_allowed=apply_allowed,
            preserve_started=preserve_started,
            live_operator_snapshot=self._live_operator_snapshot,
        )

    def serialize_browser_action_state(self) -> dict[str, Any]:
        return browser_runtime_state.serialize_browser_action_state(self._browser_action_state)

    def next_browser_action_id(self) -> int:
        return browser_runtime_state.next_browser_action_id(self._browser_action_state)

    def find_approved_browser_action(self, proposal_id: int) -> Optional[dict[str, Any]]:
        return browser_runtime_state.find_approved_browser_action(
            proposal_id,
            self._browser_action_state,
        )

    def release_browser_preview_attachment(self, preview: dict | None = None) -> None:
        browser_runtime_state.release_browser_preview_attachment(
            preview,
            browser_action_state=self._browser_action_state,
        )

    async def attach_preview_browser(
        self,
        url: str,
        *,
        preview: dict | None = None,
        workspace: dict | None = None,
        auto_meta: dict | None = None,
    ) -> dict[str, object]:
        return await browser_runtime_state.attach_preview_browser(
            url,
            preview=preview,
            workspace=workspace,
            auto_meta=auto_meta,
            browser_action_state=self._browser_action_state,
        )

    def auto_session_live_operator(self, session_meta: dict[str, Any], event: dict[str, Any]) -> None:
        live_operator_state.auto_session_live_operator(
            session_meta,
            event,
            set_live_operator_fn=self.set_live_operator,
        )

    def task_sandbox_live_operator(self, task: dict[str, Any], event: dict[str, Any]) -> None:
        live_operator_state.task_sandbox_live_operator(
            task,
            event,
            set_live_operator_fn=self.set_live_operator,
        )

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def now_iso(self) -> str:
        return self.utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def probe_public_origin(self, public_base_url: str, enabled: bool) -> dict[str, Any]:
        return connection_runtime_state.probe_public_origin(
            public_base_url,
            enabled,
            domain_probe_cache=self._domain_probe_cache,
            time_module=self._time_module,
            urlrequest_module=self._urlrequest_module,
            urlerror_module=self._urlerror_module,
            json_module=self._json_module,
        )

    def connection_snapshot(self) -> dict[str, Any]:
        snapshot = connection_runtime_state.connection_snapshot(
            self._connection_config_fn,
            self.probe_public_origin,
            self._read_tunnel_url_fn,
        )
        snapshot["stable_domain_status"] = snapshot["probe"]["status"]
        snapshot["stable_domain_detail"] = snapshot["probe"]["detail"]
        snapshot["named_tunnel_ready"] = self._connection_config_fn().get("named_tunnel_ready", False)
        snapshot.pop("probe", None)
        return snapshot
