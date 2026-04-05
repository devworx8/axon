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
        self.assertIn('/js/navigation.js', body)
        self.assertIn('/js/runtime_selector.js', body)
        self.assertIn('/js/dashboard_preview.js', body)
        self.assertIn('/js/chat-followups.js', body)
        self.assertIn('/js/console-state.js', body)
        self.assertIn('/js/chat-console-guidance.js', body)
        self.assertIn('Control Room', body)
        self.assertIn('Operator Settings Deck', body)
        self.assertIn("settingsSection = 'runtime'", body)
        self.assertIn('A.X.O.N Control Ring', body)
        self.assertIn("followUpSuggestions.length && !chatLoading", body)
        self.assertIn('Autonomous', body)
        self.assertIn('console-runtime-popover', body)
        self.assertIn('consoleQuickStartHints()', body)
        self.assertIn("handleComposerHistoryKey($event, 'up')", body)
        self.assertIn('editUserMessage(msg)', body)
        self.assertIn('openWorkspaceInNewWindow(projectId)', body)
        self.assertIn('Axon Browser', body)
        self.assertIn('preview-frame-shell', body)


if __name__ == "__main__":
    unittest.main()
