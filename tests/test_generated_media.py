from __future__ import annotations

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

import brain
from axon_core import image_generation, pdf_generation


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
        self.assertIn("http_get", deps.tool_registry)


if __name__ == "__main__":
    unittest.main()
