from __future__ import annotations

import html
import textwrap
from typing import Any


TEMPLATE_META = {
    "ecd_cover_page": {"orientation": "portrait", "width": 794, "height": 1123},
    "ecd_weekly_overview": {"orientation": "landscape", "width": 1123, "height": 794},
    "ecd_cycle_diagram": {"orientation": "landscape", "width": 1123, "height": 794},
    "ecd_strategy_grid": {"orientation": "landscape", "width": 1123, "height": 794},
    "ecd_support_poster": {"orientation": "landscape", "width": 1123, "height": 794},
}


def _wrap_lines(value: str, width: int) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return [""]
    lines: list[str] = []
    for block in raw.splitlines():
        parts = textwrap.wrap(block.strip(), width=width) or [""]
        lines.extend(parts)
    return lines


def _svg_multiline(
    value: str,
    *,
    x: float,
    y: float,
    width: int,
    line_height: int,
    css_class: str,
    anchor: str = "middle",
) -> str:
    lines = _wrap_lines(value, width)
    escaped = []
    for index, line in enumerate(lines):
        dy = "0" if index == 0 else str(line_height)
        escaped.append(f'<tspan x="{x}" dy="{dy}">{html.escape(line)}</tspan>')
    return f'<text x="{x}" y="{y}" class="{css_class}" text-anchor="{anchor}">{"".join(escaped)}</text>'


def _render_ecd_cover_page_svg(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "Workbook Answers and Evidence Pack").strip()
    subtitle = str(document.get("subtitle") or "").strip()
    unit_standard = str(document.get("unit_standard") or "").strip()
    learner_name = str(document.get("learner_name") or "").strip()
    centre_name = str(document.get("centre_name") or "").strip()
    theme = str(document.get("theme") or "").strip()
    activity_date = str(document.get("activity_date") or "").strip()
    compilation_date = str(document.get("compilation_date") or "").strip()
    focus_areas = list(document.get("focus_areas") or [])
    summary_lines = list(document.get("summary_lines") or [])

    chips = [
        ("Play-based learning", "#c45c4d"),
        ("Observation", "#2f8892"),
        ("Mediation", "#6a9e3d"),
        ("Reflection", "#7a67b9"),
    ]
    if focus_areas:
        chips = []
        colors = ["#c45c4d", "#2f8892", "#6a9e3d", "#7a67b9"]
        for index, item in enumerate(focus_areas[:4]):
            chips.append((str(item), colors[index % len(colors)]))

    meta_rows = [
        ("Prepared for", learner_name),
        ("Centre", centre_name),
        ("Theme", theme),
        ("Activity date", activity_date),
        ("Compilation date", compilation_date),
    ]

    chip_svg = []
    chip_x = [106, 276, 428, 563]
    chip_w = [152, 136, 120, 129]
    for index, (label, color) in enumerate(chips[:4]):
        chip_svg.append(
            f'<rect x="{chip_x[index]}" y="872" width="{chip_w[index]}" height="36" rx="14" fill="{color}"/>'
        )
        chip_svg.append(
            _svg_multiline(
                label,
                x=chip_x[index] + chip_w[index] / 2,
                y=895,
                width=18,
                line_height=15,
                css_class="chip",
            )
        )

    summary_svg = []
    for index, line in enumerate(summary_lines[:3]):
        cy = 970 + (index * 28)
        summary_svg.append(f'<circle cx="132" cy="{cy}" r="4" fill="#2f8892"/>')
        summary_svg.append(
            f'<text x="148" y="{cy + 6}" class="body-left">{html.escape(str(line))}</text>'
        )

    meta_svg = []
    row_y = 588
    for label, value in meta_rows:
        meta_svg.append(
            f'<rect x="120" y="{row_y}" width="145" height="30" rx="10" fill="#d9e7f7" stroke="#b2c9e4"/>'
        )
        meta_svg.append(f'<text x="136" y="{row_y + 20}" class="label-left">{html.escape(label)}</text>')
        meta_svg.append(f'<text x="286" y="{row_y + 21}" class="body-left">{html.escape(value)}</text>')
        row_y += 36

    subtitle_block = ""
    if unit_standard:
        subtitle_block = _svg_multiline(unit_standard, x=396, y=442, width=48, line_height=30, css_class="subhead")
    elif subtitle:
        subtitle_block = _svg_multiline(subtitle, x=396, y=442, width=48, line_height=30, css_class="subhead")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">ECD cover page for {html.escape(learner_name or 'learner')}.</desc>
  <defs>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="6" dy="8" stdDeviation="0" flood-color="#d7e4ea" flood-opacity="1"/>
    </filter>
    <filter id="softShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#d7d0c6" flood-opacity="0.35"/>
    </filter>
    <style>
      .heading {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #27446d; font-size: 58px; }}
      .subhead {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2f8892; font-size: 27px; }}
      .body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #334a62; font-size: 21px; }}
      .label-left {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #27446d; font-size: 18px; }}
      .body-left {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #334a62; font-size: 19px; }}
      .chip {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 15px; }}
    </style>
  </defs>
  <rect width="794" height="1123" fill="#fbf5ea"/>
  <circle cx="48" cy="126" r="208" fill="#bfe6f5"/>
  <circle cx="702" cy="118" r="185" fill="#fee7a8"/>
  <circle cx="105" cy="1040" r="190" fill="#d6efc2"/>
  <circle cx="686" cy="1054" r="214" fill="#f5d0db"/>
  <path d="M72 76 H735" stroke="#2f8892" stroke-width="3"/>
  <path d="M72 76 L108 112 L145 76 Z" fill="#c45c4d"/>
  <path d="M145 76 L182 112 L218 76 Z" fill="#dc9a2b"/>
  <path d="M218 76 L255 112 L292 76 Z" fill="#2f8892"/>
  <path d="M292 76 L329 112 L366 76 Z" fill="#6a9e3d"/>
  <path d="M366 76 L403 112 L440 76 Z" fill="#7a67b9"/>
  <path d="M440 76 L477 112 L514 76 Z" fill="#c45c4d"/>
  <path d="M514 76 L551 112 L588 76 Z" fill="#dc9a2b"/>
  <path d="M588 76 L625 112 L662 76 Z" fill="#2f8892"/>
  <path d="M662 76 L699 112 L735 76 Z" fill="#6a9e3d"/>
  <g filter="url(#shadow)">
    <rect x="60" y="178" width="672" height="688" rx="30" fill="#ffffff" stroke="#f0d7b3" stroke-width="2"/>
  </g>
  <rect x="100" y="211" width="292" height="34" rx="12" fill="#27446d"/>
  <text x="118" y="233" font-family="Trebuchet MS, Verdana, sans-serif" font-size="16" font-weight="700" fill="#ffffff">ECD ASSESSMENT PORTFOLIO</text>
  {_svg_multiline(title, x=396, y=333, width=28, line_height=56, css_class="heading")}
  {subtitle_block}
  {_svg_multiline(subtitle or "Submission-ready workbook answers and supporting evidence", x=396, y=512, width=64, line_height=24, css_class="body")}
  <g filter="url(#softShadow)">
    <rect x="98" y="560" width="598" height="216" rx="22" fill="#fffdfa" stroke="#ead8bf" stroke-width="2"/>
  </g>
  {''.join(meta_svg)}
  {''.join(chip_svg)}
  {"<g filter='url(#softShadow)'><rect x='72' y='926' width='650' height='126' rx='24' fill='#ffffff' stroke='#ead8bf' stroke-width='2'/></g>" if summary_svg else ""}
  {"<text x='111' y='964' font-family='Trebuchet MS, Verdana, sans-serif' font-size='28' font-weight='700' fill='#27446d'>Submission highlights</text>" if summary_svg else ""}
  {''.join(summary_svg)}
  <path d="M178 1084 H616" stroke="#ead8bf" stroke-width="2" stroke-linecap="round"/>
  <text x="397" y="1111" font-family="Trebuchet MS, Verdana, sans-serif" font-size="17" font-weight="700" fill="#27446d" text-anchor="middle">Young children learn best through talk, play, movement, repetition and caring adult guidance.</text>
</svg>"""


def _render_ecd_weekly_overview_svg(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "Figure 1. Weekly Learning Programme Overview").strip()
    subtitle = str(document.get("subtitle") or "").strip()
    theme = str(document.get("theme") or "").strip()
    planning_principles = list(document.get("planning_principles") or [])
    days = list(document.get("days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    rows = list(document.get("rows") or [])
    if len(days) != 5:
        raise RuntimeError("ecd_weekly_overview requires exactly five day labels.")
    if not rows:
        raise RuntimeError("ecd_weekly_overview requires at least one row.")

    bullet_svg = []
    bullet_y = 268
    for item in planning_principles[:5]:
        bullet_svg.append(f'<circle cx="76" cy="{bullet_y}" r="6" fill="#2d7e88"/>')
        bullet_svg.append(_svg_multiline(str(item), x=96, y=bullet_y + 6, width=28, line_height=20, css_class="left-body", anchor="start"))
        bullet_y += 86

    header_cells = []
    day_x = [459, 582, 705, 828, 951]
    day_w = 121
    day_centers = [x + (day_w / 2) for x in day_x]
    header_cells.append('<rect x="307" y="210" width="150" height="62" rx="16" fill="#d6e3f2" stroke="#b8cde1"/>')
    header_cells.append(_svg_multiline("Area / evidence", x=382, y=233, width=12, line_height=22, css_class="table-head"))
    for idx, day in enumerate(days):
        header_cells.append(f'<rect x="{day_x[idx]}" y="210" width="{day_w}" height="62" rx="16" fill="#e5f1ed" stroke="#b8d8d0"/>')
        header_cells.append(f'<text x="{day_centers[idx]}" y="249" class="day-head" text-anchor="middle">{html.escape(str(day))}</text>')

    row_svg = []
    row_y = 276
    gap = 4
    remaining = 738 - row_y - (gap * max(0, len(rows) - 1))
    base_height = max(74, int(remaining / len(rows)))
    for index, row in enumerate(rows):
        label = str(row.get("label") or "").strip()
        values = [str(value or "") for value in list(row.get("values") or [])[:5]]
        while len(values) < 5:
            values.append("")
        height = base_height if index < len(rows) - 1 else 738 - row_y
        row_svg.append(f'<rect x="307" y="{row_y}" width="150" height="{height}" rx="16" fill="#fff6e6" stroke="#ead8bf"/>')
        row_svg.append(_svg_multiline(label, x=382, y=row_y + 34, width=14, line_height=21, css_class="row-label"))
        for cell_index, value in enumerate(values):
            row_svg.append(f'<rect x="{day_x[cell_index]}" y="{row_y}" width="{day_w}" height="{height}" rx="16" fill="#ffffff" stroke="#d3e1ec"/>')
            row_svg.append(
                _svg_multiline(
                    value,
                    x=day_centers[cell_index],
                    y=row_y + 28,
                    width=12,
                    line_height=17,
                    css_class="cell-text",
                )
            )
        row_y += height + gap

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1123" height="794" viewBox="0 0 1123 794" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">ECD weekly learning programme overview.</desc>
  <defs>
    <filter id="cardShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="7" dy="10" stdDeviation="0" flood-color="#d8e5ed" flood-opacity="1"/>
    </filter>
    <style>
      .page-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 32px; }}
      .left-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2a466f; font-size: 26px; }}
      .theme {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2d7e88; font-size: 17px; }}
      .left-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: 16px; }}
      .table-head {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2a466f; font-size: 18px; }}
      .day-head {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2a466f; font-size: 18px; }}
      .row-label {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2a466f; font-size: 18px; }}
      .cell-text {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: 13px; }}
    </style>
  </defs>
  <rect width="1123" height="794" fill="#f7f3ec"/>
  <circle cx="48" cy="727" r="145" fill="#dcecf2"/>
  <circle cx="1086" cy="104" r="165" fill="#e4eef4"/>
  <circle cx="965" cy="756" r="128" fill="#edf3d7"/>
  <circle cx="109" cy="114" r="90" fill="#fff0c8"/>
  <rect x="44" y="34" width="1035" height="84" rx="28" fill="#314e79" filter="url(#cardShadow)"/>
  <rect x="56" y="117" width="1020" height="10" rx="5" fill="#2d7e88"/>
  <text x="72" y="86" class="page-title">{html.escape(title)}</text>
  <text x="72" y="115" font-family="Trebuchet MS, Verdana, sans-serif" font-size="18" fill="#dce8f0">{html.escape(subtitle)}</text>
  <rect x="736" y="145" width="292" height="40" rx="16" fill="#e4f1ed"/>
  <text x="877" y="170" class="theme" text-anchor="middle">Theme: {html.escape(theme)}</text>
  <g filter="url(#cardShadow)">
    <rect x="44" y="170" width="230" height="522" rx="24" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/>
  </g>
  {_svg_multiline("Planning principles", x=70, y=228, width=12, line_height=28, css_class="left-title", anchor="start")}
  {''.join(bullet_svg)}
  <g filter="url(#cardShadow)">
    <rect x="289" y="170" width="790" height="586" rx="24" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/>
  </g>
  {''.join(header_cells)}
  {''.join(row_svg)}
</svg>"""


def _render_ecd_cycle_diagram_svg(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "ECD Cycle Diagram").strip()
    subtitle = str(document.get("subtitle") or "").strip()
    center_title = str(document.get("center_title") or "Continuous").strip()
    center_subtitle = str(document.get("center_subtitle") or "Child-centred improvement").strip()
    steps = list(document.get("steps") or [])
    if len(steps) != 5:
        raise RuntimeError("ecd_cycle_diagram requires exactly five steps.")

    positions = [(558, 208), (790, 320), (700, 548), (416, 548), (326, 320)]
    colors = ["#d7e6f5", "#e2f2e8", "#fff0cf", "#f1e3fa", "#e7eef7"]
    card_svg = []
    connector_svg = []
    circle_points = [(558, 334), (660, 386), (620, 486), (496, 486), (456, 386)]
    next_points = circle_points[1:] + circle_points[:1]
    for idx, step in enumerate(steps):
        title_text = str(step.get("title") or "").strip()
        body_text = str(step.get("body") or "").strip()
        fill = str(step.get("color") or colors[idx % len(colors)])
        x, y = positions[idx]
        card_svg.append(f'<rect x="{x - 98}" y="{y - 52}" width="196" height="104" rx="18" fill="{fill}" stroke="#b9cad9" stroke-width="2"/>')
        card_svg.append(_svg_multiline(title_text, x=x, y=y - 14, width=14, line_height=19, css_class="card-title"))
        card_svg.append(_svg_multiline(body_text, x=x, y=y + 18, width=16, line_height=17, css_class="card-body"))
        sx, sy = circle_points[idx]
        ex, ey = next_points[idx]
        connector_svg.append(f'<path d="M {sx} {sy} Q 558 395 {ex} {ey}" fill="none" stroke="#7088a5" stroke-width="4" stroke-linecap="round"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1123" height="794" viewBox="0 0 1123 794" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">ECD cycle diagram.</desc>
  <defs>
    <filter id="softShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="7" dy="10" stdDeviation="0" flood-color="#d8e5ed" flood-opacity="1"/>
    </filter>
    <style>
      .page-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 31px; }}
      .sub {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #dce8f0; font-size: 18px; }}
      .card-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2b466f; font-size: 21px; }}
      .card-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: 16px; }}
      .center-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2b466f; font-size: 34px; }}
      .center-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #6a7e95; font-size: 18px; }}
    </style>
  </defs>
  <rect width="1123" height="794" fill="#f7f3ec"/>
  <circle cx="88" cy="116" r="82" fill="#fff0c8"/>
  <circle cx="1024" cy="102" r="136" fill="#e4eef4"/>
  <circle cx="1038" cy="706" r="124" fill="#edf3d7"/>
  <rect x="48" y="36" width="1027" height="84" rx="28" fill="#314e79" filter="url(#softShadow)"/>
  <rect x="60" y="120" width="1010" height="10" rx="5" fill="#2d7e88"/>
  <text x="76" y="88" class="page-title">{html.escape(title)}</text>
  <text x="76" y="116" class="sub">{html.escape(subtitle)}</text>
  <g filter="url(#softShadow)">
    <rect x="82" y="162" width="958" height="566" rx="28" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/>
  </g>
  <circle cx="558" cy="395" r="124" fill="#ffffff" stroke="#d4e2ed" stroke-width="4"/>
  <circle cx="558" cy="395" r="156" fill="none" stroke="#7088a5" stroke-width="4"/>
  {''.join(connector_svg)}
  {''.join(card_svg)}
  <text x="558" y="388" class="center-title" text-anchor="middle">{html.escape(center_title)}</text>
  <text x="558" y="420" class="center-body" text-anchor="middle">{html.escape(center_subtitle)}</text>
</svg>"""


def _render_ecd_strategy_grid_svg(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "ECD Strategy Grid").strip()
    subtitle = str(document.get("subtitle") or "").strip()
    footer = str(document.get("footer") or "").strip()
    cards = list(document.get("cards") or [])
    if len(cards) < 3:
        raise RuntimeError("ecd_strategy_grid requires at least three cards.")

    default_colors = ["#e7f0fa", "#e7f5eb", "#fff2d8", "#f3e8fb", "#faece4", "#e8f3de"]
    card_svg = []
    badge_font = "18" if len(cards) <= 4 else "16.5"
    body_font = "18" if len(cards) <= 4 else "16"
    if len(cards) <= 4:
        positions = [(136, 208), (584, 208), (136, 424), (584, 424)]
        card_width = 404
        body_width = 34
    else:
        positions = [(78, 208), (411, 208), (744, 208), (78, 424), (411, 424), (744, 424)]
        card_width = 300
        body_width = 23
    for idx, card in enumerate(cards[: len(positions)]):
        x, y = positions[idx]
        fill = str(card.get("color") or default_colors[idx % len(default_colors)])
        title_text = str(card.get("title") or "").strip()
        body_text = str(card.get("body") or "").strip()
        accent = str(card.get("accent") or "#314e79")
        card_svg.append(f'<g filter="url(#softShadow)"><rect x="{x}" y="{y}" width="{card_width}" height="176" rx="24" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/></g>')
        card_svg.append(f'<rect x="{x + 22}" y="{y + 20}" width="168" height="34" rx="14" fill="{fill}" stroke="#c9d9e8"/>')
        card_svg.append(f'<text x="{x + 106}" y="{y + 43}" class="badge" text-anchor="middle">{html.escape(title_text)}</text>')
        card_svg.append(_svg_multiline(body_text, x=x + (card_width / 2), y=y + 102, width=body_width, line_height=21, css_class="card-body"))
        card_svg.append(f'<rect x="{x + 22}" y="{y + 69}" width="44" height="8" rx="4" fill="{accent}"/>')

    footer_svg = ""
    if footer:
        footer_svg = f"""
  <g filter="url(#softShadow)">
    <rect x="354" y="650" width="414" height="48" rx="18" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/>
  </g>
  <text x="561" y="681" class="footer" text-anchor="middle">{html.escape(footer)}</text>
"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1123" height="794" viewBox="0 0 1123 794" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">ECD strategy grid.</desc>
  <defs>
    <filter id="softShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="7" dy="10" stdDeviation="0" flood-color="#d8e5ed" flood-opacity="1"/>
    </filter>
    <style>
      .page-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 33px; }}
      .sub {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #dce8f0; font-size: 18px; }}
      .badge {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2b466f; font-size: {badge_font}px; }}
      .card-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: {body_font}px; }}
      .footer {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2d7e88; font-size: 18px; }}
    </style>
  </defs>
  <rect width="1123" height="794" fill="#f7f3ec"/>
  <circle cx="86" cy="706" r="120" fill="#dcecf2"/>
  <circle cx="1036" cy="98" r="136" fill="#e4eef4"/>
  <circle cx="1022" cy="706" r="124" fill="#edf3d7"/>
  <rect x="48" y="36" width="1027" height="84" rx="28" fill="#314e79" filter="url(#softShadow)"/>
  <rect x="60" y="120" width="1010" height="10" rx="5" fill="#2d7e88"/>
  <text x="76" y="88" class="page-title">{html.escape(title)}</text>
  <text x="76" y="116" class="sub">{html.escape(subtitle)}</text>
  {''.join(card_svg)}
  {footer_svg}
</svg>"""


def _render_ecd_support_poster_svg(document: dict[str, Any]) -> str:
    title = str(document.get("title") or "ECD Support Poster").strip()
    subtitle = str(document.get("subtitle") or "").strip()
    footer_title = str(document.get("footer_title") or "").strip()
    footer_lines = [str(item or "").strip() for item in list(document.get("footer_lines") or [])[:4]]
    steps = list(document.get("steps") or [])
    if len(steps) < 4:
        raise RuntimeError("ecd_support_poster requires at least four steps.")

    colors = ["#e5eef8", "#e5f5f1", "#fff1d6", "#edf6de", "#f9e8e1", "#ece6fb"]
    accents = ["#314e79", "#2f8892", "#dc9a2b", "#6a9e3d", "#c45c4d", "#7a67b9"]
    card_width = 165
    gap = 14
    start_x = 40
    card_svg = []
    for idx, step in enumerate(steps[:6]):
        x = start_x + (idx * (card_width + gap))
        fill = str(step.get("color") or colors[idx % len(colors)])
        accent = str(step.get("accent") or accents[idx % len(accents)])
        number = str(step.get("number") or idx + 1)
        step_title = str(step.get("title") or "").strip()
        body_text = str(step.get("body") or "").strip()
        card_svg.append(f'<g filter="url(#softShadow)"><rect x="{x}" y="176" width="{card_width}" height="300" rx="24" fill="#ffffff" stroke="{accent}" stroke-width="2"/></g>')
        card_svg.append(f'<rect x="{x}" y="176" width="{card_width}" height="300" rx="24" fill="{fill}" opacity="0.75"/>')
        card_svg.append(f'<circle cx="{x + (card_width / 2)}" cy="220" r="28" fill="{accent}"/>')
        card_svg.append(f'<text x="{x + (card_width / 2)}" y="233" class="step-number" text-anchor="middle">{html.escape(number)}</text>')
        card_svg.append(_svg_multiline(step_title, x=x + (card_width / 2), y=292, width=14, line_height=22, css_class="step-title"))
        card_svg.append(_svg_multiline(body_text, x=x + (card_width / 2), y=354, width=18, line_height=18, css_class="step-body"))
        card_svg.append(f'<rect x="{x + 34}" y="426" width="{card_width - 68}" height="6" rx="3" fill="{accent}" opacity="0.8"/>')

    footer_svg = []
    if footer_title or footer_lines:
        footer_svg.append('<g filter="url(#softShadow)"><rect x="74" y="536" width="972" height="144" rx="24" fill="#ffffff" stroke="#d9e7f2" stroke-width="2"/></g>')
        if footer_title:
            footer_svg.append(f'<text x="106" y="588" class="footer-title">{html.escape(footer_title)}</text>')
        for idx, line in enumerate(footer_lines):
            y = 616 + (idx * 28)
            footer_svg.append(f'<circle cx="136" cy="{y - 6}" r="5" fill="#2f8892"/>')
            footer_svg.append(f'<text x="156" y="{y}" class="footer-body">{html.escape(line)}</text>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1123" height="794" viewBox="0 0 1123 794" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(title)}</title>
  <desc id="desc">ECD support poster.</desc>
  <defs>
    <filter id="softShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="7" dy="10" stdDeviation="0" flood-color="#d8e5ed" flood-opacity="1"/>
    </filter>
    <style>
      .page-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 30px; }}
      .sub {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #dce8f0; font-size: 17px; }}
      .step-number {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #ffffff; font-size: 24px; }}
      .step-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2b466f; font-size: 21px; }}
      .step-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: 16px; }}
      .footer-title {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 700; fill: #2b466f; font-size: 28px; }}
      .footer-body {{ font-family: "Trebuchet MS", "Verdana", sans-serif; font-weight: 400; fill: #30455f; font-size: 16px; }}
    </style>
  </defs>
  <rect width="1123" height="794" fill="#f7f3ec"/>
  <circle cx="90" cy="112" r="76" fill="#fff0c8"/>
  <circle cx="1030" cy="104" r="132" fill="#e4eef4"/>
  <circle cx="1022" cy="700" r="126" fill="#edf3d7"/>
  <rect x="44" y="36" width="1035" height="84" rx="28" fill="#314e79" filter="url(#softShadow)"/>
  <rect x="56" y="120" width="1020" height="10" rx="5" fill="#2d7e88"/>
  <text x="72" y="86" class="page-title">{html.escape(title)}</text>
  <text x="72" y="114" class="sub">{html.escape(subtitle)}</text>
  {''.join(card_svg)}
  {''.join(footer_svg)}
</svg>"""


def render_svg(template: str, document: dict[str, Any]) -> str:
    if template == "ecd_cover_page":
        return _render_ecd_cover_page_svg(document)
    if template == "ecd_weekly_overview":
        return _render_ecd_weekly_overview_svg(document)
    if template == "ecd_cycle_diagram":
        return _render_ecd_cycle_diagram_svg(document)
    if template == "ecd_strategy_grid":
        return _render_ecd_strategy_grid_svg(document)
    if template == "ecd_support_poster":
        return _render_ecd_support_poster_svg(document)
    raise RuntimeError(f"Unsupported visual document template `{template}`.")


__all__ = ["TEMPLATE_META", "render_svg"]
