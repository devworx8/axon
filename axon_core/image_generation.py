from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import resource_bank


DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image-preview"
DEFAULT_GEMINI_IMAGE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
SUPPORTED_ASPECT_RATIOS = ("1:1", "3:4", "4:3", "9:16", "16:9")

_ASPECT_RATIO_ALIASES = {
    "square": "1:1",
    "1x1": "1:1",
    "1/1": "1:1",
    "portrait": "3:4",
    "3x4": "3:4",
    "3/4": "3:4",
    "landscape": "16:9",
    "16x9": "16:9",
    "16/9": "16:9",
    "9x16": "9:16",
    "9/16": "9:16",
    "4x3": "4:3",
    "4/3": "4:3",
}


class ImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime_type: str
    model: str
    prompt: str
    aspect_ratio: str
    image_size: str
    provider_id: str = "gemini_gems"
    provider_label: str = "Gemini"
    provider_text: str = ""


@dataclass(frozen=True)
class StoredGeneratedImage:
    resource_id: int
    path: Path
    title: str
    mime_type: str
    content_url: str
    prompt: str
    summary: str


def normalize_aspect_ratio(value: str = "") -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "1:1"
    normalized = _ASPECT_RATIO_ALIASES.get(normalized, normalized.replace(" ", ""))
    if normalized not in SUPPORTED_ASPECT_RATIOS:
        allowed = ", ".join(SUPPORTED_ASPECT_RATIOS)
        raise ImageGenerationError(f"Unsupported aspect ratio `{value}`. Allowed: {allowed}")
    return normalized


def normalize_image_size(value: str = "") -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return "1K"
    aliases = {
        "1024": "1K",
        "1K": "1K",
        "2K": "2K",
        "2048": "2K",
        "4K": "4K",
        "4096": "4K",
        "512": "512",
    }
    return aliases.get(normalized, normalized)


def build_gemini_image_payload(*, prompt: str, aspect_ratio: str) -> dict[str, Any]:
    return {
        "contents": [{"parts": [{"text": str(prompt or "").strip()}]}],
        "generationConfig": {
            "imageConfig": {
                "aspectRatio": aspect_ratio,
            }
        },
    }


def parse_gemini_image_response(data: dict[str, Any]) -> tuple[bytes, str, str]:
    text_parts: list[str] = []
    image_parts: list[tuple[str, str]] = []
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            text_value = part.get("text")
            if text_value:
                text_parts.append(str(text_value))
            inline_data = part.get("inlineData") or part.get("inline_data") or {}
            encoded = inline_data.get("data")
            if encoded:
                mime_type = (
                    inline_data.get("mimeType")
                    or inline_data.get("mime_type")
                    or "image/png"
                )
                image_parts.append((str(mime_type), str(encoded)))
    if not image_parts:
        provider_text = " ".join(text_parts).strip()
        detail = f" Provider text: {provider_text[:240]}" if provider_text else ""
        raise ImageGenerationError(f"Provider returned no image bytes.{detail}")
    mime_type, encoded = image_parts[0]
    return base64.b64decode(encoded), mime_type, " ".join(text_parts).strip()


def generate_gemini_image(
    *,
    prompt: str,
    api_key: str,
    api_model: str = "",
    api_base_url: str = "",
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    timeout_seconds: float = 120.0,
) -> GeneratedImage:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ImageGenerationError("Image prompt is required.")
    if not str(api_key or "").strip():
        raise ImageGenerationError("Gemini API key is required for image generation.")

    normalized_aspect_ratio = normalize_aspect_ratio(aspect_ratio)
    normalized_size = normalize_image_size(image_size)
    model_name = str(api_model or DEFAULT_GEMINI_IMAGE_MODEL).strip() or DEFAULT_GEMINI_IMAGE_MODEL
    base_url = str(api_base_url or DEFAULT_GEMINI_IMAGE_BASE_URL).strip().rstrip("/") or DEFAULT_GEMINI_IMAGE_BASE_URL
    target = model_name if model_name.startswith("models/") else f"models/{model_name}"
    payload = build_gemini_image_payload(prompt=clean_prompt, aspect_ratio=normalized_aspect_ratio)

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            f"{base_url}/{target}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    image_bytes, mime_type, provider_text = parse_gemini_image_response(data)
    return GeneratedImage(
        data=image_bytes,
        mime_type=mime_type,
        model=model_name,
        prompt=clean_prompt,
        aspect_ratio=normalized_aspect_ratio,
        image_size=normalized_size,
        provider_text=provider_text,
    )


def _extension_for_mime_type(mime_type: str) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized == "image/jpeg":
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    return ".png"


def _load_settings_sync(db_path: Path) -> dict[str, str]:
    if not Path(db_path).exists():
        return {}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
    except sqlite3.Error:
        return {}
    return {str(key): str(value or "") for key, value in rows}


def gemini_runtime_from_settings(db_path: Path) -> dict[str, str]:
    settings = _load_settings_sync(db_path)
    return {
        "api_key": str(settings.get("gemini_api_key") or "").strip(),
        "api_base_url": str(settings.get("gemini_base_url") or DEFAULT_GEMINI_IMAGE_BASE_URL).strip() or DEFAULT_GEMINI_IMAGE_BASE_URL,
        "api_model": str(
            settings.get("gemini_image_model")
            or settings.get("gemini_api_model")
            or DEFAULT_GEMINI_IMAGE_MODEL
        ).strip() or DEFAULT_GEMINI_IMAGE_MODEL,
    }


def store_generated_image(
    *,
    db_path: Path,
    generated: GeneratedImage,
    title: str = "",
    workspace_id: int | None = None,
) -> StoredGeneratedImage:
    settings = _load_settings_sync(db_path)
    resolved_title = str(title or "").strip() or "Generated Image"
    preview_text = generated.prompt[:500]
    summary = (
        f"Generated image via {generated.provider_label} using {generated.model}. "
        f"Aspect ratio {generated.aspect_ratio}."
    )
    meta_json = json.dumps(
        {
            "prompt": generated.prompt,
            "provider_id": generated.provider_id,
            "provider_label": generated.provider_label,
            "provider_text": generated.provider_text,
            "model": generated.model,
            "aspect_ratio": generated.aspect_ratio,
            "requested_image_size": generated.image_size,
        },
        sort_keys=True,
    )
    sha256 = hashlib.sha256(generated.data).hexdigest()
    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """
            INSERT INTO resources (
                title, kind, source_type, source_url, local_path, file_path, mime_type,
                size_bytes, sha256, status, summary, preview_text, trust_level, pinned, workspace_id, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_title,
                "image",
                "generated",
                "",
                "",
                "",
                generated.mime_type,
                len(generated.data),
                sha256,
                "ready",
                summary,
                preview_text,
                "medium",
                0,
                workspace_id,
                meta_json,
            ),
        )
        resource_id = int(cur.lastrowid)
        filename = resource_bank.sanitize_filename(resolved_title) + _extension_for_mime_type(generated.mime_type)
        saved_path = resource_bank.save_resource_file(
            resource_id=resource_id,
            filename=filename,
            content=generated.data,
            settings=settings,
        )
        conn.execute(
            """
            UPDATE resources
            SET local_path = ?, file_path = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (str(saved_path), str(saved_path), resource_id),
        )
        conn.commit()
    return StoredGeneratedImage(
        resource_id=resource_id,
        path=saved_path,
        title=resolved_title,
        mime_type=generated.mime_type,
        content_url=resource_bank.resource_content_url(resource_id),
        prompt=generated.prompt,
        summary=summary,
    )


def generate_and_store_image(
    *,
    db_path: Path,
    prompt: str,
    api_key: str,
    api_model: str = "",
    api_base_url: str = "",
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    title: str = "",
    workspace_id: int | None = None,
) -> StoredGeneratedImage:
    generated = generate_gemini_image(
        prompt=prompt,
        api_key=api_key,
        api_model=api_model,
        api_base_url=api_base_url,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
    )
    return store_generated_image(
        db_path=db_path,
        generated=generated,
        title=title,
        workspace_id=workspace_id,
    )


__all__ = [
    "DEFAULT_GEMINI_IMAGE_BASE_URL",
    "DEFAULT_GEMINI_IMAGE_MODEL",
    "GeneratedImage",
    "ImageGenerationError",
    "StoredGeneratedImage",
    "build_gemini_image_payload",
    "gemini_runtime_from_settings",
    "generate_and_store_image",
    "generate_gemini_image",
    "normalize_aspect_ratio",
    "normalize_image_size",
    "parse_gemini_image_response",
    "store_generated_image",
]
