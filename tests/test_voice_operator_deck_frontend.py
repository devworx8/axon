from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_STREAM_BLOCKS_JS = ROOT / "ui/js/voice-stream-blocks.js"
VOICE_ACTIVITY_FEED_JS = ROOT / "ui/js/voice-activity-feed.js"
VOICE_OPERATOR_DECK_JS = ROOT / "ui/js/voice-operator-deck.js"
VOICE_COMMAND_DOCK_PARTIAL = ROOT / "ui/partials/voice_command_dock.html"
VOICE_RESPONSE_PANEL_PARTIAL = ROOT / "ui/partials/voice_response_panel.html"
CHAT_PENDING_APPROVAL_PARTIAL = ROOT / "ui/partials/chat_pending_approval.html"


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
          {json.dumps(str(VOICE_ACTIVITY_FEED_JS))},
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
              label: app.voiceResponsePanelLabel(),
            }));
            """
        )

        self.assertIn("Goal", payload["html"])
        self.assertIn("Command", payload["html"])
        self.assertIn("npx eas-cli build --platform android", payload["html"])
        self.assertIn("Next", payload["html"])
        self.assertEqual(payload["label"], "Operator deck")

    def test_operator_feed_html_includes_command_trace_from_working_blocks(self):
        payload = _run_operator_deck_script(
            """
            const streamMixin = ctx.window.axonVoiceStreamBlocksMixin();
            const deckMixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Running Shell Cmd',
                detail: 'Axon is checking the workspace.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Understanding the task', detail: 'Goal received: Fix the live operator deck' },
              ],
              chatMessages: [
                {
                  id: 'resp-1',
                  role: 'assistant',
                  streaming: true,
                  content: '',
                  workingBlocks: [
                    {
                      id: 'work-1',
                      title: 'Working · Shell Cmd',
                      args: { cmd: 'npm run build', cwd: '/tmp/mobile' },
                      result: '[axon] build passed',
                      status: 'done',
                    },
                  ],
                },
              ],
              latestAssistantMessage() {
                return this.chatMessages[this.chatMessages.length - 1];
              },
              voiceResponseAvailable() { return false; },
              voiceLatestResponseText() { return ''; },
            };
            Object.assign(app, streamMixin, deckMixin);
            console.log(JSON.stringify({ html: app.voiceLiveOperatorFeedHtml() }));
            """
        )

        self.assertIn("Command trace", payload["html"])
        self.assertIn("npm run build", payload["html"])
        self.assertIn("/tmp/mobile", payload["html"])
        self.assertIn("[axon] build passed", payload["html"])

    def test_operator_feed_html_surfaces_live_cards_and_artifacts(self):
        payload = _run_operator_deck_script(
            """
            const activityMixin = ctx.window.axonVoiceActivityFeedMixin();
            const deckMixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              chatProject: { name: 'Companion', path: '/home/edp/Desktop/companion-native' },
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Preparing the preview',
                detail: 'Axon is wiring the local dev server and terminal together.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Workspace attached', detail: 'Using /home/edp/Desktop/companion-native as the workspace root' },
              ],
              latestAssistantMessage() {
                return {
                  id: 'resp-2',
                  role: 'assistant',
                  content: 'I surfaced [build log](/api/files/open?path=%2Fhome%2Fedp%2FDesktop%2Fcompanion-native%2Flogs%2Fbuild.log) and /home/edp/Desktop/companion-native/docs/release-notes.pdf for review.',
                };
              },
              dashboardLiveTerminalSession() {
                return {
                  title: 'Companion shell',
                  active_command: 'npm run dev',
                  cwd: '/home/edp/Desktop/companion-native',
                };
              },
              browserFrameUrl() { return 'http://127.0.0.1:3000'; },
              browserAttachedWorkspaceLabel() { return 'Companion preview'; },
              browserCommandLabel() { return 'Serving the local preview inside Axon'; },
              browserPreviewStatusLabel() { return 'Live'; },
              browserSourcePath() { return '/home/edp/Desktop/companion-native'; },
              voiceResponseAvailable() { return false; },
              voiceLatestResponseText() { return ''; },
            };
            Object.assign(app, activityMixin, deckMixin);
            app.pushActivityEntry('execute', 'Opened release notes', 'Inspecting /home/edp/Desktop/companion-native/docs/release-notes.pdf', { tool: 'files.read' });
            console.log(JSON.stringify({ html: app.voiceLiveOperatorFeedHtml() }));
            """
        )

        self.assertIn("Live surfaces", payload["html"])
        self.assertIn("Artifacts in play", payload["html"])
        self.assertIn("Console terminal", payload["html"])
        self.assertIn("Companion preview", payload["html"])
        self.assertIn("build.log", payload["html"])
        self.assertIn("release-notes.pdf", payload["html"])
        self.assertIn("Live Activity", payload["html"])

    def test_activity_feed_html_uses_stable_rows_without_reveal_animation_attrs(self):
        payload = _run_operator_deck_script(
            """
            const activityMixin = ctx.window.axonVoiceActivityFeedMixin();
            const app = {};
            Object.assign(app, activityMixin);
            app.pushActivityEntry('plan', 'Planning the next step', 'Axon is analysing the workspace.');
            console.log(JSON.stringify({ html: app.voiceActivityFeedHtml(4) }));
            """
        )

        self.assertIn("Live Activity", payload["html"])
        self.assertNotIn('data-voice-reveal="1"', payload["html"])
        self.assertNotIn('animation-delay:', payload["html"])

    def test_activity_feed_merges_repeated_plan_updates_in_place(self):
        payload = _run_operator_deck_script(
            """
            const activityMixin = ctx.window.axonVoiceActivityFeedMixin();
            const app = {};
            Object.assign(app, activityMixin);
            app.pushActivityEntry('plan', 'Thinking through the task', 'Checking the live deck stream path.');
            app.pushActivityEntry('plan', 'Thinking through the task', 'Narrowing the issue to repeated plan updates.');
            console.log(JSON.stringify({
              feedCount: app.voiceActivityFeed.length,
              detail: app.voiceActivityFeed[0]?.detail || '',
              hits: app.voiceActivityFeed[0]?.hits || 0,
            }));
            """
        )

        self.assertEqual(payload["feedCount"], 1)
        self.assertEqual(payload["detail"], "Narrowing the issue to repeated plan updates.")
        self.assertEqual(payload["hits"], 2)

    def test_artifact_entries_hold_stable_copy_during_active_run(self):
        payload = _run_operator_deck_script(
            """
            const activityMixin = ctx.window.axonVoiceActivityFeedMixin();
            const app = {
              chatLoading: true,
              liveOperator: { active: true, phase: 'execute', title: 'Opening file', detail: 'Inspecting the workspace.' },
            };
            Object.assign(app, activityMixin);
            app.pushActivityEntry('execute', 'Opening file', 'Inspecting /home/edp/.devbrain/brain.py', {
              filePath: '/home/edp/.devbrain/brain.py',
              tool: 'files.read',
            });
            const first = app.voiceArtifactEntries(4);
            app.voiceActivityFeed[0].detail = 'Updated detail for /home/edp/.devbrain/brain.py that should not churn the rail mid-run.';
            const second = app.voiceArtifactEntries(4);
            app.chatLoading = false;
            app.liveOperator = { active: false, phase: 'verify', title: 'Done', detail: '' };
            const third = app.voiceArtifactEntries(4);
            console.log(JSON.stringify({
              firstDetail: first[0]?.detail || '',
              secondDetail: second[0]?.detail || '',
              thirdDetail: third[0]?.detail || '',
            }));
            """
        )

        self.assertEqual(payload["firstDetail"], "Inspecting /home/edp/.devbrain/brain.py")
        self.assertEqual(payload["secondDetail"], payload["firstDetail"])
        self.assertEqual(
            payload["thirdDetail"],
            "Updated detail for /home/edp/.devbrain/brain.py that should not churn the rail mid-run.",
        )

    def test_artifact_entries_prefer_resolved_path_over_raw_json_detail(self):
        payload = _run_operator_deck_script(
            """
            const activityMixin = ctx.window.axonVoiceActivityFeedMixin();
            const app = {
              chatLoading: true,
              liveOperator: { active: true, phase: 'execute', title: 'Opening file', detail: 'Inspecting the workspace.' },
              _normalizeRevealPath(value = '') {
                return value === '/js/voice-stream-blocks.js'
                  ? '/home/edp/.devbrain/ui/js/voice-stream-blocks.js'
                  : value;
              },
            };
            Object.assign(app, activityMixin);
            app.pushActivityEntry('execute', 'Opening file', '{"path":"/js/voice-stream-blocks.js"}', {
              filePath: '/js/voice-stream-blocks.js',
              tool: 'files.read',
            });
            const artifact = app.voiceArtifactEntries(4)[0] || {};
            console.log(JSON.stringify({
              path: artifact.path || '',
              detail: artifact.detail || '',
            }));
            """
        )

        self.assertEqual(payload["path"], "/home/edp/.devbrain/ui/js/voice-stream-blocks.js")
        self.assertEqual(payload["detail"], "/home/edp/.devbrain/ui/js/voice-stream-blocks.js")

    def test_operator_deck_holds_visibility_briefly_between_live_updates(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Running Shell Cmd',
                detail: 'Axon is verifying the workspace.',
              },
            };
            Object.assign(app, mixin);
            const visibleDuringRun = app.voiceShouldRenderOperatorDeck();
            app.chatLoading = false;
            app.liveOperator = { active: false, phase: 'observe', title: '', detail: '' };
            const visibleWithinHold = app.voiceShouldRenderOperatorDeck();
            const holdUntil = app.voiceOperatorDeck.holdUntil;
            app.voiceOperatorDeck.holdUntil = 0;
            const visibleAfterHold = app.voiceShouldRenderOperatorDeck();
            console.log(JSON.stringify({
              visibleDuringRun,
              visibleWithinHold,
              visibleAfterHold,
              holdUntil,
            }));
            """
        )

        self.assertTrue(payload["visibleDuringRun"])
        self.assertTrue(payload["visibleWithinHold"])
        self.assertGreater(payload["holdUntil"], 0)
        self.assertFalse(payload["visibleAfterHold"])

    def test_operator_timeline_collapses_duplicate_plan_steps_without_replay_styles(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: true,
              liveOperator: {
                active: true,
                phase: 'plan',
                title: 'Thinking through the task',
                detail: 'Checking the stream path.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Inspecting the task', detail: 'Goal received: Fix the live deck', at: new Date().toISOString() },
                { id: '2', phase: 'plan', title: 'Thinking through the task', detail: 'Checking the live deck stream path.', at: new Date().toISOString() },
                { id: '3', phase: 'plan', title: 'Thinking through the task', detail: 'Narrowing the issue to repeated plan updates.', at: new Date().toISOString() },
              ],
              voiceLatestResponseText() { return ''; },
              voiceResponseAvailable() { return false; },
            };
            Object.assign(app, mixin);
            const timeline = app.voiceOperatorTimeline(5);
            const html = app.voiceOperatorDeckHtml();
            console.log(JSON.stringify({
              timelineCount: timeline.length,
              latestDetail: timeline[0]?.detail || '',
              html,
            }));
            """
        )

        self.assertEqual(payload["timelineCount"], 2)
        self.assertEqual(payload["latestDetail"], "Narrowing the issue to repeated plan updates.")
        self.assertNotIn("animation-delay:", payload["html"])

    def test_operator_deck_stays_visible_for_agent_stream_before_blocks_arrive(self):
        payload = _run_operator_deck_script(
            """
            const mixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: false,
              currentWorkspaceRunActive() { return true; },
              liveOperator: {
                active: false,
                phase: 'observe',
                title: '',
                detail: '',
              },
              liveOperatorFeed: [
                {
                  id: 'feed-1',
                  phase: 'observe',
                  title: 'Observing the task',
                  detail: 'Goal received: Summarize what you are doing right now.',
                  at: new Date().toISOString(),
                },
              ],
              chatMessages: [
                {
                  id: 'resp-2',
                  role: 'assistant',
                  mode: 'agent',
                  streaming: true,
                  content: '',
                  thinkingBlocks: [],
                  workingBlocks: [],
                },
              ],
              latestAssistantMessage() {
                return this.chatMessages[this.chatMessages.length - 1];
              },
              voiceLatestResponseText() { return ''; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              renderDeck: app.voiceShouldRenderOperatorDeck(),
              label: app.voiceResponsePanelLabel(),
            }));
            """
        )

        self.assertTrue(payload["renderDeck"])
        self.assertEqual(payload["label"], "Operator deck")

    def test_voice_operator_partials_use_task_deck_bindings(self):
        command_partial = VOICE_COMMAND_DOCK_PARTIAL.read_text(encoding="utf-8")
        response_partial = VOICE_RESPONSE_PANEL_PARTIAL.read_text(encoding="utf-8")
        approval_partial = CHAT_PENDING_APPROVAL_PARTIAL.read_text(encoding="utf-8")

        self.assertIn("voiceCommandDeckTitle()", command_partial)
        self.assertIn("voiceCommandDeckSubmitLabel()", command_partial)
        self.assertIn("voiceOperatorSurfaceChip()", command_partial)
        self.assertIn("voiceResponsePanelLabel()", response_partial)
        self.assertIn("voiceDisplayResponseHtml()", response_partial)
        self.assertIn("voiceResponseRenderClass()", response_partial)
        self.assertIn("approvalPromptTitle(currentPendingAgentApproval())", approval_partial)
        self.assertIn("approvalPromptActionLabel('session'", approval_partial)


if __name__ == "__main__":
    unittest.main()
