"""Agent orchestration core extracted from brain.py.

This module keeps the ReAct-style agent loop isolated from the helper surfaces
that now live in dedicated axon_core modules.
"""

from __future__ import annotations

import re as _re
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from .approval_actions import build_command_approval_action, build_edit_approval_action
from .agent_blocked_actions import blocked_tool_retry_prompt
from .async_workers import run_sync_agent_call
from . import agent_runtime_state
from .agent_file_actions import (
    _direct_agent_action,
    _extract_append_content,
    _extract_replace_strings,
    _extract_requested_content,
    _format_file_delete_answer,
    _format_file_edit_answer,
    _format_file_write_answer,
    _format_listing_answer,
    _parse_list_dir_entries,
    _requested_tail_line_count,
    _strip_wrapping_quotes,
    _wants_diff,
)
from .agent_delete_intent import has_explicit_delete_intent
from .agent_intent import (
    _contains_phrase,
    _filtered_general_history,
    _has_local_operator_markers,
    _is_casual_conversation,
    _is_general_planning_request,
    _requires_local_operator_execution,
)
from .agent_output import (
    _build_evidence_repair_prompt,
    _filter_thinking_chunk,
    _guard_unverified_edit_claim,
    _needs_evidence_section_repair,
    _looks_like_hallucinated_execution,
    _looks_like_unverified_edit_claim,
    _parse_react_action,
    _sanitize_agent_text,
)
from .agent_paths import (
    DEFAULT_DEVBRAIN_DB_PATH,
    _extract_path_from_text,
    _project_name_pattern,
    _recent_file_path,
    _recent_repo_path,
    _resolve_project_path_from_text,
)
from .agent_prompts import _build_react_system
from .agent_toolspecs import (
    AGENT_TOOL_DEFS,
    AgentRuntimeDeps,
    _canonical_tool_name,
    _execute_tool,
)
from .agent_browser_tools import (
    is_screenshot_result,
    extract_screenshot_path,
    build_vision_tool_message,
)


def _tool_evidence_source(tool_name: str, result: str = "") -> str:
    name = str(tool_name or "").strip().lower()
    text = str(result or "")
    if name == "http_get":
        if "[cache hit]" in text:
            return "cached_external"
        if "[live fetch]" in text:
            return "live_external"
    if name in {"read_file", "list_dir", "show_diff", "git_status", "shell_cmd", "shell_bg", "shell_bg_check"}:
        return "workspace"
    if name.startswith("memory_") or name in {"remember", "recall"}:
        return "memory"
    if name == "generate_image":
        return "resource"
    return "deterministic"


def _blocked_tool_event(
    tool_name: str,
    tool_args: dict[str, Any],
    result: str,
    *,
    workspace_id: int | None = None,
    session_id: str = "",
    workspace_path: str = "",
) -> Optional[dict[str, Any]]:
    if not isinstance(result, str):
        return None
    public_args = {
        key: value
        for key, value in dict(tool_args or {}).items()
        if not str(key).startswith("_")
    }
    resume_task = str(tool_args.get("_resume_task") or "").strip()
    draft_commit_message = str(tool_args.get("_draft_commit_message") or "").strip()
    if result.startswith("BLOCKED_EDIT:"):
        _, operation, target = result.split(":", 2)
        action = operation or tool_name.replace("_file", "")
        approval_action = build_edit_approval_action(
            action,
            target,
            workspace_id=workspace_id,
            session_id=session_id,
            workspace_root=workspace_path,
        )
        payload = {
            "type": "approval_required",
            "kind": "edit",
            "tool_name": tool_name,
            "action": action,
            "path": target,
            "args": public_args,
            "message": f"Approval required before Axon can {action} `{target}`.",
            "approval_action": approval_action,
            "action_fingerprint": approval_action.get("action_fingerprint"),
            "action_type": approval_action.get("action_type"),
            "scope_options": approval_action.get("scope_options"),
            "persist_allowed": approval_action.get("persist_allowed"),
            "summary": approval_action.get("summary"),
            "repo_root": approval_action.get("repo_root"),
            "workspace_id": workspace_id,
            "evidence_source": approval_action.get("evidence_source", "deterministic"),
        }
        if resume_task:
            payload["resume_task"] = resume_task
        return payload
    if result.startswith("BLOCKED_CMD:"):
        _, command_name, full_command = result.split(":", 2)
        approval_action = build_command_approval_action(
            full_command,
            cwd=str(tool_args.get("cwd") or ""),
            workspace_id=workspace_id,
            session_id=session_id,
        )
        message = f"Approval required before Axon can run `{full_command}`."
        if draft_commit_message:
            message += f" Drafted commit message: `{draft_commit_message}`."
        payload = {
            "type": "approval_required",
            "kind": "command",
            "tool_name": tool_name,
            "command": command_name,
            "full_command": full_command,
            "args": public_args,
            "message": message,
            "approval_action": approval_action,
            "action_fingerprint": approval_action.get("action_fingerprint"),
            "action_type": approval_action.get("action_type"),
            "scope_options": approval_action.get("scope_options"),
            "persist_allowed": approval_action.get("persist_allowed"),
            "summary": approval_action.get("summary"),
            "repo_root": approval_action.get("repo_root"),
            "workspace_id": workspace_id,
            "evidence_source": approval_action.get("evidence_source", "deterministic"),
        }
        if resume_task:
            payload["resume_task"] = resume_task
        if draft_commit_message:
            payload["draft_commit_message"] = draft_commit_message
        return payload
    return None


def _tool_followup_message(
    tool_name: str,
    result: str,
    *,
    active_tool_names: list[str],
    workspace_path: str,
) -> str:
    preview = str(result or "").strip()
    if len(preview) > 1200:
        preview = preview[:1200] + "\n...[truncated]"
    workspace_note = workspace_path or "cwd"
    return (
        f"Tool result for {tool_name}:\n{preview}\n\n"
        f"Workspace: {workspace_note}.\n"
        f"You are still operating inside {workspace_note}.\n"
        "Do not invent foreign toolsets or OAuth-only tools. "
        "If another action is needed, emit exactly one valid ACTION/ARGS pair."
    )


def _is_cli_rate_limit_error(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return any(token in lower for token in (
        "rate limit", "rate_limit", "hit your limit", "usage limit",
        "hit your usage limit", "try again at", "get more access",
    ))


def _coerce_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            for key in ("text", "thinking"):
                value = block.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
        return "\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "thinking"):
            value = content.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _rewrite_messages_for_backend(
    messages: list[dict[str, Any]],
    *,
    backend: str,
    deps: AgentRuntimeDeps,
    user_message: str,
    resource_image_paths: Optional[list[str]],
) -> list[dict[str, Any]]:
    rewritten: list[dict[str, Any]] = []
    user_indexes = [
        index for index, message in enumerate(messages)
        if str(message.get("role") or "") == "user"
    ]
    final_user_index = user_indexes[-1] if user_indexes else -1

    for index, message in enumerate(messages):
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if role != "user" or index != final_user_index:
            if isinstance(content, list):
                rewritten.append({"role": role, "content": _coerce_message_text(content)})
            else:
                rewritten.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            if backend == "api":
                rewritten.append(deps.api_message_with_images(user_message, resource_image_paths))
            elif backend == "ollama":
                rewritten.append(deps.ollama_message_with_images(user_message, resource_image_paths))
            else:
                rewritten.append(message)
        else:
            rewritten.append({"role": role, "content": content})
    return rewritten


async def run_agent(
    user_message: str,
    history: list[dict[str, Any]],
    *,
    deps: AgentRuntimeDeps,
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    workspace_path: str = "",
    tools: list[str] | None = None,
    ollama_url: str = "",
    ollama_model: str = "",
    max_iterations: int = 25,
    context_compact: bool = True,
    force_tool_mode: bool = False,
    api_key: str = "",
    api_base_url: str = "",
    api_model: str = "",
    api_provider: str = "",
    cli_path: str = "",
    cli_model: str = "",
    cli_session_persistence: bool = False,
    backend: str = "",
    workspace_id: Optional[int] = None,
    resume_session_id: str = "",
    resume_reason: str = "",
    continue_task: str = "",
    external_fetch_policy: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Async generator yielding agent events (ReAct-style, streaming-compatible):
      {"type": "text",        "chunk": str}
      {"type": "tool_call",   "name": str, "args": dict}
      {"type": "tool_result", "name": str, "result": str}
      {"type": "done",        "iterations": int}

    Uses ReAct text-based tool calling (reliable across all Ollama models).
    Session state is auto-saved to SQLite on every iteration so the user can
    say "please continue" after closing the console and pick up exactly where
    they left off.
    """
    try:
        from axon_core.session_store import SessionStore, is_resume_request, new_session_id

        _ss = SessionStore(deps.db_path) if not force_tool_mode else None
    except Exception:
        _ss = None

    session_id = new_session_id() if _ss else ""
    tool_log: list[dict] = []
    _resuming = False
    _resumed_messages: list[dict[str, Any]] = []
    resume_task_override = ""
    explicit_resume_target = str(resume_session_id or "").strip()
    explicit_resume_reason = str(resume_reason or "").strip()
    explicit_continue_task = str(continue_task or "").strip()
    try:
        import brain as _brain_mod
    except Exception:
        _brain_mod = None

    def _session_metadata(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        metadata = dict(extra or {})
        if workspace_id is not None:
            metadata.setdefault("workspace_id", workspace_id)
        if workspace_path:
            metadata.setdefault("workspace_path", workspace_path)
        if project_name:
            metadata.setdefault("project_name", project_name)
        if explicit_resume_reason:
            metadata.setdefault("resume_reason", explicit_resume_reason)
        return metadata

    prefer_latest_continue_task = bool(explicit_continue_task and not explicit_resume_target)
    if prefer_latest_continue_task:
        yield {
            "type": "text",
            "chunk": (
                "♻️ **Continuing the current task**\n"
                "No paused session was found, so Axon is using the latest concrete task from this chat "
                "instead of asking you to restate it.\n\n"
            ),
        }
        user_message = explicit_continue_task
    if _ss and not prefer_latest_continue_task and (explicit_resume_target or is_resume_request(user_message)):
        prev = _ss.get_interrupted(
            max_age_hours=4.0,
            preferred_session_id=explicit_resume_target,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            project_name=project_name,
        )
        if prev:
            prev_metadata = dict(prev.metadata or {})
            resume_task_override = str(prev_metadata.get("resume_task") or "").strip()
            if not prev.tool_log:
                _ss.mark_complete(prev.session_id)
                if prev.task.strip():
                    yield {
                        "type": "text",
                        "chunk": (
                            "♻️ **Resuming task from the saved prompt**\n"
                            "The previous run stopped before any verified tool actions were recorded, "
                            "so Axon is restarting that task cleanly instead of guessing.\n\n"
                        ),
                    }
                    user_message = prev.task
                else:
                    if explicit_continue_task:
                        yield {
                            "type": "text",
                            "chunk": (
                                "No paused session with verified work was available to resume, "
                                "so Axon is continuing from the latest concrete task in this chat instead.\n\n"
                            ),
                        }
                        user_message = explicit_continue_task
                    else:
                        yield {
                            "type": "text",
                            "chunk": (
                                "No paused session with verified work was available to resume. "
                                "Tell me what you'd like to work on and I'll get started."
                            ),
                        }
                        yield {"type": "done", "iterations": 0}
                        return
            else:
                yield {
                    "type": "text",
                    "chunk": (
                        f"♻️ **Resuming session** `{prev.session_id[:8]}…`\n"
                        f"Task: _{prev.task[:120]}_\n"
                        f"Last iteration: {prev.iteration}\n\n"
                    ),
                }
                session_id = prev.session_id
                tool_log = prev.tool_log
                _resuming = True
                _resumed_messages = [
                    m for m in prev.messages if m.get("role") in ("user", "assistant")
                ]
                user_message = resume_task_override or prev.task
        elif explicit_continue_task:
            yield {
                "type": "text",
                "chunk": (
                    "♻️ **Continuing the current task**\n"
                    "No paused session was found, so Axon is using the latest concrete task from this chat "
                    "instead of asking you to restate it.\n\n"
                ),
            }
            user_message = explicit_continue_task
        else:
            # No interrupted session found — tell the user directly instead of
            # letting the LLM see "please continue" and ask what to continue.
            yield {
                "type": "text",
                "chunk": (
                    "No paused session found to resume. "
                    "Tell me what you'd like to work on and I'll get started."
                ),
            }
            yield {"type": "done", "iterations": 0}
            return

    allow_delete = has_explicit_delete_intent(user_message)
    if _brain_mod is not None and hasattr(_brain_mod, "_update_agent_runtime_context"):
        try:
            _brain_mod._update_agent_runtime_context(
                agent_session_id=session_id,
                allow_delete=allow_delete,
            )
        except Exception:
            pass

    active_tool_names = sorted(deps.tool_registry.keys()) if tools is None else [
        tool_name for tool_name in tools if tool_name in deps.tool_registry
    ]
    if not allow_delete:
        active_tool_names = [tool_name for tool_name in active_tool_names if tool_name != "delete_file"]
    # Browser tools are dispatched outside the sync registry — include them
    from .agent_browser_tools import BROWSER_TOOL_NAMES as _BTN
    for _bt in sorted(_BTN):
        if _bt not in active_tool_names:
            active_tool_names.append(_bt)
    wrote_files = False

    backend_mode = str(backend or "").strip().lower()
    use_cli = backend_mode == "cli"
    if backend_mode == "api":
        use_api = bool(api_key and api_base_url)
    elif backend_mode in {"cli", "ollama"}:
        use_api = False
    else:
        # Backward-compatible fallback for older callers that do not pass an
        # explicit backend but still supply API credentials.
        use_api = bool(api_key and api_base_url)
    resolved_cli = deps.find_cli(cli_path) if use_cli else ""
    # Autonomous operator runs must stay isolated from any external Claude Code
    # conversation state. Plain chat can reuse sessions, but the agent loop
    # should remain self-contained until Axon manages its own session ids.
    agent_cli_session_persistence = False

    async def _stream_cli_with_fallback(
        local_messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        purpose: str,
    ) -> AsyncGenerator[str, None]:
        try:
            async for chunk in deps.stream_cli(
                local_messages,
                cli_path=resolved_cli,
                max_tokens=max_tokens,
                model=cli_model,
                allow_session_persistence=agent_cli_session_persistence,
            ):
                yield chunk
            return
        except Exception as exc:
            if not _is_cli_rate_limit_error(str(exc)):
                raise

        if api_key and api_base_url:
            fallback_label = api_provider or "API"
            fallback_model = api_model or "configured model"
            yield (
                f"⚠️ CLI runtime hit a rate limit. Switching this {purpose} turn to "
                f"{fallback_label} (`{fallback_model}`).\n\n"
            )
            api_messages = _rewrite_messages_for_backend(
                local_messages,
                backend="api",
                deps=deps,
                user_message=user_message,
                resource_image_paths=resource_image_paths,
            )
            async for chunk in deps.stream_api_chat(
                messages=api_messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=max_tokens,
                api_provider=api_provider,
            ):
                yield chunk
            return

        if ollama_url or ollama_model:
            fallback_model = vision_model or ollama_model or deps.ollama_default_model
            yield (
                f"⚠️ CLI runtime hit a rate limit. Switching this {purpose} turn to "
                f"Local Ollama (`{fallback_model}`).\n\n"
            )
            execution = await run_sync_agent_call(
                deps.ollama_execution_profile_sync,
                fallback_model,
                ollama_url,
                streaming=True,
                purpose="chat",
            )
            ollama_messages = _rewrite_messages_for_backend(
                local_messages,
                backend="ollama",
                deps=deps,
                user_message=user_message,
                resource_image_paths=resource_image_paths,
            )
            if execution.get("note"):
                yield f"⚠️ {execution['note']}\n\n"
            async for chunk in deps.stream_ollama_chat(
                messages=ollama_messages,
                model=execution["model"],
                ollama_url=ollama_url,
                max_tokens=max_tokens,
                purpose="chat",
            ):
                yield chunk
            return

        raise RuntimeError("CLI runtime hit a rate limit.")

    if not force_tool_mode and not _resuming and _is_casual_conversation(user_message):
        casual_system = (
            "You are Axon — a sharp, friendly AI copilot embedded in the user's local developer OS.\n"
            "The user is making casual conversation. Reply naturally and warmly, like a capable colleague.\n"
            "Be brief (2-4 sentences max). Mention what you can help with if relevant, but keep it conversational.\n"
            "Do NOT use tools, do NOT list files, do NOT run commands, do NOT produce reports."
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": casual_system}]
        messages.extend(
            _filtered_general_history(history, db_path=deps.db_path, workspace_path=workspace_path)
        )
        messages.append(deps.cli_message_with_images(user_message, resource_image_paths) if use_cli else {"role": "user", "content": user_message})
        if use_cli:
            async for chunk in _stream_cli_with_fallback(messages, max_tokens=1200, purpose="casual"):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            async for chunk in deps.stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=300,
                api_provider=api_provider,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            async for chunk in deps.stream_ollama_chat(
                messages=messages,
                model=ollama_model or deps.ollama_default_model,
                ollama_url=ollama_url,
                max_tokens=300,
            ):
                yield {"type": "text", "chunk": chunk}
        yield {"type": "done", "iterations": 0}
        return

    if not force_tool_mode and not _resuming and _is_general_planning_request(
        user_message,
        db_path=deps.db_path,
        workspace_path=workspace_path,
    ):
        system = (
            "You are Axon, a calm and practical AI operator.\n"
            "This request is a general planning or writing task, not a local tool task.\n"
            "Do not use tools. Do not inspect files or directories unless the user explicitly asks for local data.\n"
            "Answer directly with a clear structure, a concise draft, and 2-4 helpful next-step options."
        )
        if resource_context:
            system += f"\n\nUse these attached resources when they are relevant:\n{resource_context[:5000]}"
        messages = [{"role": "system", "content": system}]
        messages.extend(
            _filtered_general_history(history, db_path=deps.db_path, workspace_path=workspace_path)
        )

        if use_cli:
            messages.append(deps.cli_message_with_images(user_message, resource_image_paths))
            async for chunk in _stream_cli_with_fallback(messages, max_tokens=3000, purpose="planning"):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            messages.append(deps.api_message_with_images(user_message, resource_image_paths))
            async for chunk in deps.stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=1200,
                api_provider=api_provider,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            execution = await run_sync_agent_call(
                deps.ollama_execution_profile_sync,
                vision_model or ollama_model or deps.ollama_default_model,
                ollama_url,
                streaming=True,
                purpose="chat",
            )
            messages.append(deps.ollama_message_with_images(user_message, resource_image_paths))
            if execution.get("note"):
                yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}
            async for chunk in deps.stream_ollama_chat(
                messages=messages,
                model=execution["model"],
                max_tokens=1200,
                ollama_url=ollama_url,
                purpose="chat",
            ):
                yield {"type": "text", "chunk": chunk}
        yield {"type": "done", "iterations": 1}
        return

    # Synthetic/internal callers (for example mission sandbox runs) should stay
    # on the full ReAct path instead of letting the user-message heuristics
    # reinterpret a generated prompt as a direct local file command.
    allow_resume_direct_action = bool(_resuming and resume_task_override)
    if not force_tool_mode and (not _resuming or allow_resume_direct_action):
        direct_action = _direct_agent_action(
            user_message,
            history=history,
            project_name=project_name,
            workspace_path=workspace_path,
            deps=deps,
        )
        if direct_action:
            tool_name, tool_args, result, answer = direct_action
            evidence_source = _tool_evidence_source(tool_name, str(result))
            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            yield {"type": "tool_result", "name": tool_name, "result": result[:2500], "evidence_source": evidence_source}
            blocked = _blocked_tool_event(
                tool_name,
                tool_args,
                str(result),
                workspace_id=workspace_id,
                session_id=session_id,
                workspace_path=workspace_path,
            )
            if blocked:
                tool_log.append({"name": tool_name, "args": tool_args, "result": str(result)[:500]})
                if _ss and session_id:
                    _ss.save(
                        session_id=session_id,
                        task=user_message[:300],
                        messages=[],
                        iteration=0,
                        tool_log=tool_log,
                        status="approval_required",
                        project_name=project_name,
                        backend=backend or ("cli" if use_cli else ("api" if use_api else "ollama")),
                        metadata=_session_metadata({k: v for k, v in blocked.items() if k != "type"}),
                    )
                yield blocked
                return
            yield {"type": "text", "chunk": answer, "evidence_source": evidence_source}
            if _ss and session_id:
                _ss.mark_complete(session_id)
            yield {"type": "done", "iterations": 1}
            return

    system_context = context_block
    if resource_context:
        system_context = f"{system_context}\n\n{resource_context}" if system_context else resource_context
    system = _build_react_system(system_context, project_name, active_tool_names)

    messages = [{"role": "system", "content": system}]
    if _resuming and _resumed_messages:
        for message in _resumed_messages[-16:]:
            messages.append({"role": message["role"], "content": str(message.get("content", ""))[:1200]})
    else:
        for item in history[-8:]:
            messages.append({"role": item["role"], "content": item["content"][:1200]})

    _need_user_append = not (_resuming and _resumed_messages)

    if use_cli:
        if _need_user_append:
            messages.append(deps.cli_message_with_images(user_message, resource_image_paths))
        execution = None
    elif use_api:
        if _need_user_append:
            messages.append(deps.api_message_with_images(user_message, resource_image_paths))
        execution = None
    else:
        execution = await run_sync_agent_call(
            deps.ollama_execution_profile_sync,
            vision_model or ollama_model or deps.ollama_agent_model,
            ollama_url,
            streaming=True,
            purpose="agent",
        )
        if _need_user_append:
            messages.append(deps.ollama_message_with_images(user_message, resource_image_paths))

    iteration = 0
    tool_arg_repair_attempts = 0
    blocked_tool_repair_attempts = 0
    evidence_section_repair_attempts = 0
    # Resolve brain module once for runtime-context updates
    _brain_mod = None
    try:
        import importlib
        _brain_mod = importlib.import_module("brain")
    except Exception:
        pass

    for iteration in range(max_iterations):
        # ── Steer: inject any guidance messages from the UI ──
        _steer_msgs = agent_runtime_state.drain_steer_messages(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        if _steer_msgs:
            steer_text = "\n".join(f"[User guidance]: {m}" for m in _steer_msgs)
            messages.append({"role": "user", "content": steer_text})
        full_text = ""
        streamed_up_to = 0
        found_action_live = False
        try:

            async def _token_source() -> AsyncGenerator[str, None]:
                if use_cli:
                    async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=2400, model=cli_model, allow_session_persistence=agent_cli_session_persistence):
                        yield chunk
                elif use_api:
                    async for chunk in deps.stream_api_chat(
                        messages=messages,
                        api_key=api_key,
                        api_base_url=api_base_url,
                        api_model=api_model,
                        max_tokens=2400,
                        api_provider=api_provider,
                    ):
                        yield chunk
                else:
                    async for chunk in deps.stream_ollama_chat(
                        messages=messages,
                        model=execution["model"] if execution else deps.ollama_agent_model,
                        max_tokens=2400,
                        ollama_url=ollama_url,
                        purpose="agent",
                    ):
                        yield chunk

            if not use_api and not use_cli and iteration == 0 and execution and execution.get("note"):
                yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}

            async for chunk in _token_source():
                full_text += chunk
                if not found_action_live:
                    for marker in ("ACTION:", "ANSWER:"):
                        pos = full_text.find(marker)
                        if pos >= 0:
                            found_action_live = True
                            remaining = _filter_thinking_chunk(
                                _sanitize_agent_text(full_text[streamed_up_to:pos].strip())
                            )
                            if remaining:
                                yield {"type": "thinking", "chunk": remaining}
                            streamed_up_to = pos
                            break
                    if not found_action_live:
                        # Use a larger buffer and only emit on word boundaries to
                        # prevent sub-word token fragments reaching the client
                        # (DeepSeek streams character-by-character, causing broken
                        # words like "bl ock ed" if chunked naively).
                        buf_size = max(80, len(full_text) // 8)
                        safe_end = max(streamed_up_to, len(full_text) - buf_size)
                        if safe_end > streamed_up_to:
                            # Snap to last whitespace to avoid mid-word splits
                            candidate = full_text[streamed_up_to:safe_end]
                            last_ws = candidate.rfind(' ')
                            if last_ws > 0:
                                safe_end = streamed_up_to + last_ws + 1
                            new_text = _filter_thinking_chunk(full_text[streamed_up_to:safe_end], strip=False)
                            if new_text.strip():
                                yield {"type": "thinking", "chunk": new_text}
                                streamed_up_to = safe_end

        except Exception as exc:
            provider_label = "CLI" if use_cli else (api_provider or ("API" if use_api else "Ollama"))
            exc_lower = str(exc).lower()
            if use_cli and _is_cli_rate_limit_error(exc_lower):
                if api_key and api_base_url:
                    fallback_label = api_provider or "API"
                    fallback_model = api_model or "configured model"
                    yield {
                        "type": "thinking",
                        "chunk": (
                            f"\n⏳ CLI runtime hit a rate limit — switching this task to "
                            f"{fallback_label} (`{fallback_model}`)…\n"
                        ),
                    }
                    use_cli = False
                    use_api = True
                    if _brain_mod is not None and hasattr(_brain_mod, "_update_agent_runtime_context"):
                        try:
                            _brain_mod._update_agent_runtime_context(backend="api")
                        except Exception:
                            pass
                    messages = _rewrite_messages_for_backend(
                        messages,
                        backend="api",
                        deps=deps,
                        user_message=user_message,
                        resource_image_paths=resource_image_paths,
                    )
                    continue
                if ollama_url or ollama_model:
                    fallback_model = ollama_model or deps.ollama_agent_model
                    yield {
                        "type": "thinking",
                        "chunk": (
                            f"\n⏳ CLI runtime hit a rate limit — switching this task to "
                            f"Local Ollama (`{fallback_model}`)…\n"
                        ),
                    }
                    use_cli = False
                    use_api = False
                    execution = await run_sync_agent_call(
                        deps.ollama_execution_profile_sync,
                        vision_model or ollama_model or deps.ollama_agent_model,
                        ollama_url,
                        streaming=True,
                        purpose="agent",
                    )
                    if _brain_mod is not None and hasattr(_brain_mod, "_update_agent_runtime_context"):
                        try:
                            _brain_mod._update_agent_runtime_context(backend="ollama")
                        except Exception:
                            pass
                    messages = _rewrite_messages_for_backend(
                        messages,
                        backend="ollama",
                        deps=deps,
                        user_message=user_message,
                        resource_image_paths=resource_image_paths,
                    )
                    continue
            # ── Unrecoverable error ──────────────────────────────────────────
            if _ss and session_id:
                persisted_messages = list(messages)
                persisted_error = f"⚠️ {provider_label} error: {exc}"
                if full_text.strip():
                    persisted_messages.append({"role": "assistant", "content": full_text.strip()})
                persisted_messages.append({"role": "assistant", "content": persisted_error})
                _ss.save(
                    session_id=session_id,
                    task=user_message[:300],
                    messages=persisted_messages,
                    iteration=iteration,
                    tool_log=tool_log,
                    status="interrupted",
                    project_name=project_name,
                    backend=backend or ("cli" if use_cli else ("api" if use_api else "ollama")),
                    metadata=_session_metadata({"error_message": str(exc), "provider": provider_label.lower()}),
                )
            yield {"type": "error", "message": f"{provider_label} error: {exc}"}
            return

        if not full_text.strip():
            yield {"type": "error", "message": "Empty response from model."}
            break

        action = _parse_react_action(full_text)
        answer_match = _re.search(r"ANSWER:\s*([\s\S]+)", full_text)
        clean_text = _sanitize_agent_text(full_text)

        if action:
            tool_name, tool_args = action
            canonical_tool_name = _canonical_tool_name(tool_name, tool_args)
            if not found_action_live:
                think_text = full_text[: full_text.find("ACTION:")].strip()
                think_text = _filter_thinking_chunk(_sanitize_agent_text(think_text))
                if think_text:
                    yield {"type": "thinking", "chunk": think_text}

            if canonical_tool_name not in active_tool_names:
                unavailable_result = (
                    f"ERROR: Tool `{canonical_tool_name}` is unavailable for this task. "
                    f"Use one of: {', '.join(active_tool_names)}"
                )
                yield {"type": "tool_result", "name": canonical_tool_name, "result": unavailable_result[:2500]}
                tool_log.append({"name": canonical_tool_name, "args": tool_args, "result": unavailable_result[:500]})
                messages.append({"role": "assistant", "content": full_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your last tool call used an unavailable tool.\n\n"
                            f"Tool: {canonical_tool_name}\n"
                            f"Available tools: {', '.join(active_tool_names)}\n\n"
                            "Re-emit exactly one valid tool call now. "
                            "Do not use delete_file unless the user explicitly asked to delete a file."
                        ),
                    }
                )
                continue

            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            result = await run_sync_agent_call(_execute_tool, tool_name, tool_args, deps)
            blocked = _blocked_tool_event(
                tool_name,
                tool_args,
                str(result),
                workspace_id=workspace_id,
                session_id=session_id,
                workspace_path=workspace_path,
            )
            if tool_name in ("write_file", "edit_file") and not blocked and not str(result).startswith("ERROR:"):
                wrote_files = True
            yield {
                "type": "tool_result",
                "name": tool_name,
                "result": result[:2500],
                "evidence_source": _tool_evidence_source(tool_name, str(result)),
            }

            tool_log.append({"name": tool_name, "args": tool_args, "result": str(result)[:500]})

            if str(result).startswith("ERROR: Bad arguments for") and tool_arg_repair_attempts < 1:
                tool_arg_repair_attempts += 1
                messages.append({"role": "assistant", "content": full_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your last tool call failed due to malformed or missing arguments.\n\n"
                            f"Tool: {tool_name}\n"
                            f"Error: {result[:2000]}\n\n"
                            "Re-emit exactly one corrected tool call now.\n"
                            "Output only:\n"
                            f"ACTION: {tool_name}\n"
                            "ARGS: {valid JSON object}\n"
                            "Do not include explanation, thinking, or ANSWER."
                        ),
                    }
                )
                continue

            repair_prompt = None
            if blocked and blocked_tool_repair_attempts < 1:
                repair_prompt = blocked_tool_retry_prompt(tool_name, tool_args, str(result))
            if repair_prompt:
                blocked_tool_repair_attempts += 1
                yield {
                    "type": "thinking",
                    "chunk": "⚠️ Rewriting the blocked shell command to use `cwd` and retrying.\n",
                }
                messages.append({"role": "assistant", "content": full_text})
                messages.append({"role": "user", "content": repair_prompt})
                continue

            if blocked:
                messages.append({"role": "assistant", "content": full_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tool result for {tool_name}:\n{result[:4000]}\n\n"
                            "Approval is required for that action. Stop now and wait for the user to "
                            "approve or deny it. Do not assume the action ran."
                        ),
                    }
                )
                if _ss and session_id:
                    _ss.save(
                        session_id=session_id,
                        task=user_message[:300],
                        messages=messages,
                        iteration=iteration,
                        tool_log=tool_log,
                        status="approval_required",
                        project_name=project_name,
                        backend=backend or ("cli" if use_cli else ("api" if use_api else "ollama")),
                        metadata=_session_metadata({k: v for k, v in blocked.items() if k != "type"}),
                    )
                yield blocked
                return

            messages.append({"role": "assistant", "content": full_text})
            followup_text = _tool_followup_message(
                tool_name,
                result,
                active_tool_names=active_tool_names,
                workspace_path=workspace_path,
            )
            # Inject screenshot image into vision context for the LLM
            screenshot_path = extract_screenshot_path(str(result)) if is_screenshot_result(str(result)) else None
            if screenshot_path:
                messages.append(
                    build_vision_tool_message(
                        followup_text,
                        screenshot_path,
                        use_api=use_api,
                        use_cli=use_cli,
                    )
                )
            else:
                messages.append({"role": "user", "content": followup_text})

            _ctx_chars = sum(len(str(message.get("content", ""))) for message in messages)
            _ctx_limit = 128_000
            _ctx_pct = min(100, int(_ctx_chars * 100 / _ctx_limit))
            yield {
                "type": "context_usage",
                "chars": _ctx_chars,
                "pct": _ctx_pct,
                "iteration": iteration + 1,
                "max_iterations": max_iterations,
            }

            if context_compact and _ctx_pct >= 50 and len(messages) > 8:
                system_msgs = [message for message in messages if message.get("role") == "system"]
                non_system = [message for message in messages if message.get("role") != "system"]
                recent_msgs = non_system[-6:]
                old_msgs = non_system[:-6]
                summary_lines: list[str] = []
                idx = 0
                while idx < len(old_msgs) - 1:
                    if old_msgs[idx].get("role") == "assistant" and old_msgs[idx + 1].get("role") == "user":
                        content = str(old_msgs[idx + 1].get("content", ""))
                        if content.startswith("Tool result for "):
                            colon = content.find(":")
                            tool_label = content[16:colon].strip() if colon > 16 else "tool"
                            preview = content[colon + 1 : colon + 80].strip().replace("\n", " ")
                            summary_lines.append(f"- {tool_label}: {preview}")
                        idx += 2
                    else:
                        idx += 1
                if summary_lines:
                    compact_note = "Prior tool results (compacted):\n" + "\n".join(summary_lines[:12])
                    messages = (
                        system_msgs
                        + [{"role": "user", "content": compact_note}]
                        + [{"role": "assistant", "content": "Understood. Resuming task."}]
                        + recent_msgs
                    )
                    yield {
                        "type": "thinking",
                        "chunk": f"📦 Context compacted ({_ctx_pct}% full) — continuing…\n",
                    }

            if _ss and session_id:
                _ss.save(
                    session_id=session_id,
                    task=user_message[:300],
                    messages=messages,
                    iteration=iteration,
                    tool_log=tool_log,
                    status="active",
                    project_name=project_name,
                    backend=backend or ("cli" if use_cli else ("api" if use_api else "ollama")),
                    metadata=_session_metadata(),
                )

        elif answer_match:
            answer = _guard_unverified_edit_claim(
                answer_match.group(1).strip(),
                wrote_files=wrote_files,
                tool_log=tool_log,
            )
            if not answer or answer == "your response here":
                yield {"type": "text", "chunk": "\n⚠️ Axon could not form a clean answer. Please retry the task."}
                break
            if _needs_evidence_section_repair(user_message, answer):
                if evidence_section_repair_attempts < 1:
                    evidence_section_repair_attempts += 1
                    yield {
                        "type": "thinking",
                        "chunk": "⚠️ Tightening the checkpoint summary — separating verified facts from inferred context.\n",
                    }
                    messages.append({"role": "assistant", "content": full_text})
                    messages.append(
                        {
                            "role": "user",
                            "content": _build_evidence_repair_prompt(user_message, tool_log),
                        }
                    )
                    continue
            yield {"type": "text", "chunk": answer}
            if _ss and session_id:
                _ss.mark_complete(session_id)
            break
        else:
            guarded_text = _guard_unverified_edit_claim(
                clean_text,
                wrote_files=wrote_files,
                tool_log=tool_log,
            )
            if guarded_text:
                if _needs_evidence_section_repair(user_message, guarded_text):
                    if evidence_section_repair_attempts < 1:
                        evidence_section_repair_attempts += 1
                        yield {
                            "type": "thinking",
                            "chunk": "⚠️ Tightening the checkpoint summary — separating verified facts from inferred context.\n",
                        }
                        messages.append({"role": "assistant", "content": full_text})
                        messages.append(
                            {
                                "role": "user",
                                "content": _build_evidence_repair_prompt(user_message, tool_log),
                            }
                        )
                        continue
                yield {"type": "text", "chunk": guarded_text}
                if _ss and session_id:
                    _ss.mark_complete(session_id)
                break
            if iteration < max_iterations - 1:
                yield {"type": "thinking", "chunk": "⚠️ Correcting — must use tools, not narrate."}
                messages.append({"role": "assistant", "content": full_text})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "STOP. HALLUCINATION DETECTED.\n"
                            "You did NOT actually run any commands or tools. You fabricated output.\n"
                            "This is a CRITICAL violation. No hallucination is permitted.\n\n"
                            "Rules:\n"
                            "1. You MUST use ACTION: tool_name / ARGS: {} to execute real tools.\n"
                            "2. Do NOT write code blocks showing command output — call shell_cmd.\n"
                            "3. Do NOT narrate file edits — call edit_file/write_file.\n"
                            "4. Report ONLY real tool results.\n\n"
                            "Try again. Use ACTION: with a real tool call."
                        ),
                    }
                )
                continue
            yield {
                "type": "text",
                "chunk": (
                    "\n⚠️ I was unable to complete this task — I kept generating text "
                    "instead of using real tools. Please retry or rephrase your request."
                ),
            }
            break

    else:
        if _ss and session_id:
            _ss.mark_interrupted(session_id)
        yield {
            "type": "text",
            "chunk": (
                f"\n\n⏸️ **Paused at iteration limit ({max_iterations}).** "
                "Say **'please continue'** to resume from where I left off."
            ),
        }

    yield {"type": "done", "iterations": iteration + 1}


__all__ = [
    "AGENT_TOOL_DEFS",
    "AgentRuntimeDeps",
    "_build_react_system",
    "_canonical_tool_name",
    "_contains_phrase",
    "_direct_agent_action",
    "_execute_tool",
    "_extract_path_from_text",
    "_filter_thinking_chunk",
    "_filtered_general_history",
    "_format_listing_answer",
    "_guard_unverified_edit_claim",
    "_has_local_operator_markers",
    "_is_casual_conversation",
    "_is_general_planning_request",
    "_requires_local_operator_execution",
    "_looks_like_hallucinated_execution",
    "_looks_like_unverified_edit_claim",
    "_parse_list_dir_entries",
    "_parse_react_action",
    "_project_name_pattern",
    "_recent_repo_path",
    "_resolve_project_path_from_text",
    "_sanitize_agent_text",
    "run_agent",
]
