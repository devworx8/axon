"""Chat context and fast-path helpers extracted from server.py."""
from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime
from typing import Optional


async def memory_bundle(
    memory_engine_module,
    ensure_memory_layers_synced_fn,
    composer_memory_layers_fn,
    conn,
    *,
    user_message: str,
    project_id: Optional[int],
    resource_ids: list[int],
    settings: dict,
    composer_options: dict,
    snapshot_revision: str = "",
) -> dict:
    if str(settings.get("memory_first_enabled", "1")).strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "items": [],
            "context_block": "",
            "overview": {"total": 0, "layers": {}, "state": "memory_first_disabled"},
            "evidence_source": "model_only",
        }
    try:
        await ensure_memory_layers_synced_fn(conn, settings)
    except sqlite3.DatabaseError as exc:
        print(f"[Axon] Memory bundle sync degraded: {exc}")
    layers = composer_memory_layers_fn(composer_options, has_attached_resources=bool(resource_ids))
    intelligence = str(composer_options.get("intelligence_mode") or "ask").lower()
    limit = 8 if intelligence == "deep_research" else 5
    results = await memory_engine_module.search_memory(
        conn,
        query=user_message,
        settings=settings,
        workspace_id=project_id,
        layers=layers,
        limit=limit,
        snapshot_revision=snapshot_revision,
    )
    try:
        overview = await memory_engine_module.build_memory_overview(conn)
    except sqlite3.DatabaseError as exc:
        print(f"[Axon] Memory overview degraded: {exc}")
        overview = {"total": 0, "layers": {}, "state": "degraded"}
    return {
        "items": results,
        "context_block": memory_engine_module.build_memory_context(results),
        "overview": overview,
        "evidence_source": "memory" if results else "model_only",
    }


async def ensure_memory_layers_synced(
    memory_engine_module,
    memory_sync_cache: dict,
    memory_sync_cache_ttl_seconds: float,
    conn,
    settings: dict,
    *,
    force: bool = False,
) -> dict:
    now = time.time()
    cached_overview = memory_sync_cache.get("overview")
    cached_at = float(memory_sync_cache.get("checked_at") or 0.0)
    if (
        not force
        and isinstance(cached_overview, dict)
        and cached_overview
        and (now - cached_at) < memory_sync_cache_ttl_seconds
    ):
        return dict(cached_overview)

    overview = await memory_engine_module.sync_memory_layers(conn, settings)
    memory_sync_cache["checked_at"] = now
    memory_sync_cache["overview"] = dict(overview or {})
    return dict(overview or {})


def setting_int(settings: dict, key: str, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(str(settings.get(key, default) or default).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def compact_text(value: str, *, limit: int = 180) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_thread_summary_text(rows, *, parse_stored_chat_message_fn) -> str:
    if not rows:
        return ""
    lines = ["## Conversation Summary"]
    for raw_row in rows[-12:]:
        row = dict(raw_row)
        parsed = parse_stored_chat_message_fn(str(row.get("content") or ""))
        content = compact_text(str(parsed.get("content") or ""), limit=180)
        if not content:
            continue
        role = str(row.get("role") or "assistant").strip().lower()
        label = "User" if role == "user" else "Axon"
        lines.append(f"- {label}: {content}")
    return "\n".join(lines[:13])


async def workspace_snapshot_bundle(
    db_module,
    brain_module,
    json_module,
    conn,
    *,
    project_id: Optional[int],
    settings: dict,
) -> dict:
    if project_id is None:
        projects = [dict(row) for row in await db_module.get_projects(conn, status="active")]
        tasks = [dict(row) for row in await db_module.get_tasks(conn, status="open")]
        prompts_list = [dict(row) for row in await db_module.get_prompts(conn)]
        context_block = brain_module._build_context_block(projects, tasks, prompts_list)
        return {
            "revision": "global",
            "context_block": context_block,
            "data": {"projects": projects[:10], "tasks": tasks[:10], "prompts": prompts_list[:5]},
            "evidence_source": "workspace_snapshot",
        }

    ttl_seconds = setting_int(settings, "workspace_snapshot_ttl_seconds", 60, minimum=10, maximum=3600)
    snapshot_key = f"workspace:{project_id}"
    revision = await db_module.compute_workspace_revision(conn, project_id)
    existing = await db_module.get_workspace_snapshot(conn, workspace_id=project_id, snapshot_key=snapshot_key)
    if existing and str(existing["revision"] or "") == revision:
        updated_at = str(existing["updated_at"] or "")
        age_ok = True
        if updated_at:
            try:
                stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00").replace(" ", "T"))
                age_ok = (time.time() - stamp.timestamp()) < ttl_seconds
            except Exception:
                age_ok = True
        if age_ok:
            try:
                data = json_module.loads(str(existing["data_json"] or "{}"))
            except Exception:
                data = {}
            return {
                "revision": revision,
                "context_block": str(existing["context_block"] or ""),
                "data": data,
                "evidence_source": "workspace_snapshot",
            }

    project_row = await db_module.get_project(conn, project_id)
    projects = [dict(project_row)] if project_row else []
    tasks = [dict(row) for row in await db_module.get_tasks(conn, project_id=project_id, status="open")]
    prompts_list = [dict(row) for row in await db_module.get_prompts(conn, project_id=project_id)]
    high_trust_memory = [
        dict(row)
        for row in await db_module.list_memory_items_filtered(
            conn,
            workspace_id=project_id,
            trust_level="high",
            limit=4,
        )
    ]
    context_block = brain_module._build_context_block(projects, tasks, prompts_list)
    if high_trust_memory:
        memory_lines = [
            f"- {item.get('title', 'Memory')}: {compact_text(item.get('summary') or item.get('content') or '', limit=160)}"
            for item in high_trust_memory[:2]
        ]
        context_block = "\n\n".join(
            block
            for block in (context_block, "## Known Workspace Facts\n" + "\n".join(memory_lines))
            if block
        )
    snapshot_data = {
        "project": projects[0] if projects else {},
        "tasks": tasks[:8],
        "prompts": prompts_list[:5],
        "memory": high_trust_memory[:4],
    }
    await db_module.upsert_workspace_snapshot(
        conn,
        workspace_id=project_id,
        snapshot_key=snapshot_key,
        revision=revision,
        context_block=context_block,
        data_json=json_module.dumps(snapshot_data, ensure_ascii=True),
        commit=False,
    )
    await conn.commit()
    return {
        "revision": revision,
        "context_block": context_block,
        "data": snapshot_data,
        "evidence_source": "workspace_snapshot",
    }


async def chat_history_bundle(
    db_module,
    select_history_for_chat,
    history_messages_from_rows_fn,
    load_chat_history_rows_fn,
    json_module,
    conn,
    *,
    project_id: Optional[int],
    settings: dict,
    backend: str,
    history_rows=None,
    parse_stored_chat_message_fn,
) -> dict:
    history_budget = setting_int(
        settings,
        "max_history_turns",
        setting_int(settings, "max_chat_history", 12, minimum=6, maximum=120),
        minimum=6,
        maximum=60,
    )
    rows = list(history_rows or [])
    if not rows:
        rows = await load_chat_history_rows_fn(
            conn,
            project_id=project_id,
            limit=max(history_budget * 4, 40),
            degrade_to_empty=True,
        )
    recent_rows = rows[-history_budget:]
    history = select_history_for_chat(
        "",
        history_messages_from_rows_fn(recent_rows),
        backend=backend,
        max_turns=history_budget,
    )
    summary_block = ""
    if len(rows) > len(recent_rows):
        older_rows = rows[:-len(recent_rows)] if recent_rows else rows
        revision_payload = "|".join(str(dict(row).get("id") or "") for row in older_rows[-20:]) + f":{len(older_rows)}"
        revision = json_module.dumps({"digest": revision_payload}, sort_keys=True)
        thread_key = f"chat:{project_id or 0}:{backend}"
        existing = await db_module.get_thread_summary(conn, thread_key)
        if existing and str(existing["revision"] or "") == revision:
            summary_block = str(existing["summary"] or "")
        else:
            summary_block = build_thread_summary_text(
                older_rows,
                parse_stored_chat_message_fn=parse_stored_chat_message_fn,
            )
            if summary_block:
                await db_module.upsert_thread_summary(
                    conn,
                    thread_key=thread_key,
                    workspace_id=project_id,
                    revision=revision,
                    summary=summary_block,
                    message_count=len(rows),
                    commit=False,
                )
                await conn.commit()
    return {
        "history": history,
        "summary_block": summary_block,
        "history_budget": history_budget,
        "row_count": len(rows),
    }


def extract_first_url(message: str) -> str:
    match = re.search(r"https?://[^\s<>'\"`]+", str(message or ""))
    if not match:
        return ""
    return match.group(0).rstrip(").,;!?]}")


def requires_fresh_external_fetch(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    if extract_first_url(lowered):
        return bool(re.search(r"\b(latest|today|current|recent|right now|as of|up[- ]to[- ]date)\b", lowered))
    return False


def looks_like_mutating_or_generation_request(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    return bool(
        re.search(
            r"\b(create|generate|build|write|draft|fix|change|edit|update|modify|implement|refactor|commit|push|deploy|rollback|delete|remove)\b",
            lowered,
        )
    )


def looks_like_local_fast_path_candidate(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if len(lowered) < 8 or len(lowered) > 320:
        return False
    if looks_like_mutating_or_generation_request(lowered):
        return False
    question_mark = lowered.endswith("?")
    starts_with_query = lowered.startswith(("what ", "which ", "who ", "where ", "when ", "is ", "are ", "do ", "does ", "did ", "can ", "could "))
    if extract_first_url(lowered):
        return question_mark or starts_with_query or "summarize" in lowered or "what does" in lowered
    return question_mark or starts_with_query


def format_cached_web_fast_answer(row, *, url: str) -> str:
    title = str(row.get("title") or url).strip() or url
    summary = str(row.get("summary") or "").strip()
    content = str(row.get("content") or "").strip()
    snippets = []
    if summary:
        snippets.append(summary)
    if content and content != summary:
        snippets.append(content[:500])
    detail = "\n\n".join(snippets) if snippets else "I have a cached copy of that page, but it does not have a text summary yet."
    return f"Cached answer from {title}:\n\n{detail}".strip()


def looks_like_task_snapshot_question(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    return bool(
        re.search(
            r"\b("
            r"what(?:'s| is)?(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|show(?:\s+me)?(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|list(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|check(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|review(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|summarize(?:\s+(?:my|the|open|active|pending|current))?\s+(?:tasks?|missions?)"
            r"|any\s+(?:open|active|pending|current)?\s*(?:tasks?|missions?)"
            r"|(?:open|active|pending|current)\s+(?:tasks?|missions?)"
            r")\b",
            lowered,
        )
    )


def workspace_snapshot_fast_answer(message: str, snapshot_bundle: dict) -> str:
    data = snapshot_bundle.get("data") if isinstance(snapshot_bundle, dict) else {}
    lowered = str(message or "").strip().lower()
    if not isinstance(data, dict):
        return ""
    if "project" in lowered or "workspace" in lowered:
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        name = str(project.get("name") or "").strip()
        path = str(project.get("path") or "").strip()
        if name or path:
            parts = []
            if name:
                parts.append(f"Workspace: {name}")
            if path:
                parts.append(f"Path: {path}")
            return "\n".join(parts)
    if looks_like_task_snapshot_question(lowered):
        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        if tasks:
            lines = ["Open missions:"]
            for item in tasks[:5]:
                title = str(item.get("title") or "Untitled").strip()
                status = str(item.get("status") or "open").strip()
                lines.append(f"- {title} ({status})")
            return "\n".join(lines)
    return ""


def memory_fast_answer(message: str, memory_bundle_payload: dict) -> str:
    lowered = str(message or "").strip().lower()
    items = memory_bundle_payload.get("items") if isinstance(memory_bundle_payload, dict) else []
    if not items:
        return ""
    if any(token in lowered for token in ("remember", "memory", "known about", "what do you know")):
        top = items[0]
        title = str(top.get("title") or "Memory").strip()
        summary = str(top.get("summary") or top.get("content") or "").strip()
        if summary:
            return f"From memory: {title}\n\n{summary}"
    return ""


def capability_orchestration_fast_answer(message: str, settings: dict) -> str:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return ""
    if not re.search(r"\b(gpts?|gems?|agents?|workers?|models?)\b", lowered):
        return ""
    if not re.search(r"\b(connect|use|monitor|manage|orchestrate|delegate|supervise|watch)\b", lowered):
        return ""

    openai_enabled = str(settings.get("openai_gpts_enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
    gemini_enabled = str(settings.get("gemini_gems_enabled") or "").strip().lower() in {"1", "true", "yes", "on"}
    cloud_enabled = str(settings.get("cloud_agents_enabled") or "").strip().lower() in {"1", "true", "yes", "on"}

    enabled_labels = []
    if openai_enabled:
        enabled_labels.append("OpenAI GPT routing")
    if gemini_enabled:
        enabled_labels.append("Gemini Gem routing")
    if cloud_enabled:
        enabled_labels.append("cloud agents")
    enabled_text = ", ".join(enabled_labels) if enabled_labels else "none of the external worker bridges"

    lines = [
        "Partly.",
        f"Enabled in this Axon session: {enabled_text}.",
        "I can coordinate Axon's own agent runs plus installed tools like GitHub, Linear, and Vercel.",
        "I cannot yet supervise arbitrary external ChatGPT GPTs or Gems as a persistent worker fleet unless a dedicated connector or control API is wired in.",
        "Concrete upgrades: provider task adapters, worker heartbeats, shared task state, and voice alerts when a delegated run needs attention.",
    ]
    return "\n".join(lines)


async def maybe_local_fast_chat_response(
    db_module,
    normalized_external_fetch_policy_fn,
    conn,
    *,
    user_message: str,
    project_id: Optional[int],
    settings: dict,
    snapshot_bundle: dict,
    memory_bundle_payload: dict,
) -> dict | None:
    text = str(user_message or "").strip()
    if not looks_like_local_fast_path_candidate(text):
        return None

    fetch_policy = normalized_external_fetch_policy_fn(settings.get("external_fetch_policy") or "cache_first")
    url = extract_first_url(text)
    if url and fetch_policy != "live_first" and not requires_fresh_external_fetch(text):
        try:
            cached_row = await db_module.get_external_fetch_cache(conn, url)
        except Exception:
            cached_row = None
        if cached_row:
            return {
                "content": format_cached_web_fast_answer(cached_row, url=url),
                "tokens": 0,
                "evidence_source": "cached_external",
                "model_label": "Cached web",
                "fast_path": True,
            }

    workspace_answer = workspace_snapshot_fast_answer(text, snapshot_bundle)
    if workspace_answer:
        return {
            "content": workspace_answer,
            "tokens": 0,
            "evidence_source": "workspace_snapshot",
            "model_label": "Workspace snapshot",
            "fast_path": True,
        }

    memory_answer = memory_fast_answer(text, memory_bundle_payload)
    if memory_answer:
        return {
            "content": memory_answer,
            "tokens": 0,
            "evidence_source": "memory",
            "model_label": "Memory fast path",
            "fast_path": True,
        }

    capability_answer = capability_orchestration_fast_answer(text, settings)
    if capability_answer:
        return {
            "content": capability_answer,
            "tokens": 0,
            "evidence_source": "capabilities",
            "model_label": "Capability fast path",
            "fast_path": True,
        }
    return None
