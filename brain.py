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
import sqlite3
import time
import logging
from pathlib import Path
from typing import Optional, AsyncGenerator
import re as _re
import anthropic
import httpx
import gpu_guard
import resource_bank

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

# Default CLI-compatible paths (auto-detected)
_DEFAULT_CLI_PATHS = [
    "/home/edp/.config/Claude/claude-code/2.1.63/claude",
    "/home/edp/.vscode/extensions/anthropic.claude-code-2.1.81-linux-x64/resources/native-binary/claude",
    "/usr/local/bin/claude",
    "claude",
]


OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5-coder:7b"
OLLAMA_FAST_MODEL = "qwen2.5-coder:1.5b"    # quick tasks
OLLAMA_AGENT_MODEL = "qwen2.5-coder:7b"     # tool-calling / agent loops
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
        kwargs["base_url"] = api_base_url
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
        "options": {"num_predict": max_tokens, "num_ctx": execution["num_ctx"]},
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
        "options": {"num_predict": max_tokens, "num_ctx": execution["num_ctx"]},
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
) -> AsyncGenerator[str, None]:
    """Async generator yielding text chunks from an OpenAI-compatible streaming API."""
    base = (api_base_url or "https://api.deepseek.com").rstrip("/")
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1" if "/v1" not in base else base
    model = api_model or "deepseek-chat"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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


async def stream_chat(
    user_message: str,
    history: list[dict],
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    ollama_url: str = "",
    ollama_model: str = "",
) -> AsyncGenerator[str, None]:
    """Public async generator — yields chat response chunks (Ollama only, for SSE streaming)."""
    system = SYSTEM_PROMPT_OLLAMA
    if _is_general_planning_request(user_message):
        history = _filtered_general_history(history)
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

    messages: list[dict] = [{"role": "system", "content": system}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"][:600]})
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
    "pwd", "env", "python3", "python", "node", "npm", "npx", "yarn",
    "cargo", "go", "rustc", "make", "cmake", "pip", "pip3",
    "docker", "kubectl", "terraform", "supabase",
    "eas", "expo", "expo-cli",
    "which", "type", "file", "stat", "du", "df", "ps",
    "jq", "yq", "awk", "sed", "sort", "uniq", "cut", "tr",
])


def _tool_read_file(path: str, max_kb: int = 32) -> str:
    """Read a file, sandboxed to home directory."""
    p = os.path.realpath(os.path.expanduser(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory is not allowed."
    if not os.path.exists(p):
        return f"ERROR: File not found: {p}"
    if os.path.isdir(p):
        return f"ERROR: {p} is a directory — use list_dir."
    size = os.path.getsize(p)
    if size > max_kb * 1024:
        return f"ERROR: File too large ({size // 1024}KB > {max_kb}KB limit). Use head/tail or search_code."
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"=== {p} ({size} bytes) ===\n{content}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_list_dir(path: str = "~") -> str:
    """List directory contents, sandboxed to home."""
    p = os.path.realpath(os.path.expanduser(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory is not allowed."
    if not os.path.exists(p):
        return f"ERROR: Path not found: {p}"
    if not os.path.isdir(p):
        return f"ERROR: {p} is a file — use read_file."
    try:
        entries = sorted(os.scandir(p), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'DIR ' if e.is_dir() else 'FILE'} {e.name}" for e in entries if not e.name.startswith(".")]
        return f"=== {p} ===\n" + "\n".join(lines[:100])
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _tool_shell_cmd(cmd: str, cwd: str = "", timeout: int = 15) -> str:
    """Run a shell command (allowlisted). Returns stdout+stderr, truncated at 4KB."""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return f"ERROR: Invalid command: {e}"
    if not parts:
        return "ERROR: Empty command."
    base_cmd = os.path.basename(parts[0])
    if base_cmd not in _ALLOWED_CMDS:
        return f"ERROR: Command '{base_cmd}' is not in the allowed list. Allowed: {', '.join(sorted(_ALLOWED_CMDS))}"
    work_dir = os.path.realpath(os.path.expanduser(cwd)) if cwd else _HOME
    if not work_dir.startswith(_HOME):
        return "ERROR: cwd must be within home directory."
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


def _tool_git_status(path: str = "~") -> str:
    """Get git status + recent log for a directory."""
    p = os.path.realpath(os.path.expanduser(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    if not os.path.exists(p):
        return f"ERROR: Path not found: {p}"
    status = _tool_shell_cmd(f"git status --short", cwd=p)
    log = _tool_shell_cmd(f"git log --oneline -10", cwd=p)
    branch = _tool_shell_cmd(f"git branch --show-current", cwd=p)
    return f"Branch: {branch.strip()}\n\nStatus:\n{status}\n\nRecent commits:\n{log}"


def _tool_search_code(pattern: str, path: str = "~", glob: str = "*.py *.ts *.tsx *.js *.jsx") -> str:
    """Grep for a pattern in source files. Returns matching lines with context."""
    p = os.path.realpath(os.path.expanduser(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    includes = " ".join(f"--include={g}" for g in glob.split())
    cmd = f"grep -rn --max-count=3 {includes} -l {shlex.quote(pattern)} {shlex.quote(p)}"
    result = _tool_shell_cmd(cmd)
    return result[:3000] if len(result) > 3000 else result


def _tool_write_file(path: str, content: str) -> str:
    """Write content to a file (sandboxed to home)."""
    p = os.path.realpath(os.path.expanduser(path))
    if not p.startswith(_HOME):
        return "ERROR: Access outside home directory."
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {p}"
    except PermissionError:
        return f"ERROR: Permission denied: {p}"


def _normalize_tool_args(name: str, args: dict) -> dict:
    """Accept common argument aliases from weaker local models."""
    normalized = dict(args or {})

    if name == "shell_cmd":
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
        return {k: v for k, v in normalized.items() if k in {"cmd", "cwd", "timeout"}}

    if name in {"git_status", "list_dir", "read_file"}:
        if not normalized.get("path"):
            for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        for alias in ("cwd", "dir", "directory", "repo", "repository", "file"):
            normalized.pop(alias, None)
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

    if name == "write_file":
        if not normalized.get("path"):
            for alias in ("file", "target", "destination"):
                if normalized.get(alias):
                    normalized["path"] = normalized.pop(alias)
                    break
        if not normalized.get("content"):
            for alias in ("text", "body"):
                if normalized.get(alias):
                    normalized["content"] = normalized.pop(alias)
                    break
        for alias in ("file", "target", "destination", "text", "body"):
            normalized.pop(alias, None)
        return {k: v for k, v in normalized.items() if k in {"path", "content"}}

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


_TOOL_REGISTRY = {
    "read_file": _tool_read_file,
    "list_dir": _tool_list_dir,
    "shell_cmd": _tool_shell_cmd,
    "git_status": _tool_git_status,
    "search_code": _tool_search_code,
    "write_file": _tool_write_file,
    "create_mission": lambda **kw: _tool_mission_create(**kw),
    "update_mission": lambda **kw: _tool_mission_update(**kw),
    "list_missions": lambda **kw: _tool_mission_list(**kw),
}

AGENT_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the filesystem. Returns file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (absolute or ~-relative)"},
                    "max_kb": {"type": "integer", "description": "Max KB to read (default 32)", "default": 32},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: ~)", "default": "~"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_cmd",
            "description": "Run an allowlisted shell command (git, ls, grep, python3, etc.) and return output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory (default: home)", "default": "~"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 15)", "default": 15},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git branch, status, and recent commit log for a project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in source code files using grep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "~"},
                    "glob": {"type": "string", "description": "File glob patterns (space-separated)", "default": "*.py *.ts *.tsx *.js *.jsx"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_mission",
            "description": "Create a new mission (task) for tracking. Use this when the user asks to create, add, or queue a mission/task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short mission title (e.g. 'Fix login page bug')"},
                    "detail": {"type": "string", "description": "Detailed description of what needs to be done", "default": ""},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Priority level", "default": "medium"},
                    "project_id": {"type": "integer", "description": "Project ID to link to (optional)"},
                    "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format (optional)"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_mission",
            "description": "Update an existing mission's status or fields. Use this to mark missions as done, in_progress, or to change details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {"type": "integer", "description": "The mission ID to update"},
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "New status"},
                    "title": {"type": "string", "description": "Updated title"},
                    "detail": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Updated priority"},
                    "due_date": {"type": "string", "description": "Updated due date (YYYY-MM-DD)"},
                },
                "required": ["mission_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_missions",
            "description": "List current missions/tasks, optionally filtered by status or project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "done", "cancelled"], "description": "Filter by status (default: all open)"},
                    "project_id": {"type": "integer", "description": "Filter by project ID"},
                },
                "required": [],
            },
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name with the given arguments."""
    fn = _TOOL_REGISTRY.get(name)
    if not fn:
        return f"ERROR: Unknown tool '{name}'"
    try:
        return fn(**_normalize_tool_args(name, args))
    except TypeError as e:
        return f"ERROR: Bad arguments for {name}: {e}"
    except Exception as e:
        return f"ERROR: {name} failed: {e}"


def _project_name_pattern(name: str) -> str:
    parts = [part for part in _re.split(r"[^a-z0-9]+", (name or "").lower()) if part]
    if not parts:
        return ""
    return rf"(?<![a-z0-9]){'[\\s/_-]*'.join(_re.escape(part) for part in parts)}(?![a-z0-9])"


def _resolve_project_path_from_text(text: str) -> Optional[str]:
    """Resolve a scanned Axon workspace name mentioned in free text."""
    if not DEVBRAIN_DB_PATH.exists():
        return None

    lower = text.lower()
    try:
        with sqlite3.connect(str(DEVBRAIN_DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT name, path FROM projects "
                "WHERE COALESCE(status, 'active') != 'archived' "
                "ORDER BY LENGTH(name) DESC"
            ).fetchall()
    except sqlite3.Error:
        return None

    for name, path in rows:
        pattern = _project_name_pattern(name)
        if pattern and _re.search(pattern, lower):
            return path
    return None


def _extract_path_from_text(text: str) -> Optional[str]:
    """Best-effort path extraction for common local-path requests."""
    candidates = _re.findall(r'(~\/[^\s,"\')]+|\/home\/[^\s,"\')]+)', text)
    if candidates:
        return candidates[0].rstrip(".,:;!?")

    lower = text.lower()
    common_paths = [
        ("desktop", "~/Desktop"),
        ("downloads", "~/Downloads"),
        ("documents", "~/Documents"),
        ("pictures", "~/Pictures"),
        ("music", "~/Music"),
        ("videos", "~/Videos"),
        ("home directory", "~"),
        ("home folder", "~"),
        ("home", "~"),
    ]
    for label, path in common_paths:
        if label in lower:
            return path
    return _resolve_project_path_from_text(text)


def _recent_repo_path(history: list[dict] | None = None, project_name: Optional[str] = None) -> Optional[str]:
    """Reuse the most recent explicit or workspace-derived path from chat history."""
    if project_name:
        project_path = _resolve_project_path_from_text(project_name)
        if project_path:
            return project_path

    for item in reversed(history or []):
        content = str(item.get("content", "") or "")
        path = _extract_path_from_text(content)
        if path:
            return path
    return None


def _contains_phrase(text: str, phrase: str) -> bool:
    lower = (text or "").lower()
    token = (phrase or "").lower().strip()
    if not token:
        return False
    return bool(_re.search(rf"(?<![a-z0-9]){_re.escape(token)}(?![a-z0-9])", lower))


def _has_local_operator_markers(text: str) -> bool:
    lower = (text or "").lower()
    return (
        bool(_extract_path_from_text(text or ""))
        or "action:" in lower
        or "args:" in lower
        or "answer:" in lower
        or any(_contains_phrase(lower, term) for term in (
            "git ", "git status", "branch", "commit", "repo", "repository",
            "workspace", "file", "folder", "directory", "path", "readme",
            ".py", ".ts", ".tsx", ".js", ".jsx", ".md", "package.json",
            "list_dir", "shell_cmd", "read_file", "search_code",
        ))
    )


def _filtered_general_history(history: list[dict] | None = None) -> list[dict]:
    filtered: list[dict] = []
    for item in history or []:
        content = str(item.get("content", "") or "")
        if not content.strip():
            continue
        if _has_local_operator_markers(content):
            continue
        filtered.append({"role": item.get("role", "user"), "content": content[:500]})
    return filtered[-4:]


def _is_general_planning_request(user_message: str) -> bool:
    lower = (user_message or "").strip().lower()
    if not lower:
        return False

    local_action_terms = (
        "git", "repo", "repository", "branch", "commit", "file", "files", "folder",
        "folders", "directory", "directories", "desktop", "workspace", "scan", "inspect",
        "search code", "read ", "open ", "run ", "execute ", "check ", "look at ",
    )
    if any(_contains_phrase(lower, term) for term in local_action_terms):
        return False
    if _extract_path_from_text(user_message):
        return False

    business_terms = (
        "company profile", "business profile", "enterprise", "company", "business",
        "capability statement", "proposal", "strategy", "go-to-market", "brand profile",
        "executive summary", "corporate profile", "mission statement", "vision statement",
        "service offering", "value proposition", "pitch deck", "brochure", "profile for me",
    )
    writing_terms = (
        "plan", "draft", "write", "create", "prepare", "outline", "summarize",
        "improve", "rewrite", "structure",
    )
    return any(_contains_phrase(lower, term) for term in business_terms) and any(_contains_phrase(lower, term) for term in writing_terms)


def _parse_list_dir_entries(result: str) -> list[tuple[str, str]]:
    """Parse _tool_list_dir output into (kind, name) pairs."""
    entries: list[tuple[str, str]] = []
    for line in result.splitlines():
        if line.startswith("DIR "):
            entries.append(("dir", line[4:].strip()))
        elif line.startswith("FILE "):
            entries.append(("file", line[5:].strip()))
    return entries


def _format_listing_answer(path: str, names: list[str], label: str) -> str:
    resolved = os.path.realpath(os.path.expanduser(path))
    if not names:
        return f"I checked `{resolved}` and there are no visible {label} there."
    visible = names[:40]
    bullets = "\n".join(f"- {name}" for name in visible)
    more = ""
    if len(names) > len(visible):
        more = f"\n- ...and {len(names) - len(visible)} more"
    return f"Here are the {label} in `{resolved}`:\n{bullets}{more}"


def _direct_agent_action(
    user_message: str,
    history: list[dict] | None = None,
    project_name: Optional[str] = None,
) -> tuple[str, dict, str, str] | None:
    """
    Handle obvious local actions deterministically so the agent behaves like a copilot
    even when the model does not emit a tool call.
    Returns (tool_name, args, tool_result, final_answer) or None.
    """
    lower = user_message.lower()

    power_phrases = (
        "reboot", "restart the system", "restart my system", "restart the machine",
        "restart my machine", "restart the computer", "restart my computer",
        "shutdown", "shut down", "power off", "poweroff", "turn off the computer",
        "turn off the machine", "halt the system",
    )
    if any(phrase in lower for phrase in power_phrases):
        answer = (
            "I can't reboot or power off this system directly from chat.\n\n"
            "- Full power actions stay blocked in agent mode by design.\n"
            "- Open `Settings -> System Actions` for the guided restart and reboot flow.\n"
            "- From there, Axon can restart safe local services or prepare the exact OS command for you to run manually."
        )
        return "shell_cmd", {"cmd": "echo blocked-power-action"}, "BLOCKED: power action not allowed", answer

    path = _extract_path_from_text(user_message)
    lower_has_git = any(term in lower for term in ("git", "branch", "repo", "repository", "status", "commit"))
    if not path and lower_has_git:
        path = _recent_repo_path(history, project_name)

    if not path:
        return None

    branch_list_phrases = (
        "list all branches", "list branches", "show all branches", "show branches",
        "what branches", "which branches",
    )
    if any(phrase in lower for phrase in branch_list_phrases):
        tool_name = "shell_cmd"
        tool_args = {"cmd": "git branch --all --no-color", "cwd": path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        branches = [line.rstrip() for line in tool_result.splitlines() if line.strip()]
        visible = "\n".join(f"- {line}" for line in branches[:80]) if branches else "- (no branches found)"
        answer = f"Here are the branches in `{os.path.realpath(os.path.expanduser(path))}`:\n{visible}"
        return tool_name, tool_args, tool_result, answer

    status_phrases = (
        "git status", "report the status", "repo status", "repository status",
        "working tree", "uncommitted changes",
    )
    if any(phrase in lower for phrase in status_phrases):
        tool_name = "git_status"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        return tool_name, tool_args, tool_result, tool_result

    branch_verify_match = _re.search(r'\b(?:verify|confirm|check)\b.*?\b(?:the )?([a-z0-9._/-]+)\s+branch\b', lower)
    current_branch_phrases = ("current branch", "which branch", "what branch", "verify this is the branch")
    if branch_verify_match or any(phrase in lower for phrase in current_branch_phrases):
        tool_name = "shell_cmd"
        tool_args = {"cmd": "git branch --show-current", "cwd": path, "timeout": 15}
        tool_result = _execute_tool(tool_name, tool_args)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result
        current_branch = tool_result.strip().splitlines()[-1].strip()
        target_branch = branch_verify_match.group(1).strip() if branch_verify_match else ""
        if target_branch:
            if current_branch == target_branch:
                answer = f"Yes — `{os.path.realpath(os.path.expanduser(path))}` is currently on the `{current_branch}` branch."
            else:
                answer = f"No — `{os.path.realpath(os.path.expanduser(path))}` is on `{current_branch}`, not `{target_branch}`."
        else:
            answer = f"`{os.path.realpath(os.path.expanduser(path))}` is currently on the `{current_branch}` branch."
        return tool_name, tool_args, tool_result, answer

    listing_phrases = (
        "list", "show", "what's in", "what is in", "contents of", "items in", "items on",
        "folders in", "folders on", "directories in", "directories on", "files in", "files on",
        "inside",
    )
    if any(phrase in lower for phrase in listing_phrases):
        tool_name = "list_dir"
        tool_args = {"path": path}
        tool_result = _execute_tool(tool_name, tool_args)
        if tool_result.startswith("ERROR:"):
            return tool_name, tool_args, tool_result, tool_result

        parsed = _parse_list_dir_entries(tool_result)
        wants_all = any(phrase in lower for phrase in ("contents", "inside", "what's in", "what is in", "items"))
        wants_dirs = any(word in lower for word in ("folder", "folders", "directory", "directories")) and not wants_all
        wants_files = ("file" in lower or "files" in lower) and not wants_dirs and not wants_all

        if wants_all:
            names = [name for _, name in parsed]
            label = "items"
        elif wants_dirs:
            names = [name for kind, name in parsed if kind == "dir"]
            label = "folders"
        elif wants_files:
            names = [name for kind, name in parsed if kind == "file"]
            label = "files"
        else:
            names = [name for _, name in parsed]
            label = "items"

        answer = _format_listing_answer(path, names, label)
        return tool_name, tool_args, tool_result, answer

    return None


def _build_react_system(context_block: str, project_name: Optional[str], tool_names: list[str]) -> str:
    """Build ReAct-style system prompt for the agent."""
    tool_list = "\n".join(f"- {n}" for n in tool_names)

    # Self-improvement context when working on the Axon codebase
    axon_ctx = ""
    if project_name and ("axon" in project_name.lower() or "devbrain" in project_name.lower() or "dashpro" in project_name.lower()):
        axon_ctx = """

SELF-IMPROVEMENT MODE — You are working on your own codebase (Axon).
Axon lives at ~/.devbrain/ and you can read, search, and modify your own source code.

Architecture:
  server.py    — FastAPI app (~5800 lines), all API routes, SSE streaming
  brain.py     — AI orchestration, ReAct agent loop, tool execution, model routing
  db.py        — SQLite schema + CRUD (aiosqlite), 20+ tables
  scheduler.py — APScheduler background jobs (scans, digests, webhook queue)
  integrations.py — GitHub CLI, Slack webhooks, generic webhook retry queue
  vault.py     — AES-256-GCM encrypted secrets with TOTP
  memory_engine.py — Memory layer (facts, preferences, project context)
  scanner.py   — Project directory scanner
  model_router.py — Multi-provider model selection
  ui/index.html — SPA (Alpine.js + Tailwind), ~5900 lines
  ui/js/       — chat.js, helpers.js, dashboard.js, settings.js, voice.js
  ui/styles.css — Custom styles for prose, canvas, animations

Key patterns:
  - Routes use: async with devdb.get_db() as conn
  - Agent tools: _TOOL_REGISTRY dict, AGENT_TOOL_DEFS list
  - SSE events: {"type": "text|thinking|tool_call|tool_result|done|error"}
  - DB: aiosqlite with row_factory, init_db() for schema migrations
  - Venv: .venv/bin/python, deps in requirements.txt

When asked to improve Axon, use read_file + search_code to understand the current code,
then write_file to make changes. Test with shell_cmd: "cd ~/.devbrain && .venv/bin/python -c 'import ast; ast.parse(open(\"<file>\").read()); print(\"OK\")'".
After changes, suggest the user restart Axon (axon restart) to apply."""

    return f"""You are Axon Agent — a local AI operator that can use tools to help developers.

Available tools: {', '.join(tool_names)}

To use a tool, output EXACTLY in this format (no extra text before it):
ACTION: tool_name
ARGS: {{"arg1": "value1"}}

When you have the final answer, output EXACTLY:
ANSWER: your response here

Rules:
- ALWAYS use tools for: find, locate, search, where is, list, read, check, run, show me, open, what files, what is in, scan, look for, get, fetch — do NOT describe how the user could do it themselves.
- Use tools when you need real data (file contents, git status, directory listings, search results, etc.)
- If the user asks you to find/locate/search for ANYTHING on the filesystem — do it yourself with search_files or list_dir. Never tell the user to open Finder or File Explorer.
- When the user asks to create/add/track a mission or task, use create_mission immediately. When asked to complete/update a mission, use update_mission. Use list_missions to check current missions.
- Do not give the user shell instructions for tasks you can complete with the available tools.
- Only skip tools for pure creative writing, brainstorming, or math that requires NO local data.
- After seeing tool results, either use another tool or give ANSWER
- Be concise in ANSWER — use markdown
- Never make up file contents or command output
- All paths must start with ~ or /home/{os.getenv('USER', 'edp')}
{axon_ctx}
{('Context: ' + context_block[:800]) if context_block else ''}
{('Project: ' + project_name) if project_name else ''}"""


def _sanitize_agent_text(text: str) -> str:
    """Remove leaked internal ReAct instructions before showing text to the user."""
    skip_contains = (
        "To use a tool, output EXACTLY in this format",
        "When you have the final answer, output EXACTLY",
        "EXACTLY in this format (no extra text before it)",
        "ANSWER: your response here",
    )
    skip_exact = {
        "ACTION: tool_name",
        'ARGS: {"arg1": "value1"}',
    }

    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if stripped in skip_exact:
            continue
        if any(marker in stripped for marker in skip_contains):
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _parse_react_action(text: str) -> tuple[str, dict] | None:
    """Parse ACTION/ARGS from ReAct-formatted text. Returns (tool_name, args) or None."""
    action_match = _re.search(r'ACTION:\s*(\w+)', text)
    args_match = _re.search(r'ARGS:\s*(\{[^}]*\}|\{[\s\S]*?\})', text)
    if not action_match:
        return None
    tool_name = action_match.group(1).strip()
    if tool_name == "tool_name":
        return None
    args = {}
    if args_match:
        try:
            args = json.loads(args_match.group(1))
        except json.JSONDecodeError:
            # Try to extract key-value pairs loosely
            for kv in _re.findall(r'"(\w+)":\s*"([^"]*)"', args_match.group(1)):
                args[kv[0]] = kv[1]
    return tool_name, args


async def run_agent(
    user_message: str,
    history: list[dict],
    context_block: str = "",
    resource_context: str = "",
    resource_image_paths: Optional[list[str]] = None,
    vision_model: str = "",
    project_name: Optional[str] = None,
    tools: list[str] | None = None,
    ollama_url: str = "",
    ollama_model: str = "",
    max_iterations: int = 6,
    force_tool_mode: bool = False,
    api_key: str = "",
    api_base_url: str = "",
    api_model: str = "",
    api_provider: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Async generator yielding agent events (ReAct-style, streaming-compatible):
      {"type": "text",        "chunk": str}
      {"type": "tool_call",   "name": str, "args": dict}
      {"type": "tool_result", "name": str, "result": str}
      {"type": "done",        "iterations": int}

    Uses ReAct text-based tool calling (reliable across all Ollama models).
    """
    active_tool_names = list(_TOOL_REGISTRY.keys()) if tools is None else [
        t for t in tools if t in _TOOL_REGISTRY
    ]

    use_api = bool(api_key and api_base_url)

    if not force_tool_mode and _is_general_planning_request(user_message):
        system = (
            "You are Axon, a calm and practical AI operator.\n"
            "This request is a general planning or writing task, not a local tool task.\n"
            "Do not use tools. Do not inspect files or directories unless the user explicitly asks for local data.\n"
            "Answer directly with a clear structure, a concise draft, and 2-4 helpful next-step options."
        )
        if resource_context:
            system += f"\n\nUse these attached resources when they are relevant:\n{resource_context[:5000]}"
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend(_filtered_general_history(history))

        if use_api:
            messages.append({"role": "user", "content": user_message})
            async for chunk in _stream_api_chat(
                messages=messages, api_key=api_key,
                api_base_url=api_base_url, api_model=api_model, max_tokens=1200,
            ):
                yield {"type": "text", "chunk": chunk}
        else:
            execution = await asyncio.to_thread(
                _ollama_execution_profile_sync,
                vision_model or ollama_model or OLLAMA_DEFAULT_MODEL,
                ollama_url, streaming=True, purpose="chat",
            )
            messages.append(_ollama_message_with_images(user_message, resource_image_paths))
            if execution.get("note"):
                yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}
            async for chunk in _stream_ollama_chat(
                messages=messages, model=execution["model"],
                max_tokens=1200, ollama_url=ollama_url, purpose="chat",
            ):
                yield {"type": "text", "chunk": chunk}
        yield {"type": "done", "iterations": 1}
        return

    direct_action = _direct_agent_action(user_message, history=history, project_name=project_name)
    if direct_action:
        tool_name, tool_args, result, answer = direct_action
        yield {"type": "tool_call", "name": tool_name, "args": tool_args}
        yield {"type": "tool_result", "name": tool_name, "result": result[:2000]}
        yield {"type": "text", "chunk": answer}
        yield {"type": "done", "iterations": 1}
        return

    system_context = context_block
    if resource_context:
        system_context = f"{system_context}\n\n{resource_context}" if system_context else resource_context
    system = _build_react_system(system_context, project_name, active_tool_names)

    messages: list[dict] = [{"role": "system", "content": system}]
    for h in history[-4:]:
        messages.append({"role": h["role"], "content": h["content"][:400]})

    if use_api:
        messages.append({"role": "user", "content": user_message})
    else:
        execution = await asyncio.to_thread(
            _ollama_execution_profile_sync,
            vision_model or ollama_model or OLLAMA_AGENT_MODEL,
            ollama_url, streaming=True, purpose="agent",
        )
        messages.append(_ollama_message_with_images(user_message, resource_image_paths))

    for iteration in range(max_iterations):
        # Collect streamed response
        full_text = ""
        try:
            if use_api:
                async for chunk in _stream_api_chat(
                    messages=messages, api_key=api_key,
                    api_base_url=api_base_url, api_model=api_model, max_tokens=800,
                ):
                    full_text += chunk
            else:
                if iteration == 0 and execution.get("note"):
                    yield {"type": "text", "chunk": f"⚠️ {execution['note']}\n\n"}
                async for chunk in _stream_ollama_chat(
                    messages=messages, model=execution["model"],
                    max_tokens=800, ollama_url=ollama_url, purpose="agent",
                ):
                    full_text += chunk
        except Exception as exc:
            provider_label = api_provider or ("API" if use_api else "Ollama")
            yield {"type": "text", "chunk": f"\n⚠️ {provider_label} error: {exc}"}
            break

        if not full_text.strip():
            yield {"type": "text", "chunk": "\n⚠️ Empty response from model."}
            break

        # Parse for ReAct patterns
        action = _parse_react_action(full_text)
        answer_match = _re.search(r'ANSWER:\s*([\s\S]+)', full_text)
        clean_text = _sanitize_agent_text(full_text)

        if action:
            tool_name, tool_args = action
            # Emit the thinking text (everything before ACTION:)
            think_text = full_text[:full_text.find("ACTION:")].strip()
            think_text = _sanitize_agent_text(think_text)
            if think_text:
                yield {"type": "thinking", "chunk": think_text}

            yield {"type": "tool_call", "name": tool_name, "args": tool_args}
            result = await asyncio.to_thread(_execute_tool, tool_name, tool_args)
            yield {"type": "tool_result", "name": tool_name, "result": result[:2000]}

            messages.append({"role": "assistant", "content": full_text})
            messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{result[:2000]}\n\nContinue."})

        elif answer_match:
            answer = _sanitize_agent_text(answer_match.group(1).strip())
            if not answer or answer == "your response here":
                yield {"type": "text", "chunk": "\n⚠️ Axon could not form a clean answer. Please retry the task."}
                break
            yield {"type": "text", "chunk": answer}
            break
        else:
            # No pattern found — emit as-is (final answer without ANSWER: prefix)
            if clean_text:
                yield {"type": "text", "chunk": clean_text}
            else:
                yield {"type": "text", "chunk": "\n⚠️ Axon produced an invalid tool response. Please retry the task."}
            break

    yield {"type": "done", "iterations": iteration + 1}


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


def _find_cli(override_path: str = "") -> str:
    """Find the claude CLI binary."""
    if override_path and os.path.isfile(override_path):
        return override_path
    for p in _DEFAULT_CLI_PATHS:
        if p == "claude":
            import shutil
            found = shutil.which("claude")
            if found:
                return found
        elif os.path.isfile(p):
            return p
    return ""


async def _call_cli(prompt: str, system: str = "", cli_path: str = "") -> str:
    """
    Call the CLI agent bridge in non-interactive (-p) mode.
    Uses your locally installed CLI agent — no API key needed.
    """
    binary = _find_cli(cli_path)
    if not binary:
        raise RuntimeError("CLI agent not found. Set the path in Settings or switch to a different runtime.")

    full_prompt = prompt
    if system:
        full_prompt = f"<system>\n{system}\n</system>\n\n{prompt}"

    cmd = [binary, "-p", "--output-format", "json", full_prompt]

    # Strip CLAUDECODE so the CLI doesn't refuse to run inside another Claude session
    clean_env = {**os.environ, "NO_COLOR": "1"}
    clean_env.pop("CLAUDECODE", None)
    clean_env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=clean_env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"CLI agent error: {err[:300]}")

    raw = stdout.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(raw)
        text = data.get("result", "")
        usage = data.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        cost = float(data.get("total_cost_usd", 0.0))
        _track_usage(tokens, cost, backend="cli")
    except (json.JSONDecodeError, KeyError):
        text = raw   # fallback: treat raw as plain text
        tokens = 0

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


# ─── System Prompts ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Axon, a local AI Operator for a software developer.
You know everything about their active workspaces, missions, and saved playbooks.
You help them stay focused, organised, and productive.

Your personality:
- Direct and concise — no fluff, no padding
- Proactively flag risks (stale workspaces, overdue missions, patterns)
- South African developer context: Rands (R), local references OK
- When asked about code, give concrete actionable answers
- You remember the context of this conversation

When giving advice:
1. Be specific — mention actual project names, file paths, task titles
2. Prioritise ruthlessly — what matters TODAY?
3. Flag things that are quietly rotting (old commits, many TODOs)
4. Celebrate wins — when something ships, say so

Format rules:
- Use markdown for structure when it helps
- Keep lists short (max 5 items unless explicitly asked)
- Prefer bullet points over paragraphs for action items"""

SYSTEM_PROMPT_OLLAMA = """You are Axon, a local AI Operator for a software developer.
Be concise, direct, and practical. Use markdown when it helps.
Focus on actionable advice. Mention specific project names, file paths, task titles when relevant.
Keep responses under 400 words unless asked for more detail."""


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
ESCALATION_MODEL = "deepseek-chat"

# Model overrides by role for API backends
# deepseek-chat handles code well; only reasoning gets a distinct model
API_MODEL_BY_ROLE: dict[str, dict[str, str]] = {
    "deepseek": {"reasoning": "deepseek-reasoner"},
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
    max_tokens: int = MAX_TOKENS_CHAT,
    model: str = "",
    ollama_url: str = "",
    ollama_model: str = "",
) -> tuple[str, int]:
    """Route a call to the API, CLI, or local Ollama backend.
    When backend='ollama' and the call fails, automatically escalates
    to a cloud API if a key is available."""
    if backend == "cli":
        content, tokens = await _call_cli(prompt, system=system, cli_path=cli_path)
        return content, tokens
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
    api_key: str = "",
    api_provider: str = "anthropic",
    api_base_url: str = "",
    api_model: str = "",
    backend: str = "api",
    cli_path: str = "",
    ollama_url: str = "",
    ollama_model: str = "",
) -> dict:
    """
    Send a chat message and return {"content": str, "tokens": int}.
    Supports local Ollama, CLI agent, and external API runtimes.
    """
    system = SYSTEM_PROMPT_OLLAMA if backend == "ollama" else SYSTEM_PROMPT
    if _is_general_planning_request(user_message):
        history = _filtered_general_history(history)
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

    if backend == "ollama":
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
        for h in history[-6:]:
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
    elif backend == "cli":
        hist_limit = 10
        history_text = ""
        for h in history[-hist_limit:]:
            role = "User" if h["role"] == "user" else "Assistant"
            history_text += f"\n{role}: {h['content'][:300]}"
        if history_text:
            history_text += "\n"
        full_prompt = f"{history_text}User: {user_message}\nAssistant:"
        content, tokens = await _call(
            full_prompt, system=system, backend=backend,
            cli_path=cli_path, ollama_url=ollama_url, ollama_model=ollama_model,
            api_key=api_key, api_provider=api_provider, api_base_url=api_base_url, api_model=api_model,
            max_tokens=MAX_TOKENS_CHAT,
        )
    else:
        messages = []
        for h in history[-20:]:
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
                              cli_path=cli_path, max_tokens=MAX_TOKENS_DIGEST,
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
                              cli_path=cli_path, max_tokens=MAX_TOKENS_TASK,
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
                              cli_path=cli_path, max_tokens=600,
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
                              cli_path=cli_path, max_tokens=700,
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
                              cli_path=cli_path, max_tokens=MAX_TOKENS_TASK,
                              ollama_url=ollama_url, ollama_model=ollama_model)
    return content
