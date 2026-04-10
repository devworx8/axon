from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from axon_core.visual_document_templates import TEMPLATE_META, render_svg


@dataclass(frozen=True)
class VisualDocumentArtifact:
    template: str
    title: str
    svg_path: Path
    html_path: Path
    pdf_path: Path | None


class VisualDocumentGenerationError(RuntimeError):
    pass


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return cleaned.strip("-") or "visual-document"


def _ensure_output_dir(path: str = "") -> Path:
    base = Path(path).expanduser() if str(path or "").strip() else Path.home() / "Documents" / "axon-visuals"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_print_wrapper(*, svg_filename: str, title: str, orientation: str) -> str:
    size = "A4 portrait" if orientation == "portrait" else "A4 landscape"
    body_w = "210mm" if orientation == "portrait" else "297mm"
    body_h = "297mm" if orientation == "portrait" else "210mm"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{html.escape(title)}</title>
    <style>
      @page {{
        size: {size};
        margin: 0;
      }}
      html, body {{
        margin: 0;
        padding: 0;
        width: {body_w};
        height: {body_h};
        overflow: hidden;
        background: #ffffff;
      }}
      img {{
        display: block;
        width: {body_w};
        height: {body_h};
      }}
    </style>
  </head>
  <body>
    <img src="{html.escape(svg_filename)}" alt="{html.escape(title)}" />
  </body>
</html>
"""


def _export_pdf(html_path: Path, pdf_path: Path) -> Path:
    command = [
        "google-chrome",
        "--headless",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--no-pdf-header-footer",
        html_path.as_uri(),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise VisualDocumentGenerationError("google-chrome is required to export visual-document PDFs.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise VisualDocumentGenerationError(f"PDF export failed: {detail}") from exc
    if not pdf_path.exists():
        raise VisualDocumentGenerationError("PDF export did not create the expected file.")
    return pdf_path


def build_visual_document(document: dict[str, object]) -> VisualDocumentArtifact:
    payload = dict(document or {})
    template = str(payload.get("template") or "").strip()
    if not template:
        raise VisualDocumentGenerationError("Visual document template is required.")
    if template not in TEMPLATE_META:
        raise VisualDocumentGenerationError(f"Unsupported visual document template `{template}`.")

    title = str(payload.get("title") or "Visual Document").strip() or "Visual Document"
    output_dir = _ensure_output_dir(str(payload.get("output_dir") or ""))
    file_stem = str(payload.get("file_stem") or "").strip() or _slugify(title)
    svg_path = output_dir / f"{file_stem}.svg"
    html_path = output_dir / f"{file_stem}_print.html"
    pdf_requested = bool(payload.get("pdf", True))
    pdf_path = output_dir / f"{file_stem}.pdf" if pdf_requested else None

    try:
        svg_markup = render_svg(template, payload)
    except RuntimeError as exc:
        raise VisualDocumentGenerationError(str(exc)) from exc

    svg_path.write_text(svg_markup, encoding="utf-8")
    html_path.write_text(
        _write_print_wrapper(
            svg_filename=svg_path.name,
            title=title,
            orientation=TEMPLATE_META[template]["orientation"],
        ),
        encoding="utf-8",
    )
    if pdf_requested and pdf_path is not None:
        _export_pdf(html_path, pdf_path)

    return VisualDocumentArtifact(
        template=template,
        title=title,
        svg_path=svg_path,
        html_path=html_path,
        pdf_path=pdf_path if pdf_requested else None,
    )


__all__ = ["VisualDocumentArtifact", "VisualDocumentGenerationError", "build_visual_document"]
