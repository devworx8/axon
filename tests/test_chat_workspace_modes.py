from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_WORKSPACE_MODES_JS = ROOT / "ui/js/chat-workspace-modes.js"


def _run_workspace_mode_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync({json.dumps(str(CHAT_WORKSPACE_MODES_JS))}, 'utf8');
        const ctx = {{
          window: {{}},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          console,
        }};
        vm.createContext(ctx);
        vm.runInContext(code, ctx);
        {body}
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class ChatWorkspaceModesTests(unittest.TestCase):
    def test_workspace_tabs_remember_distinct_modes(self):
        payload = _run_workspace_mode_script(
            """
            const mixin = ctx.window.axonChatWorkspaceModesMixin();
            const app = {
              _prefs: {},
              chatProjectId: '1',
              businessMode: false,
              agentMode: false,
              composerOptions: {
                intelligence_mode: 'ask',
                action_mode: '',
                agent_role: '',
                safe_mode: false,
                require_approval: false,
                external_mode: '',
              },
              autoSessions: [{ session_id: 'auto-2', workspace_id: 2, status: 'running' }],
              currentBackendSupportsAgent() { return true; },
              usesOllamaBackend() { return false; },
              readWindowPref(key, fallback = '') {
                return Object.prototype.hasOwnProperty.call(this._prefs, key) ? this._prefs[key] : fallback;
              },
              writeWindowPref(key, value) {
                if (value === '') delete this._prefs[key];
                else this._prefs[key] = String(value);
              },
              normalizedComposerOptions() { return this.composerOptions; },
            };
            Object.assign(app, mixin);

            app.chooseConversationModeAgent();
            app.chatProjectId = '2';
            app.chooseConversationModeAuto();

            app.chatProjectId = '1';
            const workspaceOneMode = app.restoreConversationModePreference({ workspaceId: '1' });
            const workspaceOneActive = app.activePrimaryConversationMode();

            app.chatProjectId = '2';
            const workspaceTwoMode = app.restoreConversationModePreference({ workspaceId: '2' });
            const workspaceTwoActive = app.activePrimaryConversationMode();

            app.autoSessions = [];
            const workspaceTwoWithoutAuto = app.restoreConversationModePreference({ workspaceId: '2' });
            const workspaceTwoFallback = app.activePrimaryConversationMode();

            console.log(JSON.stringify({
              workspaceOneMode,
              workspaceOneActive,
              workspaceTwoMode,
              workspaceTwoActive,
              workspaceTwoWithoutAuto,
              workspaceTwoFallback,
              stored: JSON.parse(app._prefs.workspaceConversationModes || '{}'),
            }));
            """
        )

        self.assertEqual(payload["workspaceOneMode"], "agent")
        self.assertEqual(payload["workspaceOneActive"], "agent")
        self.assertEqual(payload["workspaceTwoMode"], "auto")
        self.assertEqual(payload["workspaceTwoActive"], "auto")
        self.assertEqual(payload["workspaceTwoWithoutAuto"], "auto")
        self.assertEqual(payload["workspaceTwoFallback"], "auto")
        self.assertEqual(payload["stored"]["1"]["mode"], "agent")
        self.assertEqual(payload["stored"]["2"]["mode"], "auto")


if __name__ == "__main__":
    unittest.main()
