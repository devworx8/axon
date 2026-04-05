"""Safe local file-open routes for clickable file links inside Axon."""
from __future__ import annotations

import mimetypes
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


router = APIRouter(tags=["file-links"])

_HOME = Path.home().resolve()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
_LINE_SUFFIX_RE = re.compile(r"#L\d+(?:C\d+)?$", re.IGNORECASE)


def _safe_local_path(raw_path: str) -> Path:
    cleaned = _LINE_SUFFIX_RE.sub("", str(raw_path or "").strip())
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = (_REPO_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    allowed_roots = (_HOME, _TEMP_ROOT)
    if not any(str(candidate).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(403, "Access outside allowed local directories is not allowed.")
    return candidate


@router.get("/api/files/open")
async def open_local_file(path: str):
    file_path = _safe_local_path(path)
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    if file_path.is_dir():
        raise HTTPException(400, "Path is a directory")
    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(
        str(file_path),
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{file_path.name}"'},
    )
