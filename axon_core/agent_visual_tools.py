from __future__ import annotations

import os
from typing import Any, Callable

from . import visual_document_generation


VISUAL_TEMPLATE_TOOL_NAMES: dict[str, str] = {
    "create_ecd_cover_page": "ecd_cover_page",
    "create_ecd_weekly_overview": "ecd_weekly_overview",
    "create_ecd_cycle_diagram": "ecd_cycle_diagram",
    "create_ecd_strategy_grid": "ecd_strategy_grid",
    "create_ecd_support_poster": "ecd_support_poster",
}

_VISUAL_ARG_KEYS = {
    "template",
    "title",
    "subtitle",
    "theme",
    "unit_standard",
    "learner_name",
    "centre_name",
    "activity_date",
    "compilation_date",
    "focus_areas",
    "summary_lines",
    "planning_principles",
    "days",
    "rows",
    "center_title",
    "center_subtitle",
    "steps",
    "cards",
    "footer",
    "footer_title",
    "footer_lines",
    "output_dir",
    "file_stem",
    "pdf",
}


def normalize_visual_tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(args or {})
    template_name = VISUAL_TEMPLATE_TOOL_NAMES.get(name)
    if template_name and not normalized.get("template"):
        normalized["template"] = template_name
    if not normalized.get("template"):
        for alias in ("template_id", "kind", "type"):
            if normalized.get(alias):
                normalized["template"] = normalized.pop(alias)
                break
    if not normalized.get("output_dir"):
        for alias in ("path", "dir", "directory"):
            if normalized.get(alias):
                normalized["output_dir"] = normalized.pop(alias)
                break
    if not normalized.get("file_stem"):
        for alias in ("filename", "name", "slug"):
            if normalized.get(alias):
                normalized["file_stem"] = normalized.pop(alias)
                break
    for alias in ("template_id", "kind", "type", "path", "dir", "directory", "filename", "name", "slug"):
        normalized.pop(alias, None)
    return {key: value for key, value in normalized.items() if key in _VISUAL_ARG_KEYS}


def build_visual_tool_registry(*, tool_path_allowed_fn: Callable[[str], bool]) -> dict[str, Callable[..., str]]:
    def _tool_generate_visual_document(
        template: str,
        title: str,
        subtitle: str = "",
        theme: str = "",
        unit_standard: str = "",
        learner_name: str = "",
        centre_name: str = "",
        activity_date: str = "",
        compilation_date: str = "",
        focus_areas: list[str] | None = None,
        summary_lines: list[str] | None = None,
        planning_principles: list[str] | None = None,
        days: list[str] | None = None,
        rows: list[dict[str, Any]] | None = None,
        center_title: str = "",
        center_subtitle: str = "",
        steps: list[dict[str, Any]] | None = None,
        cards: list[dict[str, Any]] | None = None,
        footer: str = "",
        footer_title: str = "",
        footer_lines: list[str] | None = None,
        output_dir: str = "",
        file_stem: str = "",
        pdf: bool = True,
    ) -> str:
        resolved_output_dir = str(output_dir or "").strip()
        if resolved_output_dir:
            resolved_dir = os.path.realpath(os.path.expanduser(resolved_output_dir))
            if not tool_path_allowed_fn(resolved_dir):
                return "ERROR: Visual document output path must stay within the allowed directories."
        try:
            artifact = visual_document_generation.build_visual_document(
                {
                    "template": template,
                    "title": title,
                    "subtitle": subtitle,
                    "theme": theme,
                    "unit_standard": unit_standard,
                    "learner_name": learner_name,
                    "centre_name": centre_name,
                    "activity_date": activity_date,
                    "compilation_date": compilation_date,
                    "focus_areas": focus_areas or [],
                    "summary_lines": summary_lines or [],
                    "planning_principles": planning_principles or [],
                    "days": days or [],
                    "rows": rows or [],
                    "center_title": center_title,
                    "center_subtitle": center_subtitle,
                    "steps": steps or [],
                    "cards": cards or [],
                    "footer": footer,
                    "footer_title": footer_title,
                    "footer_lines": footer_lines or [],
                    "output_dir": resolved_output_dir,
                    "file_stem": file_stem,
                    "pdf": pdf,
                }
            )
        except visual_document_generation.VisualDocumentGenerationError as exc:
            return f"ERROR: {exc}"
        lines = [
            f"Generated visual document: {artifact.title}",
            f"Template: {artifact.template}",
            f"SVG: {artifact.svg_path}",
            f"Print HTML: {artifact.html_path}",
        ]
        if artifact.pdf_path:
            lines.append(f"PDF: {artifact.pdf_path}")
        return "\n".join(lines)

    registry: dict[str, Callable[..., str]] = {"generate_visual_document": _tool_generate_visual_document}
    for tool_name in VISUAL_TEMPLATE_TOOL_NAMES:
        registry[tool_name] = _tool_generate_visual_document
    return registry


__all__ = ["VISUAL_TEMPLATE_TOOL_NAMES", "build_visual_tool_registry", "normalize_visual_tool_args"]
