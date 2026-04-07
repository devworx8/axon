from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_STREAM_BLOCKS_JS = ROOT / "ui/js/voice-stream-blocks.js"
VOICE_OPERATOR_DECK_JS = ROOT / "ui/js/voice-operator-deck.js"
VOICE_COMMAND_DOCK_PARTIAL = ROOT / "ui/partials/voice_command_dock.html"
VOICE_RESPONSE_PANEL_PARTIAL = ROOT / "ui/partials/voice_response_panel.html"


def _run_operator_deck_script(body: str):
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
        for (const path of [
          {json.dumps(str(VOICE_STREAM_BLOCKS_JS))},
          {json.dumps(str(VOICE_OPERATOR_DECK_JS))},
        ]) {{
          vm.runInContext(fs.readFileSync(path, 'utf8'), ctx);
        }}
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


class VoiceOperatorDeckFrontendTests(unittest.TestCase):
    def test_operational_intent_detects_eas_deploy_requests(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = { voiceConversation: { textDraft: 'Deploy the mobile companion app to EAS' } };
            Object.assign(app, mixin);
            console.log(JSON.stringify(app.voiceOperationalIntent()));
            """
        )

        self.assertTrue(payload["active"])
        self.assertEqual(payload["key"], "deploy")
        self.assertEqual(payload["label"], "Deploy")

    def test_operator_deck_stays_hidden_for_staged_command_without_live_activity(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              voiceConversation: { textDraft: 'Deploy the mobile companion app to EAS' },
              currentWorkspaceAutoSession() { return null; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              renderDeck: app.voiceShouldRenderOperatorDeck(),
              headline: app.voiceOperatorHeadline(),
            }));
            """
        )

        self.assertFalse(payload["renderDeck"])
        self.assertEqual(payload["headline"], "Deploy ready to dispatch")

    def test_sync_runtime_keeps_terminal_hidden_for_plan_only_operational_runs(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              showVoiceOrb: true,
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'plan',
                title: 'Inspecting the task',
                detail: 'Axon is checking Expo config and runtime state.',
              },
              voiceConversation: {
                terminalPinned: false,
                textDraft: 'Deploy the mobile companion app to EAS',
              },
              ensureVoiceConversationState() {
                this.voiceConversation = {
                  textDockOpen: false,
                  textDraft: '',
                  handsFree: true,
                  awaitingReply: false,
                  awaitingReplySince: '',
                  awaitingReplySource: '',
                  lastReplyPreview: '',
                  lastCommand: '',
                  terminalPinned: true,
                  quickPrompts: [],
                  ...this.voiceConversation,
                };
              },
              voiceOperatorTraceLines() { return []; },
              voiceTerminalSession() { return null; },
              voiceLatestResponseText() { return ''; },
              consoleProviderIdentity() { return { providerLabel: 'CLI Agent' }; },
              hudShowTerminal(title, lines) {
                this.terminalTitle = title;
                this.terminalLines = lines;
                this.hudTerminalVisible = true;
              },
              hudHideTerminal() {
                this.hudTerminalVisible = false;
              },
            };
            Object.assign(app, mixin);
            app.syncVoiceCommandCenterRuntime();
            console.log(JSON.stringify({
              visible: !!app.hudTerminalVisible,
              title: app.terminalTitle || '',
            }));
            """
        )

        self.assertFalse(payload["visible"])
        self.assertEqual(payload["title"], "")

    def test_sync_runtime_auto_shows_terminal_when_shell_trace_is_live(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              showVoiceOrb: true,
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Running Expo shell',
                detail: 'Axon is starting the EAS build.',
              },
              hudOperatorTraceTitle: 'Expo shell telemetry',
              hudOperatorTraceLines: ['$ npx eas-cli build -p android --profile development', '@ /home/edp/.devbrain/apps/companion-native'],
              voiceConversation: {
                terminalPinned: false,
                textDraft: 'Deploy the mobile companion app to EAS',
              },
              ensureVoiceConversationState() {
                this.voiceConversation = {
                  textDockOpen: false,
                  textDraft: '',
                  handsFree: true,
                  awaitingReply: false,
                  awaitingReplySince: '',
                  awaitingReplySource: '',
                  lastReplyPreview: '',
                  lastCommand: '',
                  terminalPinned: false,
                  quickPrompts: [],
                  ...this.voiceConversation,
                };
              },
              voiceOperatorTraceLines(limit = 12) {
                return (this.hudOperatorTraceLines || []).slice(-limit);
              },
              voiceTerminalSession() { return null; },
              voiceLatestResponseText() { return ''; },
              consoleProviderIdentity() { return { providerLabel: 'CLI Agent' }; },
              hudShowTerminal(title, lines) {
                this.terminalTitle = title;
                this.terminalLines = lines;
                this.hudTerminalVisible = true;
              },
              hudHideTerminal() {
                this.hudTerminalVisible = false;
              },
            };
            Object.assign(app, mixin);
            app.syncVoiceCommandCenterRuntime();
            console.log(JSON.stringify({
              visible: app.hudTerminalVisible,
              title: app.terminalTitle || '',
              lines: app.terminalLines || [],
            }));
            """
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(payload["title"], "Expo shell telemetry")
        self.assertEqual(payload["lines"][0], "$ npx eas-cli build -p android --profile development")

    def test_operator_headline_uses_running_auto_session_when_stream_is_idle(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              currentWorkspaceAutoSession() {
                return {
                  session_id: 'auto-42',
                  status: 'running',
                  title: 'Deploy Android build',
                  detail: 'Axon is checking Expo auth before queueing the build.',
                };
              },
              voiceConversation: {},
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              renderDeck: app.voiceShouldRenderOperatorDeck(),
              headline: app.voiceOperatorHeadline(),
              next: app.voiceOperatorNextStep(),
            }));
            """
        )

        self.assertTrue(payload["renderDeck"])
        self.assertEqual(payload["headline"], "Deploy Android build")
        self.assertIn("checking Expo auth", payload["next"])

    def test_operator_feed_html_includes_streaming_thinking_blocks(self):
        payload = _run_operator_deck_script(
            """
            const streamMixin = ctx.window.axonVoiceStreamBlocksMixin();
            const deckMixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'plan',
                title: 'Thinking through the task',
                detail: 'Axon is reasoning through the deployment plan.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Understanding the request', detail: 'Goal received: Deploy the mobile companion app to EAS' },
              ],
              chatMessages: [
                {
                  id: 'resp-1',
                  role: 'assistant',
                  streaming: true,
                  content: '',
                  thinkingBlocks: [
                    {
                      id: 'think-1',
                      title: 'Thinking',
                      content: 'The user is asking for an Android EAS build first.',
                      status: 'active',
                      updatedAt: '2026-04-07T00:00:00Z',
                    },
                  ],
                  workingBlocks: [],
                },
              ],
              latestAssistantMessage() {
                return this.chatMessages[this.chatMessages.length - 1];
              },
              voiceResponseAvailable() { return false; },
              voiceLatestResponseText() { return ''; },
            };
            Object.assign(app, streamMixin, deckMixin);
            console.log(JSON.stringify({
              html: app.voiceLiveOperatorFeedHtml(),
            }));
            """
        )

        self.assertIn("Streaming blocks", payload["html"])
        self.assertIn("Thinking", payload["html"])
        self.assertIn("The user is asking for an Android EAS build first.", payload["html"])

    def test_operator_feed_html_includes_goal_command_and_next_step(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Running Expo diagnostics',
                detail: 'Axon is checking EAS auth and project config.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Understanding the task', detail: 'Goal received: Deploy the mobile companion app to EAS' },
                { id: '2', phase: 'execute', title: 'Inspecting Expo config', detail: 'Reading app.json and eas.json' },
              ],
              voiceConversation: { lastCommand: 'Deploy the mobile companion app to EAS' },
              voiceLatestResponseText() { return ''; },
              dashboardLiveTerminalSession() {
                return { active_command: 'npx eas-cli build --platform android', title: 'Expo shell' };
              },
              voiceResponseAvailable() { return false; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              html: app.voiceLiveOperatorFeedHtml(),
            }));
            """
        )

        self.assertIn("Goal", payload["html"])
        self.assertIn("Command", payload["html"])
        self.assertIn("npx eas-cli build --platform android", payload["html"])
        self.assertIn("Next", payload["html"])

    def test_voice_operator_partials_use_task_deck_bindings(self):
        command_partial = VOICE_COMMAND_DOCK_PARTIAL.read_text(encoding="utf-8")
        response_partial = VOICE_RESPONSE_PANEL_PARTIAL.read_text(encoding="utf-8")

        self.assertIn("voiceCommandDeckTitle()", command_partial)
        self.assertIn("voiceCommandDeckSubmitLabel()", command_partial)
        self.assertIn("voiceOperatorSurfaceChip()", command_partial)
        self.assertIn("voiceResponsePanelLabel()", response_partial)
        self.assertIn("voiceDisplayResponseHtml()", response_partial)


if __name__ == "__main__":
    unittest.main()
