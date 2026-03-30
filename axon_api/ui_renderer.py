from __future__ import annotations

from pathlib import Path
import re

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response


NO_STORE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate"}


_INCLUDE_RE = re.compile(r"^\s*<!-- @include (\S+) -->\s*$", re.MULTILINE)


def _expand_includes(html: str, base_dir: Path, *, _depth: int = 0) -> str:
    """Replace ``<!-- @include path/to/file.html -->`` directives with file contents."""
    if _depth > 5:
        return html

    def _replacer(m: re.Match) -> str:
        partial = base_dir / m.group(1)
        if not partial.resolve().is_relative_to(base_dir.resolve()):
            return f"<!-- include denied: {m.group(1)} -->"
        if not partial.exists():
            return f"<!-- missing partial: {m.group(1)} -->"
        return _expand_includes(partial.read_text(encoding="utf-8"), base_dir, _depth=_depth + 1)

    return _INCLUDE_RE.sub(_replacer, html)


def _read_versioned_html(path: Path, build_version: str) -> HTMLResponse:
    if not path.exists():
        if path.name == "index.html":
            return HTMLResponse(
                "<h1>Axon UI not found</h1><p>Run install.sh again.</p>",
                status_code=404,
            )
        return HTMLResponse("<h1>Manual not found</h1>", status_code=404)
    html = path.read_text(encoding="utf-8")
    html = _expand_includes(html, path.parent)
    html = html.replace("__AXON_BUILD_VERSION__", build_version)
    return HTMLResponse(html, headers=NO_STORE_HEADERS)


def render_index(ui_dir: Path, build_version: str) -> HTMLResponse:
    return _read_versioned_html(ui_dir / "index.html", build_version)


def render_manual(ui_dir: Path, build_version: str) -> HTMLResponse:
    return _read_versioned_html(ui_dir / "manual.html", build_version)


def render_manifest() -> JSONResponse:
    return JSONResponse(
        {
            "id": "/",
            "name": "Axon",
            "short_name": "Axon",
            "description": "Local AI Operator — console, workspaces, missions, secure vault",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#020617",
            "theme_color": "#0f172a",
            "orientation": "portrait-primary",
            "icons": [
                {
                    "src": "/icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
            "categories": ["productivity", "developer-tools"],
            "shortcuts": [
                {"name": "Console", "url": "/", "description": "Open Axon Console"},
                {
                    "name": "Missions",
                    "url": "/",
                    "description": "Review active missions",
                },
            ],
        }
    )


def render_styles(ui_dir: Path) -> Response:
    css_path = ui_dir / "styles.css"
    if not css_path.exists():
        return Response("/* not found */", media_type="text/css", status_code=404)
    return FileResponse(
        css_path,
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


def render_js(ui_dir: Path, filename: str) -> Response:
    if not re.match(r"^[a-zA-Z0-9_\-]+\.js$", filename):
        return Response(
            "// not found",
            media_type="application/javascript",
            status_code=404,
        )
    js_path = ui_dir / "js" / filename
    if not js_path.exists():
        return Response(
            "// not found",
            media_type="application/javascript",
            status_code=404,
        )
    return FileResponse(
        js_path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def render_icon(ui_dir: Path, filename: str) -> FileResponse:
    icon_path = ui_dir / "icons" / filename
    if not icon_path.exists() or not filename.endswith(".png"):
        raise HTTPException(404, "Icon not found")
    return FileResponse(str(icon_path), media_type="image/png")


def render_service_worker(build_version: str) -> Response:
    sw_code = f"""
const CACHE = '{build_version}';
const STATIC = ['/icons/icon-192.png', '/icons/icon-512.png', '/manifest.json'];

self.addEventListener('install', e => {{
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
}});

self.addEventListener('activate', e => {{
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => clients.claim())
  );
}});

self.addEventListener('fetch', e => {{
  const url = new URL(e.request.url);

  if (url.pathname.startsWith('/api/')) {{
    e.respondWith(fetch(e.request));
    return;
  }}

  if (url.pathname.startsWith('/icons/')) {{
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request))
    );
    return;
  }}

  e.respondWith(
    fetch(e.request)
      .then(res => {{
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      }})
      .catch(() => caches.match(e.request))
  );
}});
"""
    return Response(
        content=sw_code,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-store",
        },
    )
