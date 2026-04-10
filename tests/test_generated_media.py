from __future__ import annotations

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

import brain
from axon_core import image_generation, pdf_generation, visual_document_generation


class PdfGenerationTests(unittest.TestCase):
    def test_build_pdf_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "quarterly-update.pdf"
            spec = pdf_generation.pdf_from_dict(
                {
                    "title": "Quarterly Update",
                    "subtitle": "Q1 Snapshot",
                    "output_path": str(target),
                    "sections": [
                        {
                            "heading": "Summary",
                            "paragraphs": ["Revenue grew eighteen percent quarter over quarter."],
                            "bullets": ["Retention up", "Pipeline expanded"],
                        }
                    ],
                }
            )
            out_path = pdf_generation.build_pdf(spec)
            self.assertEqual(out_path, target)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 100)

    def test_brain_generate_pdf_tool_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "tool-generated.pdf"
            result = brain._execute_tool(
                "generate_pdf",
                {
                    "title": "Tool Generated Report",
                    "content": "This is a generated PDF from the agent runtime tool.",
                    "output_path": str(target),
                },
            )
            self.assertIn("Generated PDF:", result)
            self.assertTrue(target.exists())


class ImageGenerationTests(unittest.TestCase):
    def test_parse_gemini_image_response_extracts_inline_data(self):
        encoded = base64.b64encode(b"fake-image-bytes").decode("ascii")
        content, mime_type, provider_text = image_generation.parse_gemini_image_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Rendered successfully"},
                                {"inlineData": {"mimeType": "image/png", "data": encoded}},
                            ]
                        }
                    }
                ]
            }
        )
        self.assertEqual(content, b"fake-image-bytes")
        self.assertEqual(mime_type, "image/png")
        self.assertIn("Rendered successfully", provider_text)

    def test_store_generated_image_persists_resource_and_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            storage_root = Path(tmpdir) / "resources"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE resources (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'document',
                        source_type TEXT NOT NULL DEFAULT 'upload',
                        source_url TEXT DEFAULT '',
                        local_path TEXT NOT NULL,
                        mime_type TEXT DEFAULT '',
                        size_bytes INTEGER DEFAULT 0,
                        sha256 TEXT DEFAULT '',
                        status TEXT DEFAULT 'pending',
                        summary TEXT DEFAULT '',
                        preview_text TEXT DEFAULT '',
                        meta_json TEXT DEFAULT '{}',
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now')),
                        last_used_at TEXT,
                        file_path TEXT DEFAULT '',
                        trust_level TEXT DEFAULT 'medium',
                        pinned INTEGER DEFAULT 0,
                        workspace_id INTEGER
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    ("resource_storage_path", str(storage_root)),
                )
                conn.commit()

            stored = image_generation.store_generated_image(
                db_path=db_path,
                generated=image_generation.GeneratedImage(
                    data=b"\x89PNG\r\n\x1a\nmock",
                    mime_type="image/png",
                    model=image_generation.DEFAULT_GEMINI_IMAGE_MODEL,
                    prompt="Create a product hero image",
                    aspect_ratio="16:9",
                    image_size="1K",
                ),
                title="Hero Mock",
                workspace_id=7,
            )

            self.assertEqual(stored.resource_id, 1)
            self.assertTrue(stored.path.exists())
            self.assertTrue(str(stored.path).startswith(str(storage_root)))
            with sqlite3.connect(str(db_path)) as conn:
                row = conn.execute(
                    "SELECT title, kind, source_type, workspace_id FROM resources WHERE id = 1"
                ).fetchone()
            self.assertEqual(row, ("Hero Mock", "image", "generated", 7))

    def test_agent_runtime_registry_includes_media_tools(self):
        deps = brain._agent_runtime_deps()
        self.assertIn("generate_image", deps.tool_registry)
        self.assertIn("generate_pdf", deps.tool_registry)
        self.assertIn("generate_visual_document", deps.tool_registry)
        self.assertIn("create_ecd_cover_page", deps.tool_registry)
        self.assertIn("create_ecd_weekly_overview", deps.tool_registry)
        self.assertIn("create_ecd_cycle_diagram", deps.tool_registry)
        self.assertIn("create_ecd_strategy_grid", deps.tool_registry)
        self.assertIn("create_ecd_support_poster", deps.tool_registry)
        self.assertIn("http_get", deps.tool_registry)


class VisualDocumentGenerationTests(unittest.TestCase):
    def test_build_visual_document_creates_svg_and_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = visual_document_generation.build_visual_document(
                {
                    "template": "ecd_cover_page",
                    "title": "Workbook Answers and Evidence Pack",
                    "unit_standard": "Unit Standard 13853: Mediate active learning in ECD programmes",
                    "subtitle": "Play-based learning, observation, mediation and reflection",
                    "learner_name": "Mildred Mathebula",
                    "centre_name": "Empendulo Day Care",
                    "theme": "Healthy Food, My Body and Good Choices",
                    "activity_date": "10-19 March 2026",
                    "compilation_date": "08 April 2026",
                    "output_dir": tmpdir,
                    "file_stem": "cover-page",
                    "pdf": False,
                }
            )
            self.assertTrue(artifact.svg_path.exists())
            self.assertTrue(artifact.html_path.exists())
            self.assertIsNone(artifact.pdf_path)

    def test_build_weekly_visual_document_creates_svg_and_html(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = visual_document_generation.build_visual_document(
                {
                    "template": "ecd_weekly_overview",
                    "title": "Figure 1. Weekly Learning Programme Overview",
                    "subtitle": "Integrated literacy, numeracy and life skills",
                    "theme": "Healthy Habits",
                    "planning_principles": ["Theme-based planning linked to children's interests"],
                    "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                    "rows": [
                        {
                            "label": "Theme focus",
                            "values": ["My body", "Healthy habits", "Feelings", "Movement", "Review"],
                        }
                    ],
                    "output_dir": tmpdir,
                    "file_stem": "weekly-overview",
                    "pdf": False,
                }
            )
            self.assertTrue(artifact.svg_path.exists())
            self.assertTrue(artifact.html_path.exists())
            self.assertIsNone(artifact.pdf_path)

    def test_build_cycle_diagram_visual_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = visual_document_generation.build_visual_document(
                {
                    "template": "ecd_cycle_diagram",
                    "title": "Figure 2. Observation, Analysis and Planning Cycle",
                    "subtitle": "How daily evidence informs next-step teaching",
                    "center_title": "Continuous",
                    "center_subtitle": "child-centred improvement",
                    "steps": [
                        {"title": "Observe", "body": "Watch, listen and record factual evidence"},
                        {"title": "Interpret", "body": "Link behaviour to development and participation"},
                        {"title": "Plan", "body": "Choose next steps and support"},
                        {"title": "Teach", "body": "Implement activities and mediation"},
                        {"title": "Review", "body": "Reflect and adjust practice"},
                    ],
                    "output_dir": tmpdir,
                    "file_stem": "cycle-diagram",
                    "pdf": False,
                }
            )
            self.assertTrue(artifact.svg_path.exists())
            self.assertIn("cycle-diagram.svg", str(artifact.svg_path))

    def test_build_support_poster_visual_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = visual_document_generation.build_visual_document(
                {
                    "template": "ecd_support_poster",
                    "title": "Figure 6. Summative Activity Support Poster",
                    "subtitle": "A classroom visual aid for the lesson routine",
                    "steps": [
                        {"number": "1", "title": "Wet hands", "body": "Use clean water"},
                        {"number": "2", "title": "Add soap", "body": "Make bubbles"},
                        {"number": "3", "title": "Rub palms", "body": "Count slowly to 10"},
                        {"number": "4", "title": "Clean fingers", "body": "Between and around nails"},
                        {"number": "5", "title": "Rinse well", "body": "Wash the soap away"},
                        {"number": "6", "title": "Dry hands", "body": "Use a clean towel"},
                    ],
                    "footer_title": "How this poster supports mediation",
                    "footer_lines": ["Provides a clear visual sequence", "Supports children needing prompts"],
                    "output_dir": tmpdir,
                    "file_stem": "support-poster",
                    "pdf": False,
                }
            )
            self.assertTrue(artifact.svg_path.exists())
            self.assertIn("support-poster.svg", str(artifact.svg_path))

    def test_brain_generate_visual_document_tool_creates_svg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = brain._execute_tool(
                "generate_visual_document",
                {
                    "template": "ecd_cycle_diagram",
                    "title": "Figure 2. Observation, Analysis and Planning Cycle",
                    "subtitle": "How daily evidence informs next-step teaching",
                    "center_title": "Assessment",
                    "center_subtitle": "observe, interpret and respond",
                    "steps": [
                        {"title": "Observe", "body": "Watch, listen and record"},
                        {"title": "Analyse", "body": "Link evidence to development"},
                        {"title": "Decide next step", "body": "Choose the next support"},
                        {"title": "Plan response", "body": "Adapt grouping or resources"},
                        {"title": "Review progress", "body": "Check what improved"},
                    ],
                    "output_dir": tmpdir,
                    "file_stem": "cycle-diagram",
                    "pdf": False,
                },
            )
            self.assertIn("Generated visual document:", result)
            self.assertTrue((Path(tmpdir) / "cycle-diagram.svg").exists())

    def test_brain_named_ecd_visual_tool_creates_svg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = brain._execute_tool(
                "create_ecd_support_poster",
                {
                    "title": "Figure 6. Summative Activity Support Poster",
                    "subtitle": "A classroom visual aid for the lesson routine",
                    "steps": [
                        {"number": "1", "title": "Wet hands", "body": "Use clean water"},
                        {"number": "2", "title": "Add soap", "body": "Make bubbles"},
                        {"number": "3", "title": "Rub palms", "body": "Count slowly to 10"},
                        {"number": "4", "title": "Clean fingers", "body": "Between and around nails"},
                        {"number": "5", "title": "Rinse well", "body": "Wash the soap away"},
                        {"number": "6", "title": "Dry hands", "body": "Use a clean towel"},
                    ],
                    "footer_title": "How this poster supports mediation",
                    "footer_lines": ["Provides a clear visual sequence", "Supports children needing prompts"],
                    "output_dir": tmpdir,
                    "file_stem": "support-poster",
                    "pdf": False,
                },
            )
            self.assertIn("Generated visual document:", result)
            self.assertTrue((Path(tmpdir) / "support-poster.svg").exists())


if __name__ == "__main__":
    unittest.main()
