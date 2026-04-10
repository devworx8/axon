from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts.ecd.visual_asset_tools import build_visual_png


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def patch_evidence1_title(source_path: Path, output_path: Path) -> Path:
    image = Image.open(source_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 22, 1085, 88), fill=(247, 243, 236, 255))
    font = _load_font(28)
    text = "Evidence 1 - Circle Time at Empendulo Day Care"
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    x = (image.width - (right - left)) / 2
    draw.text((x, 35), text, fill="#38485b", font=font)
    image.save(output_path)
    return output_path


def _extract_activity_date_range(document_text: str) -> str:
    matches = re.findall(
        r"\b(\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4})\b",
        document_text,
    )
    if not matches:
        return ""
    dates = sorted(datetime.strptime(item, "%d %B %Y") for item in set(matches))
    first = dates[0]
    last = dates[-1]
    if first == last:
        return first.strftime("%d %B %Y")
    if first.year == last.year and first.month == last.month:
        return f"{first.day:02d}-{last.day:02d} {first.strftime('%B %Y')}"
    return f"{first.strftime('%d %B %Y')} to {last.strftime('%d %B %Y')}"


def build_cover_page(images_dir: Path, scratch_dir: Path, *, document_text: str) -> Path:
    output_path = images_dir / "cover_page_mildred_submission.png"
    activity_date = _extract_activity_date_range(document_text)
    compilation_date = datetime.now().strftime("%d %B %Y")
    return build_visual_png(
        {
            "template": "ecd_cover_page",
            "title": "Workbook Answers and Evidence Pack",
            "unit_standard": "Unit Standard 13853: Mediate active learning in ECD programmes",
            "subtitle": "Play-based learning, observation, mediation and reflection in an ECD classroom setting",
            "learner_name": "Mildred Mathebula",
            "centre_name": "Empendulo Day Care",
            "theme": "Healthy Food, My Body and Good Choices",
            "activity_date": activity_date,
            "compilation_date": compilation_date,
            "focus_areas": ["Play-based learning", "Observation", "Mediation", "Reflection"],
        },
        scratch_dir,
        output_path,
    )


def generate_visual_assets(images_dir: Path, scratch_dir: Path) -> dict[str, Path]:
    images_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "figure1": images_dir / "figure1_weekly_programme.png",
        "figure2": images_dir / "figure2_observation_cycle.png",
        "figure3": images_dir / "figure3_mediation_strategies.png",
        "figure4": images_dir / "figure4_grouping_language_support.png",
        "figure5": images_dir / "figure5_reflection_cycle.png",
        "figure6": images_dir / "figure6_evidence_checklist.png",
        "evidence1": images_dir / "evidence1_circle_time.png",
    }

    patch_evidence1_title(images_dir / "evidence1_circle_time.png", outputs["evidence1"])

    build_visual_png(
        {
            "template": "ecd_weekly_overview",
            "title": "Figure 1. Weekly Learning Programme Overview",
            "subtitle": "Integrated literacy, numeracy, life skills, creative play and outdoor learning",
            "theme": "Healthy Food, My Body and Good Choices",
            "planning_principles": [
                "Theme-based planning linked to children's interests and developmental level",
                "Daily balance of group time, free play, guided work, outdoor activity and routines",
                "Integration of literacy, numeracy, life skills, movement and creative expression",
                "Inclusive support through visuals, modelling, peer support and practical materials",
                "Observation notes used to adjust the next day's learning activities",
            ],
            "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "rows": [
                {"label": "Theme / literacy", "values": ["Healthy foods", "Sorting and hygiene", "Story and art", "Market role play", "Review and snack"]},
                {"label": "Numeracy", "values": ["Count foods", "Compare sets", "Count picture items", "Buying and matching", "One more / less"]},
                {"label": "Life skills / movement", "values": ["Healthy choices and action song", "Sorting relay", "Confidence and expression", "Turn-taking at market", "Hygiene and outdoor review"]},
                {"label": "Observation / next step", "values": ["Baseline vocabulary notes", "Who needs support with sorting?", "Who can retell confidently?", "Language support notes", "Plan follow-up support"]},
            ],
        },
        scratch_dir,
        outputs["figure1"],
    )

    build_visual_png(
        {
            "template": "ecd_cycle_diagram",
            "title": "Figure 2. Observation, Analysis and Planning Cycle",
            "subtitle": "How daily evidence informs next-step teaching",
            "center_title": "Continuous",
            "center_subtitle": "child-centred improvement",
            "steps": [
                {"title": "Observe", "body": "Watch, listen and record"},
                {"title": "Interpret", "body": "Link evidence to development"},
                {"title": "Plan", "body": "Choose the next support"},
                {"title": "Teach", "body": "Guide the activity"},
                {"title": "Review", "body": "Adjust and try again"},
            ],
        },
        scratch_dir,
        outputs["figure2"],
    )

    build_visual_png(
        {
            "template": "ecd_strategy_grid",
            "title": "Figure 3. Learning Mediation and Scaffolding",
            "subtitle": "Practical techniques used during guided ECD activities",
            "footer": "Scaffolding helps children move from supported practice to independence",
            "cards": [
                {"title": "Model and demonstrate", "body": "Show first, think aloud and invite imitation", "accent": "#c45c4d"},
                {"title": "Question with purpose", "body": "Ask open questions about process and ideas", "accent": "#2f8892"},
                {"title": "Use prompts", "body": "Offer hints, visuals and sentence starters", "accent": "#dc9a2b"},
                {"title": "Encourage reflection", "body": "Help children explain what they learned", "accent": "#7a67b9"},
            ],
        },
        scratch_dir,
        outputs["figure3"],
    )

    build_visual_png(
        {
            "template": "ecd_strategy_grid",
            "title": "Figure 4. Grouping, Participation and Language Support",
            "subtitle": "How I organise inclusive participation and additional language learning",
            "footer": "Intentional grouping and language support make participation safer and stronger",
            "cards": [
                {"title": "Whole-group sessions", "body": "Short, lively inputs with songs, visuals and clear routines", "accent": "#314e79"},
                {"title": "Small-group support", "body": "Closer guidance for pacing, confidence and turn-taking", "accent": "#6a9e3d"},
                {"title": "Peer interaction", "body": "Pair confident and emerging learners respectfully", "accent": "#dc9a2b"},
                {"title": "Home language support", "body": "Use familiar words while building new vocabulary", "accent": "#7a67b9"},
            ],
        },
        scratch_dir,
        outputs["figure4"],
    )

    build_visual_png(
        {
            "template": "ecd_cycle_diagram",
            "title": "Figure 5. Reflective Practice Cycle",
            "subtitle": "Daily reflection used to improve planning and interaction",
            "center_title": "Reflect",
            "center_subtitle": "improve the next lesson",
            "steps": [
                {"title": "Notice", "body": "What worked and what needed support"},
                {"title": "Analyse", "body": "Link it to learning"},
                {"title": "Adapt", "body": "Change pacing or materials"},
                {"title": "Apply", "body": "Use the new plan"},
                {"title": "Record", "body": "Keep a short note"},
            ],
        },
        scratch_dir,
        outputs["figure5"],
    )

    build_visual_png(
        {
            "template": "ecd_strategy_grid",
            "title": "Figure 6. Evidence Checklist for the Portfolio",
            "subtitle": "Examples of documentation attached to the summative activity",
            "footer": "The evidence pack links planning, mediation, observation and reflection",
            "cards": [
                {"title": "Planning records", "body": "Weekly plans, daily notes and resource lists", "accent": "#314e79"},
                {"title": "Observation records", "body": "Anecdotal notes, checklists and learner profiles", "accent": "#6a9e3d"},
                {"title": "Assessment evidence", "body": "Annotated work samples and progress comments", "accent": "#dc9a2b"},
                {"title": "Reflection records", "body": "Journal entries and activity evaluations", "accent": "#7a67b9"},
            ],
        },
        scratch_dir,
        outputs["figure6"],
    )

    return {
        "Figure 1. Integrated weekly learning programme aligned to Activity 1.": outputs["figure1"],
        "Figure 2. Observation, analysis and planning cycle used to support Activity 2.": outputs["figure2"],
        "Figure 3. Core mediation and scaffolding techniques for Activity 3.": outputs["figure3"],
        "Figure 4. Group organisation, participation and language support strategies for Activity 4.": outputs["figure4"],
        "Figure 5. Reflective practice cycle used in Activity 5.": outputs["figure5"],
        "Evidence 1. Circle-time introduction at Empendulo Day Care.": outputs["evidence1"],
        "Evidence 2. Small-group numeracy and fruit sorting activity.": images_dir / "evidence2_numeracy_group.png",
        "Evidence 3. Hygiene routine before snack time.": images_dir / "evidence3_handwashing.png",
        "Evidence 4. Storytelling, discussion and reflection.": images_dir / "evidence4_story_reflection.png",
        "Figure 6. Portfolio evidence checklist for the summative activity.": outputs["figure6"],
    }


__all__ = ["build_cover_page", "generate_visual_assets", "patch_evidence1_title"]
