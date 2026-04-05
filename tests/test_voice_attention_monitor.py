from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_ATTENTION_MONITOR_JS = ROOT / "ui/js/voice-attention-monitor.js"


def _run_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{
            setTimeout(callback) {{ return callback ? callback() : null; }},
            clearTimeout() {{}},
          }},
          URLSearchParams,
          console,
        }};
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_ATTENTION_MONITOR_JS))}, 'utf8'), ctx);
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


class VoiceAttentionMonitorTests(unittest.TestCase):
    def test_attention_summary_announces_once_and_autowakes(self):
        payload = _run_script(
            """
            const app = {
              settingsForm: { voice_attention_enabled: true, voice_attention_autowake: true },
              speechOutputSupported: true,
              chatProjectId: '42',
              chatProject: { id: 42, name: 'Hope' },
              voiceAlerts: [],
              wakes: 0,
              notifications: 0,
              activePrimaryConversationMode() { return 'auto'; },
              workspaceTabLabel() { return 'Hope'; },
              openVoiceCommandCenter() { this.wakes += 1; },
              showStickyNotification() { this.notifications += 1; },
              speakMessage(message) { this.voiceAlerts.push(message); },
            };
            Object.assign(app, ctx.window.axonVoiceAttentionMonitorMixin());

            const summary = {
              counts: { now: 1, waiting_on_me: 0, watch: 0 },
              top_now: [{ id: 7, summary: 'Preview build failed' }],
              top_waiting_on_me: [],
            };
            app.maybeAnnounceAttentionSummary(summary);
            app.maybeAnnounceAttentionSummary(summary);

            console.log(JSON.stringify({
              wakes: app.wakes,
              notifications: app.notifications,
              voiceAlerts: app.voiceAlerts,
            }));
            """
        )

        self.assertEqual(payload["wakes"], 1)
        self.assertEqual(payload["notifications"], 1)
        self.assertEqual(len(payload["voiceAlerts"]), 1)
        self.assertIn("Preview build failed", payload["voiceAlerts"][0])

    def test_live_feed_alert_announces_approval_required_once(self):
        payload = _run_script(
            """
            const app = {
              settingsForm: { voice_attention_enabled: true, voice_attention_autowake: true },
              speechOutputSupported: true,
              chatProjectId: '42',
              voiceAlerts: [],
              wakes: 0,
              activePrimaryConversationMode() { return 'auto'; },
              openVoiceCommandCenter() { this.wakes += 1; },
              showStickyNotification() {},
              speakMessage(message) { this.voiceAlerts.push(message); },
            };
            Object.assign(app, ctx.window.axonVoiceAttentionMonitorMixin());

            const payload = {
              operator: { active: false },
              auto_sessions: [
                {
                  session_id: 'auto-42',
                  workspace_id: '42',
                  title: 'Stage and commit',
                  status: 'approval_required',
                  detail: 'Approval required before git add -A.',
                },
              ],
            };
            app.syncVoiceAttentionFromLiveFeed(payload);
            app.syncVoiceAttentionFromLiveFeed(payload);

            console.log(JSON.stringify({
              wakes: app.wakes,
              voiceAlerts: app.voiceAlerts,
            }));
            """
        )

        self.assertEqual(payload["wakes"], 1)
        self.assertEqual(len(payload["voiceAlerts"]), 1)
        self.assertIn("paused for approval", payload["voiceAlerts"][0])


if __name__ == "__main__":
    unittest.main()
