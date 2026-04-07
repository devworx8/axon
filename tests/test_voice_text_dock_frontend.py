from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_JS = ROOT / "ui/js/voice.js"
VOICE_COMMAND_CENTER_JS = ROOT / "ui/js/voice-command-center.js"
VOICE_CONVERSATION_JS = ROOT / "ui/js/voice-conversation.js"


def _run_voice_dock_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          console,
          setTimeout,
          clearTimeout,
          requestAnimationFrame: (cb) => cb(),
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_JS))}, 'utf8'), ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_COMMAND_CENTER_JS))}, 'utf8'), ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_CONVERSATION_JS))}, 'utf8'), ctx);
        (async () => {{
          {body}
        }})().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
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


class VoiceTextDockFrontendTests(unittest.TestCase):
    def test_text_dock_submit_uses_actual_dispatch_chain(self):
        payload = _run_voice_dock_script(
            """
            const voiceMixin = ctx.window.axonVoiceMixin();
            const commandCenterMixin = ctx.window.axonVoiceCommandCenterMixin();
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              voiceTranscript: '',
              chatInput: '',
              chatLoading: false,
              voiceActive: false,
              voiceConversation: {},
              liveOperator: { detail: '' },
              chatMessages: [],
              resetChatComposerHeight() {},
              currentWorkspaceRunActive() { return false; },
              async sendChat() { this.sentChatInput = this.chatInput; },
            };
            Object.assign(app, voiceMixin, commandCenterMixin, conversationMixin);
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = 'Check the git status of .devbrain';
            await app.submitVoiceTextDock();
            console.log(JSON.stringify({
              dockOpen: app.voiceConversation.textDockOpen,
              lastCommand: app.voiceConversation.lastCommand,
              sentChatInput: app.sentChatInput,
              voiceTranscript: app.voiceTranscript,
            }));
            """
        )

        self.assertFalse(payload["dockOpen"])
        self.assertEqual(payload["lastCommand"], "Check the git status of .devbrain")
        self.assertEqual(payload["sentChatInput"], "Check the git status of .devbrain")
        self.assertEqual(payload["voiceTranscript"], "")


if __name__ == "__main__":
    unittest.main()
