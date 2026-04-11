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
VOICE_CONVERSATION_CSS = ROOT / "ui/css/voice-conversation.css"
VOICE_REACTOR_CSS = ROOT / "ui/css/voice-reactor.css"
VOICE_COMMAND_DOCK_PARTIAL = ROOT / "ui/partials/voice_command_dock.html"
VOICE_PARTIAL = ROOT / "ui/partials/voice.html"


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
              imageAttachments: [{ id: 'img-1', name: 'sample.png' }],
              voiceConversation: {},
              liveOperator: { detail: '' },
              chatMessages: [],
              resetChatComposerHeight() {},
              currentWorkspaceRunActive() { return false; },
              clearImageAttachments() {
                this.attachmentsCleared = true;
                this.imageAttachments = [];
              },
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
              textDraft: app.voiceConversation.textDraft,
              attachmentsCleared: app.attachmentsCleared === true,
              imageCount: (app.imageAttachments || []).length,
            }));
            """
        )

        self.assertFalse(payload["dockOpen"])
        self.assertEqual(payload["lastCommand"], "Check the git status of .devbrain")
        self.assertEqual(payload["sentChatInput"], "Check the git status of .devbrain")
        self.assertEqual(payload["voiceTranscript"], "")
        self.assertEqual(payload["textDraft"], "")
        self.assertTrue(payload["attachmentsCleared"])
        self.assertEqual(payload["imageCount"], 0)

    def test_text_dock_can_submit_with_images_only(self):
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
              imageAttachments: [{ id: 'img-1', name: 'capture.png', size: 2048 }],
              voiceConversation: {},
              resetChatComposerHeight() {},
              currentWorkspaceRunActive() { return false; },
              clearImageAttachments() {
                this.attachmentsCleared = true;
                this.imageAttachments = [];
              },
              async sendChat() { this.sentChatInput = this.chatInput; return true; },
            };
            Object.assign(app, voiceMixin, commandCenterMixin, conversationMixin);
            app.toggleVoiceTextDock(true);
            const submitted = await app.submitVoiceTextDock();
            console.log(JSON.stringify({
              submitted,
              sentChatInput: app.sentChatInput,
              attachmentsCleared: app.attachmentsCleared === true,
              dockOpen: app.voiceConversation.textDockOpen,
            }));
            """
        )

        self.assertTrue(payload["submitted"])
        self.assertEqual(payload["sentChatInput"], "Review the attached image and tell me what matters.")
        self.assertTrue(payload["attachmentsCleared"])
        self.assertFalse(payload["dockOpen"])

    def test_text_dock_enter_shortcut_submits_without_shift(self):
        payload = _run_voice_dock_script(
            """
            const voiceMixin = ctx.window.axonVoiceMixin();
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              voiceTranscript: '',
              chatInput: '',
              chatLoading: false,
              voiceActive: false,
              voiceConversation: {},
              $refs: {
                voiceTextDockInput: {
                  selectionStart: 0,
                  selectionEnd: 0,
                  focus() {},
                  setSelectionRange(start, end) {
                    this.selectionStart = start;
                    this.selectionEnd = end;
                  },
                },
              },
              resetChatComposerHeight() {},
              currentWorkspaceRunActive() { return false; },
              async sendVoiceCommand(value) { this.sent = value; },
            };
            Object.assign(app, voiceMixin, conversationMixin);
            app.sendVoiceCommand = async (value) => { app.sent = value; };
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = 'Run a project status check';
            const enterEvent = {
              key: 'Enter',
              shiftKey: false,
              altKey: false,
              ctrlKey: false,
              metaKey: false,
              preventDefault() { this.prevented = true; },
            };
            await app.handleVoiceTextDockKeydown(enterEvent);
            console.log(JSON.stringify({
              prevented: enterEvent.prevented === true,
              sent: app.sent,
              dockOpen: app.voiceConversation.textDockOpen,
            }));
            """
        )

        self.assertTrue(payload["prevented"])
        self.assertEqual(payload["sent"], "Run a project status check")
        self.assertFalse(payload["dockOpen"])

    def test_text_dock_history_reuses_shared_composer_history(self):
        payload = _run_voice_dock_script(
            """
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const input = {
              selectionStart: 0,
              selectionEnd: 0,
              focus() {},
              setSelectionRange(start, end) {
                this.selectionStart = start;
                this.selectionEnd = end;
              },
            };
            const app = {
              showVoiceOrb: true,
              voiceConversation: {},
              _composerHistory: ['first task', 'second task'],
              $refs: { voiceTextDockInput: input },
            };
            Object.assign(app, conversationMixin);
            app.toggleVoiceTextDock(true);
            const event = {
              key: 'ArrowUp',
              preventDefault() { this.prevented = true; },
            };
            app.handleVoiceTextDockKeydown(event);
            const firstRecall = app.voiceConversation.textDraft;
            input.selectionStart = firstRecall.length;
            input.selectionEnd = firstRecall.length;
            app.handleVoiceTextDockKeydown(event);
            const secondRecall = app.voiceConversation.textDraft;
            const downEvent = {
              key: 'ArrowDown',
              preventDefault() { this.prevented = true; },
            };
            input.selectionStart = secondRecall.length;
            input.selectionEnd = secondRecall.length;
            app.handleVoiceTextDockKeydown(downEvent);
            console.log(JSON.stringify({
              upPrevented: event.prevented === true,
              downPrevented: downEvent.prevented === true,
              firstRecall,
              secondRecall,
              downRecall: app.voiceConversation.textDraft,
            }));
            """
        )

        self.assertTrue(payload["upPrevented"])
        self.assertTrue(payload["downPrevented"])
        self.assertEqual(payload["firstRecall"], "second task")
        self.assertEqual(payload["secondRecall"], "first task")
        self.assertEqual(payload["downRecall"], "second task")

    def test_text_dock_submit_clears_immediately_once_chat_handoff_begins(self):
        payload = _run_voice_dock_script(
            """
            const voiceMixin = ctx.window.axonVoiceMixin();
            const commandCenterMixin = ctx.window.axonVoiceCommandCenterMixin();
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            let releaseSendChat = null;
            const app = {
              showVoiceOrb: true,
              voiceTranscript: '',
              chatInput: '',
              chatLoading: false,
              voiceActive: false,
              imageAttachments: [{ id: 'img-1', name: 'capture.png' }],
              voiceConversation: {},
              resetChatComposerHeight() {},
              currentWorkspaceRunActive() { return false; },
              clearImageAttachments() {
                this.attachmentsCleared = true;
                this.imageAttachments = [];
              },
              sendChat() {
                this.sendChatStarted = true;
                return new Promise((resolve) => {
                  releaseSendChat = resolve;
                });
              },
            };
            Object.assign(app, voiceMixin, commandCenterMixin, conversationMixin);
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = 'Ship the PWA composer refresh';
            let pendingResolved = false;
            const pending = app.submitVoiceTextDock().then((value) => {
              pendingResolved = value;
              return value;
            });
            await new Promise((resolve) => setTimeout(resolve, 0));
            const snapshot = {
              pendingResolved,
              sendChatStarted: app.sendChatStarted === true,
              textDraft: app.voiceConversation.textDraft,
              dockOpen: app.voiceConversation.textDockOpen,
              voiceTranscript: app.voiceTranscript,
              attachmentsCleared: app.attachmentsCleared === true,
              imageCount: (app.imageAttachments || []).length,
            };
            releaseSendChat?.(true);
            await pending;
            console.log(JSON.stringify(snapshot));
            """
        )

        self.assertTrue(payload["pendingResolved"])
        self.assertTrue(payload["sendChatStarted"])
        self.assertEqual(payload["textDraft"], "")
        self.assertFalse(payload["dockOpen"])
        self.assertEqual(payload["voiceTranscript"], "")
        self.assertTrue(payload["attachmentsCleared"])
        self.assertEqual(payload["imageCount"], 0)

    def test_text_dock_slash_autocomplete_prefers_known_commands(self):
        payload = _run_voice_dock_script(
            """
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              voiceConversation: {},
            };
            Object.assign(app, conversationMixin);
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = '/de';
            const matches = app.voiceTextDockSlashMatches();
            app.voiceTextDockAutocomplete();
            console.log(JSON.stringify({
              firstMatch: matches[0]?.command || '',
              autocompleted: app.voiceConversation.textDraft,
              shortcutHint: app.voiceTextDockShortcutHint(),
            }));
            """
        )

        self.assertEqual(payload["firstMatch"], "/deploy")
        self.assertEqual(payload["autocompleted"], "/deploy")
        self.assertIn("Enter send", payload["shortcutHint"])

    def test_text_dock_preview_clips_long_drafts_but_keeps_full_submission(self):
        payload = _run_voice_dock_script(
            """
            const conversationMixin = ctx.window.axonVoiceConversationMixin();
            const app = {
              showVoiceOrb: true,
              voiceConversation: {},
            };
            Object.assign(app, conversationMixin);
            app.toggleVoiceTextDock(true);
            app.voiceConversation.textDraft = 'A'.repeat(1450) + '\\nTAIL-MARKER-DO-NOT-SHOW';
            const html = app.voiceTextDockPreviewHtml();
            console.log(JSON.stringify({
              html,
              submissionEndsWithMarker: app.voiceTextDockSubmissionText().endsWith('TAIL-MARKER-DO-NOT-SHOW'),
            }));
            """
        )

        self.assertIn("Preview clipped while you type. Axon still receives the full draft.", payload["html"])
        self.assertNotIn("TAIL-MARKER-DO-NOT-SHOW", payload["html"])
        self.assertTrue(payload["submissionEndsWithMarker"])

    def test_text_dock_partial_uses_native_mobile_image_inputs(self):
        template = VOICE_COMMAND_DOCK_PARTIAL.read_text(encoding="utf-8")

        self.assertIn('type="file"', template)
        self.assertIn('capture="environment"', template)
        self.assertIn('@change="handleImageFileInput($event)"', template)
        self.assertIn('Photo library', template)
        self.assertIn('Camera', template)
        self.assertIn('voice-command-dock__body', template)
        self.assertIn('voiceTextDockPreviewHtml()', template)

    def test_desktop_text_dock_css_bounds_panel_preview_and_input(self):
        stylesheet = VOICE_CONVERSATION_CSS.read_text(encoding="utf-8")

        self.assertIn("max-height: calc(100dvh - 48px);", stylesheet)
        self.assertIn("max-height: min(44rem, calc(100dvh - 48px));", stylesheet)
        self.assertIn(".voice-command-dock__body {", stylesheet)
        self.assertIn("flex: 1 1 auto;", stylesheet)
        self.assertIn("overflow-y: auto;", stylesheet)
        self.assertIn("max-height: min(40dvh, 20rem);", stylesheet)
        self.assertIn("resize: none;", stylesheet)
        self.assertIn("position: relative;", stylesheet)
        self.assertIn("display: flex;", stylesheet)
        self.assertIn("max-height: min(28dvh, 14rem);", stylesheet)
        self.assertIn("overflow: hidden;", stylesheet)

    def test_mobile_text_dock_css_reserves_safe_area_and_scrolls(self):
        stylesheet = VOICE_CONVERSATION_CSS.read_text(encoding="utf-8")
        reactor_stylesheet = VOICE_REACTOR_CSS.read_text(encoding="utf-8")
        voice_partial = VOICE_PARTIAL.read_text(encoding="utf-8")

        self.assertIn("top: var(--voice-mobile-dock-top-clearance);", stylesheet)
        self.assertIn("bottom: var(--voice-mobile-bottom-clearance);", stylesheet)
        self.assertIn("justify-content: flex-end;", stylesheet)
        self.assertIn("transform: none;", stylesheet)
        self.assertIn("max-height: calc(100dvh - var(--voice-mobile-dock-top-clearance) - var(--voice-mobile-bottom-clearance));", stylesheet)
        self.assertIn("overflow: hidden;", stylesheet)
        self.assertIn("overflow-y: auto;", stylesheet)
        self.assertIn("overscroll-behavior: contain;", stylesheet)
        self.assertIn(".voice-command-dock__preview", stylesheet)
        self.assertIn("--voice-mobile-safe-top: env(safe-area-inset-top, 0px);", reactor_stylesheet)
        self.assertIn("--voice-mobile-top-clearance: calc(var(--voice-mobile-safe-top) + 88px);", reactor_stylesheet)
        self.assertIn("--voice-mobile-dock-top-clearance: calc(var(--voice-mobile-top-clearance) + 24px);", reactor_stylesheet)
        self.assertIn("padding-top: var(--voice-mobile-top-clearance);", reactor_stylesheet)
        self.assertIn("padding-top: calc(var(--voice-mobile-safe-top) + 18px);", reactor_stylesheet)
        self.assertIn('class="voice-command-center__close absolute', voice_partial)


if __name__ == "__main__":
    unittest.main()
