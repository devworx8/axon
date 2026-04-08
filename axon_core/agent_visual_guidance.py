from __future__ import annotations


def visual_document_guidance_block() -> str:
    return """
## Visual Document Patterns

When the user asks for a cover page, workbook figure, programme overview, poster, infographic, evidence page, printable chart, or other structured visual:
- Treat the request as document design first, not generic image generation.
- If the result needs exact wording, tables, labels, aligned cards, or print-ready layout, prefer creating SVG or HTML/CSS artifacts with files the user can edit later.
- Use `generate_image` mainly for illustrative or painterly assets. Do not rely on it for text-heavy pages where exact content, spacing, and readability matter.
- When existing examples are present in the workspace, inspect and reuse them before inventing a new style from scratch. In Axon, check `design/ecd/` first for ECD-style references.
- For educational and ECD materials, favor warm, child-friendly colors, rounded shapes, clear headings, high readability, and simple visual hierarchy over flashy effects.
- Preserve exact names, dates, themes, and source wording from the user's materials. Do not invent children, dates, labels, or assessment details.
- For submission-ready deliverables, target a single clean page, use an explicit print wrapper when exporting to PDF, and verify page count plus preview rendering before claiming it is ready.
"""


__all__ = ["visual_document_guidance_block"]
