from __future__ import annotations


def visual_document_guidance_block() -> str:
    return """
## Visual Document Patterns

When the user asks for a cover page, workbook figure, programme overview, poster, infographic, evidence page, printable chart, or other structured visual:
- Treat the request as document design first, not generic image generation.
- If the result needs exact wording, tables, labels, aligned cards, or print-ready layout, prefer creating SVG or HTML/CSS artifacts with files the user can edit later.
- Prefer the named ECD visual tools when they fit: `create_ecd_cover_page`, `create_ecd_weekly_overview`, `create_ecd_cycle_diagram`, `create_ecd_strategy_grid`, and `create_ecd_support_poster`.
- Use `generate_image` mainly for illustrative or painterly assets. Do not rely on it for text-heavy pages where exact content, spacing, and readability matter.
- When existing examples are present in the workspace, inspect and reuse them before inventing a new style from scratch. In Axon, check `design/ecd/` first for ECD-style references.
- For educational and ECD materials, favor warm, child-friendly colors, rounded shapes, clear headings, high readability, and simple visual hierarchy over flashy effects.
- Preserve exact names, dates, themes, and source wording from the user's materials. Do not invent children, dates, labels, or assessment details.
- When the user supplies an existing ECD submission DOCX, prefer refreshing the submission in place: replace draft-style cover blocks, regenerate weak figures or posters as structured visuals, keep the written content authentic and in the learner's first person, and re-export a clean assessor-ready DOCX/PDF pair.
- For submission covers, remove draft-only elements such as internal change logs, submission highlights blocks, or selected-children strips unless the user explicitly asks to keep them.
- For submission-ready deliverables, target a single clean page, use an explicit print wrapper when exporting to PDF, and verify page count, preview rendering, and print legibility before claiming it is ready.
"""


__all__ = ["visual_document_guidance_block"]
