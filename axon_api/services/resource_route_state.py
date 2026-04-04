"""Resource-route ingestion and serialization helpers extracted from server.py."""
from __future__ import annotations

from typing import Optional


def serialize_research_pack(row, *, resources: Optional[list[dict]] = None) -> dict:
    item = dict(row)
    item["pinned"] = bool(item.get("pinned"))
    item["resource_count"] = int(item.get("resource_count") or 0)
    if resources is not None:
        item["resources"] = resources
    return item


async def ingest_resource_bytes(
    conn,
    *,
    title: str,
    filename: str,
    content: bytes,
    mime_type: str,
    source_type: str,
    source_url: str,
    settings: dict,
    workspace_id: int | None = None,
    db_module,
    resource_bank_module,
    http_exception_cls,
) -> dict:
    if len(content) > resource_bank_module.upload_limit_bytes(settings):
        raise http_exception_cls(413, "Resource exceeds the configured upload size limit.")
    if not resource_bank_module.is_supported(filename, mime_type, source_type=source_type):
        raise http_exception_cls(415, f"Unsupported resource type: {mime_type or filename}")

    resource_id = await db_module.add_resource(
        conn,
        title=title,
        kind=resource_bank_module.classify_kind(filename, mime_type),
        source_type=source_type,
        source_url=source_url,
        local_path="",
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=resource_bank_module.sha256_bytes(content),
        status="pending",
        workspace_id=workspace_id,
    )
    await db_module.log_event(conn, "resource_added", f"Resource added: {title}")

    local_path = resource_bank_module.save_resource_file(
        resource_id=resource_id,
        filename=filename,
        content=content,
        settings=settings,
    )
    await db_module.update_resource(conn, resource_id, local_path=str(local_path))

    try:
        analysis = await resource_bank_module.analyze_resource_file(
            path=local_path,
            title=title,
            mime_type=mime_type,
            settings=settings,
        )
        await db_module.update_resource(
            conn,
            resource_id,
            kind=analysis["kind"],
            status=analysis["status"],
            summary=analysis["summary"],
            preview_text=analysis["preview_text"],
            meta_json=analysis["meta_json"],
        )
        await db_module.replace_resource_chunks(conn, resource_id, analysis["chunks"])
        await db_module.log_event(conn, "resource_processed", f"Resource processed: {title}")
    except Exception as exc:
        await db_module.update_resource(
            conn,
            resource_id,
            status="failed",
            summary=f"Processing failed: {exc}",
            preview_text="",
        )
        await db_module.log_event(conn, "resource_failed", f"Resource failed: {title}")
        raise http_exception_cls(500, f"Resource processing failed: {exc}")

    row = await db_module.get_resource(conn, resource_id)
    return resource_bank_module.serialize_resource(row)
