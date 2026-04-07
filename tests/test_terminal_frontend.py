from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_XTERM_JS = ROOT / "ui/js/terminal-xterm.js"
CHAT_TERMINAL_PANEL = ROOT / "ui/partials/chat_terminal_panel.html"
VOICE_TERMINAL_HUD = ROOT / "ui/partials/voice_terminal_hud.html"


def _run_terminal_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          console,
          window: {{
            location: {{ protocol: 'https:', host: 'axon.example' }},
            Terminal: function TerminalStub() {{}},
            FitAddon: {{ FitAddon: function FitAddonStub() {{}} }},
          }},
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(TERMINAL_XTERM_JS))}, 'utf8'), ctx);
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


class TerminalFrontendTests(unittest.TestCase):
    def test_terminal_xterm_socket_url_includes_view_suffix_and_auth_token(self):
        payload = _run_terminal_script(
            """
            const mixin = ctx.window.axonTerminalXtermMixin();
            const app = { authToken: 'token-123' };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              url: app.terminalPtySocketUrl('17', 'voice'),
            }));
            """
        )

        self.assertEqual(payload["url"], "wss://axon.example/ws/pty/17-voice?token=token-123")

    def test_terminal_xterm_prefers_interactive_voice_shell_when_hud_is_visible(self):
        payload = _run_terminal_script(
            """
            const mixin = ctx.window.axonTerminalXtermMixin();
            const app = {
              showVoiceOrb: true,
              hudTerminalVisible: true,
              voiceConversation: { terminalPinned: true },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              preferred: app.interactiveTerminalPreferred('voice'),
              shouldMount: app.terminalViewportShouldMount('voice'),
            }));
            """
        )

        self.assertTrue(payload["preferred"])
        self.assertTrue(payload["shouldMount"])

    def test_terminal_xterm_auto_mounts_voice_shell_for_live_terminal_activity(self):
        payload = _run_terminal_script(
            """
            const mixin = ctx.window.axonTerminalXtermMixin();
            const app = {
              showVoiceOrb: true,
              hudTerminalVisible: true,
              voiceConversation: { terminalPinned: false },
              voiceTerminalAutoDockActive() { return true; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              preferred: app.interactiveTerminalPreferred('voice'),
              shouldMount: app.terminalViewportShouldMount('voice'),
            }));
            """
        )

        self.assertTrue(payload["preferred"])
        self.assertTrue(payload["shouldMount"])

    def test_chat_terminal_panel_contains_console_xterm_mount(self):
        template = CHAT_TERMINAL_PANEL.read_text(encoding="utf-8")

        self.assertIn("x-ref=\"consoleXtermMount\"", template)
        self.assertIn("syncInteractiveTerminalViewport('console')", template)
        self.assertIn("Interactive shell", template)

    def test_voice_terminal_hud_contains_voice_xterm_mount(self):
        template = VOICE_TERMINAL_HUD.read_text(encoding="utf-8")

        self.assertIn("x-ref=\"voiceXtermMount\"", template)
        self.assertIn("syncInteractiveTerminalViewport('voice')", template)
        self.assertIn("Voice dock", template)


if __name__ == "__main__":
    unittest.main()
