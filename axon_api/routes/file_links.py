"""Safe local file-open routes for clickable file links inside Axon."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


router = APIRouter(tags=["file-links"])

_HOME = Path.home().resolve()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _safe_local_path(raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = (_REPO_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not str(candidate).startswith(str(_HOME)):
        raise HTTPException(403, "Access outside home directory is not allowed.")
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
