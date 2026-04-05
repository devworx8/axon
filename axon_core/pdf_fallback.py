from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import wrap
from typing import Any, Callable


def _pdf_escape_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    normalized = normalized.encode("latin-1", "replace").decode("latin-1")
    return normalized.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _append_wrapped_line(lines: list[tuple[str, int]], text: str, *, size: int, prefix: str = "") -> None:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return
    width = 90 if size <= 10 else 72 if size <= 12 else 60
    wrapped = wrap(normalized, width=width, break_long_words=False, break_on_hyphens=False) or [normalized]
    if prefix:
        lines.append((f"{prefix}{wrapped[0]}", size))
        indent = " " * len(prefix)
        for item in wrapped[1:]:
            lines.append((f"{indent}{item}", size))
        return
    for item in wrapped:
        lines.append((item, size))


def _fallback_pdf_lines(spec: Any) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []
    _append_wrapped_line(lines, spec.title, size=20)
    if spec.subtitle:
        _append_wrapped_line(lines, spec.subtitle, size=12)
    meta = " | ".join(part for part in (spec.author, spec.date or date.today().isoformat()) if part)
    if meta:
        _append_wrapped_line(lines, meta, size=10)
    lines.append(("", 10))
    for index, section in enumerate(spec.sections):
        if section.heading:
            _append_wrapped_line(lines, section.heading, size=14)
        if section.lead:
            _append_wrapped_line(lines, section.lead, size=11)
        for paragraph in section.paragraphs:
            _append_wrapped_line(lines, paragraph, size=10)
        for bullet in section.bullets:
            _append_wrapped_line(lines, bullet, size=10, prefix="- ")
        if index != len(spec.sections) - 1:
            lines.append(("", 10))
    return lines


def build_fallback_pdf(spec: Any, *, safe_output_path: Callable[[str, str], Path]) -> Path:
    out = safe_output_path(spec.title, spec.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    top_y = 792
    bottom_y = 56
    left_x = 54
    pages: list[list[tuple[str, int, int]]] = [[]]
    current_page = pages[0]
    cursor_y = top_y
    for text, size in _fallback_pdf_lines(spec):
        advance = size + 6 if text else 10
        if cursor_y - advance < bottom_y and current_page:
            current_page = []
            pages.append(current_page)
            cursor_y = top_y
        if text:
            current_page.append((text, size, cursor_y))
        cursor_y -= advance

    page_object_ids = [4 + (index * 2) for index in range(len(pages))]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_object_ids)}] >>".encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    for index, page in enumerate(pages):
        page_id = page_object_ids[index]
        content_id = page_id + 1
        stream_lines = ["BT"]
        for text, size, y in page:
            stream_lines.append(f"/F1 {size} Tf")
            stream_lines.append(f"1 0 0 1 {left_x} {y} Tm")
            stream_lines.append(f"({_pdf_escape_text(text)}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode("latin-1")
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("latin-1"))
        pdf.extend(obj)
        if not obj.endswith(b"\n"):
            pdf.extend(b"\n")
        pdf.extend(b"endobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
    )
    out.write_bytes(pdf)
    return out
