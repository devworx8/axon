"""Facade bindings for chat and AI runtime compatibility helpers."""

from __future__ import annotations

from typing import Any, Callable, Optional

from axon_api.services import ai_runtime_helpers, chat_context_state, chat_message_state, composer_runtime


class ChatRuntimeFacade:
    def __init__(
        self,
        *,
        brain_module: Any,
        db_module: Any,
        devvault_module: Any,
        provider_registry_module: Any,
        runtime_manager_module: Any,
        runtime_truth_service_module: Any,
        memory_engine_module: Any,
        resource_bank_module: Any,
        console_command_service_module: Any,
        select_history_for_chat_fn: Callable[..., list[dict[str, str]]],
        cli_session_persistence_enabled: Callable[..., bool],
        resolve_model_for_role: Callable[..., dict[str, Any]],
        json_module,
        memory_sync_cache: dict[str, Any],
        memory_sync_cache_ttl_seconds: float,
        runtime_truth_for_settings_fn: Callable[..., Any],
        family_cli_override_path_fn: Callable[[dict[str, Any], str], str],
        resolved_api_runtime_fn: Callable[..., Any],
        ai_params_fn: Callable[..., Any],
        composer_options_dict_fn: Callable[[Any], dict[str, Any]],
        composer_memory_layers_fn: Callable[..., list[str]],
        load_chat_history_rows_fn: Callable[..., Any],
        set_live_operator_fn: Callable[..., None],
        persist_chat_reply_fn: Callable[..., Any],
        stored_chat_message_fn: Callable[..., str],
        parse_stored_chat_message_fn: Callable[[str], dict[str, object]],
    ) -> None:
        self._brain_module = brain_module
        self._db_module = db_module
        self._devvault_module = devvault_module
        self._provider_registry_module = provider_registry_module
        self._runtime_manager_module = runtime_manager_module
        self._runtime_truth_service_module = runtime_truth_service_module
        self._memory_engine_module = memory_engine_module
        self._resource_bank_module = resource_bank_module
        self._console_command_service_module = console_command_service_module
        self._select_history_for_chat_fn = select_history_for_chat_fn
        self._cli_session_persistence_enabled = cli_session_persistence_enabled
        self._resolve_model_for_role = resolve_model_for_role
        self._json_module = json_module
        self._memory_sync_cache = memory_sync_cache
        self._memory_sync_cache_ttl_seconds = memory_sync_cache_ttl_seconds
        self._runtime_truth_for_settings_fn = runtime_truth_for_settings_fn
        self._family_cli_override_path_fn = family_cli_override_path_fn
        self._resolved_api_runtime_fn = resolved_api_runtime_fn
        self._ai_params_fn = ai_params_fn
        self._composer_options_dict_fn = composer_options_dict_fn
        self._composer_memory_layers_fn = composer_memory_layers_fn
        self._load_chat_history_rows_fn = load_chat_history_rows_fn
        self._set_live_operator_fn = set_live_operator_fn
        self._persist_chat_reply_fn = persist_chat_reply_fn
        self._stored_chat_message_fn = stored_chat_message_fn
        self._parse_stored_chat_message_fn = parse_stored_chat_message_fn

    def local_role_for_composer(self, options: dict, agent_request: bool = False) -> str:
        return composer_runtime.local_role_for_composer(options, agent_request=agent_request)

    def normalized_autonomy_profile(self, value: str, *, reject_elevated: bool = False) -> str:
        return composer_runtime.normalized_autonomy_profile(
            value,
            reject_elevated=reject_elevated,
        )

    def normalized_runtime_permissions_mode(self, value: str, *, fallback: str = "default") -> str:
        return composer_runtime.normalized_runtime_permissions_mode(value, fallback=fallback)

    def effective_agent_runtime_permissions_mode(
        self,
        settings: dict,
        *,
        override: str = "",
        backend: str = "",
        cli_path: str = "",
        autonomy_profile: str = "",
    ) -> str:
        return composer_runtime.effective_agent_runtime_permissions_mode(
            settings,
            override=override,
            backend=backend,
            cli_path=cli_path,
            autonomy_profile=autonomy_profile,
            cli_runtime_family=self._brain_module._cli_runtime_family,
        )

    def normalized_external_fetch_policy(self, value: str) -> str:
        return composer_runtime.normalized_external_fetch_policy(value)

    def normalized_max_history_turns(self, settings_or_payload: dict, key: str = "max_history_turns") -> str:
        return composer_runtime.normalized_max_history_turns(
            settings_or_payload,
            setting_int=self.setting_int,
            key=key,
        )

    def model_budget_for_request(self, composer_options: dict, *, agent_request: bool = False) -> str:
        return composer_runtime.model_budget_for_request(
            composer_options,
            agent_request=agent_request,
        )

    def configured_budget_model(self, settings: dict, budget: str) -> str:
        return ai_runtime_helpers.configured_budget_model(settings, budget)

    def default_budget_model_for_ai(self, ai: dict, settings: dict, budget: str) -> str:
        return ai_runtime_helpers.default_budget_model_for_ai(
            ai,
            settings,
            budget,
            brain_module=self._brain_module,
        )

    def model_call_kwargs(self, ai: dict) -> dict:
        return ai_runtime_helpers.model_call_kwargs(ai)

    async def effective_ai_params(
        self,
        settings: dict,
        composer_options: dict,
        *,
        conn=None,
        agent_request: bool = False,
        requested_model: str = "",
    ) -> dict:
        return await ai_runtime_helpers.effective_ai_params(
            settings,
            composer_options,
            conn=conn,
            agent_request=agent_request,
            requested_model=requested_model,
            provider_registry_module=self._provider_registry_module,
            devvault_module=self._devvault_module,
            db_module=self._db_module,
            brain_module=self._brain_module,
            runtime_manager_module=self._runtime_manager_module,
            runtime_truth_service_module=self._runtime_truth_service_module,
            resolve_model_for_role=self._resolve_model_for_role,
            runtime_truth_for_settings=self._runtime_truth_for_settings_fn,
            family_cli_override_path=self._family_cli_override_path_fn,
            resolved_api_runtime=self._resolved_api_runtime_fn,
            cli_session_persistence_enabled=self._cli_session_persistence_enabled,
            ai_params_fn=self._ai_params_fn,
        )

    def looks_like_image_generation_request(self, message: str) -> bool:
        return ai_runtime_helpers.looks_like_image_generation_request(message)

    async def auto_route_image_generation_runtime(
        self,
        conn,
        *,
        settings: dict,
        ai: dict,
        user_message: str,
        requested_model: str = "",
        agent_request: bool = False,
    ) -> tuple[dict, list[str]]:
        return await ai_runtime_helpers.auto_route_image_generation_runtime(
            conn,
            settings=settings,
            ai=ai,
            user_message=user_message,
            requested_model=requested_model,
            agent_request=agent_request,
            provider_registry_module=self._provider_registry_module,
            devvault_module=self._devvault_module,
        )

    async def memory_bundle(
        self,
        conn,
        *,
        user_message: str,
        project_id: Optional[int],
        resource_ids: list[int],
        settings: dict,
        composer_options: dict,
        snapshot_revision: str = "",
    ) -> dict:
        return await chat_context_state.memory_bundle(
            self._memory_engine_module,
            self.ensure_memory_layers_synced,
            self._composer_memory_layers_fn,
            conn,
            user_message=user_message,
            project_id=project_id,
            resource_ids=resource_ids,
            settings=settings,
            composer_options=composer_options,
            snapshot_revision=snapshot_revision,
        )

    async def ensure_memory_layers_synced(self, conn, settings: dict, *, force: bool = False) -> dict:
        return await chat_context_state.ensure_memory_layers_synced(
            self._memory_engine_module,
            self._memory_sync_cache,
            self._memory_sync_cache_ttl_seconds,
            conn,
            settings,
            force=force,
        )

    def setting_int(
        self,
        settings: dict,
        key: str,
        default: int,
        *,
        minimum: int = 1,
        maximum: int = 500,
    ) -> int:
        return chat_context_state.setting_int(
            settings,
            key,
            default,
            minimum=minimum,
            maximum=maximum,
        )

    def compact_text(self, value: str, *, limit: int = 180) -> str:
        return chat_context_state.compact_text(value, limit=limit)

    def build_thread_summary_text(self, rows) -> str:
        return chat_context_state.build_thread_summary_text(
            rows,
            parse_stored_chat_message_fn=self._parse_stored_chat_message_fn,
        )

    async def workspace_snapshot_bundle(
        self,
        conn,
        *,
        project_id: Optional[int],
        settings: dict,
    ) -> dict:
        return await chat_context_state.workspace_snapshot_bundle(
            self._db_module,
            self._brain_module,
            self._json_module,
            conn,
            project_id=project_id,
            settings=settings,
        )

    async def chat_history_bundle(
        self,
        conn,
        *,
        project_id: Optional[int],
        settings: dict,
        backend: str,
        history_rows=None,
    ) -> dict:
        return await chat_context_state.chat_history_bundle(
            self._db_module,
            self._select_history_for_chat_fn,
            self.history_messages_from_rows,
            self._load_chat_history_rows_fn,
            self._json_module,
            conn,
            project_id=project_id,
            settings=settings,
            backend=backend,
            history_rows=history_rows,
            parse_stored_chat_message_fn=self._parse_stored_chat_message_fn,
        )

    def extract_first_url(self, message: str) -> str:
        return chat_context_state.extract_first_url(message)

    def requires_fresh_external_fetch(self, message: str) -> bool:
        return chat_context_state.requires_fresh_external_fetch(message)

    def looks_like_mutating_or_generation_request(self, message: str) -> bool:
        return chat_context_state.looks_like_mutating_or_generation_request(message)

    def looks_like_local_fast_path_candidate(self, message: str) -> bool:
        return chat_context_state.looks_like_local_fast_path_candidate(message)

    def format_cached_web_fast_answer(self, row, *, url: str) -> str:
        return chat_context_state.format_cached_web_fast_answer(row, url=url)

    def workspace_snapshot_fast_answer(self, message: str, snapshot_bundle: dict) -> str:
        return chat_context_state.workspace_snapshot_fast_answer(message, snapshot_bundle)

    def memory_fast_answer(self, message: str, memory_bundle: dict) -> str:
        return chat_context_state.memory_fast_answer(message, memory_bundle)

    async def maybe_local_fast_chat_response(
        self,
        conn,
        *,
        user_message: str,
        project_id: Optional[int],
        settings: dict,
        snapshot_bundle: dict,
        memory_bundle: dict,
    ) -> dict | None:
        return await chat_context_state.maybe_local_fast_chat_response(
            self._db_module,
            self.normalized_external_fetch_policy,
            conn,
            user_message=user_message,
            project_id=project_id,
            settings=settings,
            snapshot_bundle=snapshot_bundle,
            memory_bundle_payload=memory_bundle,
        )

    async def persist_chat_reply(
        self,
        conn,
        *,
        project_id: Optional[int],
        user_message: str,
        assistant_message: str,
        resources: list[dict],
        thread_mode: str,
        tokens: int = 0,
        model_label: str = "",
        event_name: str = "chat",
        event_summary: str = "",
    ):
        return await chat_message_state.persist_chat_reply(
            self._db_module,
            self._stored_chat_message_fn,
            conn,
            project_id=project_id,
            user_message=user_message,
            assistant_message=assistant_message,
            resources=resources,
            thread_mode=thread_mode,
            tokens=tokens,
            model_label=model_label,
            event_name=event_name,
            event_summary=event_summary,
        )

    async def maybe_handle_chat_console_command(
        self,
        conn,
        *,
        project_id: Optional[int],
        user_message: str,
        thread_mode: str,
    ):
        return await chat_message_state.maybe_handle_chat_console_command(
            self._db_module,
            self._console_command_service_module,
            self._set_live_operator_fn,
            self._persist_chat_reply_fn,
            conn,
            project_id=project_id,
            user_message=user_message,
            thread_mode=thread_mode,
        )

    def clean_resource_ids(self, resource_ids: Optional[list[int]]) -> list[int]:
        return chat_message_state.clean_resource_ids(resource_ids)

    def thread_mode_from_composer_options(
        self,
        composer_options: dict | None,
        *,
        agent_request: bool = False,
    ) -> str:
        return chat_message_state.thread_mode_from_composer_options(
            composer_options,
            agent_request=agent_request,
            composer_options_dict=self._composer_options_dict_fn,
        )

    def stored_chat_message(
        self,
        message: str,
        *,
        resources: list[dict] | None = None,
        mode: str = "",
        thread_mode: str = "",
        model_label: str = "",
    ) -> str:
        return chat_message_state.stored_chat_message(
            message,
            resources=resources,
            mode=mode,
            thread_mode=thread_mode,
            model_label=model_label,
            json_module=self._json_module,
        )

    def stored_message_with_resources(self, message: str, resources: list[dict]) -> str:
        return chat_message_state.stored_message_with_resources(
            message,
            resources,
            stored_chat_message_fn=self._stored_chat_message_fn,
        )

    def parse_stored_chat_message(self, raw_content: str) -> dict[str, object]:
        return chat_message_state.parse_stored_chat_message(
            raw_content,
            json_module=self._json_module,
        )

    def history_messages_from_rows(self, rows) -> list[dict[str, str]]:
        return chat_message_state.history_messages_from_rows(
            rows,
            parse_stored_chat_message_fn=self._parse_stored_chat_message_fn,
        )

    def serialize_chat_history_row(self, row) -> dict[str, object]:
        return chat_message_state.serialize_chat_history_row(
            row,
            parse_stored_chat_message_fn=self._parse_stored_chat_message_fn,
        )

    async def resource_bundle(
        self,
        conn,
        *,
        resource_ids: list[int],
        user_message: str,
        settings: dict,
    ) -> dict:
        return await chat_message_state.resource_bundle(
            self._db_module,
            self._resource_bank_module,
            self._json_module,
            conn,
            resource_ids=resource_ids,
            user_message=user_message,
            settings=settings,
        )
