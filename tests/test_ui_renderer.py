from __future__ import annotations

import unittest
from pathlib import Path

from axon_api import ui_renderer


ROOT = Path(__file__).resolve().parents[1]


class UiRendererTests(unittest.TestCase):
    def test_render_index_includes_devops_partial(self):
        response = ui_renderer.render_index(ROOT / "ui", "axon-test-build")
        body = response.body.decode("utf-8")

        self.assertIn("DevOps Monitor", body)
        self.assertIn("activeTab === 'devops'", body)


if __name__ == "__main__":
    unittest.main()
