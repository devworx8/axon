"""Chat message persistence and serialization helpers extracted from server.py."""
from __future__ import annotations

import re
from typing import Optional


CHAT_HISTORY_ENVELOPE_PREFIX = "AXON_CHAT_V1:"


async def persist_chat_reply(
    db_module,
    stored_chat_message,
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
) -> None:
    await db_module.save_message(
        conn,
        "user",
        stored_chat_message(
            user_message,
            resources=resources,
            mode="chat",
            thread_mode=thread_mode,
        ),
        project_id=project_id,
    )
    await db_module.save_message(
        conn,
        "assistant",
        stored_chat_message(
            assistant_message,
            mode="chat",
            thread_mode=thread_mode,
            model_label=model_label,
        ),
        project_id=project_id,
        tokens=tokens,
    )
    await db_module.log_event(conn, event_name, event_summary or user_message[:100], project_id=project_id)


async def maybe_handle_chat_console_command(
    db_module,
    console_command_service,
    set_live_operator,
    persist_chat_reply_fn,
    conn,
    *,
    project_id: Optional[int],
    user_message: str,
    thread_mode: str,
):
    text = str(user_message or "").strip().lower()
    login_overrides = None
    if text.startswith("/login") or text.startswith("/login-cli"):
        login_overrides = {
            "claude": str(await db_module.get_setting(conn, "claude_cli_path") or "").strip(),
            "codex": str(await db_module.get_setting(conn, "cli_runtime_path") or "").strip(),
        }

    command_result = console_command_service.maybe_handle_console_command(
        user_message,
        login_overrides=login_overrides,
    )
    if not command_result:
        return None

    assistant_message = str(command_result.get("response") or "")
    set_live_operator(
        active=False,
        mode="chat",
        phase="execute",
        title="Handled console command",
        detail=str(command_result.get("command") or "command"),
        summary=assistant_message[:180],
        workspace_id=project_id,
    )
    await persist_chat_reply_fn(
        conn,
        project_id=project_id,
        user_message=user_message,
        assistant_message=assistant_message,
        resources=[],
        thread_mode=thread_mode,
        tokens=0,
        model_label="Axon console",
        event_name=str(command_result.get("event_name") or "chat_console_command"),
        event_summary=str(command_result.get("event_summary") or user_message[:100]),
    )
    payload = dict(command_result.get("data") or {})
    payload.update(
        {
            "response": assistant_message,
            "tokens": 0,
            "console_command": True,
            "command": str(command_result.get("command") or ""),
        }
    )
    return payload


def clean_resource_ids(resource_ids: Optional[list[int]]) -> list[int]:
    seen: list[int] = []
    for resource_id in resource_ids or []:
        try:
            value = int(resource_id)
        except Exception:
            continue
        if value > 0 and value not in seen:
            seen.append(value)
    return seen


def thread_mode_from_composer_options(
    composer_options: dict | None,
    *,
    agent_request: bool = False,
    composer_options_dict,
) -> str:
    options = composer_options_dict(composer_options)
    intelligence = str(options.get("intelligence_mode") or "ask").strip().lower()
    action = str(options.get("action_mode") or "").strip().lower()
    agent_role = str(options.get("agent_role") or "").strip().lower()
    if agent_role == "auto":
        return "auto"
    if agent_request or agent_role:
        return "agent"
    if intelligence == "deep_research":
        return "research"
    if intelligence == "analyze" and action == "generate":
        return "code"
    if intelligence == "build_brief" and action == "generate":
        return "business"
    return "ask"


def stored_chat_message(
    message: str,
    *,
    resources: list[dict] | None = None,
    mode: str = "",
    thread_mode: str = "",
    model_label: str = "",
    json_module,
) -> str:
    payload = {"content": str(message or "")}
    resource_refs = []
    for resource in resources or []:
        title = str(resource.get("title") or "resource").strip() or "resource"
        ref = {
            key: value
            for key, value in dict(resource or {}).items()
            if key in {"kind", "mime_type", "source_type", "source_url"}
            and value not in (None, "")
        }
        ref["title"] = title
        resource_id = resource.get("id")
        try:
            if resource_id not in (None, ""):
                ref["id"] = int(resource_id)
        except Exception:
            ref["id"] = str(resource_id)
        resource_refs.append(ref)
    if resource_refs:
        payload["resources"] = resource_refs[:12]
    if mode:
        payload["mode"] = str(mode)
    if thread_mode:
        payload["thread_mode"] = str(thread_mode)
    if model_label:
        payload["model_label"] = str(model_label)
    return CHAT_HISTORY_ENVELOPE_PREFIX + json_module.dumps(payload, ensure_ascii=False)


def stored_message_with_resources(message: str, resources: list[dict], *, stored_chat_message_fn) -> str:
    return stored_chat_message_fn(message, resources=resources, mode="chat")


def parse_stored_chat_message(raw_content: str, *, json_module) -> dict[str, object]:
    raw = str(raw_content or "")
    if raw.startswith(CHAT_HISTORY_ENVELOPE_PREFIX):
        try:
            payload = json_module.loads(raw[len(CHAT_HISTORY_ENVELOPE_PREFIX):])
        except Exception:
            payload = None
        if isinstance(payload, dict):
            resources = payload.get("resources") if isinstance(payload.get("resources"), list) else []
            return {
                "content": str(payload.get("content") or ""),
                "resources": [dict(item) for item in resources if isinstance(item, dict)],
                "mode": str(payload.get("mode") or ""),
                "thread_mode": str(payload.get("thread_mode") or ""),
                "model_label": str(payload.get("model_label") or ""),
            }

    match = re.match(r"(?s)^(.*?)(?:\n\n\[Attached resources: ([^\]]+)\]\s*)?$", raw)
    content = raw
    resources: list[dict[str, object]] = []
    if match and match.group(2):
        content = match.group(1).rstrip()
        resources = [
            {"id": f"history-{index}-{title.strip()}", "title": title.strip()}
            for index, title in enumerate(match.group(2).split(","))
            if title.strip()
        ]
    return {
        "content": content,
        "resources": resources,
        "mode": "",
        "thread_mode": "",
        "model_label": "",
    }


def history_messages_from_rows(rows, *, parse_stored_chat_message_fn) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for row in rows or []:
        parsed = parse_stored_chat_message_fn(row["content"])
        content = str(parsed.get("content") or "")
        resources = parsed.get("resources") if isinstance(parsed.get("resources"), list) else []
        if resources:
            labels = ", ".join(str(item.get("title") or "resource") for item in resources[:6])
            suffix = "…" if len(resources) > 6 else ""
            content = f"{content}\n\n[Attached resources: {labels}{suffix}]".strip()
        messages.append({"role": row["role"], "content": content})
    return messages


def serialize_chat_history_row(row, *, parse_stored_chat_message_fn) -> dict[str, object]:
    parsed = parse_stored_chat_message_fn(row["content"])
    return {
        "role": row["role"],
        "content": parsed.get("content") or "",
        "created_at": row["created_at"],
        "tokens_used": row["tokens_used"],
        "resources": parsed.get("resources") or [],
        "mode": parsed.get("mode") or "",
        "thread_mode": parsed.get("thread_mode") or "",
        "model_label": parsed.get("model_label") or "",
    }


async def resource_bundle(
    db_module,
    resource_bank_module,
    json_module,
    conn,
    *,
    resource_ids: list[int],
    user_message: str,
    settings: dict,
) -> dict:
    ids = clean_resource_ids(resource_ids)
    if not ids:
        return {
            "resources": [],
            "context_block": "",
            "image_paths": [],
            "vision_model": "",
            "warnings": [],
        }

    rows = await db_module.get_resources_by_ids(conn, ids)
    resources = [resource_bank_module.serialize_resource(row) for row in rows]
    warnings: list[str] = []
    context_parts = ["## Attached Resources"]
    image_paths: list[str] = []
    vision_model = (settings.get("vision_model") or "").strip()
    backend = (settings.get("ai_backend") or "api").lower()
    if not vision_model and backend == "api":
        vision_model = settings.get("api_model") or ""

    for resource in resources:
        await db_module.touch_resource_used(conn, resource["id"])
        await db_module.log_event(conn, "resource_used", f"Used resource: {resource['title']}")

        if resource.get("kind") == "image":
            image_paths.append(resource.get("local_path", ""))
            meta = resource.get("meta") or {}
            dimensions = ""
            if meta.get("width") and meta.get("height"):
                dimensions = f" ({meta['width']}×{meta['height']})"
            context_parts.append(
                f"- Image: {resource['title']}{dimensions}. Summary: {resource.get('summary') or 'Image attached.'}"
            )
            continue

        chunk_rows = await db_module.get_resource_chunks(conn, resource["id"])
        chunks = []
        for row in chunk_rows:
            try:
                embedding = json_module.loads(row["embedding_json"]) if row["embedding_json"] else None
            except Exception:
                embedding = None
            chunks.append({"text": row["text"], "embedding": embedding})

        selected = await resource_bank_module.select_relevant_chunks(
            query=user_message,
            chunks=chunks,
            settings=settings,
            limit=4,
        )
        context_parts.append(
            f"- {resource['title']}: {resource.get('summary') or resource.get('preview_text') or 'Attached document.'}"
        )
        for index, chunk in enumerate(selected, start=1):
            context_parts.append(f"  Excerpt {index}: {chunk}")

    if image_paths and not vision_model and backend not in {"api", "cli"}:
        warnings.append("Image resources are attached, but the current runtime does not have direct vision enabled. Axon will use image metadata only.")

    return {
        "resources": resources,
        "context_block": "\n".join(context_parts),
        "image_paths": [path for path in image_paths if path],
        "vision_model": vision_model,
        "warnings": warnings,
    }
