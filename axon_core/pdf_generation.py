from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import pdf_fallback


@dataclass
class PdfSection:
    heading: str = ""
    lead: str = ""
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


@dataclass
class PdfSpec:
    title: str
    subtitle: str = ""
    author: str = ""
    date: str = ""
    theme: str = "clean"
    sections: list[PdfSection] = field(default_factory=list)
    output_path: str = ""


def _safe_output_path(title: str, output_path: str = "") -> Path:
    if output_path:
        return Path(output_path).expanduser()
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "", title or "Document").strip().replace(" ", "_")
    return downloads / f"{safe_title or 'Document'}_{date.today().isoformat()}.pdf"


def _paragraphs_from_content(content: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", str(content or "").strip()) if block.strip()]
    return [block.replace("\n", " ") for block in blocks]


def pdf_from_dict(data: dict[str, Any]) -> PdfSpec:
    sections: list[PdfSection] = []
    for raw in data.get("sections", []) or []:
        sections.append(
            PdfSection(
                heading=str(raw.get("heading") or "").strip(),
                lead=str(raw.get("lead") or "").strip(),
                paragraphs=[
                    str(item).strip()
                    for item in (raw.get("paragraphs") or [])
                    if str(item).strip()
                ],
                bullets=[
                    str(item).strip()
                    for item in (raw.get("bullets") or [])
                    if str(item).strip()
                ],
            )
        )

    if not sections:
        top_paragraphs = _paragraphs_from_content(str(data.get("content") or ""))
        top_bullets = [
            str(item).strip()
            for item in (data.get("bullets") or [])
            if str(item).strip()
        ]
        sections.append(
            PdfSection(
                heading=str(data.get("section_heading") or "").strip(),
                lead=str(data.get("lead") or "").strip(),
                paragraphs=top_paragraphs,
                bullets=top_bullets,
            )
        )

    return PdfSpec(
        title=str(data.get("title") or "Document").strip() or "Document",
        subtitle=str(data.get("subtitle") or "").strip(),
        author=str(data.get("author") or "").strip(),
        date=str(data.get("date") or date.today().isoformat()).strip(),
        theme=str(data.get("theme") or "clean").strip() or "clean",
        sections=sections,
        output_path=str(data.get("output_path") or "").strip(),
    )


def build_pdf(spec: PdfSpec) -> Path:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    except Exception as exc:  # pragma: no cover - dependency check
        if isinstance(exc, ModuleNotFoundError):
            return pdf_fallback.build_fallback_pdf(spec, safe_output_path=_safe_output_path)
        raise RuntimeError("reportlab is required for PDF generation") from exc

    out = _safe_output_path(spec.title, spec.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="AxonTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AxonSubtitle",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#475569"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AxonHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AxonLead",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="AxonBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#334155"),
            spaceAfter=7,
        )
    )

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=spec.title,
        author=spec.author,
    )

    story: list[Any] = [Paragraph(escape(spec.title), styles["AxonTitle"])]
    if spec.subtitle:
        story.append(Paragraph(escape(spec.subtitle), styles["AxonSubtitle"]))
    meta_parts = [part for part in (spec.author, spec.date or date.today().isoformat()) if part]
    if meta_parts:
        story.append(Paragraph(escape(" | ".join(meta_parts)), styles["AxonSubtitle"]))
    story.append(Spacer(1, 6))

    for index, section in enumerate(spec.sections):
        has_heading = bool(section.heading)
        if has_heading:
            story.append(Paragraph(escape(section.heading), styles["AxonHeading"]))
        if section.lead:
            story.append(Paragraph(escape(section.lead), styles["AxonLead"]))
        for paragraph in section.paragraphs:
            if paragraph:
                story.append(Paragraph(escape(paragraph), styles["AxonBody"]))
        if section.bullets:
            story.append(
                ListFlowable(
                    [
                        ListItem(Paragraph(escape(item), styles["AxonBody"]))
                        for item in section.bullets
                        if item
                    ],
                    bulletType="bullet",
                    start="circle",
                    leftIndent=12,
                )
            )
            story.append(Spacer(1, 4))
        if index != len(spec.sections) - 1:
            story.append(Spacer(1, 8))

    doc.build(story)
    return out


SYSTEM_PROMPT = """You are a document designer. Given a document request and context,
return a JSON document specification. Use this exact schema:

{
  "title": "Document title",
  "subtitle": "Optional subtitle",
  "theme": "clean",
  "sections": [
    {
      "heading": "Optional section heading",
      "lead": "Short introduction sentence",
      "paragraphs": ["Paragraph one", "Paragraph two"],
      "bullets": ["Bullet one", "Bullet two"]
    }
  ]
}

Rules:
- Return ONLY valid JSON, no markdown fences
- Keep paragraphs concise and factual
- Use bullets for checklists, action items, or short points
- Produce 2 to 8 sections total
- Every section should have at least one paragraph or one bullet
"""


def prompt_to_pdf_json(prompt: str, context: str = "", model_fn=None) -> dict[str, Any]:
    if model_fn is None:
        raise RuntimeError("model_fn required for AI PDF generation")

    user_msg = f"Document request: {prompt}"
    if context:
        user_msg += f"\n\nContext:\n{context}"

    raw = model_fn(SYSTEM_PROMPT, user_msg)
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return json.loads(raw)


__all__ = [
    "PdfSection",
    "PdfSpec",
    "build_pdf",
    "pdf_from_dict",
    "prompt_to_pdf_json",
]
