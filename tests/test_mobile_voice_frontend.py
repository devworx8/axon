from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_JS = ROOT / "ui/js/voice.js"
VOICE_COMMAND_CENTER_JS = ROOT / "ui/js/voice-command-center.js"
CHAT_WORKSPACE_MODES_JS = ROOT / "ui/js/chat-workspace-modes.js"
MOBILE_JS = ROOT / "ui/js/mobile.js"


def _run_mobile_voice_script(files: list[Path], body: str):
    load_modules = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(path))}, 'utf8'), ctx);"
        for path in files
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const nav = {{
          style: {{ display: '' }},
          hidden: false,
          attrs: {{}},
          setAttribute(name, value) {{ this.attrs[name] = value; }},
        }};
        const fetchCalls = [];
        const micTracks = [{{ stopped: false, stop() {{ this.stopped = true; }} }}];
        const documentClasses = new Set();
        const bodyClasses = new Set();

        class FakeMediaRecorder {{
          constructor(stream, options = {{}}) {{
            this.stream = stream;
            this.mimeType = options.mimeType || 'audio/webm';
            this.ondataavailable = null;
            this.onstop = null;
            this.onerror = null;
          }}
          start() {{
            this.started = true;
          }}
          stop() {{
            if (typeof this.ondataavailable === 'function') {{
              this.ondataavailable({{ data: new Blob(['voice']) }});
            }}
            setTimeout(() => {{
              if (typeof this.onstop === 'function') this.onstop();
            }}, 0);
          }}
          static isTypeSupported(type) {{
            return String(type || '').includes('webm');
          }}
        }}

        const ctx = {{
          window: {{
            MediaRecorder: FakeMediaRecorder,
            matchMedia: () => ({{ matches: true }}),
            navigator: {{ standalone: false }},
            addEventListener() {{}},
            removeEventListener() {{}},
          }},
          navigator: {{
            mediaDevices: {{
              async getUserMedia() {{
                return {{
                  getTracks() {{
                    return micTracks;
                  }},
                }};
              }},
            }},
          }},
          document: {{
            documentElement: {{
              classList: {{
                toggle(name, active) {{ if (active) documentClasses.add(name); else documentClasses.delete(name); }},
              }},
            }},
            body: {{
              classList: {{
                toggle(name, active) {{ if (active) bodyClasses.add(name); else bodyClasses.delete(name); }},
              }},
            }},
            head: {{ appendChild() {{}} }},
            getElementById() {{ return null; }},
            createElement() {{ return {{ id: '', textContent: '' }}; }},
            querySelector(selector) {{
              if (selector === 'nav[aria-label="Main navigation"]') return nav;
              return null;
            }},
          }},
          location: {{ hostname: 'localhost' }},
          fetch: async (url, init = {{}}) => {{
            fetchCalls.push({{ url, headers: init.headers || {{}}, method: init.method || 'GET' }});
            return {{
              ok: true,
              status: 200,
              async json() {{
                return {{ text: 'deploy the mobile app', engine: 'azure-stt' }};
              }},
            }};
          }},
          Blob,
          FormData,
          console,
          setTimeout,
          clearTimeout,
          requestAnimationFrame: (cb) => setTimeout(cb, 0),
        }};
        ctx.window.window = ctx.window;
        ctx.window.navigator = ctx.navigator;
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


class MobileVoiceFrontendTests(unittest.TestCase):
    def test_mobile_open_voice_command_center_defaults_to_agent_mode(self):
      payload = _run_mobile_voice_script(
          [VOICE_JS, CHAT_WORKSPACE_MODES_JS, MOBILE_JS],
          """
          const voiceMixin = ctx.window.axonVoiceMixin();
          const workspaceMixin = ctx.window.axonChatWorkspaceModesMixin();
          const mobileMixin = ctx.window.axonMobileMixin();
          const app = {
            showVoiceOrb: false,
            isMobile: true,
            agentMode: false,
            businessMode: false,
            chatLoading: false,
            liveOperator: { active: false },
            chatInput: '',
            voiceTranscript: '',
            composerOptions: { intelligence_mode: 'ask', action_mode: '', agent_role: '' },
            settingsForm: { ai_backend: 'cli', azure_speech_key: '', _azureSpeechKeyHint: '' },
            runtimeStatus: { backend: 'cli', cli_model: 'gpt-5.4' },
            voiceConversation: {},
            currentBackendSupportsAgent() { return true; },
            switchTab(tab) { this.tab = tab; },
            ensureVoiceConversationState() {},
            initVoiceSurfaceDirector() {},
            syncVoiceCommandCenterRuntime() {},
            syncVoiceSurfaceDirector() {},
            async loadVoiceStatus() { return this.voiceStatus || {}; },
          };
          Object.assign(app, workspaceMixin, voiceMixin, mobileMixin);
          app.openVoiceCommandCenter();
          await new Promise(resolve => setTimeout(resolve, 0));
          console.log(JSON.stringify({
            tab: app.tab,
            showVoiceOrb: app.showVoiceOrb,
            agentMode: app.agentMode,
            mode: app.activePrimaryConversationMode(),
          }));
          """,
      )

      self.assertEqual(payload["tab"], "chat")
      self.assertTrue(payload["showVoiceOrb"])
      self.assertTrue(payload["agentMode"])
      self.assertEqual(payload["mode"], "agent")

    def test_mobile_refresh_voice_capability_promotes_agent_mode_while_voice_shell_is_open(self):
      payload = _run_mobile_voice_script(
          [VOICE_JS, CHAT_WORKSPACE_MODES_JS, MOBILE_JS],
          """
          const voiceMixin = ctx.window.axonVoiceMixin();
          const workspaceMixin = ctx.window.axonChatWorkspaceModesMixin();
          const mobileMixin = ctx.window.axonMobileMixin();
          const app = {
            showVoiceOrb: true,
            isMobile: true,
            agentMode: false,
            businessMode: false,
            composerOptions: { intelligence_mode: 'ask', action_mode: '', agent_role: '' },
            settingsForm: { ai_backend: 'cli', azure_speech_key: '', _azureSpeechKeyHint: '' },
            runtimeStatus: { backend: 'cli', cli_model: 'gpt-5.4' },
            voiceStatus: { transcription_ready: true },
            currentBackendSupportsAgent() { return true; },
          };
          Object.assign(app, workspaceMixin, voiceMixin, mobileMixin);
          app.refreshVoiceCapability();
          console.log(JSON.stringify({
            speechInputSupported: app.speechInputSupported,
            agentMode: app.agentMode,
            mode: app.activePrimaryConversationMode(),
          }));
          """,
      )

      self.assertTrue(payload["agentMode"])
      self.assertEqual(payload["mode"], "agent")

    def test_mobile_close_voice_command_center_stops_speech_and_clears_runtime(self):
      payload = _run_mobile_voice_script(
          [MOBILE_JS],
          """
          const mobileMixin = ctx.window.axonMobileMixin();
          const app = {
            showVoiceOrb: true,
            isMobile: true,
            voiceActive: false,
            stopVoiceSurfaceDirector() { this.surfaceDirectorStopped = true; },
            syncMobileVoiceChrome() { this.chromeSyncs = (this.chromeSyncs || 0) + 1; },
            closeVoiceConversationRuntime() { this.runtimeClosed = true; },
            _cancelNarrationQueue() { this.narrationCancelled = true; },
            clearVoiceAwaitingReply() { this.awaitingCleared = true; },
            stopSpeech() { this.speechStopped = true; },
          };
          Object.assign(app, mobileMixin);
          app.closeVoiceCommandCenter(false);
          await new Promise(resolve => setTimeout(resolve, 0));
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

    def test_busy_open_skips_boot_sound_and_keeps_resume_flow(self):
      payload = _run_mobile_voice_script(
          [VOICE_COMMAND_CENTER_JS, MOBILE_JS],
          """
          let bootCount = 0;
          ctx.window.axonVoiceBootSound = { play() { bootCount += 1; } };
          const commandMixin = ctx.window.axonVoiceCommandCenterMixin();
          const mobileMixin = ctx.window.axonMobileMixin();
          const app = {
            chatLoading: true,
            liveOperator: { active: true, title: 'Inspecting the task', detail: 'Retrying the Android build.' },
            voiceConversation: {},
            showVoiceOrb: false,
            isMobile: true,
            showMoreMenu: true,
            switchTab(tab) { this.tab = tab; },
            ensureVoiceConversationState() {},
            async loadVoiceStatus() { this.loadedVoiceStatus = true; },
            syncVoiceCommandCenterRuntime() { this.syncedRuntime = true; },
          };
          Object.assign(app, commandMixin, mobileMixin);
          app.openVoiceCommandCenter();
          await new Promise(resolve => setTimeout(resolve, 0));
          console.log(JSON.stringify({
            bootCount,
            showVoiceOrb: app.showVoiceOrb,
            tab: app.tab,
            syncedRuntime: !!app.syncedRuntime,
            navHidden: nav.style.display,
            navHiddenAttr: nav.hidden,
            moreMenuOpen: app.showMoreMenu,
            shellClassActive: documentClasses.has('axon-mobile-voice-shell'),
          }));
          """,
      )

      self.assertEqual(payload["bootCount"], 0)
      self.assertTrue(payload["showVoiceOrb"])
      self.assertEqual(payload["tab"], "chat")
      self.assertTrue(payload["syncedRuntime"])
      self.assertEqual(payload["navHidden"], "none")
      self.assertTrue(payload["navHiddenAttr"])
      self.assertFalse(payload["moreMenuOpen"])
      self.assertTrue(payload["shellClassActive"])

    def test_mobile_voice_chrome_restores_nav_when_voice_overlay_closes(self):
      payload = _run_mobile_voice_script(
          [MOBILE_JS],
          """
          const mixin = ctx.window.axonMobileMixin();
          const app = { showVoiceOrb: true, isMobile: true, showMoreMenu: true };
          Object.assign(app, mixin);
          app.syncMobileVoiceChrome();
          app.showVoiceOrb = false;
          app.syncMobileVoiceChrome();
          console.log(JSON.stringify({
            navDisplay: nav.style.display,
            moreMenuOpen: app.showMoreMenu,
          }));
          """,
      )

      self.assertEqual(payload["navDisplay"], "")
      self.assertFalse(payload["moreMenuOpen"])

    def test_mobile_recorder_fallback_transcribes_on_stop(self):
      payload = _run_mobile_voice_script(
          [MOBILE_JS],
          """
          const mixin = ctx.window.axonMobileMixin();
          const app = {
            isMobile: true,
            voiceStatus: { transcription_ready: true, detail: 'Cloud transcription ready.' },
            settingsForm: { azure_speech_key: '', _azureSpeechKeyHint: '', azure_voice: 'en-GB-RyanNeural' },
            voiceConversation: {},
            voiceTranscript: '',
            chatInput: '',
            authHeaders(extra = {}) { return { ...extra, 'X-Axon-Token': 'token-1' }; },
            async loadVoiceStatus() { return this.voiceStatus; },
            speechLocale() { return 'en-US'; },
            azureSpeechConfigured() { return false; },
            voiceOutputAvailable() { return false; },
            syncVoiceTranscript(value) {
              this.voiceTranscript = value;
              this.chatInput = value;
            },
            showToast(message) { this.toast = message; },
          };
          Object.assign(app, mixin);
          app.refreshVoiceCapability();
          await app.startVoice();
          const activeWhileRecording = app.voiceActive;
          await app.startVoice();
          console.log(JSON.stringify({
            speechInputSupported: app.speechInputSupported,
            activeWhileRecording,
            activeAfterStop: app.voiceActive,
            transcript: app.voiceTranscript,
            toast: app.toast || '',
            fetchUrl: fetchCalls[0]?.url || '',
            authHeader: fetchCalls[0]?.headers?.['X-Axon-Token'] || '',
            trackStopped: micTracks[0].stopped,
          }));
          """,
      )

      self.assertTrue(payload["speechInputSupported"])
      self.assertTrue(payload["activeWhileRecording"])
      self.assertFalse(payload["activeAfterStop"])
      self.assertEqual(payload["transcript"], "deploy the mobile app")
      self.assertEqual(payload["toast"], "")
      self.assertIn("/api/voice/transcribe?language=en-US", payload["fetchUrl"])
      self.assertEqual(payload["authHeader"], "token-1")
      self.assertTrue(payload["trackStopped"])

    def test_mobile_recorder_fallback_routes_transcript_through_capture_handler(self):
      payload = _run_mobile_voice_script(
          [MOBILE_JS],
          """
          const mixin = ctx.window.axonMobileMixin();
          const app = {
            isMobile: true,
            voiceStatus: { transcription_ready: true, detail: 'Cloud transcription ready.' },
            settingsForm: { azure_speech_key: '', _azureSpeechKeyHint: '', azure_voice: 'en-GB-RyanNeural' },
            voiceConversation: {},
            voiceTranscript: '',
            chatInput: '',
            authHeaders(extra = {}) { return { ...extra, 'X-Axon-Token': 'token-1' }; },
            async loadVoiceStatus() { return this.voiceStatus; },
            speechLocale() { return 'en-US'; },
            azureSpeechConfigured() { return false; },
            voiceOutputAvailable() { return false; },
            handled: [],
            handleVoiceCaptureTranscript(value, options = {}) {
              this.handled.push({ value, final: !!options.final, source: options.source || '' });
              return true;
            },
            syncVoiceTranscript(value) {
              this.voiceTranscript = value;
              this.chatInput = value;
            },
            showToast(message) { this.toast = message; },
          };
          Object.assign(app, mixin);
          app.refreshVoiceCapability();
          await app.startVoice();
          await app.startVoice();
          console.log(JSON.stringify({
            transcript: app.voiceTranscript,
            handled: app.handled,
            toast: app.toast || '',
          }));
          """,
      )

      self.assertEqual(payload["transcript"], "")
      self.assertEqual(payload["handled"][0]["value"], "deploy the mobile app")
      self.assertTrue(payload["handled"][0]["final"])
      self.assertEqual(payload["handled"][0]["source"], "recorded")
      self.assertEqual(payload["toast"], "")

    def test_resume_greeting_mentions_active_task(self):
      payload = _run_mobile_voice_script(
          [VOICE_COMMAND_CENTER_JS],
          """
          const mixin = ctx.window.axonVoiceCommandCenterMixin();
          const app = {
            chatLoading: true,
            liveOperator: { active: true, title: 'Inspecting the task', detail: 'Retrying the Android build now.' },
            currentWorkspaceRunActive() { return true; },
            voiceOperatorHeadline() { return 'Inspecting the task'; },
            voiceOperatorNextStep() { return 'Retrying the Android build now.'; },
            voiceConversation: {},
          };
          Object.assign(app, mixin);
          console.log(JSON.stringify({ greeting: app._pickBootGreeting() }));
          """,
      )

      self.assertIn("Resuming the active task", payload["greeting"])
      self.assertIn("Inspecting the task", payload["greeting"])
      self.assertIn("Retrying the Android build now", payload["greeting"])


if __name__ == "__main__":
    unittest.main()
