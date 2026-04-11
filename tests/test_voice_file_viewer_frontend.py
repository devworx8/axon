from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_FILE_VIEWER_JS = ROOT / "ui/js/voice-file-viewer.js"


def _run_voice_file_viewer_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const documentListeners = {{}};
        const ctx = {{
          window: {{ addEventListener() {{}} }},
          console,
          document: {{
            addEventListener(type, handler) {{ documentListeners[type] = handler; }},
            getElementById() {{ return null; }},
          }},
          documentListeners,
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_FILE_VIEWER_JS))}, 'utf8'), ctx);
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


class VoiceFileViewerFrontendTests(unittest.TestCase):
    def test_reset_voice_file_reveal_state_closes_auto_opened_viewer_for_new_run(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            ctx.fetch = async () => ({
              ok: true,
              json: async () => ({ content: 'artifact rail' }),
            });
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/js/voice-activity-feed.js', 'code', { auto: true });
            app.voiceFileReveal.queue = [{ path: '/tmp/stale', kind: 'folder' }];
            app.voiceFileReveal.active = true;
            app.resetVoiceFileRevealState({ closeViewer: true });
            console.log(JSON.stringify({
              open: app.voiceFileViewer.open,
              path: app.voiceFileViewer.path,
              autoOpened: app.voiceFileViewer.autoOpened,
              queueLength: app.voiceFileReveal.queue.length,
              active: app.voiceFileReveal.active,
            }));
            """
        )

        self.assertFalse(payload["open"])
        self.assertEqual(payload["path"], "")
        self.assertFalse(payload["autoOpened"])
        self.assertEqual(payload["queueLength"], 0)
        self.assertFalse(payload["active"])

    def test_reset_voice_file_reveal_state_keeps_manual_viewer_open(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            ctx.fetch = async () => ({
              ok: true,
              json: async () => ({ content: 'artifact rail' }),
            });
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/js/voice-activity-feed.js', 'code');
            app.voiceFileReveal.queue = [{ path: '/tmp/stale', kind: 'folder' }];
            app.voiceFileReveal.active = true;
            app.resetVoiceFileRevealState({ closeViewer: true });
            console.log(JSON.stringify({
              open: app.voiceFileViewer.open,
              path: app.voiceFileViewer.path,
              autoOpened: app.voiceFileViewer.autoOpened,
              queueLength: app.voiceFileReveal.queue.length,
              active: app.voiceFileReveal.active,
            }));
            """
        )

        self.assertTrue(payload["open"])
        self.assertEqual(payload["path"], "/home/edp/.devbrain/ui/js/voice-activity-feed.js")
        self.assertFalse(payload["autoOpened"])
        self.assertEqual(payload["queueLength"], 0)
        self.assertFalse(payload["active"])

    def test_open_voice_file_viewer_loads_directory_listing(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return { authorization: 'Bearer test' }; } };
            Object.assign(app, mixin);
            ctx.fetch = async () => ({
              ok: true,
              json: async () => ({
                path: '/home/edp/Desktop/project',
                parent: '/home/edp/Desktop',
                items: [
                  { name: 'docs', path: '/home/edp/Desktop/project/docs', is_dir: true, size: 0 },
                  { name: 'README.md', path: '/home/edp/Desktop/project/README.md', is_dir: false, size: 1200 },
                ],
              }),
            });
            await app.openVoiceFileViewer('/home/edp/Desktop/project', 'folder');
            console.log(JSON.stringify({
              type: app.voiceFileViewer.type,
              parent: app.voiceFileViewer.parent,
              items: app.voiceFileViewer.items.map((item) => ({ name: item.name, is_dir: item.is_dir })),
            }));
            """
        )

        self.assertEqual(payload["type"], "folder")
        self.assertEqual(payload["parent"], "/home/edp/Desktop")
        self.assertEqual(payload["items"][0]["name"], "docs")
        self.assertTrue(payload["items"][0]["is_dir"])
        self.assertEqual(payload["items"][1]["name"], "README.md")

    def test_open_voice_file_viewer_falls_back_to_browse_for_directories(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            const calls = [];
            ctx.fetch = async (url) => {
              calls.push(url);
              if (url.startsWith('/api/files/read?path=')) {
                return {
                  ok: false,
                  status: 400,
                  statusText: 'Bad Request',
                  json: async () => ({ detail: 'Path is a directory — use /browse' }),
                };
              }
              return {
                ok: true,
                json: async () => ({
                  path: '/home/edp/Desktop/project',
                  parent: '/home/edp/Desktop',
                  items: [
                    { name: 'src', path: '/home/edp/Desktop/project/src', is_dir: true, size: 0 },
                  ],
                }),
              };
            };
            await app.openVoiceFileViewer('/home/edp/Desktop/project.log');
            console.log(JSON.stringify({
              type: app.voiceFileViewer.type,
              calls,
              firstItem: app.voiceFileViewer.items[0]?.name || '',
            }));
            """
        )

        self.assertEqual(payload["type"], "folder")
        self.assertEqual(len(payload["calls"]), 2)
        self.assertTrue(payload["calls"][0].startswith("/api/files/read?path="))
        self.assertTrue(payload["calls"][1].startswith("/api/files/browse?path="))
        self.assertEqual(payload["firstItem"], "src")

    def test_open_voice_file_viewer_normalizes_local_file_refs_with_line_anchors(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            const calls = [];
            ctx.fetch = async (url) => {
              calls.push(url);
              return {
                ok: true,
                json: async () => ({ content: 'voice dock' }),
              };
            };
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/partials/voice_command_dock.html#L27');
            console.log(JSON.stringify({
              path: app.voiceFileViewer.path,
              fetchUrl: calls[0] || '',
              error: app.voiceFileViewer.error || '',
            }));
            """
        )

        self.assertEqual(payload["path"], "/home/edp/.devbrain/ui/partials/voice_command_dock.html")
        self.assertIn(
            "/api/files/read?path=%2Fhome%2Fedp%2F.devbrain%2Fui%2Fpartials%2Fvoice_command_dock.html",
            payload["fetchUrl"],
        )
        self.assertEqual(payload["error"], "")

    def test_open_voice_file_viewer_ignores_duplicate_open_for_same_path(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            let fetchCount = 0;
            ctx.fetch = async () => {
              fetchCount += 1;
              return {
                ok: true,
                json: async () => ({ content: 'live operator' }),
              };
            };
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/js/live-operator.js', 'code', { auto: true });
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/js/live-operator.js', 'code', { auto: true });
            console.log(JSON.stringify({
              fetchCount,
              open: app.voiceFileViewer.open,
              path: app.voiceFileViewer.path,
              type: app.voiceFileViewer.type,
            }));
            """
        )

        self.assertEqual(payload["fetchCount"], 1)
        self.assertTrue(payload["open"])
        self.assertEqual(payload["path"], "/home/edp/.devbrain/ui/js/live-operator.js")
        self.assertEqual(payload["type"], "code")

    def test_queue_voice_file_reveal_skips_recently_opened_path(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = { authHeaders() { return {}; } };
            Object.assign(app, mixin);
            let fetchCount = 0;
            ctx.fetch = async () => {
              fetchCount += 1;
              return {
                ok: true,
                json: async () => ({ content: 'live operator' }),
              };
            };
            await app.openVoiceFileViewer('/home/edp/.devbrain/ui/js/live-operator.js', 'code', { auto: true });
            app.queueVoiceFileReveal('/home/edp/.devbrain/ui/js/live-operator.js');
            console.log(JSON.stringify({
              fetchCount,
              queueLength: app.voiceFileReveal.queue.length,
              lastOpenPath: app.voiceFileReveal.lastOpenPath,
            }));
            """,
        )

        self.assertEqual(payload["fetchCount"], 1)
        self.assertEqual(payload["queueLength"], 0)
        self.assertEqual(payload["lastOpenPath"], "/home/edp/.devbrain/ui/js/live-operator.js")

    def test_open_voice_file_viewer_resolves_workspace_relative_ui_path_hints(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = {
              authHeaders() { return {}; },
              chatProject: { path: '/home/edp/.devbrain' },
            };
            Object.assign(app, mixin);
            const calls = [];
            ctx.fetch = async (url) => {
              calls.push(url);
              return {
                ok: true,
                json: async () => ({ content: 'stream blocks' }),
              };
            };
            await app.openVoiceFileViewer('/js/voice-stream-blocks.js', 'code');
            console.log(JSON.stringify({
              path: app.voiceFileViewer.path,
              fetchUrl: calls[0] || '',
              error: app.voiceFileViewer.error || '',
            }));
            """
        )

        self.assertEqual(payload["path"], "/home/edp/.devbrain/ui/js/voice-stream-blocks.js")
        self.assertIn(
            "/api/files/read?path=%2Fhome%2Fedp%2F.devbrain%2Fui%2Fjs%2Fvoice-stream-blocks.js",
            payload["fetchUrl"],
        )
        self.assertEqual(payload["error"], "")

    def test_terminal_surface_click_focuses_terminal_instead_of_opening_file_viewer(self):
        payload = _run_voice_file_viewer_script(
            """
            const mixin = ctx.window.axonVoiceFileViewerMixin();
            const app = {
              focusTarget: null,
              focusVoiceSurfaceSpotlight(target) {
                this.focusTarget = target;
              },
            };
            Object.assign(app, mixin);
            app.initVoiceFileViewer();
            const trigger = {
              getAttribute(name) {
                return ({
                  'data-voice-surface': 'terminal',
                  'data-voice-path': '/tmp/project',
                  'data-voice-kind': 'folder',
                })[name] || '';
              },
              closest(selector) {
                if (selector === '[data-voice-surface]') return this;
                return null;
              },
            };
            let prevented = false;
            ctx.documentListeners.click({
              target: trigger,
              preventDefault() { prevented = true; },
            });
            console.log(JSON.stringify({
              prevented,
              focusTarget: app.focusTarget,
            }));
            """
        )

        self.assertTrue(payload["prevented"])
        self.assertEqual(payload["focusTarget"]["type"], "terminal")
        self.assertEqual(payload["focusTarget"]["path"], "/tmp/project")


if __name__ == "__main__":
    unittest.main()
