"""Generated media routes for PDFs and images."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional
import urllib.parse

import db as devdb
import httpx
import provider_registry
import resource_bank
import vault as devvault
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from axon_core import image_generation, pdf_generation


router = APIRouter()


class PdfFromPromptRequest(BaseModel):
    prompt: str
    context: str = ""
    theme: str = "clean"
    output_path: str = ""


class PdfFromDataRequest(BaseModel):
    document: dict[str, Any]
    output_path: str = ""


class ImageGenerationRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "1:1"
    image_size: str = "1K"
    title: Optional[str] = None
    workspace_id: Optional[int] = None


def _pdf_model_fn_from_settings(settings: dict[str, Any]):
    def model_fn(system: str, user: str) -> str:
        ollama_model = settings.get("code_model") or settings.get("ollama_model") or "qwen2.5-coder:1.5b"
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.3},
        }
        response = httpx.post("http://localhost:11434/api/chat", json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["message"]["content"]

    return model_fn


async def generate_pdf_ai(body: PdfFromPromptRequest):
    try:
        async with devdb.get_db() as conn:
            settings = await devdb.get_all_settings(conn)
        document_json = await asyncio.to_thread(
            pdf_generation.prompt_to_pdf_json,
            body.prompt,
            body.context,
            _pdf_model_fn_from_settings(settings),
        )
        if body.output_path:
            document_json["output_path"] = body.output_path
        if body.theme:
            document_json["theme"] = body.theme
        spec = pdf_generation.pdf_from_dict(document_json)
        out_path = await asyncio.to_thread(pdf_generation.build_pdf, spec)
        return {
            "ok": True,
            "path": str(out_path),
            "filename": out_path.name,
            "sections": len(spec.sections),
            "title": spec.title,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def generate_pdf_from_data(body: PdfFromDataRequest):
    try:
        document = dict(body.document)
        if body.output_path:
            document["output_path"] = body.output_path
        spec = pdf_generation.pdf_from_dict(document)
        out_path = await asyncio.to_thread(pdf_generation.build_pdf, spec)
        return {
            "ok": True,
            "path": str(out_path),
            "filename": out_path.name,
            "sections": len(spec.sections),
            "title": spec.title,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def download_pdf(path: str):
    file_path = Path(urllib.parse.unquote(path))
    if not file_path.exists() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(404, "File not found")
    home = Path.home()
    try:
        file_path.relative_to(home)
    except ValueError as exc:
        raise HTTPException(403, "Access denied") from exc
    return FileResponse(str(file_path), media_type="application/pdf", filename=file_path.name)


async def generate_image(body: ImageGenerationRequest):
    async with devdb.get_db() as conn:
        settings = await devdb.get_all_settings(conn)
        provider = provider_registry.merged_provider_config(
            "gemini_gems",
            settings,
            {"model": settings.get("gemini_image_model") or image_generation.DEFAULT_GEMINI_IMAGE_MODEL},
        )
        api_key = settings.get(provider.get("key_setting", ""), "") or ""
        if not api_key and devvault.VaultSession.is_unlocked():
            api_key = await devvault.vault_resolve_provider_key(conn, "gemini_gems")
    if not api_key:
        raise HTTPException(400, "Gemini image generation is not configured. Set the Gemini key in Settings or unlock the vault.")

    try:
        artifact = await asyncio.to_thread(
            image_generation.generate_and_store_image,
            db_path=Path(devdb.DB_PATH),
            prompt=body.prompt,
            api_key=api_key,
            api_model=str(provider.get("model") or image_generation.DEFAULT_GEMINI_IMAGE_MODEL),
            api_base_url=str(provider.get("base_url") or image_generation.DEFAULT_GEMINI_IMAGE_BASE_URL),
            aspect_ratio=body.aspect_ratio,
            image_size=body.image_size,
            title=str(body.title or "").strip(),
            workspace_id=body.workspace_id,
        )
    except image_generation.ImageGenerationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Image provider request failed: {exc}") from exc

    async with devdb.get_db() as conn:
        row = await devdb.get_resource(conn, artifact.resource_id)
    if not row:
        raise HTTPException(500, "Generated image resource was stored, but could not be reloaded.")
    return resource_bank.serialize_resource(row)


router.add_api_route("/api/generate/pdf/ai", generate_pdf_ai, methods=["POST"])
router.add_api_route("/api/generate/pdf", generate_pdf_from_data, methods=["POST"])
router.add_api_route("/api/generate/pdf/download", download_pdf, methods=["GET"])
router.add_api_route("/api/generate/image", generate_image, methods=["POST"])
