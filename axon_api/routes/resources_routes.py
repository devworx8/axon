"""Resource bank and research pack routes extracted from server.py."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel


class ResourceImportRequest(BaseModel):
    url: str
    title: Optional[str] = None
    workspace_id: Optional[int] = None


class ResourceUpdate(BaseModel):
    trust_level: Optional[str] = None
    pinned: Optional[bool] = None
    workspace_id: Optional[int] = None


class ResearchPackCreate(BaseModel):
    title: str
    description: str = ""
    pinned: bool = False


class ResearchPackUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    pinned: Optional[bool] = None


class ResearchPackItemsBody(BaseModel):
    resource_ids: list[int] = []


class ResourceRouteHandlers:
    def __init__(
        self,
        *,
        db_module: Any,
        resource_bank_module: Any,
        ingest_resource_bytes: Callable[..., Awaitable[dict[str, Any]]],
        serialize_research_pack: Callable[..., dict[str, Any]],
        clean_resource_ids: Callable[[list[int]], list[int]],
    ) -> None:
        self._db = db_module
        self._resource_bank = resource_bank_module
        self._ingest_resource_bytes = ingest_resource_bytes
        self._serialize_research_pack = serialize_research_pack
        self._clean_resource_ids = clean_resource_ids

    async def list_resources(
        self,
        search: str = "",
        kind: str = "",
        source_type: str = "",
        status: str = "",
        limit: int = Query(200, ge=1, le=500),
    ):
        async with self._db.get_db() as conn:
            rows = await self._db.list_resources(
                conn,
                search=search,
                kind=kind,
                source_type=source_type,
                status=status,
                limit=limit,
            )
        return {"items": [self._resource_bank.serialize_resource(row) for row in rows]}

    async def upload_resources(self, files: list[UploadFile] = File(...), workspace_id: Optional[int] = Form(None)):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            created = []
            for upload in files:
                raw = await upload.read()
                filename = upload.filename or "resource"
                mime_type = (upload.content_type or self._resource_bank.detect_mime_type(filename)).strip().lower()
                title = Path(filename).stem or filename
                created.append(
                    await self._ingest_resource_bytes(
                        conn,
                        title=title,
                        filename=filename,
                        content=raw,
                        mime_type=mime_type,
                        source_type="upload",
                        source_url="",
                        settings=settings,
                        workspace_id=workspace_id,
                    )
                )
        return {"items": created}

    async def import_resource_url(self, body: ResourceImportRequest):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            fetched = await self._resource_bank.fetch_url_resource(body.url, settings)
            title = (body.title or Path(fetched["filename"]).stem or fetched["filename"]).strip()
            created = await self._ingest_resource_bytes(
                conn,
                title=title,
                filename=fetched["filename"],
                content=fetched["content"],
                mime_type=fetched["mime_type"],
                source_type="url",
                source_url=fetched["final_url"],
                settings=settings,
                workspace_id=body.workspace_id,
            )
        return created

    async def get_resource(self, resource_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_resource(conn, resource_id)
            if not row:
                raise HTTPException(404, "Resource not found")
            chunks = await self._db.get_resource_chunks(conn, resource_id)
        data = self._resource_bank.serialize_resource(row)
        data["chunk_count"] = len(chunks)
        return data

    async def update_resource(self, resource_id: int, body: ResourceUpdate):
        if body.trust_level not in (None, "high", "medium", "low"):
            raise HTTPException(400, "Invalid trust level")
        fields = body.model_dump(exclude_unset=True)
        async with self._db.get_db() as conn:
            row = await self._db.get_resource(conn, resource_id)
            if not row:
                raise HTTPException(404, "Resource not found")
            if fields:
                await self._db.update_resource(conn, resource_id, **fields)
                changes = []
                if "pinned" in fields:
                    changes.append("pinned" if fields["pinned"] else "unpinned")
                if "trust_level" in fields:
                    changes.append(f"trust={fields['trust_level']}")
                if "workspace_id" in fields:
                    changes.append("workspace link updated")
                await self._db.log_event(
                    conn,
                    "resource_updated",
                    f"Resource updated: {dict(row).get('title', 'resource')} ({', '.join(changes) or 'metadata'})",
                )
            updated = await self._db.get_resource(conn, resource_id)
        return self._resource_bank.serialize_resource(updated)

    async def get_resource_content(self, resource_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_resource(conn, resource_id)
            if not row:
                raise HTTPException(404, "Resource not found")
            chunks = await self._db.get_resource_chunks(conn, resource_id)
        resource = self._resource_bank.serialize_resource(row)
        path = Path(resource["local_path"])
        if resource.get("kind") == "image":
            if not path.exists():
                raise HTTPException(404, "Image file not found")
            return FileResponse(str(path), media_type=resource.get("mime_type") or "image/png")
        content = "\n\n".join(chunk["text"] for chunk in [dict(item) for item in chunks])[:50000]
        return {
            "id": resource["id"],
            "title": resource["title"],
            "kind": resource["kind"],
            "mime_type": resource.get("mime_type", ""),
            "summary": resource.get("summary", ""),
            "preview_text": resource.get("preview_text", ""),
            "content": content,
        }

    async def reprocess_resource(self, resource_id: int):
        async with self._db.get_db() as conn:
            settings = await self._db.get_all_settings(conn)
            row = await self._db.get_resource(conn, resource_id)
            if not row:
                raise HTTPException(404, "Resource not found")
            resource = self._resource_bank.serialize_resource(row)
            path = Path(resource["local_path"])
            if not path.exists():
                raise HTTPException(404, "Resource file not found")
            analysis = await self._resource_bank.analyze_resource_file(
                path=path,
                title=resource["title"],
                mime_type=resource.get("mime_type") or self._resource_bank.detect_mime_type(path.name),
                settings=settings,
            )
            await self._db.update_resource(
                conn,
                resource_id,
                kind=analysis["kind"],
                status=analysis["status"],
                summary=analysis["summary"],
                preview_text=analysis["preview_text"],
                meta_json=analysis["meta_json"],
            )
            await self._db.replace_resource_chunks(conn, resource_id, analysis["chunks"])
            await self._db.log_event(conn, "resource_processed", f"Resource reprocessed: {resource['title']}")
            updated = await self._db.get_resource(conn, resource_id)
        return self._resource_bank.serialize_resource(updated)

    async def delete_resource(self, resource_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_resource(conn, resource_id)
            if not row:
                raise HTTPException(404, "Resource not found")
            path = Path(dict(row).get("local_path") or "")
            await self._db.delete_resource(conn, resource_id)
            await self._db.log_event(conn, "resource_removed", f"Resource deleted: {dict(row).get('title', 'resource')}")
        try:
            if path.exists():
                folder = path.parent
                if folder.is_dir():
                    shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
        return {"deleted": True}

    async def list_research_packs(self, search: str = "", include_resources: bool = False):
        async with self._db.get_db() as conn:
            rows = await self._db.list_research_packs(conn, search=search)
            items = []
            for row in rows:
                resources = None
                if include_resources:
                    resource_rows = await self._db.get_research_pack_items(conn, row["id"])
                    resources = [self._resource_bank.serialize_resource(item) for item in resource_rows]
                items.append(self._serialize_research_pack(row, resources=resources))
            return {"items": items}

    async def get_research_pack(self, pack_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_research_pack(conn, pack_id)
            if not row:
                raise HTTPException(404, "Research pack not found")
            resource_rows = await self._db.get_research_pack_items(conn, pack_id)
            resources = [self._resource_bank.serialize_resource(item) for item in resource_rows]
            return self._serialize_research_pack(row, resources=resources)

    async def create_research_pack(self, body: ResearchPackCreate):
        async with self._db.get_db() as conn:
            pack_id = await self._db.create_research_pack(conn, title=body.title, description=body.description, pinned=body.pinned)
            await self._db.log_event(conn, "resource_added", f"Created research pack: {body.title}")
            row = await self._db.get_research_pack(conn, pack_id)
            return self._serialize_research_pack(row, resources=[])

    async def update_research_pack(self, pack_id: int, body: ResearchPackUpdate):
        fields = {key: value for key, value in body.dict().items() if value is not None}
        if "pinned" in fields:
            fields["pinned"] = 1 if fields["pinned"] else 0
        if not fields:
            raise HTTPException(400, "Nothing to update")
        async with self._db.get_db() as conn:
            await self._db.update_research_pack(conn, pack_id, **fields)
            row = await self._db.get_research_pack(conn, pack_id)
            if not row:
                raise HTTPException(404, "Research pack not found")
            resource_rows = await self._db.get_research_pack_items(conn, pack_id)
            resources = [self._resource_bank.serialize_resource(item) for item in resource_rows]
            return self._serialize_research_pack(row, resources=resources)

    async def add_research_pack_items(self, pack_id: int, body: ResearchPackItemsBody):
        ids = self._clean_resource_ids(body.resource_ids)
        if not ids:
            raise HTTPException(400, "No resources selected")
        async with self._db.get_db() as conn:
            row = await self._db.get_research_pack(conn, pack_id)
            if not row:
                raise HTTPException(404, "Research pack not found")
            await self._db.add_research_pack_items(conn, pack_id, ids)
            await self._db.log_event(conn, "resource_used", f"Updated research pack: {row['title']}")
            resource_rows = await self._db.get_research_pack_items(conn, pack_id)
            resources = [self._resource_bank.serialize_resource(item) for item in resource_rows]
            fresh = await self._db.get_research_pack(conn, pack_id)
            return self._serialize_research_pack(fresh, resources=resources)

    async def remove_research_pack_item(self, pack_id: int, resource_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_research_pack(conn, pack_id)
            if not row:
                raise HTTPException(404, "Research pack not found")
            await self._db.remove_research_pack_item(conn, pack_id, resource_id)
            resource_rows = await self._db.get_research_pack_items(conn, pack_id)
            resources = [self._resource_bank.serialize_resource(item) for item in resource_rows]
            fresh = await self._db.get_research_pack(conn, pack_id)
            return self._serialize_research_pack(fresh, resources=resources)

    async def delete_research_pack(self, pack_id: int):
        async with self._db.get_db() as conn:
            row = await self._db.get_research_pack(conn, pack_id)
            if not row:
                raise HTTPException(404, "Research pack not found")
            await self._db.delete_research_pack(conn, pack_id)
            await self._db.log_event(conn, "resource_removed", f"Deleted research pack: {row['title']}")
        return {"deleted": True}


def build_resource_router(
    *,
    db_module: Any,
    resource_bank_module: Any,
    ingest_resource_bytes: Callable[..., Awaitable[dict[str, Any]]],
    serialize_research_pack: Callable[..., dict[str, Any]],
    clean_resource_ids: Callable[[list[int]], list[int]],
):
    handlers = ResourceRouteHandlers(
        db_module=db_module,
        resource_bank_module=resource_bank_module,
        ingest_resource_bytes=ingest_resource_bytes,
        serialize_research_pack=serialize_research_pack,
        clean_resource_ids=clean_resource_ids,
    )
    router = APIRouter()
    router.add_api_route("/api/resources", handlers.list_resources, methods=["GET"])
    router.add_api_route("/api/resources/upload", handlers.upload_resources, methods=["POST"])
    router.add_api_route("/api/resources/import-url", handlers.import_resource_url, methods=["POST"])
    router.add_api_route("/api/resources/{resource_id}", handlers.get_resource, methods=["GET"])
    router.add_api_route("/api/resources/{resource_id}", handlers.update_resource, methods=["PATCH"])
    router.add_api_route("/api/resources/{resource_id}/content", handlers.get_resource_content, methods=["GET"])
    router.add_api_route("/api/resources/{resource_id}/reprocess", handlers.reprocess_resource, methods=["POST"])
    router.add_api_route("/api/resources/{resource_id}", handlers.delete_resource, methods=["DELETE"])
    router.add_api_route("/api/research-packs", handlers.list_research_packs, methods=["GET"])
    router.add_api_route("/api/research-packs/{pack_id}", handlers.get_research_pack, methods=["GET"])
    router.add_api_route("/api/research-packs", handlers.create_research_pack, methods=["POST"])
    router.add_api_route("/api/research-packs/{pack_id}", handlers.update_research_pack, methods=["PATCH"])
    router.add_api_route("/api/research-packs/{pack_id}/items", handlers.add_research_pack_items, methods=["POST"])
    router.add_api_route("/api/research-packs/{pack_id}/items/{resource_id}", handlers.remove_research_pack_item, methods=["DELETE"])
    router.add_api_route("/api/research-packs/{pack_id}", handlers.delete_research_pack, methods=["DELETE"])
    return router, handlers
