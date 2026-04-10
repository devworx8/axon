from __future__ import annotations

import subprocess
from pathlib import Path

from axon_core import visual_document_generation
from axon_core.visual_document_templates import TEMPLATE_META


def screenshot_visual_document(svg_path: Path, png_path: Path, template: str) -> Path:
    meta = TEMPLATE_META[template]
    subprocess.run(
        [
            "google-chrome",
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--screenshot={png_path}",
            f"--window-size={meta['width']},{meta['height']}",
            svg_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return png_path


def build_visual_png(document: dict[str, object], scratch_dir: Path, output_path: Path) -> Path:
    artifact = visual_document_generation.build_visual_document(
        {
            **document,
            "output_dir": str(scratch_dir),
            "file_stem": output_path.stem,
            "pdf": False,
        }
    )
    return screenshot_visual_document(artifact.svg_path, output_path, str(document["template"]))


__all__ = ["build_visual_png", "screenshot_visual_document"]
