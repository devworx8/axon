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

        const ctx = {{
          window: {{ addEventListener() {{}} }},
          console,
          document: {{
            addEventListener() {{}},
            getElementById() {{ return null; }},
          }},
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


if __name__ == "__main__":
    unittest.main()
