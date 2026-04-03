"""
Axon — AI Brain
Supports three runtime paths:
  1. Ollama (local)      — runs on your machine, no internet needed
  2. CLI agent bridge    — uses a locally installed Claude-compatible CLI
  3. External API        — current cloud adapter path, API-key backed

Set ai_backend = 'api' | 'cli' | 'ollama' in Settings.
"""

import os
import asyncio
import subprocess
import shlex
import json
import base64
import mimetypes
import sqlite3
import hashlib
import time
import threading
import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional, AsyncGenerator
import re as _re
import anthropic
import httpx
import gpu_guard
import resource_bank
from axon_data.sqlite_utils import managed_connection
from axon_core.cli_command import build_cli_command, build_codex_exec_command
from axon_core.cli_pacing import cli_cooldown_remaining, current_cli_cooldown, note_cli_cooldown, wait_for_cli_slot
from axon_core.chat_context import select_history_for_chat
from axon_core.approval_actions import (
    AUTONOMY_PROFILES,
    autonomy_profile_allows,
    build_command_approval_action,
    build_edit_approval_action,
)
from axon_core.agent import (
    AGENT_TOOL_DEFS as AGENT_TOOL_DEFS_CORE,
    AgentRuntimeDeps,
    _build_react_system,
    _execute_tool as _execute_tool_core,
    _filtered_general_history,
    _guard_unverified_edit_claim,
    _is_casual_conversation,
    _is_general_planning_request,
    _requires_local_operator_execution,
    _direct_agent_action as _direct_agent_action_core,
    run_agent as _run_agent_core,
)

# ─── Load .env (fallback API keys) ───────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

_log = logging.getLogger("axon.brain")

# ─── Session usage tracker ───────────────────────────────────────────────────

_session_usage: dict = {
    "tokens": 0, "cost_usd": 0.0, "calls": 0,
    "cli_calls": 0, "api_calls": 0, "ollama_calls": 0,
}
_ACTIVE_AGENT_RUNTIME_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "axon_active_agent_runtime_context",
    default={},
)


def get_session_usage() -> dict:
    return dict(_session_usage)


def reset_session_usage():
    _session_usage.update({"tokens": 0, "cost_usd": 0.0, "calls": 0, "cli_calls": 0, "api_calls": 0, "ollama_calls": 0})


def _track_usage(tokens: int, cost_usd: float = 0.0, backend: str = "api"):
    _session_usage["tokens"] += tokens
    _session_usage["cost_usd"] += cost_usd
    _session_usage["calls"] += 1
    if backend == "cli":
        _session_usage["cli_calls"] += 1
    elif backend == "ollama":
        _session_usage["ollama_calls"] += 1
    else:
        _session_usage["api_calls"] += 1

# ─── Models ──────────────────────────────────────────────────────────────────

FAST_MODEL    = "claude-haiku-4-5"       # quick responses, summaries
BALANCED_MODEL = "claude-sonnet-4-5"     # detailed analysis, digest
PREMIUM_MODEL  = "claude-opus-4-5"       # complex multi-project reasoning

MAX_TOKENS_CHAT   = 1500
MAX_TOKENS_DIGEST = 2000
MAX_TOKENS_TASK   = 800
_CLI_RATE_LIMIT_COOLDOWN_SECONDS = 300

# Default CLI-compatible paths (auto-detected)
_DEFAULT_CLAUDE_CLI_PATHS = [
    "/home/edp/.config/Claude/claude-code/2.1.63/claude",
    "/home/edp/.vscode/extensions/anthropic.claude-code-2.1.81-linux-x64/resources/native-binary/claude",
    "/usr/local/bin/claude",
    "/usr/bin/claude",
    "claude",
]

_DEFAULT_CODEX_CLI_PATHS = [
    "/usr/local/bin/codex",
    "/usr/bin/codex",
    "codex",
]

_CLAUDE_CLI_MODEL_OPTIONS = [
    {"id": "", "label": "Claude default", "description": "Use the CLI default model alias."},
    {"id": "sonnet", "label": "Sonnet", "description": "Latest Sonnet alias."},
    {"id": "opus", "label": "Opus", "description": "Latest Opus alias."},
    {"id": "haiku", "label": "Haiku", "description": "Latest Haiku alias."},
    {"id": "claude-sonnet-4-6", "label": "claude-sonnet-4-6", "description": "Pinned Sonnet release."},
    {"id": "claude-opus-4-5", "label": "claude-opus-4-5", "description": "Pinned Opus release."},
    {"id": "claude-haiku-4-5", "label": "claude-haiku-4-5", "description": "Pinned Haiku release."},
]

_CODEX_CLI_MODEL_OPTIONS = [
    {
        "id": "",
        "label": "Codex default",
        "description": "Use the Codex CLI default model. ChatGPT-backed Codex currently defaults to GPT-5.1-Codex-Max.",
    },
    {
        "id": "gpt-5.4",
        "label": "gpt-5.4",
        "description": "Verified working with this installed Codex CLI account.",
    },
    {
        "id": "gpt-5.1-codex-max",
        "label": "gpt-5.1-codex-max",
        "description": "Current default long-running Codex model supported by Codex CLI.",
    },
    {
        "id": "gpt-5.1-codex-mini",
        "label": "gpt-5.1-codex-mini",
        "description": "Smaller Codex model currently supported by Codex CLI.",
    },
]

_CODEX_SELF_HEAL_MODEL = "gpt-5.4"
_CODEX_CLI_MIN_INTERVAL_SECONDS = 1.0
_CODEX_CLI_CALL_TIMEOUT_SECONDS = 90
_CLI_SUBPROCESS_STREAM_LIMIT_BYTES = 1024 * 1024


OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:7b"         # general chat default
OLLAMA_FAST_MODEL = "qwen2.5:1.5b"          # quick tasks
OLLAMA_AGENT_MODEL = "qwen2.5:7b"           # tool-calling / agent loops
DEVBRAIN_DB_PATH = Path.home() / ".devbrain" / "devbrain.db"


def _ollama_execution_profile_sync(
    model: str = "",
    ollama_url: str = "",
    *,
    streaming: bool = False,
    purpose: str = "chat",
) -> dict:
    requested_model = model or (OLLAMA_AGENT_MODEL if purpose == "agent" else OLLAMA_DEFAULT_MODEL)
    profile = gpu_guard.detect_display_gpu_state()
    selection = {
        "model": requested_model,
        "changed": False,
        "note": "",
        "profile": profile,
        "safety": gpu_guard.ollama_model_safety(requested_model, profile),
    }

    if selection["safety"].get("risky"):
        available_models = _ollama_list_models_sync(ollama_url)
        selection = gpu_guard.pick_safe_model(
            requested_model,
            available_models,
            profile=profile,
            purpose=purpose,
        )

    num_ctx = 4096 if streaming else 2048
    preferred_num_ctx = selection["safety"].get("preferred_num_ctx")
    if preferred_num_ctx:
        num_ctx = min(num_ctx, preferred_num_ctx)
    selection["num_ctx"] = num_ctx
    if not selection.get("model"):
        selection["model"] = requested_model
    return selection


def _get_client(api_key: str, api_base_url: str = "") -> anthropic.Anthropic:
    kwargs = {"api_key": api_key}
    if api_base_url:
        base_url = str(api_base_url).strip().rstrip("/")
        # Anthropic's SDK adds `/v1/...` paths internally, so Axon's normalized
        # provider URL must be trimmed back to the API root before we pass it in.
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _coerce_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if text:
            return str(text)
    return ""


def _cli_runtime_family(path: str = "") -> str:
    candidate = os.path.basename(str(path or "")).strip().lower()
    if "codex" in candidate:
        return "codex"
    return "claude"


def _runtime_label_for_cli_family(family: str) -> str:
    return "Codex CLI" if family == "codex" else "Claude CLI"


def _cli_runtime_key(path: str = "") -> str:
    binary = os.path.realpath(str(path or "").strip()) if path else ""
    family = _cli_runtime_family(binary)
    return f"{family}:{binary}" if binary else family


def _api_provider_label(provider_id: str = "") -> str:
    return (provider_id or "configured API").replace("_", " ").strip().title()


def _is_rate_limited_message(message: str) -> bool:
    lower = str(message or "").lower()
    return any(token in lower for token in (
        "rate limit", "rate_limit", "hit your limit", "usage limit",
        "hit your usage limit", "try again at", "get more access",
    ))


def available_cli_models(cli_path: str = "") -> list[dict[str, str]]:
    binary = _resolve_selected_cli_binary(cli_path)
    options = _CODEX_CLI_MODEL_OPTIONS if _cli_runtime_family(binary) == "codex" else _CLAUDE_CLI_MODEL_OPTIONS
    return [dict(item) for item in options]


def normalize_cli_model(cli_path: str = "", model: str = "") -> str:
    requested = str(model or "").strip()
    if not requested:
        return ""
    binary = _resolve_selected_cli_binary(cli_path)
    if _cli_runtime_family(binary) != "codex":
        return requested
    supported_ids = {str(item.get("id") or "").strip() for item in _CODEX_CLI_MODEL_OPTIONS}
    return requested if requested in supported_ids else ""


def _is_cli_rate_limit_message(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return any(token in lower for token in ("rate limit", "rate_limit", "hit your limit"))


def _is_cli_chunk_limit_message(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return (
        "chunk is longer than limit" in lower
        or "limitoverrunerror" in lower
        or ("separator is found" in lower and "limit" in lower)
    )


def _is_codex_fatal_error_message(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return any(
        token in lower for token in (
            "rate limit",
            "hit your usage limit",
            "hit your limit",
            "not authenticated",
            "login required",
            "logged out",
            "authentication",
            "subscription",
        )
    )


def _is_claude_recoverable_problem_message(message: str) -> bool:
    lower = str(message or "").strip().lower()
    return any(
        token in lower for token in (
            "rate limit",
            "rate_limit",
            "hit your limit",
            "not authenticated",
            "not signed in",
            "login required",
            "sign in",
            "logged out",
            "authentication",
            "subscription",
        )
    )


def _codex_retry_attempt(message: str) -> int:
    match = _re.search(r"reconnecting\.\.\.\s+(\d+)/(\d+)", str(message or ""), _re.IGNORECASE)
    if not match:
        return 0
    try:
        return int(match.group(1) or 0)
    except Exception:
        return 0


def _resolve_cli_runtime_fallback(
    *,
    api_key: str = "",
    api_provider: str = "",
    api_base_url: str = "",
    api_model: str = "",
    cli_path: str = "",
    ollama_url: str = "",
    ollama_model: str = "",
) -> tuple[str, str]:
    selected_binary = _resolve_selected_cli_binary(cli_path)
    if _cli_runtime_family(selected_binary) != "claude":
        return "cli", ""

    cooldown = current_cli_cooldown(key=_cli_runtime_key(selected_binary))
    if not cooldown.get("active"):
        return "cli", ""

    wait_seconds = max(1, int(cooldown.get("remaining_seconds") or 0))
    fallback_binary = _find_codex_cli()
    if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(selected_binary):
        return (
            "cli",
            (
                f"Claude CLI is cooling down after a rate limit ({wait_seconds}s remaining). "
                f"Switching this turn to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`)."
            ),
        )

    provider_label = _api_provider_label(api_provider)
    if api_key and api_base_url:
        model_label = api_model or "configured model"
        return (
            "api",
            (
                f"Claude CLI is cooling down after a rate limit ({wait_seconds}s remaining). "
                f"Switching this turn to {provider_label} (`{model_label}`)."
            ),
        )

    ollama_label = (ollama_model or OLLAMA_AGENT_MODEL or OLLAMA_DEFAULT_MODEL).strip()
    if ollama_url or ollama_model:
        return (
            "ollama",
            (
                f"Claude CLI is cooling down after a rate limit ({wait_seconds}s remaining). "
                f"Switching this turn to Local Ollama (`{ollama_label or 'saved default'}`)."
            ),
        )

    return (
        "cli",
        str(
            cooldown.get("message")
            or (
                f"Claude CLI is cooling down after a rate limit ({wait_seconds}s remaining). "
                f"Switching this turn to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`) when it is available."
            )
        ),
    )

    return "cli", ""


def _current_agent_runtime_context() -> dict[str, Any]:
    return dict(_ACTIVE_AGENT_RUNTIME_CONTEXT.get() or {})


def _update_agent_runtime_context(**updates: Any) -> None:
    current = _current_agent_runtime_context()
    current.update({key: value for key, value in updates.items() if value is not None})
    _ACTIVE_AGENT_RUNTIME_CONTEXT.set(current)


def _cli_image_source_from_path(path: str) -> dict[str, Any] | None:
    if not path or not os.path.isfile(path):
        return None
    mime_type, _ = mimetypes.guess_type(path)
    if not mime_type or not mime_type.startswith("image/"):
        return None
    try:
        with open(path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode("ascii")
    except Exception:
        return None
    if not data:
        return None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": data,
        },
    }


def _cli_message_with_images(content: str, image_paths: Optional[list[str]] = None) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for image_path in image_paths or []:
        image_source = _cli_image_source_from_path(image_path)
        if image_source:
            blocks.append(image_source)
    text = str(content or "")
    if text or not blocks:
        blocks.append({"type": "text", "text": text})
    return {"role": "user", "content": blocks}


def _cli_stream_input_event(messages: list[dict]) -> dict[str, Any]:
    system_parts: list[str] = []
    transcript_parts: list[str] = []
    final_blocks: list[dict[str, Any]] = []

    if not messages:
        return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": ""}]}}

    leading_messages = messages[:-1]
    final_message = messages[-1]
    if final_message.get("role") != "user":
        leading_messages = messages
        final_message = {"role": "user", "content": ""}

    for message in leading_messages:
        role = message.get("role", "user")
        text = _coerce_text_content(message.get("content", "")).strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            transcript_parts.append(f"Assistant: {text}")
        else:
            transcript_parts.append(f"Human: {text}")

    preamble_parts: list[str] = []
    if system_parts:
        preamble_parts.append(f"<system>\n{'\n\n'.join(system_parts)}\n</system>")
    if transcript_parts:
        preamble_parts.append("\n".join(transcript_parts))
    preamble = "\n\n".join(part for part in preamble_parts if part).strip()
    if preamble:
        final_blocks.append({"type": "text", "text": preamble})

    final_content = final_message.get("content", "")
    if isinstance(final_content, list):
        for block in final_content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").lower()
            if block_type == "text":
                text = str(block.get("text") or "")
                if text:
                    final_blocks.append({"type": "text", "text": text})
            elif block_type == "image":
                source = block.get("source")
                if not isinstance(source, dict):
                    continue
                source_type = str(source.get("type") or "").lower()
                media_type = str(source.get("media_type") or "")
                data = str(source.get("data") or "")
                if source_type == "base64" and media_type.startswith("image/") and data:
                    final_blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        }
                    )
    else:
        text = _coerce_text_content(final_content).strip()
        if text:
            final_blocks.append({"type": "text", "text": text})

    if not final_blocks:
        final_blocks.append({"type": "text", "text": ""})

    return {"type": "user", "message": {"role": "user", "content": final_blocks}}


def _cli_prompt_from_messages(
    messages: list[dict],
    *,
    disallow_native_tools: bool = False,
) -> str:
    system_parts: list[str] = []
    transcript_parts: list[str] = []

    if disallow_native_tools:
        system_parts.append(
            "You are running inside Axon's orchestrator. "
            "Do not use your own shell, file, git, browser, web, or MCP tools. "
            "Do not inspect the workspace directly. "
            "Only respond with the plain-text protocol requested by the prompt."
        )

    for message in messages:
        role = str(message.get("role") or "user")
        text = _coerce_text_content(message.get("content", "")).strip()
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
        elif role == "assistant":
            transcript_parts.append(f"Assistant: {text}")
        else:
            transcript_parts.append(f"User: {text}")

    sections: list[str] = []
    if system_parts:
        sections.append(f"<system>\n{'\n\n'.join(system_parts)}\n</system>")
    if transcript_parts:
        sections.append("\n\n".join(transcript_parts))
    return "\n\n".join(section for section in sections if section).strip()


async def _call_api_messages(
    messages: list[dict],
    *,
    system: str = "",
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    max_tokens: int = MAX_TOKENS_CHAT,
) -> tuple[str, int]:
    if not api_key:
        raise ValueError("External API key not set. Go to Settings → Runtime.")

    provider = (api_provider or "anthropic").strip().lower()

    if provider == "anthropic":
        client = _get_client(api_key, api_base_url=api_base_url)

        def _anthropic_request():
            return client.messages.create(
                model=api_model or BALANCED_MODEL,
                max_tokens=max_tokens,
                system=system or SYSTEM_PROMPT,
                messages=messages,
            )

        resp = await asyncio.to_thread(_anthropic_request)
        tokens = resp.usage.input_tokens + resp.usage.output_tokens
        _track_usage(tokens, backend="api")
        return resp.content[0].text, tokens

    if provider in {"openai_gpts", "generic_api", "deepseek"}:
        model_name = (api_model or "").strip()
        if not model_name:
            raise ValueError("API model not set. Configure it in Settings → Cloud Agents.")
        base = (api_base_url or "").rstrip("/")
        if not base:
            raise ValueError("API base URL not set. Configure it in Settings → Cloud Agents.")
        payload = {
            "model": model_name,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            if resp.status_code >= 400 and "max_completion_tokens" in resp.text:
                retry_payload = dict(payload)
                retry_payload.pop("max_tokens", None)
                retry_payload["max_completion_tokens"] = max_tokens
                resp = await client.post(f"{base}/chat/completions", headers=headers, json=retry_payload)
            resp.raise_for_status()
            data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        content = _coerce_text_content(message.get("content"))
        usage = data.get("usage", {}) or {}
        tokens = usage.get("total_tokens") or (
            usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        )
        _track_usage(tokens, backend="api")
        return content, int(tokens or 0)

    if provider == "gemini_gems":
        model_name = (api_model or "gemini-2.5-flash").strip()
        base = (api_base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        target = model_name if model_name.startswith("models/") else f"models/{model_name}"
        payload = {
            "contents": messages,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        gemini_contents = []
        for msg in messages:
            role = "model" if msg.get("role") == "assistant" else "user"
            gemini_contents.append({
                "role": role,
                "parts": [{"text": msg.get("content", "")}],
            })
        payload["contents"] = gemini_contents
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{base}/{target}:generateContent",
                params={"key": api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates") or []
        parts = []
        if candidates:
            content = (candidates[0].get("content") or {}).get("parts") or []
            parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("text")]
        usage = data.get("usageMetadata", {}) or {}
        tokens = usage.get("totalTokenCount") or (
            usage.get("promptTokenCount", 0) + usage.get("candidatesTokenCount", 0)
        )
        _track_usage(tokens, backend="api")
        return "".join(parts), int(tokens or 0)

    raise ValueError(f"Unsupported API provider: {api_provider}")


def _call_ollama_sync(
    prompt: str,
    system: str = "",
    model: str = "",
    max_tokens: int = 1500,
    ollama_url: str = "",
) -> tuple[str, int]:
    """
    Synchronous Ollama HTTP call — runs in a thread to avoid blocking the event loop.
    """
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    base = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
    execution = _ollama_execution_profile_sync(model, ollama_url, streaming=False, purpose="chat")
    chosen_model = execution["model"]

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": chosen_model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": execution["num_ctx"],
            "num_gpu": 0,   # force CPU
        },
    }).encode()

    req = _urlreq.Request(
        f"{base}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with _urlreq.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            break
        except (_urlerr.URLError, OSError, TimeoutError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    else:
        raise RuntimeError(
            f"Ollama not reachable at {base} after 3 attempts. Start it with: ollama serve\n{last_exc}"
        )

    content = data.get("message", {}).get("content", "")
    tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
    _track_usage(tokens, backend="ollama")
    return content, tokens


async def _call_ollama(
    prompt: str,
    system: str = "",
    model: str = "",
    max_tokens: int = 1500,
    ollama_url: str = "",
) -> tuple[str, int]:
    """
    Call a local Ollama model via its HTTP API.
    Runs in a thread pool to avoid blocking the async event loop.
    """
    return await asyncio.to_thread(
        _call_ollama_sync, prompt, system, model, max_tokens, ollama_url
    )


async def _stream_ollama_chat(
    messages: list[dict],
    model: str = "",
    max_tokens: int = 1500,
    ollama_url: str = "",
    purpose: str = "chat",
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from a streaming Ollama /api/chat call."""
    base = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
    execution = await asyncio.to_thread(
        _ollama_execution_profile_sync,
        model,
        ollama_url,
        streaming=True,
        purpose=purpose,
    )
    chosen_model = execution["model"]
    payload = {
        "model": chosen_model,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": max_tokens,
            "num_ctx": execution["num_ctx"],
            "num_gpu": 0,   # force CPU — GPU causes freezes on low-VRAM machines
        },
    }
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done"):
                            return
            return  # stream completed successfully
        except (httpx.RequestError, httpx.HTTPStatusError, OSError) as exc:
            last_exc = exc
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Ollama not reachable at {base} after 3 attempts: {last_exc}")


async def _stream_api_chat(
    messages: list[dict],
    api_key: str,
    api_base_url: str = "",
    api_model: str = "",
    max_tokens: int = 1500,
    api_provider: str = "",
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from the configured external API."""
    provider = (api_provider or "generic_api").strip().lower()

    if provider not in {"openai_gpts", "generic_api", "deepseek"}:
        system_parts: list[str] = []
        normalized_messages: list[dict] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            content = _coerce_text_content(message.get("content"))
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            normalized_messages.append({"role": role or "user", "content": content})
        content, _ = await _call_api_messages(
            normalized_messages,
            system="\n\n".join(part for part in system_parts if part).strip(),
            api_key=api_key,
            api_provider=provider,
            api_base_url=api_base_url,
            api_model=api_model,
            max_tokens=max_tokens,
        )
        if content:
            yield content
        return

    base = (api_base_url or "https://api.deepseek.com").rstrip("/")
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1" if "/v1" not in base else base
    model = api_model or "deepseek-reasoner"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Models known to NOT support vision — strip image_url blocks
    _text_only_models = {"deepseek-reasoner", "deepseek-coder"}
    if any(m in model.lower() for m in _text_only_models):
        clean_messages = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                clean_messages.append({**msg, "content": " ".join(text_parts)})
            else:
                clean_messages.append(msg)
        messages = clean_messages

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", f"{base}/chat/completions", json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content


def _ollama_message_with_images(content: str, image_paths: list[str] | None = None) -> dict:
    message = {"role": "user", "content": content}
    encoded_images: list[str] = []
    for path in image_paths or []:
        try:
            encoded_images.append(resource_bank.encode_image_base64(path))
        except Exception:
            continue
    if encoded_images:
        message["images"] = encoded_images
    return message


def _api_message_with_images(content: str, image_paths: list[str] | None = None) -> dict:
    """Build an OpenAI-compatible multimodal user message with inline base64 images.

    For models that support vision (GPT-4o, Claude, Gemini), actual image data
    is embedded.  The caller should pass only valid local paths.
    """
    paths = [p for p in (image_paths or []) if p]
    if not paths:
        return {"role": "user", "content": content}
    parts: list[dict] = [{"type": "text", "text": content}]
    images_added = 0
    for path in paths:
        try:
            b64 = resource_bank.encode_image_base64(Path(path))
            mime = resource_bank.detect_mime_type(str(path)) or "image/png"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "auto"},
            })
            images_added += 1
        except Exception:
            continue
    if not images_added:
        return {"role": "user", "content": content}
    return {"role": "user", "content": parts}

async def stream_chat(
    user_message: str,
    history: list[dict],
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    workspace_path: str = "",
    backend: str = "ollama",
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    cli_path: str = "",
    cli_model: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> AsyncGenerator[str, None]:
    """Public async generator — yields chat response chunks across supported runtimes."""
    runtime = (backend or "ollama").strip().lower()
    runtime_notice = ""
    if runtime == "cli":
        runtime, runtime_notice = _resolve_cli_runtime_fallback(
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model,
            cli_path=cli_path,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )

    system = SYSTEM_PROMPT_OLLAMA if runtime == "ollama" else SYSTEM_PROMPT
    if _requires_local_operator_execution(user_message, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path):
        yield (
            "This request needs local tools. I did not create, edit, append, delete, "
            "or verify any local file, repo, or workspace state in this plain chat turn. "
            "Run it in Agent mode or let Axon auto-route it to the local operator."
        )
        return
    if _is_general_planning_request(user_message, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path):
        history = _filtered_general_history(history, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path)
        system += (
            "\n\nThis is a general planning, writing, or research task."
            "\nDo not assume repository or file context unless the user explicitly asks for local data."
            "\nRespond with a clear structure, a polished draft when useful, and concise next-step options."
        )
    if context_block:
        system += f"\n\n{context_block[:2000]}"
    if resource_context:
        system += f"\n\n{resource_context[:5000]}"
    if project_name:
        system += f"\n\nCurrently focused on workspace: **{project_name}**"

    selected_history = select_history_for_chat(
        user_message,
        history,
        backend=runtime,
        resource_image_paths=resource_image_paths,
    )

    messages: list[dict] = [{"role": "system", "content": system}]
    for h in selected_history:
        messages.append({"role": h["role"], "content": h["content"][:600]})

    if runtime_notice:
        yield f"⚠️ {runtime_notice}\n\n"

    if runtime == "cli":
        # Stream directly from the CLI binary — do NOT buffer via chat()
        cli_system = SYSTEM_PROMPT
        if _is_general_planning_request(user_message, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path):
            cli_system += (
                "\n\nThis is a general planning or writing task."
                "\nDo not inspect local files unless the user explicitly asks."
            )
        if context_block:
            cli_system += f"\n\n{context_block[:2000]}"
        if resource_context:
            cli_system += f"\n\n{resource_context[:3000]}"
        if project_name:
            cli_system += f"\n\nCurrently focused on workspace: **{project_name}**"
        cli_messages: list[dict] = [{"role": "system", "content": cli_system}]
        for h in selected_history:
            cli_messages.append({"role": h["role"], "content": h["content"][:600]})
        cli_messages.append(_cli_message_with_images(user_message, resource_image_paths))
        try:
            async for chunk in _stream_cli(
                cli_messages,
                cli_path=cli_path,
                max_tokens=1500,
                model=cli_model,
                allow_session_persistence=False,
            ):
                yield chunk
        except Exception as exc:
            if _is_cli_rate_limit_message(str(exc)):
                if api_key and api_base_url:
                    yield f"⚠️ Claude CLI hit a rate limit. Falling back to {_api_provider_label(api_provider)} (`{api_model or BALANCED_MODEL}`).\n\n"
                    api_messages = list(messages)
                    api_messages.append(_api_message_with_images(user_message, resource_image_paths))
                    if api_provider in {"openai_gpts", "generic_api", "deepseek"} and api_key:
                        async for chunk in _stream_api_chat(
                            messages=api_messages,
                            api_key=api_key,
                            api_base_url=api_base_url,
                            api_model=api_model or BALANCED_MODEL,
                            max_tokens=1500,
                            api_provider=api_provider,
                        ):
                            yield chunk
                    else:
                        content, _ = await _call_api_messages(
                            api_messages[1:],
                            system=system,
                            api_key=api_key,
                            api_provider=api_provider,
                            api_base_url=api_base_url,
                            api_model=api_model or BALANCED_MODEL,
                            max_tokens=1500,
                        )
                        yield content
                    return
                if ollama_model or ollama_url:
                    yield "⚠️ Claude CLI hit a rate limit. Falling back to Local Ollama.\n\n"
                    ollama_messages = list(messages)
                    ollama_messages.append(_ollama_message_with_images(user_message, resource_image_paths))
                    execution = await asyncio.to_thread(
                        _ollama_execution_profile_sync,
                        vision_model or ollama_model,
                        ollama_url,
                        streaming=True,
                        purpose="chat",
                    )
                    async for chunk in _stream_ollama_chat(
                        messages=ollama_messages,
                        model=execution["model"],
                        max_tokens=1500,
                        ollama_url=ollama_url,
                        purpose="chat",
                    ):
                        yield chunk
                    return
            raise
        return

    if runtime != "ollama":
        messages.append(_api_message_with_images(user_message, resource_image_paths))
        if api_provider in {"openai_gpts", "generic_api", "deepseek"} and api_key:
            async for chunk in _stream_api_chat(
                messages=messages,
                api_key=api_key,
                api_base_url=api_base_url,
                api_model=api_model,
                max_tokens=1500,
                api_provider=api_provider,
            ):
                yield chunk
            return

        content, _ = await _call_api_messages(
            messages[1:],
            system=system,
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model,
            max_tokens=1500,
        )
        yield content
        return

    messages.append(_ollama_message_with_images(user_message, resource_image_paths))

    execution = await asyncio.to_thread(
        _ollama_execution_profile_sync,
        vision_model or ollama_model,
        ollama_url,
        streaming=True,
        purpose="chat",
    )
    if execution.get("note"):
        yield f"⚠️ {execution['note']}\n\n"

    try:
        async for chunk in _stream_ollama_chat(
            messages=messages,
            model=execution["model"],
            max_tokens=1500,
            ollama_url=ollama_url,
            purpose="chat",
        ):
            yield chunk
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if _escalation_api_key():
            _log.warning("Stream escalating to %s: %s", ESCALATION_PROVIDER, reason)
            yield f"\n\n☁️ *Ollama failed — switching to {ESCALATION_MODEL}...*\n\n"
            user_content = messages[-1].get("content", user_message) if messages else user_message
            content, _ = await _call_api_messages(
                [{"role": "user", "content": user_content}],
                system=system,
                api_key=_escalation_api_key(),
                api_provider=ESCALATION_PROVIDER,
                api_base_url=ESCALATION_BASE_URL,
                api_model=ESCALATION_MODEL,
                max_tokens=1500,
            )
            yield content
        else:
            yield f"\n\n⚠️ Ollama failed: {reason}"


# ─── Agent tools ──────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")

# Shell commands that agents are allowed to execute
_ALLOWED_CMDS = frozenset([
    "git", "ls", "cat", "head", "tail", "grep", "find", "wc", "echo",
    "bash", "sh", "zsh", "rg", "xargs",
    "pwd", "env", "python3", "python", "node", "npm", "npx", "yarn", "pnpm", "bun",
    "next", "vite", "tsc", "tsx", "prisma",
    "cargo", "go", "rustc", "make", "cmake", "pip", "pip3",
    "docker", "kubectl", "terraform", "supabase",
    "eas", "expo", "expo-cli",
    "cp", "mv", "mkdir", "touch",
    "which", "type", "file", "stat", "du", "df", "ps",
    "jq", "yq", "awk", "sed", "sort", "uniq", "cut", "tr",
])

# Runtime-session allowlist — now internal-only for sandbox infrastructure helpers.
# User-facing broad command grants are deprecated in favour of exact ApprovalAction fingerprints.
_SESSION_ALLOWED_CMDS: set[str] = set()

# Sentinel value for "allow all" mode (no command filtering)
_ALLOW_ALL_CMDS: bool = False

# ── Edit permission gate ────────────────────────────────────────────────────
_SESSION_ALLOWED_PATHS: set[str] = set()   # specific file paths cleared this session
_SESSION_ALLOWED_REPOS: set[str] = set()   # repo roots — all files under these are OK
_ALLOW_ALL_EDITS: bool = False             # session-wide allow-all for file writes/edits
_SESSION_ALLOWED_ACTIONS: set[str] = set()
_ONCE_ALLOWED_ACTIONS: set[str] = set()
_TASK_ALLOWED_ACTIONS: dict[str, set[str]] = {}
_PERSISTENT_ALLOWED_ACTIONS: set[str] = set()
_PERSISTENT_ALLOWED_ACTIONS_LOADED: bool = False

# Active workspace root — set at the start of each agent run for cwd defaulting
_ACTIVE_WORKSPACE_PATH: str = ""


def _workspace_root() -> str:
    """Return the active workspace root for the current agent run, if available."""
    if _ACTIVE_WORKSPACE_PATH:
        resolved = os.path.realpath(os.path.expanduser(_ACTIVE_WORKSPACE_PATH))
        if resolved.startswith(_HOME) and os.path.isdir(resolved):
            return resolved
    return _HOME


def _current_autonomy_profile() -> str:
    profile = str(_current_agent_runtime_context().get("autonomy_profile") or "workspace_auto").strip().lower()
    if profile == "manual":
        return "manual"
    return "workspace_auto"


def _current_agent_session_id() -> str:
    return str(_current_agent_runtime_context().get("agent_session_id") or "").strip()


def _load_persistent_action_grants() -> None:
    global _PERSISTENT_ALLOWED_ACTIONS_LOADED
    if _PERSISTENT_ALLOWED_ACTIONS_LOADED:
        return
    try:
        with managed_connection(str(DEVBRAIN_DB_PATH), timeout=10, row_factory=sqlite3.Row) as conn:
            rows = conn.execute(
                """
                SELECT action_fingerprint
                FROM approval_grants
                WHERE scope = 'persist'
                  AND (expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now'))
                """
            ).fetchall()
        _PERSISTENT_ALLOWED_ACTIONS.clear()
        _PERSISTENT_ALLOWED_ACTIONS.update(
            str(row["action_fingerprint"]).strip()
            for row in rows
            if str(row["action_fingerprint"]).strip()
        )
    except Exception:
        _PERSISTENT_ALLOWED_ACTIONS.clear()
    _PERSISTENT_ALLOWED_ACTIONS_LOADED = True


def _action_is_allowed(action: dict[str, Any]) -> bool:
    if not action:
        return False
    if autonomy_profile_allows(action, _current_autonomy_profile()):
        return True
    fingerprint = str(action.get("action_fingerprint") or "").strip()
    if not fingerprint:
        return False
    if fingerprint in _ONCE_ALLOWED_ACTIONS:
        _ONCE_ALLOWED_ACTIONS.discard(fingerprint)
        return True
    if fingerprint in _SESSION_ALLOWED_ACTIONS:
        return True
    session_id = str(action.get("session_id") or _current_agent_session_id() or "").strip()
    if session_id and fingerprint in _TASK_ALLOWED_ACTIONS.get(session_id, set()):
        return True
    _load_persistent_action_grants()
    return fingerprint in _PERSISTENT_ALLOWED_ACTIONS


def agent_allow_action(action: dict[str, Any], scope: str = "once", *, session_id: str = "") -> None:
    """Grant approval for an exact normalized action fingerprint."""
    global _PERSISTENT_ALLOWED_ACTIONS_LOADED
    normalized_scope = str(scope or "once").strip().lower()
    fingerprint = str((action or {}).get("action_fingerprint") or "").strip()
    if not fingerprint:
        return
    if normalized_scope == "once":
        _ONCE_ALLOWED_ACTIONS.add(fingerprint)
        return
    if normalized_scope == "task":
        key = str(session_id or action.get("session_id") or _current_agent_session_id() or "").strip()
        if not key:
            _SESSION_ALLOWED_ACTIONS.add(fingerprint)
            return
        _TASK_ALLOWED_ACTIONS.setdefault(key, set()).add(fingerprint)
        return
    if normalized_scope == "session":
        _SESSION_ALLOWED_ACTIONS.add(fingerprint)
        return
    if normalized_scope == "persist":
        if not bool(action.get("persist_allowed", False)):
            return
        _SESSION_ALLOWED_ACTIONS.add(fingerprint)
        try:
            with managed_connection(str(DEVBRAIN_DB_PATH), timeout=10, row_factory=None) as conn:
                conn.execute(
                    """
                    INSERT INTO approval_grants (
                        action_fingerprint, action_type, scope, workspace_id, repo_root,
                        summary, command_preview, destructive, meta_json, updated_at
                    ) VALUES (?, ?, 'persist', ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(action_fingerprint) DO UPDATE SET
                        action_type = excluded.action_type,
                        workspace_id = excluded.workspace_id,
                        repo_root = excluded.repo_root,
                        summary = excluded.summary,
                        command_preview = excluded.command_preview,
                        destructive = excluded.destructive,
                        meta_json = excluded.meta_json,
                        updated_at = datetime('now')
                    """,
                    (
                        fingerprint,
                        str(action.get("action_type") or ""),
                        action.get("workspace_id"),
                        str(action.get("repo_root") or ""),
                        str(action.get("summary") or ""),
                        str(action.get("command_preview") or ""),
                        1 if bool(action.get("destructive")) else 0,
                        json.dumps(action, sort_keys=True, ensure_ascii=True),
                    ),
                )
                conn.commit()
            _PERSISTENT_ALLOWED_ACTIONS.add(fingerprint)
            _PERSISTENT_ALLOWED_ACTIONS_LOADED = True
        except Exception:
            pass


def agent_get_action_state() -> dict[str, object]:
    return {
        "autonomy_profile": _current_autonomy_profile(),
        "once": sorted(_ONCE_ALLOWED_ACTIONS),
        "session": sorted(_SESSION_ALLOWED_ACTIONS),
        "task_scopes": {key: sorted(values) for key, values in _TASK_ALLOWED_ACTIONS.items()},
        "persistent": sorted(_PERSISTENT_ALLOWED_ACTIONS),
    }


def _first_non_option_token(tokens: list[str], *, value_options: set[str] | None = None) -> tuple[str, list[str]]:
    """Return the first non-option token plus the remaining tail."""
    value_options = set(value_options or ())
    items = [str(token or "") for token in tokens]
    index = 0
    while index < len(items):
        token = items[index]
        if not token:
            index += 1
            continue
        if token == "--":
            tail = items[index + 1:]
            return (tail[0].lower(), tail[1:]) if tail else ("", [])
        if token in value_options:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in value_options if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token.lower(), items[index + 1:]
    return "", []


def _git_command_is_read_only(parts: list[str]) -> bool:
    subcommand, remainder = _first_non_option_token(
        parts[1:],
        value_options={"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"},
    )
    lower_rest = [str(item).lower() for item in remainder]
    if not subcommand:
        return True
    if subcommand in {
        "status", "diff", "show", "log", "rev-parse", "rev-list", "describe",
        "symbolic-ref", "ls-files", "ls-tree", "grep", "blame", "shortlog",
        "merge-base", "name-rev", "reflog",
    }:
        return True
    if subcommand == "remote":
        if not lower_rest:
            return True
        return lower_rest[0] in {"-v", "show", "get-url"}
    if subcommand == "config":
        return any(
            arg in {"-l", "--list", "--get", "--get-all", "--get-regexp", "--name-only"}
            or arg.startswith("--get")
            for arg in lower_rest
        )
    if subcommand == "branch":
        if not lower_rest:
            return True
        mutating_flags = {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "--set-upstream-to", "-u", "--unset-upstream"}
        if any(flag in lower_rest for flag in mutating_flags):
            return False
        listing_flags = {"--show-current", "--all", "-a", "--remotes", "-r", "--list", "-l", "-v", "-vv", "--contains", "--no-contains", "--merged", "--no-merged"}
        if any(flag in lower_rest for flag in listing_flags):
            return True
        return False
    if subcommand == "stash":
        return bool(lower_rest) and lower_rest[0] in {"list", "show"}
    return False


def _gh_command_is_read_only(parts: list[str]) -> bool:
    group, remainder = _first_non_option_token(
        parts[1:],
        value_options={"-R", "--repo", "--hostname"},
    )
    if not group:
        return True
    action, _tail = _first_non_option_token(
        remainder,
        value_options={"-R", "--repo", "--hostname"},
    )
    if group == "auth":
        return action in {"", "status"}
    if not action:
        return False
    safe_pairs = {
        ("pr", "list"),
        ("pr", "view"),
        ("pr", "status"),
        ("pr", "checks"),
        ("pr", "diff"),
        ("issue", "list"),
        ("issue", "view"),
        ("issue", "status"),
        ("repo", "view"),
        ("run", "list"),
        ("run", "view"),
        ("workflow", "list"),
        ("workflow", "view"),
        ("release", "list"),
        ("release", "view"),
    }
    return (group, action) in safe_pairs


def _command_requires_approval(parts: list[str], *, cmd: str = "", cwd: str = "") -> bool:
    base_cmd = os.path.basename(str(parts[0] or "")).lower()
    if base_cmd == "git":
        if _git_command_is_read_only(parts):
            return False
        action = build_command_approval_action(
            cmd or " ".join(parts),
            cwd=_resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root(),
            session_id=_current_agent_session_id(),
        )
        return not _action_is_allowed(action)
    if base_cmd == "gh":
        if _gh_command_is_read_only(parts):
            return False
        action = build_command_approval_action(
            cmd or " ".join(parts),
            cwd=_resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root(),
            session_id=_current_agent_session_id(),
        )
        return not _action_is_allowed(action)
    if base_cmd not in _effective_allowed_cmds():
        action = build_command_approval_action(
            cmd or " ".join(parts),
            cwd=_resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root(),
            session_id=_current_agent_session_id(),
        )
        return not _action_is_allowed(action)
    if base_cmd in {"bash", "sh", "zsh"}:
        action = build_command_approval_action(
            cmd or " ".join(parts),
            cwd=_resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root(),
            session_id=_current_agent_session_id(),
        )
        return not _action_is_allowed(action)
    return False


def _resolve_agent_path(path: str = "", *, default_to_workspace: bool = True) -> str:
    """Resolve agent paths relative to the selected workspace instead of server cwd."""
    raw = str(path or "").strip()
    if raw.startswith("~"):
        candidate = os.path.expanduser(raw)
    elif os.path.isabs(raw):
        candidate = raw
    elif raw:
        base = _workspace_root() if default_to_workspace else _HOME
        candidate = os.path.join(base, raw)
    else:
        candidate = _workspace_root() if default_to_workspace else _HOME
    return os.path.realpath(candidate)


def _resolve_hidden_path(path: str) -> str:
    """Auto-correct common hidden-path omissions like devbrain -> .devbrain."""
    if os.path.exists(path):
        return path
    parts = path.split(os.sep)
    for i, part in enumerate(parts):
        if part and not part.startswith("."):
            candidate = os.sep.join(parts[:i] + ["." + part] + parts[i + 1 :])
            if os.path.exists(candidate):
                return candidate
    return path


def _resolve_git_work_dir(path: str = "") -> str:
    """Normalize file/repo inputs into a directory suitable for git commands."""
    raw = str(path or "").strip()
    candidate = _resolve_agent_path(raw, default_to_workspace=True) if raw else _workspace_root()
    if os.path.isfile(candidate):
        candidate = os.path.dirname(candidate)
    elif not os.path.exists(candidate) and os.path.splitext(candidate)[1]:
        candidate = os.path.dirname(candidate)

    probe = Path(candidate)
    while probe != probe.parent:
        if (probe / ".git").exists():
            return str(probe)
        probe = probe.parent
    return candidate


def _edit_is_allowed(path: str, *, operation: str = "edit") -> bool:
    """Return True if this absolute path is cleared for writing/editing/deletion."""
    if _ALLOW_ALL_EDITS:
        return True
    if path in _SESSION_ALLOWED_PATHS:
        return True
    for repo in _SESSION_ALLOWED_REPOS:
        if path == repo or path.startswith(repo + os.sep):
            return True
    action = build_edit_approval_action(
        operation,
        path,
        workspace_id=None,
        session_id=_current_agent_session_id(),
    )
    return _action_is_allowed(action)


def agent_allow_edit(path: str = "", scope: str = "session") -> None:
    """Whitelist file edits: scope='file' | 'repo' | 'session'."""
    global _ALLOW_ALL_EDITS
    if scope == "session":
        _ALLOW_ALL_EDITS = False
        return
    if not path:
        return
    if scope == "repo":
        # Walk up from path to find .git root; fall back to parent dir
        candidate = Path(path)
        if candidate.is_file() or not candidate.exists():
            candidate = candidate.parent
        while candidate != candidate.parent:
            if (candidate / ".git").exists():
                break
            candidate = candidate.parent
        _SESSION_ALLOWED_REPOS.add(str(candidate))
    else:  # scope == "file"
        _SESSION_ALLOWED_PATHS.add(path)


def agent_get_edit_state() -> dict:
    """Return current edit-gate state (for debug / status endpoints)."""
    return {
        "allow_all": _ALLOW_ALL_EDITS,
        "paths": sorted(_SESSION_ALLOWED_PATHS),
        "repos": sorted(_SESSION_ALLOWED_REPOS),
    }


def _effective_allowed_cmds() -> frozenset[str]:
    return _ALLOWED_CMDS | _SESSION_ALLOWED_CMDS


def agent_allow_command(cmd: str, allow_all: bool = False) -> None:
    """Add a command to the session allowlist (called from server endpoints)."""
    if allow_all:
        return
    else:
        normalized = cmd.strip().lower()
        if normalized in {"git", "gh"}:
            return
        _SESSION_ALLOWED_CMDS.add(normalized)


def agent_get_session_allowed() -> list[str]:
    """Return the current session-allowed commands list."""
    return sorted(_SESSION_ALLOWED_CMDS)


def agent_capture_permission_state() -> dict[str, object]:
    """Snapshot the in-process command/edit approval state for scoped overrides."""
    return {
        "allow_all_cmds": bool(_ALLOW_ALL_CMDS),
        "session_allowed_cmds": set(_SESSION_ALLOWED_CMDS),
        "allow_all_edits": bool(_ALLOW_ALL_EDITS),
        "session_allowed_paths": set(_SESSION_ALLOWED_PATHS),
        "session_allowed_repos": set(_SESSION_ALLOWED_REPOS),
        "session_allowed_actions": set(_SESSION_ALLOWED_ACTIONS),
        "once_allowed_actions": set(_ONCE_ALLOWED_ACTIONS),
        "task_allowed_actions": {key: set(values) for key, values in _TASK_ALLOWED_ACTIONS.items()},
    }


def agent_restore_permission_state(state: dict[str, object] | None) -> None:
    """Restore a previously captured permission snapshot."""
    global _ALLOW_ALL_CMDS, _ALLOW_ALL_EDITS
    snapshot = state or {}
    _ALLOW_ALL_CMDS = bool(snapshot.get("allow_all_cmds", False))
    _ALLOW_ALL_EDITS = bool(snapshot.get("allow_all_edits", False))
    _SESSION_ALLOWED_CMDS.clear()
    _SESSION_ALLOWED_CMDS.update({str(item).strip().lower() for item in (snapshot.get("session_allowed_cmds") or set()) if str(item).strip()})
    _SESSION_ALLOWED_PATHS.clear()
    _SESSION_ALLOWED_PATHS.update({str(item) for item in (snapshot.get("session_allowed_paths") or set()) if str(item)})
    _SESSION_ALLOWED_REPOS.clear()
    _SESSION_ALLOWED_REPOS.update({str(item) for item in (snapshot.get("session_allowed_repos") or set()) if str(item)})
    _SESSION_ALLOWED_ACTIONS.clear()
    _SESSION_ALLOWED_ACTIONS.update({str(item) for item in (snapshot.get("session_allowed_actions") or set()) if str(item)})
    _ONCE_ALLOWED_ACTIONS.clear()
    _ONCE_ALLOWED_ACTIONS.update({str(item) for item in (snapshot.get("once_allowed_actions") or set()) if str(item)})
    _TASK_ALLOWED_ACTIONS.clear()
    for key, values in dict(snapshot.get("task_allowed_actions") or {}).items():
        clean_key = str(key).strip()
        if not clean_key:
            continue
        _TASK_ALLOWED_ACTIONS[clean_key] = {str(item) for item in (values or set()) if str(item)}


def _tool_read_file(path: str, max_kb: int = 512) -> str:
    """Read a file, sandboxed to home directory. Reads up to 512 KB by default."""
    p = _resolve_hidden_path(_resolve_agent_path(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory is not allowed."
    if not os.path.exists(p):
        return f"ERROR: File not found: {p}"
    if os.path.isdir(p):
        return f"ERROR: {p} is a directory — use list_dir."
    size = os.path.getsize(p)
    if size > max_kb * 1024:
        # For very large files, return the first 512 KB with a warning
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                content = f.read(max_kb * 1024)
            return (
                f"=== {p} ({size // 1024}KB — showing first {max_kb}KB) ===\n{content}\n"
                f"\n[...file truncated at {max_kb}KB. Use search_code to find specific sections.]"
            )
        except PermissionError:
            return f"ERROR: Permission denied: {p}"
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"=== {p} ({size} bytes) ===\n{content}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_list_dir(path: str = "") -> str:
    """List directory contents, sandboxed to home."""
    p = _resolve_hidden_path(_resolve_agent_path(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory is not allowed."
    if not os.path.exists(p):
        return f"ERROR: Path not found: {p}"
    if not os.path.isdir(p):
        return f"ERROR: {p} is a file — use read_file."
    try:
        entries = sorted(os.scandir(p), key=lambda e: (e.is_file(), e.name.lower()))
        # Include dot-directories (like .devbrain, .git) but skip dot-files to reduce noise
        lines = [
            f"{'DIR ' if e.is_dir() else 'FILE'} {e.name}"
            for e in entries
            if e.is_dir() or not e.name.startswith(".")
        ]
        return f"=== {p} ===\n" + "\n".join(lines[:120])
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_shell_cmd(cmd: str, cwd: str = "", timeout: int = 30) -> str:
    """Run a shell command (allowlisted). Returns stdout+stderr, truncated at 4KB."""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return f"ERROR: Invalid command: {e}"
    if not parts:
        return "ERROR: Empty command."
    base_cmd = os.path.basename(parts[0])
    if _command_requires_approval(parts, cmd=cmd, cwd=cwd):
        # Return structured blocked signal so the UI can offer an approval dialog
        return f"BLOCKED_CMD:{base_cmd}:{cmd}"
    work_dir = _resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root()
    if os.path.isfile(work_dir):
        work_dir = os.path.dirname(work_dir)
    if not work_dir.startswith(_HOME):
        return "ERROR: cwd must be within home directory."
    if not os.path.isdir(work_dir):
        return f"ERROR: cwd is not a directory: {work_dir}"
    try:
        result = subprocess.run(
            parts, capture_output=True, text=True,
            timeout=timeout, cwd=work_dir,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 4096:
            output = output[:4096] + f"\n... (truncated, total {len(output)} chars)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s."
    except FileNotFoundError:
        return f"ERROR: Command not found: {parts[0]}"
    except Exception as exc:
        return f"ERROR: {exc}"


# ── Background process management for dev servers / watchers ──────
_bg_processes: dict[int, dict] = {}  # pid -> {proc, output_path, cmd, cwd}


def _tool_shell_bg(cmd: str, cwd: str = "", wait_seconds: int = 8) -> str:
    """Start a background process and return initial output after wait_seconds."""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return f"ERROR: Invalid command: {e}"
    if not parts:
        return "ERROR: Empty command."
    base_cmd = os.path.basename(parts[0])
    if _command_requires_approval(parts, cmd=cmd, cwd=cwd):
        return f"BLOCKED_CMD:{base_cmd}:{cmd}"
    work_dir = _resolve_agent_path(cwd, default_to_workspace=True) if cwd else _workspace_root()
    if os.path.isfile(work_dir):
        work_dir = os.path.dirname(work_dir)
    if not work_dir.startswith(_HOME):
        return "ERROR: cwd must be within home directory."
    if not os.path.isdir(work_dir):
        return f"ERROR: cwd is not a directory: {work_dir}"
    wait_seconds = max(2, min(wait_seconds, 30))
    import tempfile, time
    out_file = tempfile.NamedTemporaryFile(
        mode="w", prefix="axon_bg_", suffix=".log", delete=False, dir="/tmp"
    )
    try:
        proc = subprocess.Popen(
            parts, stdout=out_file, stderr=subprocess.STDOUT,
            cwd=work_dir, text=True,
        )
    except FileNotFoundError:
        out_file.close()
        os.unlink(out_file.name)
        return f"ERROR: Command not found: {parts[0]}"
    except Exception as exc:
        out_file.close()
        os.unlink(out_file.name)
        return f"ERROR: {exc}"

    _bg_processes[proc.pid] = {
        "proc": proc, "output_path": out_file.name,
        "cmd": cmd, "cwd": work_dir,
    }
    time.sleep(wait_seconds)
    out_file.flush()
    try:
        with open(out_file.name, "r") as f:
            output = f.read()
    except Exception:
        output = ""
    running = proc.poll() is None
    if len(output) > 6144:
        output = output[-6144:]
    status = "running" if running else f"exited (code {proc.returncode})"
    return f"PID: {proc.pid}\nStatus: {status}\nCwd: {work_dir}\n--- output ---\n{output or '(no output yet)'}"


def _tool_shell_bg_check(pid: int) -> str:
    """Check output from a background process."""
    entry = _bg_processes.get(pid)
    if not entry:
        return f"ERROR: No background process with PID {pid}. Active: {list(_bg_processes.keys()) or 'none'}"
    proc = entry["proc"]
    running = proc.poll() is None
    try:
        with open(entry["output_path"], "r") as f:
            output = f.read()
    except Exception:
        output = "(could not read output)"
    if len(output) > 6144:
        output = output[-6144:]
    status = "running" if running else f"exited (code {proc.returncode})"
    return f"PID: {pid}\nCmd: {entry['cmd']}\nStatus: {status}\n--- output ---\n{output or '(no output yet)'}"


def _tool_git_status(path: str = "") -> str:
    """Get git status + recent log for a directory."""
    p = _resolve_git_work_dir(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not os.path.exists(p):
        return f"ERROR: Path not found: {p}"
    if not os.path.isdir(p):
        return f"ERROR: Repo path is not a directory: {p}"
    status = _tool_shell_cmd(f"git status --short", cwd=p)
    log = _tool_shell_cmd(f"git log --oneline -10", cwd=p)
    branch = _tool_shell_cmd(f"git branch --show-current", cwd=p)
    return f"Branch: {branch.strip()}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"


def _tool_search_code(pattern: str, path: str = "", glob: str = "*.py *.ts *.tsx *.js *.jsx") -> str:
    """Grep for a pattern in source files. Returns matching lines with file:line context."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    includes = " ".join(f"--include={g}" for g in glob.split())
    # -E: extended regex so | works as alternation; no -l so we get actual lines not just filenames
    cmd = f"grep -rEn --max-count=5 {includes} {shlex.quote(pattern)} {shlex.quote(p)}"
    result = _tool_shell_cmd(cmd)
    return result[:3000] if len(result) > 3000 else result


def _tool_write_file(path: str, content: str) -> str:
    """Write content to a file (sandboxed to home)."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not _edit_is_allowed(p, operation="write"):
        return f"BLOCKED_EDIT:write:{p}"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {p}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_append_file(path: str, content: str = "") -> str:
    """Append content to a file (sandboxed to home)."""
    if not content:
        return "ERROR: append_file requires 'content'."
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not _edit_is_allowed(p, operation="append"):
        return f"BLOCKED_EDIT:append:{p}"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} bytes to {p}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_create_file(path: str, content: str = "") -> str:
    """Create a new file, failing if it already exists."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not _edit_is_allowed(p, operation="create"):
        return f"BLOCKED_EDIT:create:{p}"
    if os.path.exists(p):
        return f"ERROR: File already exists: {p}"
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content or "")
        return f"Created {p}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_delete_file(path: str) -> str:
    """Delete a file safely (sandboxed to home)."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not _edit_is_allowed(p, operation="delete"):
        return f"BLOCKED_EDIT:delete:{p}"
    if not os.path.exists(p):
        return f"ERROR: File not found: {p}"
    if os.path.isdir(p):
        return f"ERROR: {p} is a directory. delete_file only removes files."
    try:
        os.remove(p)
        return f"Deleted {p}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Targeted find-and-replace edit. Replaces an exact substring in a file.
    old_string must be unique in the file (unless replace_all=True).
    This is the preferred way to make code changes — surgical, reviewable edits."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not _edit_is_allowed(p, operation="edit"):
        return f"BLOCKED_EDIT:edit:{p}"
    if not os.path.exists(p):
        return f"ERROR: File not found: {p}"
    if os.path.isdir(p):
        return f"ERROR: {p} is a directory, not a file."
    if not old_string:
        return "ERROR: old_string is required and cannot be empty."
    if old_string == new_string:
        return "ERROR: old_string and new_string are identical — no change needed."
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except PermissionError:
        return f"ERROR: Permission denied: {p}"

    count = content.count(old_string)
    if count == 0:
        # Try to help: show nearby content
        lines = content.splitlines()
        first_words = old_string.split()[:4]
        hint_key = " ".join(first_words) if first_words else old_string[:40]
        nearby = [
            f"  L{i+1}: {line.rstrip()}"
            for i, line in enumerate(lines)
            if hint_key.lower() in line.lower()
        ][:5]
        hint = ""
        if nearby:
            hint = "\nDid you mean one of these lines?\n" + "\n".join(nearby)
        return f"ERROR: old_string not found in {p}. The exact text must match (including whitespace/indentation).{hint}"
    if count > 1 and not replace_all:
        return (
            f"ERROR: old_string matches {count} locations in {p}. "
            f"Provide more surrounding context to make it unique, or set replace_all=true."
        )

    new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
    except PermissionError:
        return f"ERROR: Permission denied: {p}"

    replaced = count if replace_all else 1
    delta = len(new_string) - len(old_string)
    return (
        f"Edited {p}: {replaced} replacement(s), {'+' if delta >= 0 else ''}{delta} chars. "
        f"File is now {len(new_content)} bytes."
    )


def _tool_show_diff(path: str = "", staged: bool = False) -> str:
    """Show git diff for a file or directory. Use after edits to review changes."""
    p = _resolve_agent_path(path)
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    flag = "--staged" if staged else ""
    diff = _tool_shell_cmd(f"git diff {flag} -- {shlex.quote(p)}", cwd=os.path.dirname(p) if os.path.isfile(p) else p, timeout=10)
    if not diff or diff.strip() == "(no output)":
        return f"No diff found for {p}. Either no changes or the file is not tracked by git."
    return diff


def _normalize_tool_args(name: str, args: dict) -> dict:
    """Accept common argument aliases from weaker local models."""
    normalized = dict(args or {})

    if name == "shell_cmd" or name == "shell_bg":
        raw_cmd = str(normalized.get("cmd") or "").strip()
        if raw_cmd and not normalized.get("cwd"):
            cd_prefix = _re.match(r"""^\s*cd\s+(['"]?)(.+?)\1\s*&&\s*(.+)$""", raw_cmd)
            if cd_prefix:
                normalized["cwd"] = cd_prefix.group(2).strip()
                normalized["cmd"] = cd_prefix.group(3).strip()
        if not normalized.get("cwd"):
            for alias in ("dir", "directory", "workdir", "working_dir", "path"):
                if normalized.get(alias):
                    normalized["cwd"] = normalized.pop(alias)
                    break
        for alias in ("dir", "directory", "workdir", "working_dir", "path"):
            normalized.pop(alias, None)
        valid_keys = {"cmd", "cwd", "timeout"} if name == "shell_cmd" else {"cmd", "cwd", "wait_seconds"}
        return {k: v for k, v in normalized.items() if k in valid_keys}

    if name == "shell_bg_check":
        if not normalized.get("pid"):
            for alias in ("process_id", "id"):
                if normalized.get(alias):
                    normalized["pid"] = int(normalized.pop(alias))
                    break
        return {k: v for k, v in normalized.items() if k in {"pid"}}

    if name in {"git_status", "list_dir", "read_file"}:
        if not normalized.get("path"):
            for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
            normalized.pop(alias, None)
        if name == "git_status" and normalized.get("path"):
            normalized["path"] = _resolve_git_work_dir(str(normalized["path"]))
        allowed = {"path"}
        if name == "read_file":
            allowed.add("max_kb")
        return {k: v for k, v in normalized.items() if k in allowed}

    if name == "search_code":
        if not normalized.get("path"):
            for alias in ("cwd", "dir", "directory", "repo", "repository"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if not normalized.get("pattern"):
            for alias in ("query", "text", "search", "term"):
                if normalized.get(alias):
                    normalized["pattern"] = normalized.pop(alias)
                    break
        for alias in ("cwd", "dir", "directory", "repo", "repository", "query", "text", "search", "term"):
            normalized.pop(alias, None)
        return {k: v for k, v in normalized.items() if k in {"pattern", "path", "glob"}}

    if name in {"write_file", "append_file", "create_file", "delete_file"}:
        if not normalized.get("path"):
            for alias in ("file", "target", "destination"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if name != "delete_file" and not normalized.get("content"):
            for alias in ("text", "body"):
                if normalized.get(alias):
                    normalized["content"] = normalized.pop(alias)
                    break
        for alias in ("file", "target", "destination", "text", "body"):
            normalized.pop(alias, None)
        allowed = {"path"} if name == "delete_file" else {"path", "content"}
        return {k: v for k, v in normalized.items() if k in allowed}

    if name == "edit_file":
        if not normalized.get("path"):
            for alias in ("file", "filepath", "filename", "target"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if not normalized.get("old_string"):
            for alias in ("old", "find", "search", "original", "before"):
                if normalized.get(alias):
                    normalized["old_string"] = normalized.pop(alias)
                    break
        if not normalized.get("new_string"):
            for alias in ("new", "replace", "replacement", "after", "with"):
                if normalized.get(alias):
                    normalized["new_string"] = normalized.pop(alias)
                    break
        for alias in ("file", "filepath", "filename", "target", "old", "find", "search",
                       "original", "before", "new", "replace", "replacement", "after", "with"):
            normalized.pop(alias, None)
        return {k: v for k, v in normalized.items() if k in {"path", "old_string", "new_string", "replace_all"}}

    if name == "show_diff":
        if not normalized.get("path"):
            for alias in ("file", "dir", "directory", "cwd", "repo"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        for alias in ("file", "dir", "directory", "cwd", "repo"):
            normalized.pop(alias, None)
        return {k: v for k, v in normalized.items() if k in {"path", "staged"}}

    if name == "create_mission":
        if not normalized.get("title"):
            for alias in ("name", "mission", "task", "label"):
                if normalized.get(alias):
                    normalized["title"] = normalized.pop(alias)
                    break
        for alias in ("description", "desc", "body"):
            if normalized.get(alias) and not normalized.get("detail"):
                normalized["detail"] = normalized.pop(alias)
        return {k: v for k, v in normalized.items() if k in {"title", "detail", "priority", "project_id", "due_date"}}

    if name == "update_mission":
        if not normalized.get("mission_id"):
            for alias in ("id", "task_id"):
                if normalized.get(alias):
                    normalized["mission_id"] = int(normalized.pop(alias))
                    break
        return {k: v for k, v in normalized.items() if k in {"mission_id", "status", "title", "detail", "priority", "due_date"}}

    if name == "list_missions":
        return {k: v for k, v in normalized.items() if k in {"status", "project_id"}}

    if name == "http_get":
        return {k: v for k, v in normalized.items() if k in {"url", "headers"}}

    if name == "generate_image":
        if not normalized.get("prompt"):
            for alias in ("description", "text", "idea", "brief"):
                if normalized.get(alias):
                    normalized["prompt"] = normalized.pop(alias)
                    break
        if not normalized.get("image_size"):
            for alias in ("size", "resolution"):
                if normalized.get(alias):
                    normalized["image_size"] = normalized.pop(alias)
                    break
        if not normalized.get("aspect_ratio"):
            for alias in ("ratio", "aspect"):
                if normalized.get(alias):
                    normalized["aspect_ratio"] = normalized.pop(alias)
                    break
        return {
            k: v
            for k, v in normalized.items()
            if k in {"prompt", "aspect_ratio", "image_size", "workspace_id", "title"}
        }

    if name == "remember":
        if not normalized.get("key"):
            for alias in ("name", "label", "id"):
                if normalized.get(alias):
                    normalized["key"] = normalized.pop(alias)
                    break
        if not normalized.get("value"):
            for alias in ("content", "text", "note", "data"):
                if normalized.get(alias):
                    normalized["value"] = normalized.pop(alias)
                    break
        return {k: v for k, v in normalized.items() if k in {"key", "value"}}

    if name == "recall":
        if not normalized.get("query"):
            for alias in ("key", "search", "term", "text"):
                if normalized.get(alias):
                    normalized["query"] = normalized.pop(alias)
                    break
        return {k: v for k, v in normalized.items() if k in {"query"}}

    if name == "plan_task":
        if not normalized.get("goal"):
            for alias in ("title", "task", "objective"):
                if normalized.get(alias):
                    normalized["goal"] = normalized.pop(alias)
                    break
        return {k: v for k, v in normalized.items() if k in {"goal", "steps"}}

    if name == "spawn_subagent":
        if not normalized.get("task"):
            for alias in ("prompt", "query", "goal", "subtask"):
                if normalized.get(alias):
                    normalized["task"] = normalized.pop(alias)
                    break
        return {k: v for k, v in normalized.items() if k in {"task", "context", "max_iterations"}}

    return normalized


# ── Mission (Task) tools ──────────────────────────────────────────────────────

def _run_async_from_sync(coro):
    """Bridge to call async DB functions from synchronous tool context."""
    import asyncio as _aio
    try:
        loop = _aio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: _aio.run(coro)).result(timeout=10)
    return _aio.run(coro)


def _tool_mission_create(title: str, detail: str = "", priority: str = "medium",
                         project_id: int = None, due_date: str = None, **_kw) -> str:
    """Create a new mission (task)."""
    if not title or not title.strip():
        return "ERROR: Mission title is required."
    priority = priority.lower() if priority else "medium"
    if priority not in ("low", "medium", "high", "urgent"):
        priority = "medium"
    async def _do():
        import db as devdb
        async with devdb.get_db() as conn:
            mid = await devdb.add_task(conn, project_id, title.strip(), detail.strip(), priority, due_date)
            await devdb.log_event(conn, "task_added", f"Mission created by Axon: {title.strip()}", project_id=project_id)
            return mid
    mid = _run_async_from_sync(_do())
    result = f"✅ Mission created (ID: {mid}): {title.strip()}"
    if priority in ("high", "urgent"):
        result += f" [{priority.upper()}]"
    if due_date:
        result += f" — due {due_date}"
    return result


def _tool_mission_update(mission_id: int = None, status: str = None, title: str = None,
                         detail: str = None, priority: str = None, due_date: str = None, **_kw) -> str:
    """Update an existing mission's status or fields."""
    if mission_id is None:
        return "ERROR: mission_id is required."
    fields = {}
    if status:
        status = status.lower().replace(" ", "_")
        if status in ("open", "in_progress", "done", "cancelled"):
            fields["status"] = status
        elif status in ("complete", "completed", "finish", "finished"):
            fields["status"] = "done"
        elif status in ("active", "working", "started"):
            fields["status"] = "in_progress"
        elif status in ("cancel", "drop", "remove"):
            fields["status"] = "cancelled"
    if title:
        fields["title"] = title.strip()
    if detail is not None and detail != "":
        fields["detail"] = detail.strip()
    if priority:
        p = priority.lower()
        if p in ("low", "medium", "high", "urgent"):
            fields["priority"] = p
    if due_date:
        fields["due_date"] = due_date
    if not fields:
        return "ERROR: No valid fields to update. Provide status, title, detail, priority, or due_date."
    async def _do():
        import db as devdb
        async with devdb.get_db() as conn:
            await devdb.update_task(conn, int(mission_id), **fields)
            return True
    _run_async_from_sync(_do())
    parts = [f"{k}={v}" for k, v in fields.items()]
    return f"✅ Mission {mission_id} updated: {', '.join(parts)}"


def _tool_mission_list(status: str = None, project_id: int = None, **_kw) -> str:
    """List current missions."""
    async def _do():
        import db as devdb
        async with devdb.get_db() as conn:
            rows = await devdb.get_tasks(conn, project_id=project_id, status=status)
            return [dict(r) for r in rows]
    tasks = _run_async_from_sync(_do())
    if not tasks:
        return "No missions found" + (f" with status={status}" if status else "") + "."
    lines = []
    for t in tasks:
        s = t.get("status", "open")
        icon = {"open": "🔵", "in_progress": "🟡", "done": "✅", "cancelled": "⛔"}.get(s, "⚪")
        p = t.get("priority", "medium")
        line = f"{icon} [{t['id']}] {t['title']} ({p})"
        if t.get("project_name"):
            line += f" — {t['project_name']}"
        if t.get("due_date"):
            line += f" due:{t['due_date']}"
        lines.append(line)
    return f"{len(tasks)} mission(s):\n" + "\n".join(lines)


def _tool_http_get(url: str, headers: str = "") -> str:
    """Perform an HTTP GET request and return the response body (max 6 KB)."""
    import urllib.request as _req
    import urllib.error as _err
    if not url.startswith(("http://", "https://")):
        return "ERROR: Only http:// and https:// URLs are allowed."
    runtime_ctx = _current_agent_runtime_context()
    workspace_id = runtime_ctx.get("workspace_id")
    fetch_policy = str(runtime_ctx.get("external_fetch_policy") or "cache_first").strip().lower()
    if fetch_policy == "memory_first":
        fetch_policy = "cache_first"
    try:
        cache_ttl = max(60, int(runtime_ctx.get("external_fetch_cache_ttl_seconds") or 21600))
    except Exception:
        cache_ttl = 21600
    if fetch_policy != "live_first":
        try:
            with managed_connection(str(DEVBRAIN_DB_PATH), timeout=10, row_factory=sqlite3.Row) as conn:
                row = conn.execute(
                    """
                    SELECT * FROM external_fetch_cache
                    WHERE url = ?
                      AND (expires_at IS NULL OR expires_at = '' OR expires_at > datetime('now'))
                    """,
                    (url,),
                ).fetchone()
                if row:
                    title = str(row["title"] or "").strip()
                    summary = str(row["summary"] or "").strip()
                    content = str(row["content"] or "")
                    status_code = int(row["status_code"] or 200)
                    mime_type = str(row["mime_type"] or "")
                    prefix = f"HTTP {status_code} — {mime_type or 'cached'}"
                    if title:
                        prefix += f" [{title}]"
                    if summary:
                        return f"{prefix}\n[cache hit]\n\n{summary}\n\n{content[:6144]}"
                    return f"{prefix}\n[cache hit]\n\n{content[:6144]}"
        except Exception:
            pass
    try:
        req = _req.Request(url, headers={"User-Agent": "Axon/1.0 (axon-agent)"})
        if headers:
            # Accept simple "Key: Value\nKey2: Value2" format
            for line in headers.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    req.add_header(k.strip(), v.strip())
        with _req.urlopen(req, timeout=20) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read(6144)
            body = raw.decode("utf-8", errors="replace")
            title = ""
            match = _re.search(r"<title[^>]*>(.*?)</title>", body, flags=_re.IGNORECASE | _re.DOTALL)
            if match:
                title = " ".join(match.group(1).split())[:160]
        summary = " ".join(body.split())[:280]
        try:
            cache_key = hashlib.sha1(url.encode("utf-8")).hexdigest()
            memory_key = f"cached_web:{cache_key}"
            with managed_connection(str(DEVBRAIN_DB_PATH), timeout=10, row_factory=None) as conn:
                conn.execute(
                    """
                    INSERT INTO external_fetch_cache (
                        cache_key, url, title, content, summary, status_code, mime_type,
                        workspace_id, meta_json, fetched_at, expires_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'),
                        datetime('now', '+' || ? || ' seconds'),
                        datetime('now')
                    )
                    ON CONFLICT(cache_key) DO UPDATE SET
                        title = excluded.title,
                        content = excluded.content,
                        summary = excluded.summary,
                        status_code = excluded.status_code,
                        mime_type = excluded.mime_type,
                        workspace_id = excluded.workspace_id,
                        meta_json = excluded.meta_json,
                        fetched_at = datetime('now'),
                        expires_at = datetime('now', '+' || ? || ' seconds'),
                        updated_at = datetime('now')
                    """,
                    (
                        cache_key,
                        url,
                        title,
                        body,
                        summary,
                        int(resp.status),
                        ct,
                        workspace_id,
                        json.dumps({"source": "http_get", "url": url}, sort_keys=True, ensure_ascii=True),
                        cache_ttl,
                        cache_ttl,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO memory_items (
                        memory_key, layer, memory_type, title, content, summary, source, source_id,
                        source_ref, workspace_id, trust_level, relevance_score, meta_json, updated_at
                    ) VALUES (?, 'resource', 'cached_external', ?, ?, ?, 'http_get', ?, ?, ?, 'medium', 0.45, ?, datetime('now'))
                    ON CONFLICT(memory_key) DO UPDATE SET
                        title = excluded.title,
                        content = excluded.content,
                        summary = excluded.summary,
                        source_id = excluded.source_id,
                        source_ref = excluded.source_ref,
                        workspace_id = excluded.workspace_id,
                        meta_json = excluded.meta_json,
                        updated_at = datetime('now')
                    """,
                    (
                        memory_key,
                        title or url,
                        body[:4000],
                        summary,
                        url,
                        url,
                        workspace_id,
                        json.dumps({"ttl_seconds": cache_ttl, "url": url}, sort_keys=True, ensure_ascii=True),
                    ),
                )
                conn.commit()
        except Exception:
            pass
        return f"HTTP {resp.status} — {ct}\n[live fetch]\n\n{body}"
    except _err.HTTPError as e:
        return f"HTTP Error {e.code}: {e.reason}"
    except Exception as exc:
        return f"ERROR: {exc}"


def _store_generated_image_resource(
    *,
    content: bytes,
    mime_type: str,
    prompt: str,
    workspace_id: int | None = None,
    title: str = "",
) -> dict[str, Any]:
    async def _do() -> dict[str, Any]:
        import db as devdb

        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            final_title = (title or prompt[:80].strip() or "Generated image").strip()
            if len(final_title) > 120:
                final_title = final_title[:117].rstrip() + "..."
            resource_id = await devdb.add_resource(
                conn,
                title=final_title,
                kind="image",
                source_type="generated",
                source_url="",
                local_path="",
                mime_type=mime_type,
                size_bytes=len(content),
                sha256=resource_bank.sha256_bytes(content),
                status="pending",
                summary="",
                preview_text="",
                workspace_id=workspace_id,
                meta_json="{}",
            )
            ext = ".png" if mime_type == "image/png" else ".jpg"
            filename = resource_bank.sanitize_filename(final_title.replace(" ", "-").lower() or "generated-image") + ext
            local_path = resource_bank.save_resource_file(
                resource_id=resource_id,
                filename=filename,
                content=content,
                settings=settings,
            )
            meta = resource_bank.image_metadata(local_path)
            summary = f"AI-generated image from prompt: {(prompt or '').strip()[:180]}".strip()
            preview = f"Generated image ready: {final_title}. {meta.get('width')}×{meta.get('height')} {meta.get('format', '')}".strip()
            await devdb.update_resource(
                conn,
                resource_id,
                local_path=str(local_path),
                kind="image",
                status="ready",
                summary=summary,
                preview_text=preview,
                meta_json=json.dumps(meta),
            )
            await devdb.replace_resource_chunks(conn, resource_id, [])
            await devdb.log_event(conn, "resource_added", f"Generated image: {final_title}", project_id=workspace_id)
            row = await devdb.get_resource(conn, resource_id)
            return resource_bank.serialize_resource(row)

    return _run_async_from_sync(_do())


def _tool_generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    workspace_id: int | None = None,
    title: str = "",
    **_kw,
) -> str:
    """Generate an image via Gemini and store it as a normal Axon resource."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "ERROR: prompt is required."

    import provider_registry
    import vault as devvault

    async def _load_settings() -> dict[str, str]:
        import db as devdb
        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
            if devvault.VaultSession.is_unlocked():
                gemini_key = await devvault.vault_resolve_provider_key(conn, "gemini_gems")
                if gemini_key:
                    settings["gemini_api_key"] = gemini_key
            return settings

    settings = _run_async_from_sync(_load_settings())
    candidate = provider_registry.merged_provider_config("gemini_gems", settings, {"model": settings.get("gemini_image_model") or "gemini-3.1-flash-image-preview"})
    api_key = settings.get("gemini_api_key", "") or ""
    if not api_key:
        return "ERROR: Gemini API key is not configured. Add it in Secure Vault or Settings to enable image generation."

    model_name = candidate.get("model") or "gemini-3.1-flash-image-preview"
    if not provider_registry.model_supports_image_generation("gemini_gems", model_name):
        model_name = "gemini-3.1-flash-image-preview"
    base = (candidate.get("base_url") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    target = model_name if model_name.startswith("models/") else f"models/{model_name}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio or "1:1",
                "imageSize": image_size or "1K",
            },
        },
    }

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{base}/{target}:generateContent",
                params={"key": api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"ERROR: generate_image failed: {exc}"

    candidates = data.get("candidates") or []
    if not candidates:
        return "ERROR: Image provider returned no candidates."
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text_parts: list[str] = []
    image_blob = None
    mime_type = "image/png"
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("text"):
            text_parts.append(part["text"])
        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            image_blob = inline.get("data")
            mime_type = inline.get("mimeType") or inline.get("mime_type") or mime_type
            break
    if not image_blob:
        return "ERROR: Image provider returned text but no image bytes."

    try:
        content = base64.b64decode(image_blob)
    except Exception as exc:
        return f"ERROR: Could not decode generated image: {exc}"

    resource = _store_generated_image_resource(
        content=content,
        mime_type=mime_type,
        prompt=prompt,
        workspace_id=workspace_id,
        title=title,
    )
    notes = " ".join(p.strip() for p in text_parts if p.strip())[:240]
    extra = f"\nNotes: {notes}" if notes else ""
    return (
        f"✅ Generated image saved as resource #{resource['id']}: {resource['title']}\n"
        f"URL: {resource['content_url']}\n"
        f"Workspace: {resource.get('workspace_name') or workspace_id or 'global'}{extra}"
    )


def _tool_remember(key: str, value: str) -> str:
    """Persist a named note in agent memory for later recall across sessions."""
    db = str(DEVBRAIN_DB_PATH)
    memory_key = f"agent_memory:{key.strip()}"
    workspace_id = _current_agent_runtime_context().get("workspace_id")
    try:
        with managed_connection(db, timeout=10, row_factory=None) as conn:
            conn.execute("""
                INSERT INTO memory_items (
                    memory_key, layer, memory_type, title, content, summary, source, source_id,
                    source_ref, workspace_id, trust_level, relevance_score, meta_json, updated_at
                ) VALUES (?, 'user', 'remember', ?, ?, ?, 'agent_tool', ?, ?, ?, 'high', 0.7, ?, datetime('now'))
                ON CONFLICT(memory_key) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    summary = excluded.summary,
                    source_id = excluded.source_id,
                    source_ref = excluded.source_ref,
                    workspace_id = excluded.workspace_id,
                    meta_json = excluded.meta_json,
                    updated_at = datetime('now')
            """, (
                memory_key,
                key.strip(),
                value.strip(),
                value.strip()[:220],
                key.strip(),
                key.strip(),
                workspace_id,
                json.dumps({"tool": "remember"}, sort_keys=True, ensure_ascii=True),
            ))
            conn.commit()
        return f"Remembered: [{key}] = {value[:120]}"
    except Exception as exc:
        return f"ERROR saving note: {exc}"


def _tool_recall(query: str) -> str:
    """Search persisted agent notes. Returns all notes whose key or value contains the query."""
    db = str(DEVBRAIN_DB_PATH)
    workspace_id = _current_agent_runtime_context().get("workspace_id")
    try:
        with managed_connection(db, timeout=10, row_factory=None) as conn:
            rows = conn.execute("""
                SELECT title, content, updated_at FROM memory_items
                WHERE memory_type IN ('remember', 'facts', 'patterns', 'preferences', 'code', 'context', 'skills', 'project')
                  AND (workspace_id = ? OR workspace_id IS NULL)
                  AND (title LIKE ? OR content LIKE ? OR summary LIKE ?)
                ORDER BY pinned DESC, COALESCE(last_accessed_at, updated_at) DESC
                LIMIT 20
            """, (workspace_id, f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
        if not rows:
            return f"No notes found matching '{query}'."
        lines = [f"**{r[0]}**: {r[1][:200]}" for r in rows]
        return "Agent memory:\n" + "\n".join(lines)
    except Exception as exc:
        return f"ERROR recalling notes: {exc}"


def _tool_plan_task(goal: str, steps: Any = None) -> str:
    """Emit a structured execution plan. Call this at the start of any complex multi-step task."""
    if steps is None:
        steps = []
    if isinstance(steps, str):
        # Allow newline-delimited list as string
        steps = [s.strip() for s in steps.strip().splitlines() if s.strip()]
    if not isinstance(steps, list):
        steps = [str(steps)]
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
    return f"## Plan: {goal}\n\n{numbered}\n\n*Executing step 1 next...*"


_SUBAGENT_LOCK = threading.Lock()
_ACTIVE_SUBAGENT_CALLS = 0
_MAX_ACTIVE_SUBAGENTS = 1


def _tool_spawn_subagent(task: str, context: str = "", max_iterations: int = 10) -> str:
    """Spawn a focused sub-agent to handle a specific subtask.

    The sub-agent has access to all the same tools. Use this to parallelize work or
    delegate a well-defined subtask (e.g., "read file X and summarise it",
    "find all TODO comments in ~/project/src").

    Returns the sub-agent's final answer as a string.
    Max iterations is capped at 15 to prevent runaway loops.
    """
    global _ACTIVE_SUBAGENT_CALLS

    max_iterations = min(max(1, int(max_iterations)), 15)
    collected_text: list[str] = []
    tool_notes: list[str] = []
    init_history: list[dict] = []
    runtime_ctx = _current_agent_runtime_context()
    subagent_tools = [
        name for name in _TOOL_REGISTRY.keys()
        if name != "spawn_subagent"
    ]
    if context:
        init_history.append({"role": "assistant", "content": f"Context provided: {context[:800]}"})

    with _SUBAGENT_LOCK:
        if _ACTIVE_SUBAGENT_CALLS >= _MAX_ACTIVE_SUBAGENTS:
            return (
                "ERROR: A sub-agent is already running. "
                "Finish the current delegated task before spawning another one."
            )
        _ACTIVE_SUBAGENT_CALLS += 1

    async def _run_sub():
        async for event in run_agent(
            task,
            init_history,
            project_name=runtime_ctx.get("project_name"),
            workspace_path=str(runtime_ctx.get("workspace_path") or ""),
            tools=subagent_tools,
            max_iterations=max_iterations,
            force_tool_mode=True,
            api_key=str(runtime_ctx.get("api_key") or ""),
            api_base_url=str(runtime_ctx.get("api_base_url") or ""),
            api_model=str(runtime_ctx.get("api_model") or ""),
            api_provider=str(runtime_ctx.get("api_provider") or ""),
            cli_path=str(runtime_ctx.get("cli_path") or ""),
            cli_model=str(runtime_ctx.get("cli_model") or ""),
            cli_session_persistence=bool(runtime_ctx.get("cli_session_persistence", False)),
            backend=str(runtime_ctx.get("backend") or ""),
            ollama_url=str(runtime_ctx.get("ollama_url") or ""),
            ollama_model=str(runtime_ctx.get("ollama_model") or ""),
        ):
            t = event.get("type", "")
            if t == "text":
                collected_text.append(event.get("chunk", ""))
            elif t == "error":
                collected_text.append(f"ERROR: {event.get('message', 'Sub-agent failed.')}")
            elif t == "approval_required":
                collected_text.append("ERROR: Sub-agent paused for approval before finishing the delegated task.")
            elif t == "tool_result":
                note = f"[{event.get('name', 'tool')}]: {str(event.get('result', ''))[:300]}"
                tool_notes.append(note)

    try:
        _run_async_from_sync(_run_sub())
    finally:
        with _SUBAGENT_LOCK:
            _ACTIVE_SUBAGENT_CALLS = max(0, _ACTIVE_SUBAGENT_CALLS - 1)

    answer = "".join(collected_text).strip()
    if not answer:
        answer = "(Sub-agent produced no text answer)"
    if tool_notes:
        notes_block = "\n".join(tool_notes[:10])
        return f"**Sub-agent result:**\n{answer}\n\n**Tool trace:**\n{notes_block}"
    return f"**Sub-agent result:**\n{answer}"


def _tool_project_info(path: str = "") -> str:
    """Scan a project directory and return real structure: file tree, LOC, git log, key files.
    Always call this before making any claims about a project's structure or codebase.
    """
    import subprocess as _sp
    expanded = _resolve_agent_path(path)
    if not expanded.startswith(_HOME):
        return f"ERROR: Access outside home directory: {expanded}"
    if not os.path.isdir(expanded):
        return f"ERROR: Not a directory: {expanded}"
    lines: list[str] = []
    # File tree (2 levels, skip hidden/.venv/__pycache__)
    try:
        tree = _sp.run(
            ["find", expanded, "-maxdepth", "2", "-not", "-path", "*/.*",
             "-not", "-path", "*/__pycache__/*", "-not", "-path", "*/.venv/*",
             "-not", "-path", "*/node_modules/*"],
            capture_output=True, text=True, timeout=10
        )
        entries = [e for e in tree.stdout.strip().splitlines() if e != expanded]
        lines.append(f"## File tree ({len(entries)} entries):\n" + "\n".join(entries[:80]))
    except Exception as e:
        lines.append(f"Tree error: {e}")
    # Real LOC per language
    try:
        py_loc = _sp.run(["find", expanded, "-name", "*.py", "-not", "-path", "*/.venv/*",
                          "-not", "-path", "*/__pycache__/*", "-exec", "wc", "-l", "{}", "+"],
                         capture_output=True, text=True, timeout=10)
        js_loc = _sp.run(["find", expanded, "-name", "*.js", "-o", "-name", "*.ts",
                          "-not", "-path", "*/node_modules/*"],
                         capture_output=True, text=True, timeout=10)
        total_py = py_loc.stdout.strip().splitlines()[-1].strip() if py_loc.stdout.strip() else "0"
        lines.append(f"\n## Lines of code:\nPython: {total_py}\nJS/TS files: {len(js_loc.stdout.strip().splitlines())}")
    except Exception as e:
        lines.append(f"LOC error: {e}")
    # Git status
    try:
        git = _sp.run(["git", "-C", expanded, "log", "--oneline", "-8"],
                      capture_output=True, text=True, timeout=8)
        if git.returncode == 0:
            lines.append(f"\n## Recent git commits:\n{git.stdout.strip()}")
        else:
            lines.append("\n## Git: No repository found")
    except Exception:
        lines.append("\n## Git: Not available")
    # Key config files
    for fname in ["pyproject.toml", "package.json", "requirements.txt", "Dockerfile", "README.md"]:
        fpath = os.path.join(expanded, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    snippet = f.read(400)
                lines.append(f"\n## {fname} (first 400 chars):\n{snippet}")
            except Exception:
                pass
    return "\n".join(lines)


def _tool_web_search(query: str, max_results: int = 6) -> str:
    """Search the web using DuckDuckGo and return top results with titles and snippets.
    Use for: current events, documentation lookups, package info, error messages.
    """
    import urllib.request as _req
    import urllib.parse as _parse
    import html as _html
    import re as _rre
    try:
        encoded = _parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        request = _req.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with _req.urlopen(request, timeout=15) as resp:
            body = resp.read(65536).decode("utf-8", errors="replace")
        # Parse result blocks
        results: list[str] = []
        blocks = _rre.findall(
            r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            body, _rre.DOTALL
        )
        for href, title, snippet in blocks[:max_results]:
            title_clean = _html.unescape(_rre.sub(r'<[^>]+>', '', title)).strip()
            snippet_clean = _html.unescape(_rre.sub(r'<[^>]+>', '', snippet)).strip()
            results.append(f"**{title_clean}**\n{href}\n{snippet_clean}")
        if not results:
            return f"No results found for: {query}"
        return f"## Web search: {query}\n\n" + "\n\n---\n\n".join(results)
    except Exception as exc:
        return f"ERROR: web search failed — {exc}"


def _tool_glob_files(pattern: str, path: str = "") -> str:
    """Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').
    Returns matching paths sorted by modification time (newest first).
    """
    import glob as _glob
    base = _resolve_agent_path(path)
    if not base.startswith(_HOME):
        return f"ERROR: Access outside home directory: {base}"
    full_pattern = os.path.join(base, pattern)
    try:
        matches = _glob.glob(full_pattern, recursive=True)
        # Filter out hidden dirs, venv, __pycache__
        matches = [m for m in matches
                   if "/.venv/" not in m and "/__pycache__/" not in m
                   and "/node_modules/" not in m and "/." not in m.replace(base, "")]
        matches.sort(key=os.path.getmtime, reverse=True)
        if not matches:
            return f"No files match pattern '{pattern}' in {base}"
        lines = [f"{m} ({os.path.getsize(m):,} bytes)" for m in matches[:60]]
        return f"## {len(matches)} file(s) matching '{pattern}':\n" + "\n".join(lines)
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_grep_code(pattern: str, path: str = "", file_type: str = "",
                    context_lines: int = 2, max_results: int = 40) -> str:
    """Search file contents with regex (ripgrep-style). Faster and more powerful than search_code.
    Args:
        pattern: Regex pattern to search for
        path: Directory to search in (default: home)
        file_type: File extension filter e.g. 'py', 'js', 'ts' (optional)
        context_lines: Lines of context around each match (0-5)
        max_results: Cap on number of matches returned
    """
    import subprocess as _sp
    base = _resolve_agent_path(path)
    if not base.startswith(_HOME):
        return f"ERROR: Access outside home directory: {base}"
    cmd = ["grep", "-r",
           f"-C{max(0, min(5, int(context_lines)))}",
           "-n", "--color=never"]
    if file_type:
        cmd += [f"--include=*.{file_type.lstrip('.')}"]
    cmd += ["--exclude-dir=.venv", "--exclude-dir=__pycache__",
            "--exclude-dir=node_modules", "--exclude-dir=.git"]
    cmd += [pattern, base]
    try:
        result = _sp.run(cmd, capture_output=True, text=True, timeout=15)
        output = result.stdout.strip()
        if not output:
            return f"No matches for '{pattern}' in {base}"
        lines = output.splitlines()
        if len(lines) > max_results * 3:
            lines = lines[:max_results * 3]
            output = "\n".join(lines) + f"\n... (truncated to {max_results} results)"
        return f"## grep '{pattern}' in {base}:\n\n{output}"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_diff_files(path_a: str, path_b: str) -> str:
    """Show a unified diff between two files. Useful for reviewing changes or comparing versions."""
    import subprocess as _sp
    a = _resolve_agent_path(path_a)
    b = _resolve_agent_path(path_b)
    for p in (a, b):
        if not p.startswith(_HOME):
            return f"ERROR: Access outside home directory: {p}"
    for p in (a, b):
        if not os.path.isfile(p):
            return f"ERROR: File not found: {p}"
    try:
        result = _sp.run(["diff", "-u", a, b], capture_output=True, text=True, timeout=10)
        diff = result.stdout.strip()
        if not diff:
            return f"Files are identical: {a} vs {b}"
        lines = diff.splitlines()
        if len(lines) > 200:
            lines = lines[:200]
            diff = "\n".join(lines) + "\n... (truncated)"
        return f"## diff {a} vs {b}:\n\n{diff}"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_memory_write(category: str, key: str, value: str) -> str:
    """Write a structured memory entry for Axon. Supports categories: facts, patterns, preferences, code, context.
    Use this to build Axon's persistent knowledge base across sessions.
    Example: category='patterns', key='user_prefers_typescript', value='User always uses TypeScript with strict mode'
    """
    valid_cats = {"facts", "patterns", "preferences", "code", "context", "skills", "project"}
    category = category.strip().lower()
    if category not in valid_cats:
        category = "facts"
    db = str(DEVBRAIN_DB_PATH)
    compound_key = f"{category}:{key.strip()}"
    workspace_id = _current_agent_runtime_context().get("workspace_id")
    try:
        with managed_connection(db, timeout=10, row_factory=None) as conn:
            conn.execute("""
                INSERT INTO memory_items (
                    memory_key, layer, memory_type, title, content, summary, source, source_id,
                    source_ref, workspace_id, trust_level, relevance_score, meta_json, updated_at
                ) VALUES (?, 'user', ?, ?, ?, ?, 'agent_tool', ?, ?, ?, 'high', 0.72, ?, datetime('now'))
                ON CONFLICT(memory_key) DO UPDATE SET
                    memory_type = excluded.memory_type,
                    title = excluded.title,
                    content = excluded.content,
                    summary = excluded.summary,
                    source_id = excluded.source_id,
                    source_ref = excluded.source_ref,
                    workspace_id = excluded.workspace_id,
                    meta_json = excluded.meta_json,
                    updated_at = datetime('now')
            """, (
                f"agent_memory:{compound_key}",
                category,
                key.strip(),
                value.strip(),
                value.strip()[:220],
                compound_key,
                compound_key,
                workspace_id,
                json.dumps({"tool": "memory_write", "category": category}, sort_keys=True, ensure_ascii=True),
            ))
            conn.commit()
        return f"Memory saved [{category}:{key}] — {len(value)} chars"
    except Exception as exc:
        return f"ERROR: {exc}"


def _tool_memory_read(category: str = "", query: str = "") -> str:
    """Read from Axon's structured memory bank. Filter by category and/or search term.
    Categories: facts, patterns, preferences, code, context, skills, project
    """
    db = str(DEVBRAIN_DB_PATH)
    workspace_id = _current_agent_runtime_context().get("workspace_id")
    try:
        with managed_connection(db, timeout=10, row_factory=None) as conn:
            if category and query:
                rows = conn.execute(
                    "SELECT memory_type, title, content, updated_at FROM memory_items "
                    "WHERE memory_type = ? AND (workspace_id = ? OR workspace_id IS NULL) "
                    "AND (title LIKE ? OR content LIKE ? OR summary LIKE ?) "
                    "ORDER BY COALESCE(last_accessed_at, updated_at) DESC LIMIT 30",
                    (category, workspace_id, f"%{query}%", f"%{query}%", f"%{query}%")
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT memory_type, title, content, updated_at FROM memory_items "
                    "WHERE memory_type = ? AND (workspace_id = ? OR workspace_id IS NULL) "
                    "ORDER BY COALESCE(last_accessed_at, updated_at) DESC LIMIT 30",
                    (category.strip().lower(), workspace_id)
                ).fetchall()
            elif query:
                rows = conn.execute(
                    "SELECT memory_type, title, content, updated_at FROM memory_items "
                    "WHERE (workspace_id = ? OR workspace_id IS NULL) "
                    "AND (title LIKE ? OR content LIKE ? OR summary LIKE ?) "
                    "ORDER BY COALESCE(last_accessed_at, updated_at) DESC LIMIT 30",
                    (workspace_id, f"%{query}%", f"%{query}%", f"%{query}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT memory_type, title, content, updated_at FROM memory_items "
                    "WHERE workspace_id = ? OR workspace_id IS NULL "
                    "ORDER BY COALESCE(last_accessed_at, updated_at) DESC LIMIT 30",
                    (workspace_id,)
                ).fetchall()
        if not rows:
            return f"No memory entries found (category='{category}', query='{query}')"
        lines = [f"**[{r[0]}:{r[1]}]**: {r[2][:300]}" for r in rows]
        return f"## Axon memory ({len(rows)} entries):\n" + "\n\n".join(lines)
    except Exception as exc:
        return f"ERROR: {exc}"


_TOOL_REGISTRY = {
    "read_file":      _tool_read_file,
    "list_dir":       _tool_list_dir,
    "shell_cmd":      _tool_shell_cmd,
    "shell_bg":       _tool_shell_bg,
    "shell_bg_check": _tool_shell_bg_check,
    "git_status":     _tool_git_status,
    "search_code":    _tool_search_code,
    "write_file":     _tool_write_file,
    "delete_file":    _tool_delete_file,
    "edit_file":      _tool_edit_file,
    "show_diff":      _tool_show_diff,
    "append_file":    _tool_append_file,
    "create_file":    _tool_create_file,
    "create_mission": lambda **kw: _tool_mission_create(**kw),
    "update_mission": lambda **kw: _tool_mission_update(**kw),
    "list_missions":  lambda **kw: _tool_mission_list(**kw),
    # ── Enhanced agentic tools ─────────────────────────────────────────────
    "http_get":       _tool_http_get,
    "generate_image": _tool_generate_image,
    "remember":       _tool_remember,
    "recall":         _tool_recall,
    "plan_task":      _tool_plan_task,
    "spawn_subagent": _tool_spawn_subagent,
    # ── Power tools ───────────────────────────────────────────────────────
    "project_info":   _tool_project_info,
    "web_search":     _tool_web_search,
    "glob_files":     _tool_glob_files,
    "grep_code":      _tool_grep_code,
    "diff_files":     _tool_diff_files,
    "memory_write":   _tool_memory_write,
    "memory_read":    _tool_memory_read,
}

# Legacy in-file agent implementation removed. The extracted runtime now lives
# in axon_core.agent and is exposed below via compatibility wrappers.

def _ollama_list_models_sync(ollama_url: str = "") -> list[str]:
    """Synchronous model listing — for use in to_thread."""
    import urllib.request as _urlreq
    import urllib.error as _urlerr
    base = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
    try:
        with _urlreq.urlopen(f"{base}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except _urlerr.URLError:
        return []


async def ollama_list_models(ollama_url: str = "") -> list[str]:
    """Return names of locally available Ollama models."""
    return await asyncio.to_thread(_ollama_list_models_sync, ollama_url)


async def ollama_status(ollama_url: str = "") -> dict:
    """Return Ollama availability + available models."""
    base = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
    running = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.head(base)
            running = resp.status_code < 500
    except Exception:
        running = False
    models = await ollama_list_models(ollama_url) if running else []
    return {"running": running, "models": models, "url": base}


def _find_named_cli(binary_name: str) -> str:
    import shutil as _shutil
    import glob as _glob

    home = os.path.expanduser("~")
    if binary_name == "codex":
        default_paths = _DEFAULT_CODEX_CLI_PATHS
        local_patterns = [
            f"{home}/.nvm/versions/node/*/bin/codex",
            f"{home}/.volta/bin/codex",
            f"{home}/.npm-global/bin/codex",
            f"{home}/.local/bin/codex",
            f"{home}/bin/codex",
        ]
        extension_patterns: list[str] = []
    else:
        default_paths = _DEFAULT_CLAUDE_CLI_PATHS
        local_patterns = [
            f"{home}/.nvm/versions/node/*/bin/claude",
            f"{home}/.volta/bin/claude",
            f"{home}/.npm-global/bin/claude",
            f"{home}/.local/bin/claude",
            f"{home}/bin/claude",
        ]
        extension_patterns = [
            f"{home}/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
            f"{home}/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude",
        ]

    if binary_name == "claude":
        for pattern in extension_patterns:
            matches = sorted(_glob.glob(pattern), reverse=True)
            for match in matches:
                if os.path.isfile(match) and os.access(match, os.X_OK):
                    return match

    for pattern in local_patterns:
        matches = sorted(_glob.glob(pattern), reverse=True)
        for match in matches:
            if os.path.isfile(match) and os.access(match, os.X_OK):
                return match

    found = _shutil.which(binary_name)
    if found:
        return found

    for path in default_paths:
        if path == binary_name:
            continue
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def _find_codex_cli(override_path: str = "") -> str:
    if override_path and os.path.isfile(override_path) and _cli_runtime_family(override_path) == "codex":
        return override_path
    return _find_named_cli("codex")


def _find_cli(override_path: str = "") -> str:
    """Find the selected Claude CLI binary used by Axon's active CLI bridge."""
    if override_path and os.path.isfile(override_path) and _cli_runtime_family(override_path) == "claude":
        return override_path
    return _find_named_cli("claude")


def _resolve_selected_cli_binary(override_path: str = "") -> str:
    """Resolve the explicitly selected CLI binary, allowing Claude or Codex."""
    if override_path and os.path.isfile(override_path):
        return override_path
    return _find_cli()


def discover_cli_environments() -> list[dict]:
    """Return all available CLI binaries with labels for the UI environment picker."""
    import shutil as _shutil
    import glob as _glob

    seen: set[str] = set()
    envs: list[dict] = []

    def _add(path: str, source: str, family: str) -> None:
        real = os.path.realpath(path)
        if real in seen:
            return
        seen.add(real)
        runtime_name = _runtime_label_for_cli_family(family)
        binary_name = "codex" if family == "codex" else "claude"
        if source == "vscode":
            for seg in path.split("/"):
                if seg.startswith("anthropic.claude-code-"):
                    ver = seg.replace("anthropic.claude-code-", "").split("-linux")[0].split("-darwin")[0].split("-win")[0]
                    label = f"{runtime_name} (VS Code {ver})"
                    break
            else:
                label = f"{runtime_name} (VS Code)"
        elif source == "PATH":
            label = f"{binary_name} (PATH)"
        elif source == "local":
            if ".nvm/" in path:
                label = f"{binary_name} (nvm)"
            elif ".volta/" in path:
                label = f"{binary_name} (volta)"
            else:
                label = f"{binary_name} (local)"
        else:
            version = ""
            for seg in path.split("/"):
                if seg and seg[0].isdigit() and "." in seg:
                    version = seg
                    break
            label = f"{runtime_name} ({version})" if version else runtime_name
        envs.append({
            "path": path,
            "label": label,
            "source": source,
            "family": family,
            "runtime_id": family,
            "binary_name": binary_name,
        })

    def _discover_family(binary_name: str, family: str) -> None:
        home = os.path.expanduser("~")
        default_paths = _DEFAULT_CODEX_CLI_PATHS if family == "codex" else _DEFAULT_CLAUDE_CLI_PATHS
        local_patterns = [
            f"{home}/.nvm/versions/node/*/bin/{binary_name}",
            f"{home}/.volta/bin/{binary_name}",
            f"{home}/.npm-global/bin/{binary_name}",
            f"{home}/.local/bin/{binary_name}",
            f"{home}/bin/{binary_name}",
        ]
        extension_patterns = []
        if family == "claude":
            extension_patterns = [
                f"{home}/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude",
                f"{home}/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude",
            ]

        for path in default_paths:
            if path == binary_name:
                continue
            if os.path.isfile(path) and os.access(path, os.X_OK):
                _add(path, "default", family)

        found = _shutil.which(binary_name)
        if found:
            _add(found, "PATH", family)

        for pattern in local_patterns:
            for match in sorted(_glob.glob(pattern), reverse=True):
                if os.path.isfile(match) and os.access(match, os.X_OK):
                    _add(match, "local", family)

        for pattern in extension_patterns:
            for match in sorted(_glob.glob(pattern), reverse=True):
                if os.path.isfile(match) and os.access(match, os.X_OK):
                    _add(match, "vscode", family)

    _discover_family("claude", "claude")
    _discover_family("codex", "codex")

    return envs


async def _stream_cli(
    messages: list[dict],
    cli_path: str = "",
    max_tokens: int = 4096,
    model: str = "",
    allow_session_persistence: bool = False,
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from the selected local CLI runtime."""
    binary = _resolve_selected_cli_binary(cli_path)
    if not binary:
        raise RuntimeError("CLI agent not found. Set the path in Settings or switch to a different runtime.")
    if _cli_runtime_family(binary) == "codex":
        _update_agent_runtime_context(cli_path=binary, backend="cli")
        async for chunk in _stream_codex_cli(messages, binary=binary, model=model):
            yield chunk
        return

    runtime_key = _cli_runtime_key(binary)
    cooldown = current_cli_cooldown(key=runtime_key)
    if cooldown.get("active"):
        fallback_binary = _find_codex_cli()
        if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(binary):
            _update_agent_runtime_context(cli_path=fallback_binary, cli_model=_CODEX_SELF_HEAL_MODEL, backend="cli")
            yield f"⚠️ Claude CLI is cooling down after a rate limit. Falling back to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`).\n\n"
            async for chunk in _stream_codex_cli(messages, binary=fallback_binary, model=_CODEX_SELF_HEAL_MODEL):
                yield chunk
            return
        raise RuntimeError(str(cooldown.get("message") or "Claude CLI is cooling down after a rate limit."))

    _update_agent_runtime_context(cli_path=binary, backend="cli")

    cli_event = _cli_stream_input_event(messages)

    cmd = build_cli_command(
        binary,
        model=model,
        stream_json=True,
        allow_session_persistence=allow_session_persistence,
    )

    await wait_for_cli_slot(key=runtime_key)

    clean_env = {**os.environ, "NO_COLOR": "1"}
    clean_env.pop("CLAUDECODE", None)
    clean_env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env,
        limit=_CLI_SUBPROCESS_STREAM_LIMIT_BYTES,
    )

    if proc.stdin is not None:
        proc.stdin.write((json.dumps(cli_event, ensure_ascii=True) + "\n").encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

    total_cost = 0.0
    total_tokens = 0
    yielded_any = False
    saw_success_result = False
    stderr_chunks: list[str] = []
    fatal_error = ""

    def _cli_content_text(payload: object) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if not isinstance(payload, dict):
            return ""
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    for key in ("text", "thinking"):
                        value = block.get(key)
                        if isinstance(value, str) and value.strip():
                            parts.append(value.strip())
                if parts:
                    return "\n".join(parts)
        result_text = payload.get("result")
        if isinstance(result_text, str) and result_text.strip():
            return result_text.strip()
        return ""

    def _cli_error_text(payload: object) -> str:
        if not isinstance(payload, dict):
            return str(payload).strip()
        err = payload.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        if isinstance(err, dict):
            for key in ("message", "detail", "error"):
                value = err.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return _cli_content_text(payload)

    def _normalize_cli_failure(message: str, *, exit_code: int = 0) -> str:
        text = (message or "").strip()
        lower = text.lower()
        if _is_rate_limited_message(text):
            return text or "Claude CLI hit a rate limit."
        if any(token in lower for token in ("login", "authentication", "authenticated", "api key", "sign in")):
            base = text or "Claude CLI is not authenticated."
            if "claude /login" not in base:
                base += " Sign in with `claude /login`."
            return base
        if text:
            return text
        if exit_code:
            return f"Claude CLI exited with code {exit_code}."
        return "Claude CLI failed without returning a usable result."

    def _capture_fatal_error(message: str) -> None:
        nonlocal fatal_error
        normalized = _normalize_cli_failure(message)
        if not normalized:
            return
        if not fatal_error or fatal_error in {
            "Claude CLI hit a rate limit.",
            "Claude CLI failed without returning a usable result.",
        }:
            fatal_error = normalized

    try:
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            if etype == "rate_limit_event":
                _capture_fatal_error(_cli_error_text(event) or "Claude CLI hit a rate limit.")
                await note_cli_cooldown(
                    fatal_error or "Claude CLI hit a rate limit.",
                    _CLI_RATE_LIMIT_COOLDOWN_SECONDS,
                    key=runtime_key,
                )
                continue

            # Partial text chunk from --include-partial-messages
            if etype in ("assistant", "text"):
                if event.get("error"):
                    _capture_fatal_error(_cli_content_text(event) or _cli_error_text(event))
                    continue
                # assistant message event: content is a list of content blocks
                content = event.get("message", {}).get("content") or event.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type", "")
                        if btype == "text":
                            text = block.get("text", "")
                            if text:
                                yielded_any = True
                                yield text
                        elif btype == "thinking":
                            # Extended thinking blocks from Claude — yield so the
                            # agent loop captures them before ACTION:/ANSWER:.
                            text = block.get("thinking", "")
                            if text:
                                yielded_any = True
                                yield text
                elif isinstance(content, str) and content:
                    yielded_any = True
                    yield content
                # direct text field (legacy CLI output)
                text = event.get("text", "")
                if text:
                    yielded_any = True
                    yield text

            # Stream delta (content_block_delta style)
            elif etype == "content_block_delta":
                delta = event.get("delta", {}) if isinstance(event.get("delta"), dict) else {}
                dtype = delta.get("type", "")
                if dtype == "thinking_delta":
                    # Streaming thinking token from Claude extended thinking
                    text = delta.get("thinking", "")
                    if text:
                        yielded_any = True
                        yield text
                else:
                    text = delta.get("text", "")
                    if text:
                        yielded_any = True
                        yield text

            # Final result event
            elif etype == "result":
                result_text = event.get("result", "")
                if event.get("is_error"):
                    _capture_fatal_error(str(result_text).strip() or _cli_error_text(event))
                    if _is_rate_limited_message(fatal_error or result_text):
                        await note_cli_cooldown(
                            fatal_error or str(result_text).strip(),
                            _CLI_RATE_LIMIT_COOLDOWN_SECONDS,
                            key=runtime_key,
                        )
                    continue
                saw_success_result = True
                total_cost = float(event.get("total_cost_usd", 0.0))
                usage = event.get("usage", {})
                total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                # Only emit result text if we haven't streamed anything yet
                # (fallback for CLIs that don't stream partial messages)
                if result_text and not yielded_any:
                    yielded_any = True
                    yield result_text

            # Collect stderr-style system events (auth errors, rate limits, etc.)
            elif etype in ("system", "error"):
                msg = _cli_error_text(event)
                if msg:
                    subtype = str(event.get("subtype") or "").lower()
                    if etype == "error" or subtype in {"error", "auth", "login_required"}:
                        _capture_fatal_error(msg)
                        if _is_rate_limited_message(msg):
                            await note_cli_cooldown(
                                fatal_error or msg,
                                _CLI_RATE_LIMIT_COOLDOWN_SECONDS,
                                key=runtime_key,
                            )
                    else:
                        stderr_chunks.append(str(msg))

    finally:
        # Drain stderr in parallel with waiting for the process
        try:
            raw_stderr = await asyncio.wait_for(proc.stderr.read(), timeout=3)
            if raw_stderr:
                stderr_chunks.append(raw_stderr.decode("utf-8", errors="replace").strip())
        except (asyncio.TimeoutError, Exception):
            pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        if total_tokens or total_cost:
            _track_usage(total_tokens, total_cost, backend="cli")

    exit_code = proc.returncode or 0
    stderr_text = " | ".join(chunk for chunk in stderr_chunks if chunk).strip()
    if fatal_error:
        if _is_claude_recoverable_problem_message(fatal_error):
            if _is_rate_limited_message(fatal_error):
                await note_cli_cooldown(fatal_error, _CLI_RATE_LIMIT_COOLDOWN_SECONDS, key=runtime_key)
            fallback_binary = _find_codex_cli()
            if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(binary):
                _update_agent_runtime_context(cli_path=fallback_binary, cli_model=_CODEX_SELF_HEAL_MODEL, backend="cli")
                yield f"⚠️ Claude CLI is temporarily unavailable. Falling back to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`).\n\n"
                async for chunk in _stream_codex_cli(messages, binary=fallback_binary, model=_CODEX_SELF_HEAL_MODEL):
                    yield chunk
                return
        if stderr_text and stderr_text not in fatal_error:
            fatal_error = f"{fatal_error} | {stderr_text[:600]}"
        raise RuntimeError(fatal_error)
    if exit_code != 0 and not saw_success_result:
        normalized = _normalize_cli_failure(stderr_text, exit_code=exit_code)
        if _is_claude_recoverable_problem_message(normalized):
            if _is_rate_limited_message(normalized):
                await note_cli_cooldown(normalized, _CLI_RATE_LIMIT_COOLDOWN_SECONDS, key=runtime_key)
            fallback_binary = _find_codex_cli()
            if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(binary):
                _update_agent_runtime_context(cli_path=fallback_binary, cli_model=_CODEX_SELF_HEAL_MODEL, backend="cli")
                yield f"⚠️ Claude CLI is temporarily unavailable. Falling back to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`).\n\n"
                async for chunk in _stream_codex_cli(messages, binary=fallback_binary, model=_CODEX_SELF_HEAL_MODEL):
                    yield chunk
                return
        raise RuntimeError(normalized)
    if stderr_text and not yielded_any:
        normalized = _normalize_cli_failure(stderr_text, exit_code=exit_code)
        if _is_rate_limited_message(normalized):
            await note_cli_cooldown(normalized, _CLI_RATE_LIMIT_COOLDOWN_SECONDS, key=runtime_key)
        raise RuntimeError(normalized)


async def _stream_codex_cli(
    messages: list[dict],
    *,
    binary: str,
    model: str = "",
) -> AsyncGenerator[str, None]:
    model = normalize_cli_model(binary, model)
    prompt = _cli_prompt_from_messages(messages, disallow_native_tools=True)
    cmd = build_codex_exec_command(
        binary,
        prompt=prompt,
        model=model,
        cwd=_workspace_root(),
        # Agent-mode Codex runs should be able to operate inside the selected
        # workspace/sandbox. Keeping this read-only makes Codex report that it
        # cannot continue implementation, which breaks Axon's autonomous mode.
        sandbox_mode="workspace-write",
    )

    await wait_for_cli_slot(_CODEX_CLI_MIN_INTERVAL_SECONDS, key=_cli_runtime_key(binary))

    clean_env = {**os.environ, "NO_COLOR": "1"}
    clean_env.pop("CLAUDECODE", None)
    clean_env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env,
        limit=_CLI_SUBPROCESS_STREAM_LIMIT_BYTES,
    )

    yielded_any = False
    total_tokens = 0
    stderr_chunks: list[str] = []
    fatal_error = ""
    chunk_limit_error = ""
    emitted_text = ""

    try:
        try:
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = str(event.get("type") or "")
                if etype == "item.completed":
                    item = event.get("item") or {}
                    if isinstance(item, dict) and item.get("type") == "agent_message":
                        text = str(item.get("text") or "").strip()
                        if text:
                            yielded_any = True
                            emitted_text += text
                            yield text
                elif etype == "turn.completed":
                    usage = event.get("usage") or {}
                    if isinstance(usage, dict):
                        total_tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
                elif etype == "error":
                    message = str(event.get("message") or "").strip()
                    if message:
                        stderr_chunks.append(message)
                        if _is_codex_fatal_error_message(message):
                            fatal_error = message
                            break
                        if not yielded_any and _codex_retry_attempt(message) >= 3:
                            fatal_error = message
                            break
        except (asyncio.LimitOverrunError, ValueError) as exc:
            if _is_cli_chunk_limit_message(str(exc)):
                chunk_limit_error = str(exc).strip() or "Codex CLI emitted an oversized stream event."
            else:
                raise
    finally:
        if fatal_error and proc.returncode is None:
            proc.terminate()
        try:
            raw_stderr = await asyncio.wait_for(proc.stderr.read(), timeout=3)
            if raw_stderr:
                stderr_chunks.append(raw_stderr.decode("utf-8", errors="replace").strip())
        except (asyncio.TimeoutError, Exception):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

    if total_tokens:
        _track_usage(total_tokens, 0.0, backend="cli")

    if chunk_limit_error:
        recovered_text, _ = await _call_codex_exec_prompt(
            prompt,
            binary=binary,
            model=model,
            sandbox_mode="workspace-write",
        )
        if emitted_text and recovered_text.startswith(emitted_text):
            recovered_text = recovered_text[len(emitted_text):]
        if recovered_text:
            yield recovered_text
            return
        raise RuntimeError(
            "Codex CLI emitted an oversized stream event and Axon could not recover a usable reply."
        )

    exit_code = proc.returncode or 0
    stderr_text = " | ".join(chunk for chunk in stderr_chunks if chunk).strip()
    if fatal_error:
        raise RuntimeError(fatal_error)
    if exit_code != 0:
        raise RuntimeError(stderr_text or "Codex CLI request failed.")
    if not yielded_any:
        raise RuntimeError(stderr_text or "Codex CLI returned no usable output.")


async def _call_codex_exec_prompt(
    prompt: str,
    *,
    binary: str,
    model: str = "",
    sandbox_mode: str = "read-only",
) -> tuple[str, int]:
    model = normalize_cli_model(binary, model)
    cmd = build_codex_exec_command(
        binary,
        prompt=prompt,
        model=model,
        cwd=_workspace_root(),
        sandbox_mode=sandbox_mode,
    )

    await wait_for_cli_slot(_CODEX_CLI_MIN_INTERVAL_SECONDS, key=_cli_runtime_key(binary))

    clean_env = {**os.environ, "NO_COLOR": "1"}
    clean_env.pop("CLAUDECODE", None)
    clean_env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env,
        limit=_CLI_SUBPROCESS_STREAM_LIMIT_BYTES,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CODEX_CLI_CALL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        raise RuntimeError(f"Codex CLI timed out after {_CODEX_CLI_CALL_TIMEOUT_SECONDS}s.")

    raw_output = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    text = ""
    tokens = 0
    error_messages: list[str] = []
    fatal_error = ""

    for raw_line in raw_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = str(event.get("type") or "")
        if etype == "item.completed":
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = str(item.get("text") or "").strip() or text
        elif etype in {"error", "turn.failed"}:
            message = str(event.get("message") or "").strip()
            if not message and isinstance(event.get("error"), dict):
                message = str((event.get("error") or {}).get("message") or "").strip()
            if message:
                error_messages.append(message)
                if _is_codex_fatal_error_message(message):
                    fatal_error = message
                    break
                if not text and _codex_retry_attempt(message) >= 3:
                    fatal_error = message
                    break
        elif etype == "turn.completed":
            usage = event.get("usage") or {}
            if isinstance(usage, dict):
                tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)

    if tokens:
        _track_usage(tokens, 0.0, backend="cli")

    error_text = " | ".join(msg for msg in error_messages if msg).strip()
    if fatal_error:
        raise RuntimeError(fatal_error)
    if proc.returncode != 0:
        raise RuntimeError(error_text or stderr_text or text or "Codex CLI request failed.")
    if not text:
        raise RuntimeError(error_text or stderr_text or "Codex CLI returned no usable output.")
    return text, tokens


async def _call_cli(
    prompt: str,
    system: str = "",
    cli_path: str = "",
    model: str = "",
    allow_session_persistence: bool = False,
) -> str:
    """
    Call the CLI agent bridge in non-interactive (-p) mode.
    Uses your locally installed CLI agent — no API key needed.
    """
    binary = _resolve_selected_cli_binary(cli_path)
    if not binary:
        raise RuntimeError("CLI agent not found. Set the path in Settings or switch to a different runtime.")
    if _cli_runtime_family(binary) == "codex":
        _update_agent_runtime_context(cli_path=binary, backend="cli")
        return await _call_codex_cli(prompt, system=system, binary=binary, model=model)
    runtime_key = _cli_runtime_key(binary)
    cooldown = current_cli_cooldown(key=runtime_key)
    if cooldown.get("active"):
        fallback_binary = _find_codex_cli()
        if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(binary):
            _update_agent_runtime_context(cli_path=fallback_binary, cli_model=_CODEX_SELF_HEAL_MODEL, backend="cli")
            content, tokens = await _call_codex_cli(prompt, system=system, binary=fallback_binary, model=_CODEX_SELF_HEAL_MODEL)
            return f"⚠️ Claude CLI is cooling down after a rate limit. Fell back to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`).\n\n{content}", tokens
        raise RuntimeError(str(cooldown.get("message") or "Claude CLI is cooling down after a rate limit."))

    full_prompt = prompt
    if system:
        full_prompt = f"<system>\n{system}\n</system>\n\n{prompt}"

    cmd = build_cli_command(
        binary,
        model=model,
        stream_json=False,
        allow_session_persistence=allow_session_persistence,
    )
    cmd.append(full_prompt)

    await wait_for_cli_slot(key=runtime_key)

    # Strip CLAUDECODE so the CLI doesn't refuse to run inside another Claude session
    clean_env = {**os.environ, "NO_COLOR": "1"}
    clean_env.pop("CLAUDECODE", None)
    clean_env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env,
        limit=_CLI_SUBPROCESS_STREAM_LIMIT_BYTES,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    raw = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("is_error"):
            msg = str(data.get("result") or "").strip() or err or "Claude CLI request failed."
            raise RuntimeError(msg)
        text = data.get("result", "")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        cost = float(data.get("total_cost_usd", 0.0))
        _track_usage(tokens, cost, backend="cli")
    except (json.JSONDecodeError, KeyError):
        text = raw   # fallback: treat raw as plain text
        tokens = 0
    if proc.returncode != 0:
        msg = err or text or "Claude CLI request failed."
        if _is_claude_recoverable_problem_message(msg):
            if _is_rate_limited_message(msg):
                await note_cli_cooldown(msg, _CLI_RATE_LIMIT_COOLDOWN_SECONDS, key=runtime_key)
            fallback_binary = _find_codex_cli()
            if fallback_binary and os.path.realpath(fallback_binary) != os.path.realpath(binary):
                _update_agent_runtime_context(cli_path=fallback_binary, cli_model=_CODEX_SELF_HEAL_MODEL, backend="cli")
                content, codex_tokens = await _call_codex_cli(
                    prompt,
                    system=system,
                    binary=fallback_binary,
                    model=_CODEX_SELF_HEAL_MODEL,
                )
                return f"⚠️ Claude CLI is temporarily unavailable. Fell back to Codex CLI (`{_CODEX_SELF_HEAL_MODEL}`).\n\n{content}", codex_tokens
        raise RuntimeError(msg[:300])

    # Strip CLI sandbox/permission warning lines that pollute output
    _SANDBOX_PREFIXES = (
        "The project directory is outside",
        "I don't have access to",
        "outside my allowed working path",
        "Note: I cannot access",
        "Note: This path is outside",
        "Warning: The file",
    )
    clean_lines = [
        ln for ln in text.splitlines()
        if not any(ln.strip().startswith(p) or p in ln for p in _SANDBOX_PREFIXES)
    ]
    text = "\n".join(clean_lines).strip()

    return text, tokens


async def _call_codex_cli(
    prompt: str,
    *,
    system: str = "",
    binary: str,
    model: str = "",
) -> tuple[str, int]:
    full_prompt = _cli_prompt_from_messages(
        [
            {"role": "system", "content": system or SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        disallow_native_tools=True,
    )
    return await _call_codex_exec_prompt(
        full_prompt,
        binary=binary,
        model=model,
        sandbox_mode="read-only",
    )


# Compatibility wrappers over the extracted agent core. These intentionally
# shadow the legacy in-file implementations above until the full block is
# removed in a later cleanup pass.
AGENT_TOOL_DEFS = AGENT_TOOL_DEFS_CORE


def _agent_runtime_deps(exclude_tools: set[str] | None = None) -> AgentRuntimeDeps:
    """Build the runtime dependency bundle for the extracted agent core."""
    exclude = set(exclude_tools or ())
    tool_registry = {
        name: fn for name, fn in _TOOL_REGISTRY.items() if name not in exclude
    }
    return AgentRuntimeDeps(
        tool_registry=tool_registry,
        normalize_tool_args=_normalize_tool_args,
        stream_cli=_stream_cli,
        stream_api_chat=_stream_api_chat,
        stream_ollama_chat=_stream_ollama_chat,
        ollama_execution_profile_sync=_ollama_execution_profile_sync,
        ollama_message_with_images=_ollama_message_with_images,
        api_message_with_images=_api_message_with_images,
        cli_message_with_images=_cli_message_with_images,
        # Agent mode must resolve the actively selected local runtime, not the
        # legacy Claude-only finder. Otherwise Codex selections get silently
        # routed back to Claude and model ids like gpt-5.4 fail incorrectly.
        find_cli=_resolve_selected_cli_binary,
        ollama_default_model=OLLAMA_DEFAULT_MODEL,
        ollama_agent_model=OLLAMA_AGENT_MODEL,
        db_path=DEVBRAIN_DB_PATH,
    )


def _execute_tool(name: str, args: dict) -> str:
    """Compatibility wrapper over the extracted agent tool executor."""
    return _execute_tool_core(name, args, _agent_runtime_deps())


def _direct_agent_action(
    user_message: str,
    history: list[dict] | None = None,
    project_name: Optional[str] = None,
) -> tuple[str, dict, str, str] | None:
    """Compatibility wrapper over the extracted deterministic agent action handler."""
    return _direct_agent_action_core(
        user_message,
        history=history,
        project_name=project_name,
        deps=_agent_runtime_deps(),
    )


async def run_agent(
    user_message: str,
    history: list[dict],
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
    autonomy_profile: str = "",
    external_fetch_policy: str = "",
    external_fetch_cache_ttl_seconds: int | str = "",
    resume_session_id: str = "",
    resume_reason: str = "",
    continue_task: str = "",
    **extra_kwargs,
) -> AsyncGenerator[dict, None]:
    """Compatibility wrapper over the extracted ReAct-style agent loop.

    Accepts **extra_kwargs so that callers adding new parameters don't crash
    with 'unexpected keyword argument' TypeError if this wrapper hasn't been
    updated yet.  Any unrecognised kwargs are logged and forwarded only if
    _run_agent_core accepts them.
    """
    if extra_kwargs:
        _log.warning("run_agent wrapper received unrecognised kwargs (auto-ignored): %s", list(extra_kwargs))
    effective_backend = str(backend or "").strip().lower()
    runtime_notice = ""
    if effective_backend == "cli":
        effective_backend, runtime_notice = _resolve_cli_runtime_fallback(
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model,
            cli_path=cli_path,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )

    runtime_ctx = {
        "backend": effective_backend,
        "project_name": project_name,
        "workspace_path": workspace_path or "",
        "api_key": api_key,
        "api_base_url": api_base_url,
        "api_model": api_model,
        "api_provider": api_provider,
        "cli_path": cli_path,
        "cli_model": cli_model,
        "cli_session_persistence": cli_session_persistence,
        "ollama_url": ollama_url,
        "ollama_model": ollama_model,
        "autonomy_profile": autonomy_profile or "workspace_auto",
        "workspace_id": workspace_id,
        "external_fetch_policy": (external_fetch_policy or "cache_first"),
        "external_fetch_cache_ttl_seconds": external_fetch_cache_ttl_seconds or "21600",
    }
    ctx_token = _ACTIVE_AGENT_RUNTIME_CONTEXT.set(runtime_ctx)
    global _ACTIVE_WORKSPACE_PATH
    previous_workspace = _ACTIVE_WORKSPACE_PATH
    _ACTIVE_WORKSPACE_PATH = workspace_path or ""
    try:
        if runtime_notice:
            yield {"type": "text", "chunk": f"⚠️ {runtime_notice}\n\n"}
        async for event in _run_agent_core(
            user_message,
            history,
            deps=_agent_runtime_deps(),
            context_block=context_block,
            resource_context=resource_context,
            resource_image_paths=resource_image_paths,
            vision_model=vision_model,
            project_name=project_name,
            workspace_path=workspace_path,
            tools=tools,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            max_iterations=max_iterations,
            context_compact=context_compact,
            force_tool_mode=force_tool_mode,
            api_key=api_key,
            api_base_url=api_base_url,
            api_model=api_model,
            api_provider=api_provider,
            cli_path=cli_path,
            cli_model=cli_model,
            cli_session_persistence=cli_session_persistence,
            backend=effective_backend or backend,
            workspace_id=workspace_id,
            resume_session_id=resume_session_id,
            resume_reason=resume_reason,
            continue_task=continue_task,
        ):
            yield event
    finally:
        _ACTIVE_WORKSPACE_PATH = previous_workspace
        _ACTIVE_AGENT_RUNTIME_CONTEXT.reset(ctx_token)


# ─── System Prompts ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Axon — a proactive AI copilot and operator running locally at ~/.devbrain.

You are not a generic chatbot. You are a partner: technically sharp, direct, and always useful.
Think like a senior engineer who knows the codebase, the missions, and the developer's goals.
You live alongside the developer — you see what they're working on, you remember context, and you act.

## What you are
- A full-stack AI operator with real-time tool access (files, shell, search, git, missions)
- Your thinking and tool steps stream live in the Axon UI — the developer sees everything as it happens
- You can read and improve your own source code (you live at ~/.devbrain/)
- You know the developer's workspaces, active missions, saved playbooks, and vault secrets

## How to behave
- Warm but direct — no fluff, no corporate-speak, no unnecessary apologies
- Be specific: mention actual project names, file paths, task titles, line numbers
- If you can do something with a tool — do it. Never instruct the user to do what you can do yourself
- If the goal, workspace, file, or success criteria is ambiguous, ask one short clarification question instead of guessing
- Prioritise ruthlessly — what matters right now?
- Proactively flag risk: stale repos, overdue missions, dangerous patterns
- Celebrate when something ships — acknowledge the win
- South African developer context: Rands (R), local references fine

## Format
- Markdown for structure; short lists (≤5 items) unless asked for more
- Code blocks for any code, commands, file paths
- Match response length to complexity — be brief for quick questions, thorough for deep ones"""

SYSTEM_PROMPT_OLLAMA = """You are Axon — a local AI copilot for a software developer.
Be like a senior engineer partner: direct, warm, technically sharp, and always useful.

You are NOT a limited chatbot. Your thinking blocks and tool calls stream live in the Axon UI.
Do NOT tell the user you "can't stream" or have limitations you don't have — you can see everything they see.

Use real project names, file paths, and task titles. Be concise but complete. Use markdown.
Keep responses focused — under 500 words unless depth is needed."""


def _build_context_block(projects: list, tasks: list, prompts: list) -> str:
    """Build a structured context string about the user's current state."""
    lines = ["## Current Operator State\n"]

    if projects:
        lines.append("### Active Workspaces")
        for p in projects[:10]:  # cap at 10
            age = f"{p['last_commit_age_days']:.0f}d ago" if p.get("last_commit_age_days") else "no git"
            lines.append(
                f"- **{p['name']}** [{p.get('stack','?')}] "
                f"health={p.get('health',100)} todos={p.get('todo_count',0)} "
                f"last_commit={age} path={p.get('path','')}"
            )
        lines.append("")

    if tasks:
        lines.append("### Active Missions")
        for t in tasks[:15]:
            proj = t.get("project_name", "general")
            due = f" due:{t['due_date']}" if t.get("due_date") else ""
            lines.append(f"- [{t.get('priority','medium').upper()}] {t['title']} ({proj}){due}")
        lines.append("")

    if prompts:
        lines.append("### Saved Playbooks (recent)")
        for pr in prompts[:5]:
            proj = pr.get("project_name", "general")
            lines.append(f"- **{pr['title']}** ({proj}) — {pr['content'][:80]}...")
        lines.append("")

    return "\n".join(lines)


# ─── Smart escalation: Ollama → cloud API fallback ────────────────────────────

ESCALATION_PROVIDER = "deepseek"
ESCALATION_BASE_URL = "https://api.deepseek.com/"
ESCALATION_MODEL = "deepseek-reasoner"

# Model overrides by role for API backends.
# DeepSeek defaults to the stronger reasoning model across Axon's API paths.
# Claude and Gemini are available as alternatives per provider selection.
API_MODEL_BY_ROLE: dict[str, dict[str, str]] = {
    "deepseek": {"reasoning": "deepseek-reasoner", "code": "deepseek-reasoner", "general": "deepseek-reasoner"},
    "anthropic": {"code": "claude-sonnet-4-5", "reasoning": "claude-sonnet-4-5", "general": "claude-sonnet-4-5"},
    "gemini_gems": {"code": "gemini-2.5-pro", "reasoning": "gemini-2.5-pro", "general": "gemini-2.5-pro"},
}


def _escalation_api_key() -> str:
    """Resolve an API key for cloud escalation from env."""
    return os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")


async def _escalate_to_api(
    prompt: str,
    system: str = "",
    max_tokens: int = MAX_TOKENS_CHAT,
    reason: str = "",
) -> tuple[str, int]:
    """Fallback to cloud API when local Ollama fails."""
    api_key = _escalation_api_key()
    if not api_key:
        raise RuntimeError(
            f"Ollama failed ({reason}) and no cloud API key is configured for escalation. "
            "Set DEEPSEEK_API_KEY in .env or add a key to the Vault."
        )
    _log.warning("Escalating to %s: %s", ESCALATION_PROVIDER, reason)
    content, tokens = await _call_api_messages(
        [{"role": "user", "content": prompt}],
        system=system or SYSTEM_PROMPT,
        api_key=api_key,
        api_provider=ESCALATION_PROVIDER,
        api_base_url=ESCALATION_BASE_URL,
        api_model=ESCALATION_MODEL,
        max_tokens=max_tokens,
    )
    return f"\u2601\ufe0f *[Cloud: {ESCALATION_MODEL}]*\n\n{content}", tokens


# ─── Unified call dispatcher ─────────────────────────────────────────────────

async def _call(
    prompt: str,
    system: str = "",
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    max_tokens: int = MAX_TOKENS_CHAT,
    model: str = "",
    ollama_url: str = "",
    ollama_model: str = "",
) -> tuple[str, int]:
    """Route a call to the API, CLI, or local Ollama backend.
    When backend='ollama' and the call fails, automatically escalates
    to a cloud API if a key is available."""
    if backend == "cli":
        fallback_backend, _notice = _resolve_cli_runtime_fallback(
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model or model,
            cli_path=cli_path,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )
        if fallback_backend == "api":
            content, tokens = await _call_api_messages(
                [{"role": "user", "content": prompt}],
                system=system or SYSTEM_PROMPT,
                api_key=api_key,
                api_provider=api_provider,
                api_base_url=api_base_url,
                api_model=api_model or model or BALANCED_MODEL,
                max_tokens=max_tokens,
            )
            return f"☁️ *[Fallback: {api_model or model or BALANCED_MODEL}]*\n\n{content}", tokens
        if fallback_backend == "ollama":
            content, tokens = await _call_ollama(
                prompt,
                system=system or SYSTEM_PROMPT,
                model=ollama_model or OLLAMA_DEFAULT_MODEL,
                max_tokens=max_tokens,
                ollama_url=ollama_url,
            )
            return f"🦙 *[Fallback: {ollama_model or OLLAMA_DEFAULT_MODEL}]*\n\n{content}", tokens
        try:
            content, tokens = await _call_cli(
                prompt,
                system=system,
                cli_path=cli_path,
                model=model,
                allow_session_persistence=False,
            )
            return content, tokens
        except Exception as exc:
            if _is_cli_rate_limit_message(str(exc)):
                if api_key and api_base_url:
                    content, tokens = await _call_api_messages(
                        [{"role": "user", "content": prompt}],
                        system=system or SYSTEM_PROMPT,
                        api_key=api_key,
                        api_provider=api_provider,
                        api_base_url=api_base_url,
                        api_model=api_model or model or BALANCED_MODEL,
                        max_tokens=max_tokens,
                    )
                    return f"☁️ *[Fallback: {api_model or model or BALANCED_MODEL}]*\n\n{content}", tokens
                if ollama_model or ollama_url:
                    content, tokens = await _call_ollama(
                        prompt,
                        system=system or SYSTEM_PROMPT,
                        model=ollama_model or OLLAMA_DEFAULT_MODEL,
                        max_tokens=max_tokens,
                        ollama_url=ollama_url,
                    )
                    return f"🦙 *[Fallback: {ollama_model or OLLAMA_DEFAULT_MODEL}]*\n\n{content}", tokens
            raise
    elif backend == "ollama":
        try:
            content, tokens = await _call_ollama(
                prompt, system=system or SYSTEM_PROMPT,
                model=ollama_model, max_tokens=max_tokens, ollama_url=ollama_url,
            )
            return content, tokens
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            if _escalation_api_key():
                return await _escalate_to_api(
                    prompt, system=system or SYSTEM_PROMPT,
                    max_tokens=max_tokens, reason=reason,
                )
            raise
    else:
        return await _call_api_messages(
            [{"role": "user", "content": prompt}],
            system=system or SYSTEM_PROMPT,
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model or model or BALANCED_MODEL,
            max_tokens=max_tokens,
        )


# ─── Chat ─────────────────────────────────────────────────────────────────────

async def chat(
    user_message: str,
    history: list[dict],
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    workspace_path: str = "",
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_model: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> dict:
    """
    Send a chat message and return {"content": str, "tokens": int}.
    Supports local Ollama, CLI agent, and external API runtimes.
    """
    runtime = (backend or "api").strip().lower()
    runtime_notice = ""
    if runtime == "cli":
        runtime, runtime_notice = _resolve_cli_runtime_fallback(
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model,
            cli_path=cli_path,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
        )

    system = SYSTEM_PROMPT_OLLAMA if runtime == "ollama" else SYSTEM_PROMPT
    if _requires_local_operator_execution(user_message, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path):
        return {
            "content": (
                "This request needs local tools. I did not create, edit, append, delete, "
                "or verify any local file, repo, or workspace state in this plain chat turn. "
                "Run it in Agent mode or let Axon auto-route it to the local operator."
            ),
            "tokens": 0,
        }
    if _is_general_planning_request(user_message, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path):
        history = _filtered_general_history(history, db_path=DEVBRAIN_DB_PATH, workspace_path=workspace_path)
        system += (
            "\n\nThis is a general planning, writing, or research task."
            "\nDo not assume repository, file, or git context unless the user explicitly asks for local data."
            "\nPrefer a strong structure, concise synthesis, and 2-4 useful next-step options."
        )
    if context_block:
        # Trim context for local models (keep manageable, qwen2.5 handles 4k fine)
        if backend == "ollama":
            context_block = context_block[:2000]
        system += f"\n\n{context_block}"
    if resource_context:
        if backend == "ollama":
            system += f"\n\n{resource_context[:5000]}"
        else:
            system += f"\n\n{resource_context}"
    if project_name:
        system += f"\n\nCurrently focused on workspace: **{project_name}**"

    selected_history = select_history_for_chat(
        user_message,
        history,
        backend=runtime,
        resource_image_paths=resource_image_paths,
    )

    if runtime == "ollama":
        ollama_note = ""
        execution = await asyncio.to_thread(
            _ollama_execution_profile_sync,
            vision_model or ollama_model,
            ollama_url,
            streaming=False,
            purpose="chat",
        )
        ollama_model = execution["model"]
        ollama_note = execution.get("note", "")

        messages = [{"role": "system", "content": system}]
        for h in selected_history:
            messages.append({"role": h["role"], "content": h["content"][:600]})
        messages.append(_ollama_message_with_images(user_message, resource_image_paths))

        parts: list[str] = []
        async for chunk in _stream_ollama_chat(
            messages=messages,
            model=ollama_model,
            max_tokens=MAX_TOKENS_CHAT,
            ollama_url=ollama_url,
            purpose="chat",
        ):
            parts.append(chunk)
        content = "".join(parts)
        tokens = 0
        if ollama_note:
            content = f"⚠️ {ollama_note}\n\n{content}"
        if runtime_notice:
            content = f"⚠️ {runtime_notice}\n\n{content}"
    elif runtime == "cli":
        messages = [{"role": "system", "content": system}]
        for h in selected_history:
            messages.append({"role": h["role"], "content": h["content"][:300]})
        messages.append(_cli_message_with_images(user_message, resource_image_paths))
        try:
            parts: list[str] = []
            async for chunk in _stream_cli(
                messages,
                cli_path=cli_path,
                max_tokens=MAX_TOKENS_CHAT,
                model=cli_model or "",
                allow_session_persistence=False,
            ):
                parts.append(chunk)
            content = "".join(parts)
            tokens = 0
        except Exception as exc:
            if _is_cli_rate_limit_message(str(exc)):
                if api_key and api_base_url:
                    content, tokens = await _call_api_messages(
                        [_api_message_with_images(user_message, resource_image_paths)],
                        system=system,
                        api_key=api_key,
                        api_provider=api_provider,
                        api_base_url=api_base_url,
                        api_model=api_model or BALANCED_MODEL,
                        max_tokens=MAX_TOKENS_CHAT,
                    )
                    content = f"⚠️ Claude CLI hit a rate limit. Falling back to {_api_provider_label(api_provider)} (`{api_model or BALANCED_MODEL}`).\n\n{content}"
                elif ollama_model or ollama_url:
                    content, tokens = await _call_ollama(
                        user_message,
                        system=system,
                        model=ollama_model or OLLAMA_DEFAULT_MODEL,
                        max_tokens=MAX_TOKENS_CHAT,
                        ollama_url=ollama_url,
                    )
                    content = f"⚠️ Claude CLI hit a rate limit. Falling back to Local Ollama.\n\n{content}"
                else:
                    raise
            else:
                raise
    else:
        messages = []
        for h in selected_history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})
        content, tokens = await _call_api_messages(
            messages,
            system=system,
            api_key=api_key,
            api_provider=api_provider,
            api_base_url=api_base_url,
            api_model=api_model or BALANCED_MODEL,
            max_tokens=MAX_TOKENS_CHAT,
        )
        if runtime_notice:
            content = f"⚠️ {runtime_notice}\n\n{content}"

    return {"content": content, "tokens": tokens}


# ─── Morning Digest ──────────────────────────────────────────────────────────

async def generate_digest(
    projects: list,
    tasks: list,
    activity: list,
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> str:
    """Generate a daily morning brief."""
    context = _build_context_block(projects, tasks, [])
    recent_activity = ""
    if activity:
        recent_activity = "### Recent Activity (last 24h)\n"
        for a in activity[:10]:
            recent_activity += f"- [{a['event_type']}] {a.get('summary','')}\n"

    prompt = f"""Generate a concise morning brief for this developer.

{context}
{recent_activity}

Structure your digest as:
1. **Good morning** — one upbeat sentence about what's ahead
2. **Priority today** — top 3 most important things (specific missions or workspaces)
3. **Watch out** — any stale workspaces or overdue missions needing urgent attention
4. **Quick wins** — 1-2 things they can knock off fast
5. **Note** — anything else worth knowing

Be specific. Use actual names. Keep it under 300 words. Make it motivating."""

    content, _ = await _call(prompt, api_key=api_key, api_provider=api_provider,
                              api_base_url=api_base_url, api_model=api_model, backend=backend,
                              cli_path=cli_path, cli_session_persistence=cli_session_persistence, max_tokens=MAX_TOKENS_DIGEST,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    return content


# ─── Project Health Analysis ──────────────────────────────────────────────────

async def analyse_project(
    project: dict,
    tasks: list,
    recent_prompts: list,
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> str:
    """Generate a detailed analysis of a single project."""
    age = f"{project['last_commit_age_days']:.0f} days" if project.get("last_commit_age_days") else "no git"
    task_summary = "\n".join(
        f"- [{t.get('priority','?')}] {t['title']}" for t in tasks[:10]
    ) or "No open tasks."
    prompt_summary = "\n".join(
        f"- {p['title']}: {p['content'][:100]}" for p in recent_prompts[:5]
    ) or "No saved prompts."

    prompt = f"""Analyse this software project and give actionable advice.

Project: {project['name']}
Stack: {project.get('stack', 'unknown')}
Path: {project.get('path', '')}
Health score: {project.get('health', 100)}/100
Last commit: {age} — "{project.get('last_commit', 'unknown')}"
TODO count: {project.get('todo_count', 0)}
Git branch: {project.get('git_branch', 'unknown')}
Status: {project.get('status', 'active')}
Note: {project.get('note', 'none')}

Open tasks:
{task_summary}

Saved prompts:
{prompt_summary}

Provide:
1. **Health assessment** — what's the state of this project?
2. **Top risks** — what could go wrong if nothing changes?
3. **Next 3 actions** — concrete, ordered by impact
4. **Technical debt** — any patterns you can infer from the TODO count and stack?

Be direct and practical. Under 250 words."""

    content, _ = await _call(prompt, api_key=api_key, api_provider=api_provider,
                              api_base_url=api_base_url, api_model=api_model, backend=backend,
                              cli_path=cli_path, cli_session_persistence=cli_session_persistence, max_tokens=MAX_TOKENS_TASK,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    return content


# ─── Smart Task Suggestions ──────────────────────────────────────────────────

async def suggest_tasks(
    projects: list,
    existing_tasks: list,
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> list[dict]:
    """Suggest new tasks based on project health and workload."""
    context = _build_context_block(projects, existing_tasks, [])

    prompt = f"""Based on the developer's current project state, suggest 3-5 specific tasks they should add to their todo list.

{context}

Return ONLY a JSON array with this structure:
[
  {{
    "title": "Clear task title",
    "project_name": "exact project name or null for general",
    "priority": "urgent|high|medium|low",
    "rationale": "one sentence why this matters"
  }}
]

Focus on: stale projects needing attention, TODO debt reduction, common developer oversights.
Return valid JSON only, no other text."""

    content, _ = await _call(prompt, api_key=api_key, api_provider=api_provider,
                              api_base_url=api_base_url, api_model=api_model, backend=backend,
                              cli_path=cli_path, cli_session_persistence=cli_session_persistence, max_tokens=600,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    import json
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ─── SMART Task Suggestions (per-project) ────────────────────────────────────

async def suggest_tasks_for_project(
    project: dict,
    existing_tasks: list,
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> list[dict]:
    """Generate SMART task suggestions for a single project based on its context."""
    proj_info = (
        f"Project: {project.get('name', '?')}\n"
        f"Stack: {project.get('stack', 'unknown')}\n"
        f"Health: {project.get('health', 0)}%\n"
        f"Branch: {project.get('git_branch', '?')}\n"
        f"Last commit: \"{project.get('last_commit', '?')}\" "
        f"({project.get('last_commit_age_days') or '?'} days ago)\n"
        f"TODOs: {project.get('todo_count', 0)}\n"
        f"Status: {project.get('status', 'active')}\n"
        f"Note: {project.get('note') or 'none'}"
    )
    existing = (
        "\n".join(f"- {t['title']} [{t['priority']}]" for t in existing_tasks[:10])
        or "None"
    )

    prompt = f"""Analyse this software project and suggest 3-5 specific, actionable SMART tasks.

{proj_info}

Existing open tasks:
{existing}

Return ONLY a valid JSON array — no markdown fences, no other text:
[
  {{
    "title": "Specific actionable task (verb + object)",
    "detail": "What to do and why — one sentence",
    "priority": "urgent|high|medium|low",
    "rationale": "One sentence on why this matters for project health"
  }}
]

Rules:
- Each task must be doable in 1–4 hours by a single developer
- Do NOT duplicate existing tasks
- Match the stack ({project.get('stack', 'unknown')}) — suggest stack-specific actions
- Focus on: TODO/FIXME debt, missing tests, stale dependencies, deployment risks,
  documentation gaps, security issues, performance hot-spots"""

    content, _ = await _call(prompt, api_key=api_key, api_provider=api_provider,
                              api_base_url=api_base_url, api_model=api_model, backend=backend,
                              cli_path=cli_path, cli_session_persistence=cli_session_persistence, max_tokens=700,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    import json as _json
    text = content.strip()
    # Strip markdown fences defensively
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip().lstrip("json").strip()
            if stripped.startswith("["):
                text = stripped
                break
    return _json.loads(text.strip())


# ─── Prompt Enhancer ─────────────────────────────────────────────────────────

async def enhance_prompt(
    raw_prompt: str,
    project_context: Optional[str] = None,
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    cli_session_persistence: bool = False,
    ollama_url: str = "",
    ollama_model: str = "",
) -> str:
    """Improve a rough prompt for clarity and effectiveness."""
    context_line = f"Project context: {project_context}" if project_context else ""
    prompt = f"""Improve this developer prompt to be clearer and more effective.
Keep the same intent. Do not add unnecessary fluff. Return only the improved prompt.

{context_line}

    Original prompt:
{raw_prompt}"""
    content, _ = await _call(prompt, api_key=api_key, api_provider=api_provider,
                              api_base_url=api_base_url, api_model=api_model, backend=backend,
                              cli_path=cli_path, cli_session_persistence=cli_session_persistence, max_tokens=MAX_TOKENS_TASK,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    return content
