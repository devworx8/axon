"""Axon — Autonomous error-fix pipeline.

Orchestrates the flow:
  1. Pick an unresolved error
  2. Dispatch it to brain.chat() with the proper runtime params
  3. Update the error status based on the result
"""
from __future__ import annotations

import json
import logging
from typing import Any

from axon_data import (
    get_db,
    get_all_settings,
    get_setting,
    get_unresolved_errors,
    update_error_status,
)

log = logging.getLogger(__name__)


async def is_auto_fix_enabled() -> bool:
    async with get_db() as db:
        val = await get_setting(db, "auto_fix_enabled")
    return str(val or "0").strip() == "1"


async def pick_next_error() -> dict | None:
    """Return the highest-priority unresolved error, or None."""
    async with get_db() as db:
        rows = await get_unresolved_errors(db, limit=1)
    return rows[0] if rows else None


async def dispatch_fix(error: dict) -> dict[str, Any]:
    """Send an error to brain.chat() for fixing."""
    error_id = error["id"]
    title = error.get("title", "")
    meta = json.loads(error.get("meta_json", "{}"))
    source = error.get("source", "")
    project = error.get("project_name", "")

    prompt = _build_fix_prompt(title, meta, source, project)

    async with get_db() as db:
        await update_error_status(db, error_id, "triaging")

    try:
        result = await _run_chat_fix(prompt, error)
        async with get_db() as db:
            status = "fixed" if result.get("success") else "new"
            await update_error_status(
                db, error_id, status,
                fix_session_id=result.get("session_id", ""),
            )
        return result
    except Exception as exc:
        log.error("Auto-fix dispatch failed for error %s: %s", error_id, exc)
        async with get_db() as db:
            await update_error_status(db, error_id, "new")
        return {"success": False, "error": str(exc)}


def _build_fix_prompt(title: str, meta: dict, source: str, project: str) -> str:
    parts = [
        f"[Auto-Fix] Error detected via {source}.",
        f"Project: {project}" if project else "",
        f"Error: {title}",
    ]
    if meta.get("sentry_link"):
        parts.append(f"Sentry link: {meta['sentry_link']}")
    if meta.get("culprit"):
        parts.append(f"Culprit: {meta['culprit']}")
    parts.append(
        "\nInvestigate this error, find the root cause, fix it, "
        "commit the change, push to a feature branch, and open a PR. "
        "Explain what you found and what you changed."
    )
    return "\n".join(p for p in parts if p)


async def _resolve_runtime_kwargs() -> dict[str, Any]:
    """Load settings and build the kwargs that brain.chat() needs."""
    async with get_db() as db:
        settings = await get_all_settings(db)

    backend = settings.get("ai_backend", "ollama")
    kwargs: dict[str, Any] = {"backend": backend}

    if backend == "cli":
        kwargs["cli_path"] = settings.get("claude_cli_path", "")
        kwargs["cli_model"] = settings.get("standard_model", "")
        kwargs["cli_session_persistence"] = (
            settings.get("claude_cli_session_persistence_enabled", "0") == "1"
        )
    elif backend == "ollama":
        kwargs["ollama_url"] = settings.get("ollama_url", "http://localhost:11434")
        kwargs["ollama_model"] = settings.get("ollama_model", "llama3.1")
    else:
        kwargs["api_key"] = settings.get("anthropic_api_key", "")
        kwargs["api_provider"] = "anthropic"
        kwargs["api_model"] = settings.get("standard_model", "")

    return kwargs


async def _run_chat_fix(prompt: str, error: dict) -> dict[str, Any]:
    """Call brain.chat() with resolved runtime settings."""
    try:
        import brain
        runtime = await _resolve_runtime_kwargs()
        result = await brain.chat(
            prompt,
            history=[],
            context_block="",
            project_name=error.get("project_name", ""),
            workspace_path="",
            **runtime,
        )
        content = result.get("content", "")
        return {
            "success": bool(content),
            "session_id": "",
            "response_preview": content[:500],
        }
    except Exception as exc:
        log.error("Agent fix run failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def run_auto_fix_cycle() -> dict:
    """Run one cycle: pick an error and dispatch a fix.

    Called by the scheduler or manually via API.
    """
    if not await is_auto_fix_enabled():
        return {"status": "disabled"}

    error = await pick_next_error()
    if not error:
        return {"status": "no_errors"}

    log.info("Auto-fix: picking up error #%s — %s", error["id"], error.get("title", ""))
    result = await dispatch_fix(error)
    return {"status": "completed", "error_id": error["id"], "result": result}
