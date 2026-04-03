"""API routes for Axon's attention inbox."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from axon_api.services.attention_query import attention_summary, query_attention_inbox
from axon_data import (
    acknowledge_attention_item,
    assign_attention_item,
    build_attention_key,
    get_attention_item,
    list_attention_items,
    resolve_attention_item,
    search_attention_items,
    snooze_attention_item,
    update_attention_item_state,
    upsert_attention_item,
    get_db,
)

router = APIRouter(prefix="/api/attention", tags=["attention"])


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row else {}


class AttentionIngestRequest(BaseModel):
    source: str
    title: str
    summary: str = ""
    detail: str = ""
    item_type: str = ""
    source_event_id: str = ""
    severity: str = "medium"
    status: str = "new"
    workspace_id: int | None = None
    project_name: str = ""
    owner_kind: str = ""
    owner_id: int | None = None
    link_url: str = ""
    attention_key: str = ""
    occurrence_count: int = 1
    meta: dict[str, Any] | None = Field(default=None)


class AttentionStateRequest(BaseModel):
    status: str | None = None
    owner_kind: str | None = None
    owner_id: int | None = None


class AttentionSnoozeRequest(BaseModel):
    snoozed_until: str


class AttentionAssignRequest(BaseModel):
    owner_kind: str
    owner_id: int | None = None


@router.get("/")
async def attention_root(workspace_id: int | None = None, limit: int = 50):
    async with get_db() as db:
        return await attention_summary(db, workspace_id=workspace_id, limit=limit)


@router.get("/inbox")
async def attention_inbox(
    workspace_id: int | None = None,
    query: str = "",
    limit: int = 100,
):
    async with get_db() as db:
        return await query_attention_inbox(db, workspace_id=workspace_id, query=query, limit=limit)


@router.get("/summary")
async def attention_inbox_summary(workspace_id: int | None = None, limit: int = 20):
    async with get_db() as db:
        return await attention_summary(db, workspace_id=workspace_id, limit=limit)


@router.get("/items")
async def attention_items(
    workspace_id: int | None = None,
    status: str = "",
    source: str = "",
    severity: str = "",
    query: str = "",
    limit: int = 100,
):
    async with get_db() as db:
        if query.strip():
            rows = await search_attention_items(db, query=query, workspace_id=workspace_id, limit=limit)
        else:
            rows = await list_attention_items(
                db,
                workspace_id=workspace_id,
                status=status,
                source=source,
                severity=severity,
                limit=limit,
            )
    return {"items": [dict(row) for row in rows]}


@router.get("/items/{attention_id}")
async def attention_item(attention_id: int):
    async with get_db() as db:
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return dict(row)


@router.post("/items")
async def attention_ingest(body: AttentionIngestRequest):
    attention_key = body.attention_key.strip() or build_attention_key(
        body.source,
        body.source_event_id,
        workspace_id=body.workspace_id,
        title=body.title,
    )
    async with get_db() as db:
        attention_id = await upsert_attention_item(
            db,
            attention_key=attention_key,
            source=body.source,
            title=body.title,
            summary=body.summary,
            detail=body.detail,
            item_type=body.item_type,
            source_event_id=body.source_event_id,
            severity=body.severity,
            status=body.status,
            workspace_id=body.workspace_id,
            project_name=body.project_name,
            owner_kind=body.owner_kind,
            owner_id=body.owner_id,
            link_url=body.link_url,
            meta_json="{}" if body.meta is None else __import__("json").dumps(body.meta, sort_keys=True, ensure_ascii=True),
            occurrence_count=max(1, int(body.occurrence_count or 1)),
        )
        row = await get_attention_item(db, attention_id)
    return {"attention": dict(row) if row else {"id": attention_id, "attention_key": attention_key}}


@router.post("/items/{attention_id}/ack")
async def attention_ack(attention_id: int):
    async with get_db() as db:
        await acknowledge_attention_item(db, attention_id)
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return {"attention": dict(row)}


@router.post("/items/{attention_id}/resolve")
async def attention_resolve(attention_id: int):
    async with get_db() as db:
        await resolve_attention_item(db, attention_id)
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return {"attention": dict(row)}


@router.post("/items/{attention_id}/snooze")
async def attention_snooze(attention_id: int, body: AttentionSnoozeRequest):
    async with get_db() as db:
        await snooze_attention_item(db, attention_id, body.snoozed_until)
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return {"attention": dict(row)}


@router.post("/items/{attention_id}/assign")
async def attention_assign(attention_id: int, body: AttentionAssignRequest):
    async with get_db() as db:
        await assign_attention_item(
            db,
            attention_id,
            owner_kind=body.owner_kind,
            owner_id=body.owner_id,
        )
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return {"attention": dict(row)}


@router.patch("/items/{attention_id}")
async def attention_update_state(attention_id: int, body: AttentionStateRequest):
    if body.status is None and body.owner_kind is None and body.owner_id is None:
        raise HTTPException(400, "No state fields provided")
    async with get_db() as db:
        await update_attention_item_state(
            db,
            attention_id,
            status=body.status,
            owner_kind=body.owner_kind,
            owner_id=body.owner_id,
        )
        row = await get_attention_item(db, attention_id)
    if not row:
        raise HTTPException(404, "Attention item not found")
    return {"attention": dict(row)}
