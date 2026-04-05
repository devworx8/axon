from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "ui/index.html"
VOICE_SPEECH_JS = ROOT / "ui/js/voice-speech.js"
VOICE_PLAYBACK_JS = ROOT / "ui/js/voice-playback.js"
VOICE_COMMAND_CENTER_JS = ROOT / "ui/js/voice-command-center.js"


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
            const clean = ctx.window.axonVoiceSpeech.cleanText('```js\\nconst route = "/api/health";\\nreturn route;\\n```\\n\\nUse `npm run dev` next.');
            console.log(JSON.stringify({
              clean,
              mentionsCodeBlock: clean.includes('js code block'),
              mentionsRoute: clean.includes('slash api slash health'),
              mentionsInlineCode: clean.includes('inline code npm'),
              mentionsCodeEnd: clean.includes('End code block'),
            }));
            """,
        )

        self.assertTrue(payload["mentionsCodeBlock"])
        self.assertTrue(payload["mentionsRoute"])
        self.assertTrue(payload["mentionsInlineCode"])
        self.assertTrue(payload["mentionsCodeEnd"])

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
        self.assertTrue(all(abs(rate - 0.92) < 0.001 for rate in payload["utteranceRates"]))
        self.assertEqual(payload["toast"], "")


if __name__ == "__main__":
    unittest.main()
