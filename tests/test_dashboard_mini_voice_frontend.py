from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_MINI_VOICE_JS = ROOT / "ui/js/dashboard-mini-voice.js"
DASHBOARD_HTML = ROOT / "ui/partials/dashboard.html"
DASHBOARD_MINI_VOICE_PARTIAL = ROOT / "ui/partials/dashboard_mini_voice.html"
DASHBOARD_MISSION_CONTROL_PARTIAL = ROOT / "ui/partials/dashboard_mission_control.html"
DASHBOARD_COMMAND_DECK_PARTIAL = ROOT / "ui/partials/dashboard_command_deck.html"


def _run_dashboard_mini_voice_script(body: str):
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
        vm.runInContext(fs.readFileSync({json.dumps(str(DASHBOARD_MINI_VOICE_JS))}, 'utf8'), ctx);
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


class DashboardMiniVoiceFrontendTests(unittest.TestCase):
    def test_dashboard_shell_embeds_control_ring_voice_inside_mission_control(self):
        dashboard_html = DASHBOARD_HTML.read_text(encoding="utf-8")
        mission_control_html = DASHBOARD_MISSION_CONTROL_PARTIAL.read_text(encoding="utf-8")
        command_deck_html = DASHBOARD_COMMAND_DECK_PARTIAL.read_text(encoding="utf-8")
        partial_html = DASHBOARD_MINI_VOICE_PARTIAL.read_text(encoding="utf-8")

        self.assertNotIn('dashboard_mini_voice.html', dashboard_html)
        self.assertIn('dashboard_mini_voice.html', mission_control_html)
        self.assertIn('Control ring voice', partial_html)
        self.assertIn('dashboardMiniVoiceListeningModeLabel()', mission_control_html)
        self.assertIn('Full voice mode', partial_html)
        self.assertIn('dashboardMiniVoiceTalkNow()', partial_html)
        self.assertIn('dashboardMiniVoicePrimaryAction()', partial_html)
        self.assertIn('dashboardMiniVoiceOpenFull()', partial_html)
        self.assertIn('dashboardMiniVoiceSurfaceAction()', partial_html)
        self.assertIn('missionLiveOperator().title', mission_control_html)
        self.assertIn('missionLiveOperator().detail', mission_control_html)
        self.assertIn('missionLiveOperator().title', command_deck_html)
        self.assertIn('missionWorkspaceRunActive()', command_deck_html)

    def test_dashboard_mini_voice_manual_talk_and_wake_gate_drive_commands(self):
        payload = _run_dashboard_mini_voice_script(
            """
            const mixin = ctx.window.axonDashboardMiniVoiceMixin();
            const app = {
              activeTab: 'dashboard',
              voiceMode: true,
              voiceActive: false,
              showVoiceOrb: false,
              chatLoading: false,
              voiceConversation: { textDockOpen: false },
              voiceStatus: {
                transcription_available: true,
                synthesis_available: true,
                detail: 'Cloud transcription ready.',
              },
              companionAxonWakePhrase() { return 'Axon'; },
              dashboardLiveSurfaceModeLabel() { return 'Terminal'; },
              dashboardLiveSurfaceDescription() { return 'Streaming the active shell session.'; },
              dashboardLiveSurfaceActionLabel() { return 'Inspect'; },
              async dashboardLiveSurfaceAction() { this.surfaceActionCount = (this.surfaceActionCount || 0) + 1; },
              async startVoice() { this.listenCount = (this.listenCount || 0) + 1; },
              async sendVoiceCommand(text) {
                this.sent = this.sent || [];
                this.sent.push(text);
              },
              openVoiceCommandCenter() {
                this.fullVoiceCount = (this.fullVoiceCount || 0) + 1;
                this.showVoiceOrb = true;
              },
              voiceVisualState() { return 'agent'; },
              voiceCenterStatusDetail() { return 'Agent mode ready for commands.'; },
              voiceStatusHint() { return 'Say open voice mode to expand the console.'; },
            };
            Object.assign(app, mixin);
            app.ensureDashboardMiniVoiceState();
            await app.dashboardMiniVoiceTalkNow();
            app.handleVoiceCaptureTranscript('show the active terminal', { final: true, source: 'browser' });
            await new Promise((resolve) => setTimeout(resolve, 0));
            await app.dashboardMiniVoicePrimaryAction();
            app.handleVoiceCaptureTranscript('Can we ship after lunch', { final: true, source: 'browser' });
            app.handleVoiceCaptureTranscript('Hey Axon, open the dashboard', { final: true, source: 'browser' });
            await new Promise((resolve) => setTimeout(resolve, 0));
            app.dashboardMiniVoiceOpenFull();
            await app.dashboardMiniVoiceSurfaceAction();
            console.log(JSON.stringify({
              panelClass: app.dashboardMiniVoicePanelClass(),
              statusLabel: app.dashboardMiniVoiceStatusLabel(),
              modeLabel: app.dashboardMiniVoiceModeLabel(),
              actionLabel: app.dashboardMiniVoiceActionLabel(),
              talkLabel: app.dashboardMiniVoiceTalkLabel(),
              lastDisposition: app.dashboardMiniVoiceLastDispositionLabel(),
              surfaceLabel: app.dashboardMiniVoiceSurfaceLabel(),
              surfaceDetail: app.dashboardMiniVoiceSurfaceDetail(),
              surfaceActionLabel: app.dashboardMiniVoiceSurfaceActionLabel(),
              hint: app.dashboardMiniVoiceHint(),
              listenCount: app.listenCount || 0,
              sent: app.sent || [],
              lastHeard: app.dashboardMiniVoiceLastHeard(),
              fullVoiceCount: app.fullVoiceCount || 0,
              surfaceActionCount: app.surfaceActionCount || 0,
            }));
            """
        )

        self.assertEqual(payload['statusLabel'], 'Full voice live')
        self.assertEqual(payload['modeLabel'], 'Full voice mode')
        self.assertEqual(payload['actionLabel'], 'Arm ring')
        self.assertEqual(payload['talkLabel'], 'Talk now')
        self.assertIn('Wake-word command routed', payload['lastDisposition'])
        self.assertEqual(payload['surfaceLabel'], 'Terminal')
        self.assertIn('shell session', payload['surfaceDetail'])
        self.assertEqual(payload['surfaceActionLabel'], 'Inspect')
        self.assertGreaterEqual(payload['listenCount'], 1)
        self.assertEqual(payload['sent'], ['show the active terminal', 'open the dashboard'])
        self.assertEqual(payload['lastHeard'], 'Hey Axon, open the dashboard')
        self.assertEqual(payload['fullVoiceCount'], 1)
        self.assertEqual(payload['surfaceActionCount'], 1)

    def test_dashboard_mini_voice_filters_ambient_chat_and_requires_permission_before_chiming_in(self):
        payload = _run_dashboard_mini_voice_script(
            """
            const mixin = ctx.window.axonDashboardMiniVoiceMixin();
            const app = {
              activeTab: 'dashboard',
              voiceActive: false,
              showVoiceOrb: false,
              voiceStatus: { transcription_available: true, detail: 'Ready.' },
              companionAxonWakePhrase() { return 'Axon'; },
              refreshVoiceCapability() {},
              async loadVoiceStatus() { return this.voiceStatus; },
              async startVoice() { this.listenCount = (this.listenCount || 0) + 1; },
              async sendVoiceCommand(text) {
                this.sent = this.sent || [];
                this.sent.push(text);
              },
            };
            Object.assign(app, mixin);
            await app.dashboardMiniVoicePrimaryAction();
            const ambientConsumed = app.handleVoiceCaptureTranscript('How was the drive home today', { final: true, source: 'browser' });
            const adviceConsumed = app.handleVoiceCaptureTranscript('Maybe we should fix the DNS issue before the deploy', { final: true, source: 'browser' });
            const pendingBeforeApprove = app.dashboardMiniVoicePendingAdvice();
            await app.dashboardMiniVoiceApproveAdvice();
            await new Promise((resolve) => setTimeout(resolve, 0));
            console.log(JSON.stringify({
              ambientConsumed,
              adviceConsumed,
              pendingBeforeApprove: !!pendingBeforeApprove,
              pendingAfterApprove: !!app.dashboardMiniVoicePendingAdvice(),
              sent: app.sent || [],
              lastDisposition: app.dashboardMiniVoiceLastDispositionLabel(),
            }));
            """
        )

        self.assertTrue(payload["ambientConsumed"])
        self.assertTrue(payload["adviceConsumed"])
        self.assertTrue(payload["pendingBeforeApprove"])
        self.assertFalse(payload["pendingAfterApprove"])
        self.assertEqual(len(payload["sent"]), 1)
        self.assertIn("Offer concise, practical advice", payload["sent"][0])
        self.assertIn("Advice approved", payload["lastDisposition"])

    def test_dashboard_mini_voice_resume_waits_until_speech_is_idle(self):
        payload = _run_dashboard_mini_voice_script(
            """
            const mixin = ctx.window.axonDashboardMiniVoiceMixin();
            ctx.window.setTimeout = (callback) => {
              callback();
              return 1;
            };
            ctx.window.clearTimeout = () => {};
            const app = {
              activeTab: 'dashboard',
              chatLoading: false,
              voiceActive: false,
              showVoiceOrb: false,
              voiceStatus: { transcription_available: true, detail: 'Ready.' },
              companionAxonWakePhrase() { return 'Axon'; },
              refreshVoiceCapability() {},
              async loadVoiceStatus() { return this.voiceStatus; },
              dashboardMiniVoiceDashboardActive() { return true; },
              async startVoice() { this.listenCount = (this.listenCount || 0) + 1; },
              voiceSpeechBusy() { return !!this.busy; },
            };
            Object.assign(app, mixin);
            await app.dashboardMiniVoicePrimaryAction();
            const baselineListens = app.listenCount || 0;
            app.busy = true;
            app._scheduleDashboardMiniVoiceResume(0);
            const listensWhileBusy = (app.listenCount || 0) - baselineListens;
            app._clearDashboardMiniVoiceResume();
            app.busy = false;
            app._scheduleDashboardMiniVoiceResume(0);
            console.log(JSON.stringify({
              listensWhileBusy,
              listensAfterIdle: (app.listenCount || 0) - baselineListens,
            }));
            """
        )

        self.assertEqual(payload["listensWhileBusy"], 0)
        self.assertEqual(payload["listensAfterIdle"], 1)


if __name__ == '__main__':
    unittest.main()
