from __future__ import annotations

from pathlib import Path

from scripts.ecd.visual_asset_tools import build_visual_png


def build_cover_page(
    assets_dir: Path,
    scratch_dir: Path,
    *,
    learner_name: str,
    centre_name: str,
    theme: str,
    activity_date: str,
    compilation_date: str,
) -> Path:
    assets_dir.mkdir(parents=True, exist_ok=True)
    output_path = assets_dir / "annatjie_cover_page.png"
    return build_visual_png(
        {
            "template": "ecd_cover_page",
            "title": "Workbook Answers and Evidence Pack",
            "unit_standard": "Unit Standard 13853: Mediate active learning in ECD programmes",
            "subtitle": "Play-based learning, observation, mediation and reflection in an ECD classroom setting",
            "learner_name": learner_name,
            "centre_name": centre_name,
            "theme": theme,
            "activity_date": activity_date,
            "compilation_date": compilation_date,
            "focus_areas": ["Play-based learning", "Observation", "Mediation", "Reflection"],
        },
        scratch_dir,
        output_path,
    )


def generate_visual_assets(assets_dir: Path, scratch_dir: Path) -> dict[str, Path]:
    assets_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        "figure1": assets_dir / "annatjie_figure1_weekly_learning_programme.png",
        "figure2": assets_dir / "annatjie_figure2_observation_cycle.png",
        "figure3": assets_dir / "annatjie_figure3_mediation_strategies.png",
        "figure4": assets_dir / "annatjie_figure4_grouping_language_support.png",
        "figure5": assets_dir / "annatjie_figure5_reflective_cycle.png",
        "figure6": assets_dir / "annatjie_figure6_support_poster.png",
    }

    build_visual_png(
        {
            "template": "ecd_weekly_overview",
            "title": "Figure 1. Weekly Learning Programme Overview",
            "subtitle": "Integrated literacy, numeracy, life skills, creative play and outdoor learning",
            "theme": "My Body and Healthy Habits",
            "planning_principles": [
                "Theme-based planning linked to children's interests and developmental level",
                "Daily balance of group time, free play, guided work, outdoor activity and routines",
                "Integration of literacy, numeracy, life skills, movement and creative expression",
                "Inclusive support through visuals, modelling, peer support and practical materials",
                "Observation notes used to adjust the next day's learning activities",
            ],
            "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "rows": [
                {"label": "Theme / literacy", "values": ["Body-parts story and song", "Handwashing sequence language", "Feelings discussion", "Movement words", "Draw-and-tell review"]},
                {"label": "Numeracy", "values": ["Count body parts", "Order 1-6 cards", "Sort healthy pictures", "Compare jumps and steps", "Matching revision game"]},
                {"label": "Life skills / movement", "values": ["Action song and stretch", "Practical hygiene routine", "Feelings collage", "Obstacle course", "Health talk and play"]},
                {"label": "Observation / next step", "values": ["Record body vocabulary", "Note sequence support", "Watch social language", "Record listening notes", "Plan next support"]},
            ],
        },
        scratch_dir,
        outputs["figure1"],
    )

    build_visual_png(
        {
            "template": "ecd_cycle_diagram",
            "title": "Figure 2. Observation, Analysis and Planning Cycle",
            "subtitle": "Ongoing assessment for support, progression and inclusive next-step planning",
            "center_title": "Assessment",
            "center_subtitle": "observe, interpret and respond",
            "steps": [
                {"title": "Observe", "body": "Watch, listen and record"},
                {"title": "Analyse", "body": "Link evidence to development"},
                {"title": "Next support", "body": "Choose the next support"},
                {"title": "Plan support", "body": "Adapt grouping or resources"},
                {"title": "Review", "body": "Check what improved"},
            ],
        },
        scratch_dir,
        outputs["figure2"],
    )

    build_visual_png(
        {
            "template": "ecd_strategy_grid",
            "title": "Figure 3. Learning Mediation and Scaffolding Techniques",
            "subtitle": "Ways I support children to move from what they know to the next step",
            "footer": "These techniques support guided participation, language growth and reflection.",
            "cards": [
                {"title": "Model and think aloud", "body": "Show the task step by step and name the thinking.", "accent": "#2f8892"},
                {"title": "Ask open questions", "body": "Ask what children notice, decide and predict.", "accent": "#314e79"},
                {"title": "Give prompts and cues", "body": "Point to visuals, remind the first step and fade support.", "accent": "#dc9a2b"},
                {"title": "Focus on process", "body": "Praise effort, persistence and useful discussion.", "accent": "#6a9e3d"},
                {"title": "Extend language", "body": "Repeat key words and bridge home language support.", "accent": "#c45c4d"},
            ],
        },
        scratch_dir,
        outputs["figure3"],
    )

    build_visual_png(
        {
            "template": "ecd_strategy_grid",
            "title": "Figure 4. Group Organisation, Participation and Language Support",
            "subtitle": "Planning for individual, small-group and large-group learning in an inclusive ECD programme",
            "footer": "Active learning improves when grouping, participation routines and language support are planned together.",
            "cards": [
                {"title": "Whole-group input", "body": "Use a short story, song, visuals and modelling.", "accent": "#314e79"},
                {"title": "Small-group support", "body": "Guide practice, paired talk and confidence-building.", "accent": "#2f8892"},
                {"title": "Participation moves", "body": "Use names, wait time and praise for effort.", "accent": "#dc9a2b"},
                {"title": "Language support", "body": "Pre-teach key words and repeat sentence frames.", "accent": "#6a9e3d"},
                {"title": "Peer scaffolding", "body": "Pair confident speakers with quieter children respectfully.", "accent": "#7a67b9"},
            ],
        },
        scratch_dir,
        outputs["figure4"],
    )

    build_visual_png(
        {
            "template": "ecd_cycle_diagram",
            "title": "Figure 5. Reflective Practice Cycle",
            "subtitle": "Using daily evaluation to strengthen planning, interaction, assessment and facilitation",
            "center_title": "Reflect",
            "center_subtitle": "improve tomorrow's practice",
            "steps": [
                {"title": "Recall", "body": "What happened?"},
                {"title": "Analyse", "body": "Why did it happen?"},
                {"title": "Changes", "body": "What will I change?"},
                {"title": "Apply", "body": "Try it and watch again"},
                {"title": "Journal", "body": "Record what worked"},
            ],
        },
        scratch_dir,
        outputs["figure5"],
    )

    build_visual_png(
        {
            "template": "ecd_support_poster",
            "title": "Figure 6. Summative Activity Support Poster: Healthy Handwashing",
            "subtitle": "A developmentally appropriate visual aid for the activity 'My Body and Healthy Habits'",
            "steps": [
                {"number": "1", "title": "Wet hands", "body": "Use clean water.", "accent": "#314e79"},
                {"number": "2", "title": "Add soap", "body": "Make bubbles.", "accent": "#2f8892"},
                {"number": "3", "title": "Rub palms", "body": "Count slowly to 10.", "accent": "#dc9a2b"},
                {"number": "4", "title": "Clean fingers", "body": "Between and around nails.", "accent": "#6a9e3d"},
                {"number": "5", "title": "Rinse well", "body": "Wash the soap away.", "accent": "#c45c4d"},
                {"number": "6", "title": "Dry hands", "body": "Use a clean towel.", "accent": "#7a67b9"},
            ],
            "footer_title": "How this poster supports mediation",
            "footer_lines": [
                "Provides a clear visual sequence for children needing prompts or memory support.",
                "Helps me explain the what, how and why of the routine during guided practice.",
                "Supports independence because children can follow the steps with decreasing adult help.",
            ],
        },
        scratch_dir,
        outputs["figure6"],
    )

    return {
        "Figure 1. Weekly learning programme overview.": outputs["figure1"],
        "Figure 2. Observation, analysis and planning cycle.": outputs["figure2"],
        "Figure 3. Core mediation and scaffolding techniques.": outputs["figure3"],
        "Figure 4. Group organisation, participation and language support strategies.": outputs["figure4"],
        "Figure 5. Reflective practice cycle.": outputs["figure5"],
        "Figure 6. Visual support poster.": outputs["figure6"],
    }


__all__ = ["build_cover_page", "generate_visual_assets"]
