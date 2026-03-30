"""Agent orchestration core extracted from brain.py.

This module keeps the ReAct-style agent loop isolated from the helper surfaces
that now live in dedicated axon_core modules.
"""

from __future__ import annotations

import asyncio
import re as _re
from typing import Any, AsyncGenerator, Optional

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
from .agent_intent import (
    _contains_phrase,
    _filtered_general_history,
    _has_local_operator_markers,
    _is_casual_conversation,
    _is_general_planning_request,
    _requires_local_operator_execution,
)
from .agent_output import (
    _filter_thinking_chunk,
    _guard_unverified_edit_claim,
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
    backend: str = "",
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

    if _ss and is_resume_request(user_message):
        prev = _ss.get_interrupted(max_age_hours=4.0)
        if prev:
            if not prev.tool_log:
                _ss.mark_complete(prev.session_id)
                yield {
                    "type": "text",
                    "chunk": (
                        "⚠️ The previous session had no verified tool actions — "
                        "discarding it to avoid repeating a hallucinated response.\n\n"
                        "Please re-state your task and I'll execute it properly with real tools."
                    ),
                }
                yield {"type": "done", "iterations": 0}
                return
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
            user_message = prev.task

    active_tool_names = list(deps.tool_registry.keys()) if tools is None else [
        tool_name for tool_name in tools if tool_name in deps.tool_registry
    ]
    wrote_files = False

    use_api = bool(api_key and api_base_url)
    use_cli = backend == "cli"
    resolved_cli = deps.find_cli(cli_path) if use_cli else ""

    if not force_tool_mode and not _resuming and _is_casual_conversation(user_message):
        casual_system = (
            "You are Axon — a sharp, friendly AI copilot embedded in the user's local developer OS.\n"
            "The user is making casual conversation. Reply naturally and warmly, like a capable colleague.\n"
            "Be brief (2-4 sentences max). Mention what you can help with if relevant, but keep it conversational.\n"
            "Do NOT use tools, do NOT list files, do NOT run commands, do NOT produce reports."
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": casual_system}]
        messages.extend(_filtered_general_history(history, db_path=deps.db_path))
        messages.append({"role": "user", "content": user_message})
        if use_cli:
            async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=300):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            async for chunk in deps.stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=300,
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

    if not force_tool_mode and not _resuming and _is_general_planning_request(user_message):
        system = (
            "You are Axon, a calm and practical AI operator.\n"
            "This request is a general planning or writing task, not a local tool task.\n"
            "Do not use tools. Do not inspect files or directories unless the user explicitly asks for local data.\n"
            "Answer directly with a clear structure, a concise draft, and 2-4 helpful next-step options."
        )
        if resource_context:
            system += f"\n\nUse these attached resources when they are relevant:\n{resource_context[:5000]}"
        messages = [{"role": "system", "content": system}]
        messages.extend(_filtered_general_history(history, db_path=deps.db_path))
        messages.append({"role": "user", "content": user_message})

        if use_cli:
            async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=1200):
                yield {"type": "text", "chunk": chunk}
        elif use_api:
            async for chunk in deps.stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=1200,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            execution = await asyncio.to_thread(
                deps.ollama_execution_profile_sync,
                vision_model or ollama_model or deps.ollama_default_model,
                ollama_url,
                streaming=True,
                purpose="chat",
            )
            messages[-1] = deps.ollama_message_with_images(user_message, resource_image_paths)
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

    if not _resuming:
        direct_action = _direct_agent_action(
            user_message,
            history=history,
            project_name=project_name,
            workspace_path=workspace_path,
            deps=deps,
        )
        if direct_action:
            tool_name, tool_args, result, answer = direct_action
            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            yield {"type": "tool_result", "name": tool_name, "result": result[:4000]}
            yield {"type": "text", "chunk": answer}
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
            messages.append({"role": "user", "content": user_message})
        execution = None
    elif use_api:
        if _need_user_append:
            messages.append({"role": "user", "content": user_message})
        execution = None
    else:
        execution = await asyncio.to_thread(
            deps.ollama_execution_profile_sync,
            vision_model or ollama_model or deps.ollama_agent_model,
            ollama_url,
            streaming=True,
            purpose="agent",
        )
        if _need_user_append:
            messages.append(deps.ollama_message_with_images(user_message, resource_image_paths))

    iteration = 0
    for iteration in range(max_iterations):
        full_text = ""
        streamed_up_to = 0
        found_action_live = False
        try:

            async def _token_source() -> AsyncGenerator[str, None]:
                if use_cli:
                    async for chunk in deps.stream_cli(messages, cli_path=resolved_cli, max_tokens=4096):
                        yield chunk
                elif use_api:
                    async for chunk in deps.stream_api_chat(
                        messages=messages,
                        api_key=api_key,
                        api_base_url=api_base_url,
                        api_model=api_model,
                        max_tokens=2400,
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
                        safe_end = max(streamed_up_to, len(full_text) - 10)
                        new_text = _filter_thinking_chunk(full_text[streamed_up_to:safe_end], strip=False)
                        if new_text.strip():
                            yield {"type": "thinking", "chunk": new_text}
                            streamed_up_to = safe_end

        except Exception as exc:
            provider_label = api_provider or ("CLI" if use_cli else ("API" if use_api else "Ollama"))
            yield {"type": "text", "chunk": f"\n⚠️ {provider_label} error: {exc}"}
            break

        if not full_text.strip():
            yield {"type": "text", "chunk": "\n⚠️ Empty response from model."}
            break

        action = _parse_react_action(full_text)
        answer_match = _re.search(r"ANSWER:\s*([\s\S]+)", full_text)
        clean_text = _sanitize_agent_text(full_text)

        if action:
            tool_name, tool_args = action
            if not found_action_live:
                think_text = full_text[: full_text.find("ACTION:")].strip()
                think_text = _filter_thinking_chunk(_sanitize_agent_text(think_text))
                if think_text:
                    yield {"type": "thinking", "chunk": think_text}

            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            result = await asyncio.to_thread(_execute_tool, tool_name, tool_args, deps)
            if tool_name in ("write_file", "edit_file") and not str(result).startswith("ERROR:"):
                wrote_files = True
            yield {"type": "tool_result", "name": tool_name, "result": result[:4000]}

            messages.append({"role": "assistant", "content": full_text})
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool_name}:\n{result[:4000]}\n\nContinue.",
                }
            )

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

            if context_compact and _ctx_pct >= 70 and len(messages) > 8:
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

            tool_log.append({"name": tool_name, "args": tool_args, "result": str(result)[:500]})
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
                yield {"type": "text", "chunk": guarded_text}
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
