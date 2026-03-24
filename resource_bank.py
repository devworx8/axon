"""
Axon Resource Bank helpers.

Local-first ingestion for uploaded files and user-provided URLs.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import mimetypes
import re
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

import httpx
import numpy as np
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader


RESOURCE_ROOT = Path.home() / ".devbrain" / "resources"
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | PDF_EXTENSIONS
SUPPORTED_MIME_PREFIXES = ("text/", "image/")
SUPPORTED_MIME_TYPES = {
    "application/json",
    "application/pdf",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/html",
}


def storage_root(settings: dict | None = None) -> Path:
    raw = (settings or {}).get("resource_storage_path") or str(RESOURCE_ROOT)
    return Path(raw).expanduser()


def ensure_storage_root(settings: dict | None = None) -> Path:
    root = storage_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_limit_bytes(settings: dict | None = None) -> int:
    raw = (settings or {}).get("resource_upload_max_mb") or "20"
    try:
        mb = max(1, min(100, int(str(raw).strip())))
    except Exception:
        mb = 20
    return mb * 1024 * 1024


def url_import_enabled(settings: dict | None = None) -> bool:
    raw = str((settings or {}).get("resource_url_import_enabled", "1")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def classify_kind(filename: str = "", mime_type: str = "") -> str:
    ext = Path(filename or "").suffix.lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "image"
    return "document"


def is_supported(filename: str = "", mime_type: str = "", *, source_type: str = "upload") -> bool:
    ext = Path(filename or "").suffix.lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    if source_type == "url" and mime == "text/html":
        return True
    return (
        ext in SUPPORTED_EXTENSIONS
        or mime in SUPPORTED_MIME_TYPES
        or mime.startswith(SUPPORTED_MIME_PREFIXES)
    )


def detect_mime_type(filename: str, fallback: str = "application/octet-stream") -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or fallback


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")
    return cleaned or "resource"


def _decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except Exception:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _extract_html_text(content: bytes) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def extract_text(path: Path, mime_type: str = "") -> str:
    ext = path.suffix.lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    if ext in PDF_EXTENSIONS or mime == "application/pdf":
        return _extract_pdf_text(path)
    raw = path.read_bytes()
    if ext in {".html", ".htm"} or mime == "text/html":
        return _extract_html_text(raw)
    if ext in TEXT_EXTENSIONS or mime in SUPPORTED_MIME_TYPES or mime.startswith("text/"):
        return _decode_text_bytes(raw)
    return ""


def image_metadata(path: Path) -> dict:
    with Image.open(path) as img:
        width, height = img.size
        return {
            "width": width,
            "height": height,
            "mode": img.mode,
            "format": img.format,
        }


def summarize_text(title: str, text: str, *, limit: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return f"{title or 'Resource'} is ready for use in Axon."
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")


def preview_text(text: str, *, limit: int = 1200) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")


def chunk_text(text: str, *, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        segment = cleaned[start:end].strip()
        if segment:
            chunks.append(segment)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    va = np.array(list(a), dtype=float)
    vb = np.array(list(b), dtype=float)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
    return float(np.dot(va, vb) / denom)


async def embed_texts(texts: list[str], settings: dict) -> list[list[float]]:
    model = (settings.get("embeddings_model") or "").strip()
    if not model or not texts:
        return []
    base = (settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{base}/api/embed", json={"model": model, "input": texts})
            resp.raise_for_status()
            data = resp.json()
        embeds = data.get("embeddings") or []
        return [list(item) for item in embeds if isinstance(item, list)]
    except Exception:
        return []


async def compute_chunk_embeddings(chunks: list[str], settings: dict) -> list[list[float] | None]:
    if not chunks:
        return []
    vectors = await embed_texts(chunks, settings)
    if len(vectors) != len(chunks):
        return [None for _ in chunks]
    return vectors


def score_chunk(query: str, chunk: str) -> float:
    tokens = [token for token in re.findall(r"[a-z0-9]{3,}", query.lower())]
    if not tokens:
        return 0.0
    text = chunk.lower()
    return float(sum(text.count(token) for token in tokens))


async def select_relevant_chunks(
    *,
    query: str,
    chunks: list[dict],
    settings: dict,
    limit: int = 4,
) -> list[str]:
    usable = [chunk for chunk in chunks if (chunk.get("text") or "").strip()]
    if not usable:
        return []

    embedded = [chunk for chunk in usable if chunk.get("embedding")]
    if embedded and (settings.get("embeddings_model") or "").strip():
        query_vecs = await embed_texts([query], settings)
        if query_vecs:
            query_vec = query_vecs[0]
            ranked = sorted(
                usable,
                key=lambda item: cosine_similarity(query_vec, item.get("embedding") or []),
                reverse=True,
            )
            return [item["text"] for item in ranked[:limit]]

    ranked = sorted(usable, key=lambda item: score_chunk(query, item["text"]), reverse=True)
    top = [item["text"] for item in ranked[:limit] if score_chunk(query, item["text"]) > 0]
    return top or [item["text"] for item in usable[:limit]]


async def analyze_resource_file(
    *,
    path: Path,
    title: str,
    mime_type: str,
    settings: dict,
) -> dict:
    kind = classify_kind(path.name, mime_type)
    meta: dict = {}
    extracted = ""
    if kind == "image":
        meta = image_metadata(path)
        preview = f"Image resource ready: {title}. {meta.get('width')}×{meta.get('height')} {meta.get('format', '')}".strip()
        summary = "Image stored for visual inspection in Axon."
        return {
            "kind": kind,
            "summary": summary,
            "preview_text": preview,
            "meta_json": json.dumps(meta),
            "status": "ready",
            "chunks": [],
        }

    extracted = extract_text(path, mime_type)
    summary = summarize_text(title, extracted)
    preview = preview_text(extracted)
    chunks = chunk_text(extracted)
    chunk_embeddings = await compute_chunk_embeddings(chunks, settings)
    chunk_rows = []
    for idx, chunk in enumerate(chunks):
        embedding = chunk_embeddings[idx] if idx < len(chunk_embeddings) else None
        chunk_rows.append(
            {
                "chunk_index": idx,
                "text": chunk,
                "embedding_json": json.dumps(embedding) if embedding is not None else "",
            }
        )
    return {
        "kind": kind,
        "summary": summary,
        "preview_text": preview,
        "meta_json": json.dumps(meta),
        "status": "ready" if extracted or path.suffix.lower() in PDF_EXTENSIONS else "processed",
        "chunks": chunk_rows,
    }


async def fetch_url_resource(url: str, settings: dict) -> dict:
    if not url_import_enabled(settings):
        raise ValueError("URL import is disabled in Settings.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported.")
    limit = upload_limit_bytes(settings)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Axon/1.0 Resource Import"})
        resp.raise_for_status()
        content = resp.content
        if len(content) > limit:
            raise ValueError(f"Resource is too large ({math.ceil(len(content) / (1024 * 1024))}MB).")
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        filename = sanitize_filename(Path(urlparse(str(resp.url)).path).name or parsed.netloc or "resource")
        if "." not in filename and content_type == "text/html":
            filename = filename + ".html"
        elif "." not in filename:
            guessed_ext = mimetypes.guess_extension(content_type or "") or ""
            filename = filename + guessed_ext
        if not is_supported(filename, content_type, source_type="url"):
            raise ValueError(f"Unsupported resource type: {content_type or filename}")
        return {
            "final_url": str(resp.url),
            "filename": filename,
            "content": content,
            "mime_type": content_type or detect_mime_type(filename),
        }


def save_resource_file(*, resource_id: int, filename: str, content: bytes, settings: dict) -> Path:
    root = ensure_storage_root(settings)
    folder = root / str(resource_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / sanitize_filename(filename)
    target.write_bytes(content)
    return target


def resource_content_url(resource_id: int) -> str:
    return f"/api/resources/{resource_id}/content"


def serialize_resource(row) -> dict:
    data = dict(row)
    data["content_url"] = resource_content_url(data["id"])
    try:
        data["meta"] = json.loads(data.get("meta_json") or "{}")
    except Exception:
        data["meta"] = {}
    data["is_image"] = data.get("kind") == "image"
    return data


def encode_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")

