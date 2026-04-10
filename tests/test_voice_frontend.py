from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui/index.html"
SETTINGS_VOICE_DECK_PARTIAL = ROOT / "ui/partials/settings_voice_deck.html"
VOICE_JS = ROOT / "ui/js/voice.js"
VOICE_SPEECH_JS = ROOT / "ui/js/voice-speech.js"
VOICE_PLAYBACK_JS = ROOT / "ui/js/voice-playback.js"
VOICE_COMMAND_CENTER_JS = ROOT / "ui/js/voice-command-center.js"
VOICE_CONVERSATION_JS = ROOT / "ui/js/voice-conversation.js"
VOICE_HUD_JS = ROOT / "ui/js/voice-hud.js"
CHAT_APPROVALS_JS = ROOT / "ui/js/chat-approvals.js"
VOICE_APPROVAL_MODAL_PARTIAL = ROOT / "ui/partials/voice_approval_modal.html"


def _run_voice_script(files: list[Path], body: str):
    load_modules = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(path))}, 'utf8'), ctx);"
        for path in files
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const utterances = [];
        const utteranceRates = [];
        const ctx = {{
          window: {{
            speechSynthesis: {{
              cancel() {{}},
              speak(utterance) {{
                utterances.push(utterance.text);
                utteranceRates.push(utterance.rate);
                setTimeout(() => {{
                  if (typeof utterance.onend === 'function') utterance.onend();
                }}, 0);
              }},
            }},
            addEventListener() {{}},
            removeEventListener() {{}},
          }},
          SpeechSynthesisUtterance: function(text) {{
            this.text = text;
            this.lang = '';
            this.rate = 1;
            this.onend = null;
            this.onerror = null;
          }},
          Audio: function(url) {{
            this.url = url;
            this.src = url;
            this.onended = null;
            this.onerror = null;
            this.play = () => {{
              setTimeout(() => {{
                if (typeof this.onended === 'function') this.onended();
              }}, 0);
              return Promise.resolve();
            }};
            this.pause = () => {{}};
          }},
          URL: {{
            createObjectURL() {{ return 'blob:test'; }},
            revokeObjectURL() {{}},
          }},
          fetch: async () => {{ throw new Error('network disabled in test'); }},
          console,
          setTimeout,
          clearTimeout,
          requestAnimationFrame: (cb) => setTimeout(cb, 0),
        }};
        ctx.window.window = ctx.window;
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        {load_modules}
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


class VoiceFrontendTests(unittest.TestCase):
    def test_desktop_toolbar_keeps_dedicated_voice_command_center_trigger(self):
        template = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn('@click="openVoiceCommandCenter()"', template)
        self.assertIn('title="Voice command center"', template)

    def test_root_app_composes_voice_stream_blocks_mixin(self):
        template = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "typeof axonVoiceStreamBlocksMixin === 'function' ? axonVoiceStreamBlocksMixin() : {}",
            template,
        )

    def test_settings_voice_deck_uses_root_voice_status_loading_flag(self):
        template = SETTINGS_VOICE_DECK_PARTIAL.read_text(encoding="utf-8")

        self.assertIn("voiceStatusLoading ? 'Refreshing…' : 'Refresh runtime'", template)
        self.assertNotIn("voice.statusLoading", template)

    def test_voice_speech_helper_splits_long_text_without_truncating(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS],
            """
            const clean = ctx.window.axonVoiceSpeech.cleanText('**Hello** `code` [link](https://example.com)\\n\\n' + 'Sentence. '.repeat(120));
            const chunks = ctx.window.axonVoiceSpeech.splitText(clean, 180);
            console.log(JSON.stringify({
              cleanIncludesHello: clean.includes('Hello'),
              cleanIncludesLinkLabel: clean.includes('link'),
              removedBackticks: !clean.includes('`'),
              chunkCount: chunks.length,
              maxChunk: Math.max(...chunks.map((chunk) => chunk.length)),
              joinedLength: chunks.join(' ').length,
              cleanLength: clean.replace(/\\s+/g, ' ').trim().length,
            }));
            """,
        )

        self.assertTrue(payload["cleanIncludesHello"])
        self.assertTrue(payload["cleanIncludesLinkLabel"])
        self.assertTrue(payload["removedBackticks"])
        self.assertGreater(payload["chunkCount"], 1)
        self.assertLessEqual(payload["maxChunk"], 180)
        self.assertGreaterEqual(payload["joinedLength"], payload["cleanLength"] - 8)

    def test_voice_speech_helper_reads_code_blocks_instead_of_dropping_them(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS],
            """
            const clean = ctx.window.axonVoiceSpeech.cleanText('```js\\nconst route = "/api/health";\\nreturn route;\\n```\\n\\nUse `GIT commit --amend` with `vault.py` and `AXON_DEV_LOCAL_VAULT_BYPASS` next.');
            console.log(JSON.stringify({
              clean,
              mentionsLanguageIntro: clean.includes('In JavaScript'),
              mentionsRoute: clean.includes('slash api slash health'),
              mentionsHumanGit: clean.includes('git commit amend flag'),
              mentionsVaultFile: clean.includes('vault Python file'),
              mentionsEnvVar: clean.includes('axon dev local vault bypass'),
              mentionsInlineCode: clean.includes('inline code'),
              mentionsMinusMinus: clean.includes('minus minus'),
              mentionsCodeEnd: clean.includes('End code block'),
            }));
            """,
        )

        self.assertTrue(payload["mentionsLanguageIntro"])
        self.assertTrue(payload["mentionsRoute"])
        self.assertTrue(payload["mentionsHumanGit"])
        self.assertTrue(payload["mentionsVaultFile"])
        self.assertTrue(payload["mentionsEnvVar"])
        self.assertFalse(payload["mentionsInlineCode"])
        self.assertFalse(payload["mentionsMinusMinus"])
        self.assertFalse(payload["mentionsCodeEnd"])

    def test_voice_speech_helper_permission_command_maps_enable_and_disable_phrases(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS],
            """
            const run = async (text, current = 'default') => {
              const calls = [];
              const handled = await ctx.window.axonVoiceSpeech.permissionCommand(text, {
                setPermissionPreset: async (preset) => { calls.push(preset); },
                permissionPresetKey: () => current,
              });
              return { handled, target: calls[0] || '' };
            };
            const disableAskFirst = await run('disable ask first');
            const enableAskFirst = await run('enable ask first');
            const turnOffFullAccess = await run('turn off full access');
            const turnOnFullAccess = await run('turn on full access');
            const disableDefault = await run('disable default permissions');
            const toggleFullAccess = await run('toggle full access', 'full_access');
            console.log(JSON.stringify({
              disableAskFirst,
              enableAskFirst,
              turnOffFullAccess,
              turnOnFullAccess,
              disableDefault,
              toggleFullAccess,
            }));
            """,
        )

        self.assertTrue(payload["disableAskFirst"]["handled"])
        self.assertEqual(payload["disableAskFirst"]["target"], "default")
        self.assertTrue(payload["enableAskFirst"]["handled"])
        self.assertEqual(payload["enableAskFirst"]["target"], "ask_first")
        self.assertTrue(payload["turnOffFullAccess"]["handled"])
        self.assertEqual(payload["turnOffFullAccess"]["target"], "default")
        self.assertTrue(payload["turnOnFullAccess"]["handled"])
        self.assertEqual(payload["turnOnFullAccess"]["target"], "full_access")
        self.assertTrue(payload["disableDefault"]["handled"])
        self.assertEqual(payload["disableDefault"]["target"], "ask_first")
        self.assertTrue(payload["toggleFullAccess"]["handled"])
        self.assertEqual(payload["toggleFullAccess"]["target"], "default")

    def test_voice_command_center_uses_markdown_pipeline_for_local_links(self):
        payload = _run_voice_script(
            [Path(str(ROOT / "ui/js/helpers.js")), VOICE_COMMAND_CENTER_JS],
            """
            ctx.marked = {
              setOptions() {},
              parse(value) {
                return String(value || '').replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2">$1</a>');
              },
            };
            const helperMixin = ctx.axonHelpersMixin();
            const voiceMixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              authToken: 'token-123',
              chatMessages: [{
                id: 10,
                role: 'assistant',
                content: 'Open [vault.py](/home/edp/.devbrain/vault.py) and [status](/api/vault/status).',
              }],
              chatLoading: false,
              liveOperator: { detail: '' },
              voiceConversation: {},
            };
            Object.assign(app, helperMixin, voiceMixin);
            const html = app.voiceDisplayResponseHtml();
            console.log(JSON.stringify({
              html,
              hasFileRoute: html.includes('/api/files/open?path=%2Fhome%2Fedp%2F.devbrain%2Fvault.py'),
              hasVoicePath: html.includes('data-voice-path="/home/edp/.devbrain/vault.py"'),
              hasApiLink: html.includes('/api/vault/status'),
            }));
            """,
        )

        self.assertTrue(payload["hasFileRoute"])
        self.assertTrue(payload["hasVoicePath"])
        self.assertTrue(payload["hasApiLink"])

    def test_voice_command_center_stop_and_send_uses_current_transcript(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS],
            """
            const mixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              voiceActive: true,
              voiceTranscript: 'Read the full message',
              chatMessages: [{ id: 10, role: 'assistant', content: 'Latest response' }],
              chatLoading: false,
              liveOperator: { detail: '' },
              stopCount: 0,
              sendCount: 0,
              async startVoice() {
                this.stopCount += 1;
                this.voiceActive = false;
              },
              async sendVoiceCommand() {
                this.sendCount += 1;
                this.sentTranscript = this.voiceTranscript;
              },
              clearVoiceTranscript() {
                this.voiceTranscript = '';
              },
            };
            Object.assign(app, mixin);
            await app.startVoiceListening();
            app.clearVoiceCommandCenterState();
            const afterClear = app.voiceDisplayResponse();
            app.chatMessages.push({ id: 20, role: 'assistant', content: 'New response after clear' });
            console.log(JSON.stringify({
              stopCount: app.stopCount,
              sendCount: app.sendCount,
              sentTranscript: app.sentTranscript,
              afterClear,
              responseAfterNewMessage: app.voiceDisplayResponse(),
            }));
            """,
        )

        self.assertEqual(payload["stopCount"], 1)
        self.assertEqual(payload["sendCount"], 1)
        self.assertEqual(payload["sentTranscript"], "Read the full message")
        self.assertEqual(payload["afterClear"], "The latest voice response will appear here.")
        self.assertEqual(payload["responseAfterNewMessage"], "New response after clear")

    def test_load_voice_status_retries_after_a_failed_probe(self):
        payload = _run_voice_script(
            [VOICE_JS],
            """
            const mixin = ctx.window.axonVoiceMixin();
            let apiCalls = 0;
            const app = {
              settingsForm: { azure_speech_key: '', _azureSpeechKeyHint: '' },
              api() {
                apiCalls += 1;
                if (apiCalls === 1) {
                  return Promise.reject(new Error('Voice status unavailable'));
                }
                return Promise.resolve({
                  available: true,
                  preferred_mode: 'cloud',
                  transcription_available: false,
                  cloud_transcription_available: true,
                  transcription_ready: true,
                  synthesis_available: false,
                  detail: 'Cloud transcription ready via Azure Speech.',
                  state: {},
                });
              },
            };
            Object.assign(app, mixin);
            await app.loadVoiceStatus();
            const first = { ...app.voiceStatus };
            await app.loadVoiceStatus();
            console.log(JSON.stringify({
              apiCalls,
              firstDetail: first.detail,
              secondDetail: app.voiceStatus.detail,
              secondMode: app.voiceStatus.preferred_mode,
              secondReady: !!app.voiceStatus.transcription_ready,
            }));
            """,
        )

        self.assertEqual(payload["apiCalls"], 2)
        self.assertEqual(payload["firstDetail"], "Voice status unavailable")
        self.assertEqual(payload["secondDetail"], "Cloud transcription ready via Azure Speech.")
        self.assertEqual(payload["secondMode"], "cloud")
        self.assertTrue(payload["secondReady"])

    def test_voice_capture_handler_can_consume_final_transcript_before_it_reaches_composer(self):
        payload = _run_voice_script(
            [VOICE_JS],
            """
            class FakeRecognition {
              constructor() {
                this.onresult = null;
                this.onerror = null;
                this.onend = null;
              }
              start() {}
            }
            ctx.window.SpeechRecognition = FakeRecognition;
            ctx.navigator = {
              mediaDevices: {
                async getUserMedia() {
                  return {
                    getTracks() {
                      return [{ stop() {} }];
                    },
                  };
                },
              },
            };
            ctx.location = { hostname: 'localhost' };
            ctx.window.isSecureContext = true;
            const mixin = ctx.window.axonVoiceMixin();
            const app = {
              settingsForm: { azure_speech_key: '', _azureSpeechKeyHint: '', azure_voice: 'en-GB-RyanNeural' },
              syncCount: 0,
              handled: [],
              speechLocale() { return 'en-US'; },
              handleVoiceCaptureTranscript(text, options) {
                this.handled.push({ text, final: !!options?.final, source: options?.source || '' });
                return true;
              },
              syncVoiceTranscript() { this.syncCount += 1; },
              showToast() {},
            };
            Object.assign(app, mixin);
            await app.startVoice();
            app._speechRecognizer.onresult({
              resultIndex: 0,
              results: [
                { isFinal: true, 0: { transcript: 'hey axon open the dashboard' } },
              ],
            });
            console.log(JSON.stringify({
              handled: app.handled,
              syncCount: app.syncCount,
              voiceActive: app.voiceActive,
            }));
            """,
        )

        self.assertEqual(payload["syncCount"], 0)
        self.assertEqual(payload["handled"][0]["text"], "hey axon open the dashboard")
        self.assertTrue(payload["handled"][0]["final"])
        self.assertEqual(payload["handled"][0]["source"], "browser")
        self.assertFalse(payload["voiceActive"])

    def test_voice_command_center_prefers_text_dock_draft_for_transcript_display(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS],
            """
            const mixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              voiceTranscript: 'stale transcript',
              chatInput: '',
              voiceConversation: {
                textDockOpen: true,
                textDraft: 'Open the most recent PDF in Documents',
              },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              transcript: app.voiceDisplayTranscript(),
            }));
            """,
        )

        self.assertEqual(payload["transcript"], "Open the most recent PDF in Documents")

    def test_voice_command_center_rephrases_outside_directory_error(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS],
            """
            const mixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              chatMessages: [{
                id: 10,
                role: 'assistant',
                content: 'ERROR: Access outside the allowed directories is not allowed.',
              }],
              chatLoading: false,
              liveOperator: { detail: '' },
              voiceConversation: {},
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify({
              response: app.voiceDisplayResponse(),
            }));
            """,
        )

        self.assertIn("outside the current workspace sandbox", payload["response"])

    def test_voice_command_center_defaults_to_agent_mode_when_voice_opens_on_agent_backend(self):
        payload = _run_voice_script(
            [VOICE_JS, CHAT_APPROVALS_JS, Path(str(ROOT / "ui/js/chat-workspace-modes.js"))],
            """
            const voiceMixin = ctx.window.axonVoiceMixin();
            const workspaceMixin = ctx.window.axonChatWorkspaceModesMixin();
            const app = {
              showVoiceOrb: false,
              agentMode: false,
              businessMode: false,
              chatLoading: false,
              chatInput: '',
              voiceTranscript: '',
              voiceConversation: {},
              settingsForm: { ai_backend: 'cli' },
              runtimeStatus: { cli_model: 'gpt-5.4' },
              currentBackendSupportsAgent() { return true; },
              activePrimaryConversationMode() {
                if (this.businessMode) return 'business';
                if (this.agentMode) return 'agent';
                return 'ask';
              },
              chooseConversationModeAgent() {
                this.agentMode = true;
                this.composerOptions = this.composerOptions || {};
                this.composerOptions.agent_role = '';
              },
              ensureVoiceConversationState() {},
              initVoiceSurfaceDirector() {},
              refreshVoiceCapability() {},
              syncVoiceCommandCenterRuntime() {},
              syncVoiceSurfaceDirector() {},
              switchTab() {},
            };
            Object.assign(app, workspaceMixin, voiceMixin);
            app.openVoiceCommandCenter();
            console.log(JSON.stringify({
              agentMode: app.agentMode,
              mode: app.activePrimaryConversationMode(),
              showVoiceOrb: app.showVoiceOrb,
            }));
            """,
        )

        self.assertTrue(payload["agentMode"])
        self.assertEqual(payload["mode"], "agent")
        self.assertTrue(payload["showVoiceOrb"])

    def test_voice_capability_refresh_promotes_agent_mode_once_runtime_supports_it(self):
        payload = _run_voice_script(
            [VOICE_JS, Path(str(ROOT / "ui/js/chat-workspace-modes.js"))],
            """
            const voiceMixin = ctx.window.axonVoiceMixin();
            const workspaceMixin = ctx.window.axonChatWorkspaceModesMixin();
            const app = {
              showVoiceOrb: true,
              agentMode: false,
              businessMode: false,
              chatLoading: false,
              settingsForm: { ai_backend: 'cli' },
              runtimeStatus: { cli_model: 'gpt-5.4' },
              currentBackendSupportsAgent() { return true; },
              activePrimaryConversationMode() {
                if (this.businessMode) return 'business';
                if (this.agentMode) return 'agent';
                return 'ask';
              },
              chooseConversationModeAgent() {
                this.agentMode = true;
                this.composerOptions = this.composerOptions || {};
                this.composerOptions.agent_role = '';
              },
            };
            Object.assign(app, workspaceMixin, voiceMixin);
            app.refreshVoiceCapability();
            console.log(JSON.stringify({
              agentMode: app.agentMode,
              mode: app.activePrimaryConversationMode(),
            }));
            """,
        )

        self.assertTrue(payload["agentMode"])
        self.assertEqual(payload["mode"], "agent")

    def test_approval_prompt_helpers_render_explicit_permission_copy(self):
        payload = _run_voice_script(
            [CHAT_APPROVALS_JS],
            """
            const mixin = ctx.window.axonChatApprovalMixin();
            const app = {
              chatProjectId: '7',
              workspaceTabLabel() { return 'Hope'; },
              terminal: { approvalRequired: false },
            };
            Object.assign(app, mixin);
            app.syncPendingAgentApproval({
              workspace_id: '7',
              workspace_name: 'Hope',
              message: 'Axon needs permission to continue.',
              summary: 'Edit package.json',
              command: 'edit',
              full_command: 'sed -n \"1,80p\" package.json',
              approval_action: {
                action_type: 'file_read',
                path: '/home/edp/.devbrain/package.json',
                scope_options: ['once', 'session'],
              },
            });
            console.log(JSON.stringify({
              title: app.approvalPromptTitle(),
              body: app.approvalPromptBody(),
              meta: app.approvalPromptMeta(),
              chip: app.approvalPromptChipLabel(),
              once: app.approvalPromptActionLabel('once'),
              session: app.approvalPromptActionLabel('session'),
              preview: app.approvalCommandPreview(),
            }));
            """,
        )

        self.assertEqual(payload["title"], "File access permission required")
        self.assertIn("/home/edp/.devbrain/package.json", payload["body"])
        self.assertIn("Workspace: Hope", payload["meta"])
        self.assertEqual(payload["chip"], "File access")
        self.assertEqual(payload["once"], "Allow file access once")
        self.assertEqual(payload["session"], "Allow file access for session")
        self.assertIn("sed -n", payload["preview"])

    def test_voice_approval_modal_uses_prompt_card_markup(self):
        partial = VOICE_APPROVAL_MODAL_PARTIAL.read_text(encoding="utf-8")

        self.assertIn("voice-approval-modal", partial)
        self.assertIn("approvalPromptTitle(currentPendingAgentApproval())", partial)
        self.assertIn("approvalPromptActionLabel('session'", partial)
        self.assertIn("voiceApprovalLabel()", partial)

    def test_voice_playback_queues_multiple_browser_utterances_for_long_text(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS, VOICE_PLAYBACK_JS],
            """
            const mixin = ctx.window.axonVoicePlaybackMixin();
            const app = {
              settingsForm: { azure_speech_region: '' },
              voiceMode: false,
              chatLoading: false,
              voiceActive: false,
              agentMode: false,
              _currentAudio: null,
              authHeaders(headers) { return headers; },
              azureSpeechConfigured() { return false; },
              showToast(message) { this.toast = message; },
            };
            Object.assign(app, mixin);
            await app.speakMessage('Sentence. '.repeat(520));
            console.log(JSON.stringify({
              utteranceCount: utterances.length,
              utteranceRates,
              longestUtterance: Math.max(...utterances.map((chunk) => chunk.length)),
              totalLength: utterances.join(' ').length,
              toast: app.toast || '',
            }));
            """,
        )

        self.assertGreater(payload["utteranceCount"], 1)
        self.assertLessEqual(payload["longestUtterance"], 420)
        self.assertGreater(payload["totalLength"], 4000)
        self.assertTrue(all(abs(rate - 0.85) < 0.001 for rate in payload["utteranceRates"]))
        self.assertEqual(payload["toast"], "")

    def test_voice_playback_posts_numeric_rate_and_pitch_to_tts(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS, VOICE_PLAYBACK_JS],
            """
            let requestBody = null;
            ctx.fetch = async (_url, init) => {
              requestBody = JSON.parse(init.body);
              throw new Error('network disabled in test');
            };
            const mixin = ctx.window.axonVoicePlaybackMixin();
            const app = {
              settingsForm: {
                azure_speech_region: 'eastus',
                azure_voice: 'en-ZA-LeahNeural',
                voice_speech_rate: '0.91',
                voice_speech_pitch: '1.08',
              },
              voiceMode: false,
              chatLoading: false,
              voiceActive: false,
              agentMode: false,
              _currentAudio: null,
              authHeaders(headers) { return headers; },
              azureSpeechConfigured() { return true; },
              showToast(message) { this.toast = message; },
            };
            Object.assign(app, mixin);
            await app.speakMessage('Status report');
            console.log(JSON.stringify({ requestBody, toast: app.toast || '' }));
            """,
        )

        self.assertEqual(payload["requestBody"]["rate"], 0.91)
        self.assertEqual(payload["requestBody"]["pitch"], 1.08)
        self.assertEqual(payload["toast"], "")

    def test_voice_playback_abort_cancels_pending_tts_and_clears_busy_state(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS, VOICE_PLAYBACK_JS],
            """
            ctx.AbortController = globalThis.AbortController;
            let aborted = false;
            ctx.fetch = async (_url, init = {}) => new Promise((resolve, reject) => {
              init.signal?.addEventListener('abort', () => {
                aborted = true;
                const error = new Error('aborted');
                error.name = 'AbortError';
                reject(error);
              });
            });
            const mixin = ctx.window.axonVoicePlaybackMixin();
            const app = {
              settingsForm: {
                azure_speech_region: 'eastus',
                azure_voice: 'en-ZA-LeahNeural',
              },
              voiceMode: false,
              chatLoading: false,
              voiceActive: false,
              agentMode: false,
              _currentAudio: null,
              authHeaders(headers) { return headers; },
              azureSpeechConfigured() { return true; },
              showToast(message) { this.toast = message; },
            };
            Object.assign(app, mixin);
            const pending = app.speakMessage('Status report');
            const busyWhilePending = app.voiceSpeechBusy();
            app.stopSpeech();
            await pending;
            console.log(JSON.stringify({
              aborted,
              busyWhilePending,
              busyAfterStop: app.voiceSpeechBusy(),
              toast: app.toast || '',
            }));
            """,
        )

        self.assertTrue(payload["aborted"])
        self.assertTrue(payload["busyWhilePending"])
        self.assertFalse(payload["busyAfterStop"])
        self.assertEqual(payload["toast"], "")

    def test_voice_command_center_sleep_reactor_hard_stops_without_speaking_goodbye(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS],
            """
            let sleepSoundCount = 0;
            ctx.window.axonVoiceSleepSound = { play() { sleepSoundCount += 1; } };
            const mixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              reactorAsleep: false,
              voiceActive: true,
              _bootGreetingTimer: 42,
              clearVoiceAwaitingReply() { this.awaitingCleared = true; },
              _narrationQueue: ['queued'],
              _narrationTimer: setTimeout(() => {}, 20),
              stopSpeech() { this.stopSpeechCount = (this.stopSpeechCount || 0) + 1; },
              startVoice() {
                this.captureStopCount = (this.captureStopCount || 0) + 1;
                this.voiceActive = false;
                return Promise.resolve();
              },
              _pickSleepGoodbye() {
                this.goodbyePicked = true;
                return 'Standing down, Sir.';
              },
              _speakGreeting(text) { this.goodbyeSpoken = text; },
            };
            Object.assign(app, mixin);
            app._pickSleepGoodbye = app._pickSleepGoodbye.bind(app);
            app._speakGreeting = app._speakGreeting.bind(app);
            app.sleepReactor();
            await new Promise((resolve) => setTimeout(resolve, 0));
            console.log(JSON.stringify({
              reactorAsleep: app.reactorAsleep,
              narrationCancelled: app._narrationQueue.length === 0 && app._narrationTimer === null,
              awaitingCleared: !!app.awaitingCleared,
              stopSpeechCount: app.stopSpeechCount || 0,
              captureStopCount: app.captureStopCount || 0,
              goodbyePicked: !!app.goodbyePicked,
              goodbyeSpoken: app.goodbyeSpoken || '',
              sleepSoundCount,
            }));
            """,
        )

        self.assertTrue(payload["reactorAsleep"])
        self.assertTrue(payload["narrationCancelled"])
        self.assertTrue(payload["awaitingCleared"])
        self.assertEqual(payload["stopSpeechCount"], 1)
        self.assertEqual(payload["captureStopCount"], 1)
        self.assertFalse(payload["goodbyePicked"])
        self.assertEqual(payload["goodbyeSpoken"], "")
        self.assertEqual(payload["sleepSoundCount"], 1)

    def test_voice_command_center_narration_waits_while_reply_speech_is_pending(self):
        payload = _run_voice_script(
            [VOICE_SPEECH_JS, VOICE_PLAYBACK_JS, VOICE_COMMAND_CENTER_JS],
            """
            ctx.AbortController = globalThis.AbortController;
            let fetchCalls = 0;
            ctx.fetch = async (_url, init = {}) => new Promise((resolve, reject) => {
              fetchCalls += 1;
              init.signal?.addEventListener('abort', () => {
                const error = new Error('aborted');
                error.name = 'AbortError';
                reject(error);
              });
            });
            const playbackMixin = ctx.window.axonVoicePlaybackMixin();
            const commandMixin = ctx.window.axonVoiceCommandCenterMixin();
            const app = {
              settingsForm: {
                azure_speech_region: 'eastus',
                azure_voice: 'en-ZA-LeahNeural',
              },
              showVoiceOrb: true,
              voiceMode: true,
              reactorAsleep: false,
              voiceActive: false,
              agentMode: true,
              chatLoading: false,
              authHeaders(headers) { return headers; },
              azureSpeechConfigured() { return true; },
            };
            Object.assign(app, playbackMixin, commandMixin);
            const pending = app.speakMessage('Reply in progress');
            app.narrateAgentStep('plan', 'Planning the next step', 'Checking the workspace');
            app.stopSpeech();
            await pending;
            console.log(JSON.stringify({
              fetchCalls,
              queuedNarration: app._narrationQueue[0] || '',
            }));
            """,
        )

        self.assertEqual(payload["fetchCalls"], 1)
        self.assertEqual(payload["queuedNarration"], "Planning the next step.")

    def test_close_voice_command_center_stops_speech_and_clears_narration(self):
        payload = _run_voice_script(
            [VOICE_JS],
            """
            const mixin = ctx.window.axonVoiceMixin();
            const app = {
              showVoiceOrb: true,
              voiceActive: false,
              stopVoiceSurfaceDirector() { this.surfaceDirectorStopped = true; },
              closeVoiceConversationRuntime() { this.runtimeClosed = true; },
              _cancelNarrationQueue() { this.narrationCancelled = true; },
              clearVoiceAwaitingReply() { this.awaitingCleared = true; },
              stopSpeech() { this.speechStopped = true; },
            };
            Object.assign(app, mixin);
            app.closeVoiceCommandCenter(false);
            console.log(JSON.stringify({
              showVoiceOrb: app.showVoiceOrb,
              surfaceDirectorStopped: !!app.surfaceDirectorStopped,
              runtimeClosed: !!app.runtimeClosed,
              narrationCancelled: !!app.narrationCancelled,
              awaitingCleared: !!app.awaitingCleared,
              speechStopped: !!app.speechStopped,
            }));
            """,
        )

        self.assertFalse(payload["showVoiceOrb"])
        self.assertTrue(payload["surfaceDirectorStopped"])
        self.assertTrue(payload["runtimeClosed"])
        self.assertTrue(payload["narrationCancelled"])
        self.assertTrue(payload["awaitingCleared"])
        self.assertTrue(payload["speechStopped"])

    def test_voice_conversation_text_dock_submits_draft_command(self):
        payload = _run_voice_script(
            [VOICE_CONVERSATION_JS],
            """
            const mixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              voiceTranscript: '',
              chatInput: '',
              chatLoading: false,
              voiceConversation: {},
              syncVoiceTranscript(value) {
                this.synced = value;
                this.voiceTranscript = value;
                this.chatInput = value;
              },
              async sendVoiceCommand() {
                this.sent = this.voiceTranscript;
              },
            };
            Object.assign(app, mixin);
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = 'Run diagnostics for the active workspace';
            await app.submitVoiceTextDock();
            console.log(JSON.stringify({
              textDockOpen: app.voiceConversation.textDockOpen,
              synced: app.synced,
              sent: app.sent,
            }));
            """,
        )

        self.assertFalse(payload["textDockOpen"])
        self.assertEqual(payload["synced"], "Run diagnostics for the active workspace")
        self.assertEqual(payload["sent"], "Run diagnostics for the active workspace")

    def test_voice_conversation_marks_awaiting_reply_after_playback(self):
        payload = _run_voice_script(
            [VOICE_CONVERSATION_JS],
            """
            const mixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              reactorAsleep: false,
              chatLoading: false,
              voiceConversation: {},
              voiceInputAvailable() { return false; },
            };
            Object.assign(app, mixin);
            app.onVoiceReplyPlaybackComplete('Status report complete. Awaiting your next instruction.');
            console.log(JSON.stringify({
              awaitingReply: app.voiceConversation.awaitingReply,
              stateCaption: app.voiceConversationStateCaption(),
              preview: app.voiceConversation.lastReplyPreview,
            }));
            """,
        )

        self.assertTrue(payload["awaitingReply"])
        self.assertEqual(payload["stateCaption"], "Awaiting reply")
        self.assertIn("Status report complete", payload["preview"])

    def test_voice_conversation_surfaces_external_file_approval_copy(self):
        payload = _run_voice_script(
            [VOICE_CONVERSATION_JS],
            """
            const mixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              reactorAsleep: false,
              chatLoading: false,
              voiceConversation: {},
              terminal: { approvalRequired: false },
              currentPendingAgentApproval() {
                return {
                  action: {
                    action_type: 'file_read',
                    operation: 'read',
                    path: '/home/edp/Documents/demo.pdf',
                  },
                };
              },
              consoleProviderIdentity() { return { providerLabel: '' }; },
              hudShowApproval(detail) {
                this.hudDetail = detail;
                this.hudApprovalPending = true;
              },
              hudDismissApproval() {},
              hudHideBeam() {},
              hudShowBeam() {},
            };
            Object.assign(app, mixin);
            app.syncVoiceCommandCenterRuntime();
            console.log(JSON.stringify({
              label: app.voiceApprovalLabel(),
              summary: app.voiceApprovalSummary(),
              detail: app.hudDetail || '',
            }));
            """,
        )

        self.assertEqual(payload["label"], "Allow once")
        self.assertIn("outside the current workspace", payload["summary"])
        self.assertIn("/home/edp/Documents/demo.pdf", payload["detail"])

    def test_voice_conversation_syncs_terminal_overlay_from_live_terminal(self):
        payload = _run_voice_script(
            [VOICE_CONVERSATION_JS],
            """
            const mixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              reactorAsleep: false,
              chatLoading: true,
              voiceConversation: {},
              terminal: { approvalRequired: false },
              dashboardLiveTerminalSession() {
                return { title: 'Workspace Terminal', running: true, status: 'running', active_command: 'npm test' };
              },
              dashboardLiveTerminalDetail() {
                return {
                  recent_events: [
                    { event_type: 'command', content: 'npm test' },
                    { event_type: 'output', content: 'Ran 32 tests' },
                    { event_type: 'status', content: 'completed' },
                  ],
                };
              },
              consoleProviderIdentity() { return { providerLabel: 'CLI Agent' }; },
              hudShowTerminal(title, lines) {
                this.hudTitle = title;
                this.hudLines = lines;
                this.hudTerminalVisible = true;
              },
              hudHideBeam() {},
              hudShowBeam(label) { this.beam = label; },
            };
            Object.assign(app, mixin);
            app.syncVoiceCommandCenterRuntime();
            console.log(JSON.stringify({
              hudTerminalVisible: app.hudTerminalVisible,
              hudTitle: app.hudTitle,
              hudLines: app.hudLines,
              beam: app.beam,
            }));
            """,
        )

        self.assertTrue(payload["hudTerminalVisible"])
        self.assertIn("Workspace Terminal", payload["hudTitle"])
        self.assertEqual(payload["hudLines"][0], "$ npm test")
        self.assertIn("Ran 32 tests", payload["hudLines"][1])
        self.assertEqual(payload["beam"], "CLI Agent")

    def test_voice_conversation_uses_operator_trace_when_no_terminal_session_exists(self):
        payload = _run_voice_script(
            [VOICE_CONVERSATION_JS],
            """
            const mixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              reactorAsleep: false,
              chatLoading: true,
              liveOperator: { active: true, title: 'Running Shell Cmd' },
              hudOperatorTraceTitle: 'Shell Cmd telemetry',
              hudOperatorTraceLines: ['$ npm run build', '@ /tmp/mobile'],
              voiceConversation: {},
              terminal: { approvalRequired: false },
              consoleProviderIdentity() { return { providerLabel: '' }; },
              hudShowTerminal(title, lines) {
                this.hudTitle = title;
                this.hudLines = lines;
                this.hudTerminalVisible = true;
              },
              hudHideBeam() {},
              hudShowBeam() {},
            };
            Object.assign(app, mixin);
            app.syncVoiceCommandCenterRuntime();
            console.log(JSON.stringify({
              hudTerminalVisible: !!app.hudTerminalVisible,
              hudTitle: app.hudTitle || '',
              hudLines: app.hudLines || [],
            }));
            """,
        )

        self.assertTrue(payload["hudTerminalVisible"])
        self.assertEqual(payload["hudTitle"], "Shell Cmd telemetry")
        self.assertEqual(payload["hudLines"][0], "$ npm run build")
        self.assertEqual(payload["hudLines"][1], "@ /tmp/mobile")

    def test_voice_hud_records_shell_command_trace_from_agent_events(self):
        payload = _run_voice_script(
            [VOICE_HUD_JS],
            """
            const mixin = ctx.window.axonVoiceHudMixin();
            const app = { showVoiceOrb: true };
            Object.assign(app, mixin);
            app.hudProcessAgentEvent({
              type: 'tool_call',
              name: 'shell_cmd',
              args: { cmd: 'npm run build', cwd: '/tmp/mobile' },
            });
            app.hudProcessAgentEvent({
              type: 'tool_result',
              name: 'shell_cmd',
              result: '[axon] build passed',
            });
            console.log(JSON.stringify({
              title: app.hudOperatorTraceTitle,
              lines: app.hudOperatorTraceLines,
              badges: app.hudActiveTools.map((item) => item.name),
            }));
            """,
        )

        self.assertEqual(payload["title"], "Shell Cmd telemetry")
        self.assertEqual(payload["lines"][0], "$ npm run build")
        self.assertEqual(payload["lines"][1], "@ /tmp/mobile")
        self.assertEqual(payload["lines"][2], "# [axon] build passed")
        self.assertIn("terminal", payload["badges"])

    def test_voice_command_center_renders_live_operator_story_with_draft_reply(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS, VOICE_CONVERSATION_JS],
            """
            const commandMixin = ctx.window.axonVoiceCommandCenterMixin();
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              chatLoading: true,
              liveOperator: { active: true, phase: 'execute', updatedAt: '2026-04-06T20:20:00Z' },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Inspecting the task', detail: 'Reviewing the mobile companion app.', at: '2026-04-06T20:19:30Z' },
                { id: '2', phase: 'execute', title: 'Running Shell Cmd', detail: '{"cmd":"npm run build","cwd":"/tmp/mobile"}', at: '2026-04-06T20:20:00Z' },
              ],
              chatMessages: [{
                id: 10,
                role: 'assistant',
                content: 'Preparing the deployment report now.',
              }],
              voiceConversation: {},
              timeAgo(value) { return value === '2026-04-06T20:20:00Z' ? 'just now' : '1m ago'; },
              renderMd(value) { return '<p>' + String(value || '') + '</p>'; },
            };
            Object.assign(app, commandMixin, conversationMixin);
            const html = app.voiceDisplayResponseHtml();
            console.log(JSON.stringify({ html }));
            """,
        )

        self.assertIn("Live execution", payload["html"])
        self.assertIn("Running Shell Cmd", payload["html"])
        self.assertIn("Draft reply", payload["html"])
        self.assertIn("2 steps", payload["html"])

    def test_voice_response_stays_active_for_operator_deck_without_reply_text(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS, ROOT / "ui/js/voice-operator-deck.js"],
            """
            const commandMixin = ctx.window.axonVoiceCommandCenterMixin();
            const deckMixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: false,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Running Shell Cmd',
                detail: 'Axon is checking the active workspace.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Inspecting task', detail: 'Goal received: Check the deck', at: '2026-04-08T09:00:00Z' },
              ],
              chatMessages: [{
                id: 10,
                role: 'assistant',
                content: '',
              }],
              voiceConversation: {},
              latestAssistantMessage() {
                return this.chatMessages[this.chatMessages.length - 1];
              },
            };
            Object.assign(app, commandMixin, deckMixin);
            console.log(JSON.stringify({
              responseAvailable: app.voiceResponseAvailable(),
              renderClass: app.voiceResponseRenderClass(),
              htmlHasDeck: app.voiceDisplayResponseHtml().includes('voice-operator-deck'),
            }));
            """,
        )

        self.assertTrue(payload["responseAvailable"])
        self.assertEqual(payload["renderClass"], "")
        self.assertTrue(payload["htmlHasDeck"])

    def test_voice_task_surface_holds_last_operator_deck_during_brief_idle_gap(self):
        payload = _run_voice_script(
            [VOICE_COMMAND_CENTER_JS, ROOT / "ui/js/voice-operator-deck.js"],
            """
            const commandMixin = ctx.window.axonVoiceCommandCenterMixin();
            const deckMixin = ctx.window.axonVoiceOperatorDeckMixin();
            const app = {
              chatLoading: false,
              liveOperator: {
                active: true,
                phase: 'execute',
                title: 'Searching files',
                detail: 'Axon is walking the workspace.',
              },
              liveOperatorFeed: [
                { id: '1', phase: 'observe', title: 'Inspecting task', detail: 'Goal received: Find the latest files', at: '2026-04-08T09:00:00Z' },
              ],
              chatMessages: [{ id: 10, role: 'assistant', content: '' }],
              voiceConversation: {},
              latestAssistantMessage() {
                return this.chatMessages[this.chatMessages.length - 1];
              },
            };
            Object.assign(app, commandMixin, deckMixin);
            const first = app.voiceDisplayResponseHtml();
            app.liveOperator = { active: false, phase: '', title: '', detail: '' };
            app.liveOperatorFeed = [];
            const second = app.voiceDisplayResponseHtml();
            console.log(JSON.stringify({
              firstHasDeck: first.includes('voice-operator-deck'),
              secondHasDeck: second.includes('voice-operator-deck'),
            }));
            """,
        )

        self.assertTrue(payload["firstHasDeck"])
        self.assertTrue(payload["secondHasDeck"])


if __name__ == "__main__":
    unittest.main()
