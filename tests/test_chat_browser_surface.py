from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_BROWSER_SURFACE_JS = ROOT / "ui/js/chat-browser-surface.js"


def _run_node(script_body: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script_body)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class ChatBrowserSurfaceTests(unittest.TestCase):
    def test_other_workspace_preview_does_not_bleed_into_current_workspace(self):
        payload = _run_node(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const code = fs.readFileSync({json.dumps(str(CHAT_BROWSER_SURFACE_JS))}, 'utf8');
            const ctx = {{
              window: {{}},
              console,
            }};
            vm.createContext(ctx);
            vm.runInContext(code, ctx);

            const mixin = ctx.window.axonChatBrowserSurfaceMixin();
            const app = {{
              chatProjectId: '3',
              chatProject: {{ id: 3, name: 'Axon', path: '/home/edp/.devbrain' }},
              panelBrowserOpen: true,
              workspacePreview: {{
                session: null,
                loading: false,
                error: 'No package.json dev/start script or static index.html found for this workspace.',
                workspace_id: '3',
                workspace_name: 'Axon',
                auto_session_id: '',
              }},
              devPreview: {{
                url: 'http://localhost:3002',
                visible: true,
                scope_key: '2:',
                workspace_id: '2',
                auto_session_id: '',
              }},
              browserActions: {{
                session: {{
                  connected: true,
                  url: 'http://localhost:3002',
                  title: 'Dashpro live page',
                  control_owner: 'manual',
                  attached_preview_url: '',
                  attached_preview_status: '',
                  attached_workspace_id: null,
                  attached_workspace_name: '',
                  attached_auto_session_id: '',
                  attached_scope_key: '',
                  attached_source_workspace_path: '',
                }},
                proposals: [],
                history: [],
                pending_count: 0,
              }},
              currentWorkspaceAutoSession() {{
                return null;
              }},
            }};
            Object.assign(app, mixin);

            console.log(JSON.stringify({{
              frameUrl: app.browserFrameUrl(),
              session: app.browserSession(),
              error: app.currentWorkspacePreviewError(),
            }}));
            """
        )

        self.assertEqual(payload["frameUrl"], "")
        self.assertEqual(payload["session"], {})
        self.assertIn("No package.json", payload["error"])

    def test_detected_dev_server_url_is_scoped_to_the_active_workspace(self):
        payload = _run_node(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const code = fs.readFileSync({json.dumps(str(CHAT_BROWSER_SURFACE_JS))}, 'utf8');
            const ctx = {{
              window: {{}},
              console,
            }};
            vm.createContext(ctx);
            vm.runInContext(code, ctx);

            const mixin = ctx.window.axonChatBrowserSurfaceMixin();
            const app = {{
              chatProjectId: '7',
              chatProject: {{ id: 7, name: 'dashpro', path: '/home/edp/Desktop/dashpro' }},
              panelBrowserOpen: false,
              workspacePreview: {{
                session: null,
                loading: false,
                error: '',
                workspace_id: '7',
                workspace_name: 'dashpro',
                auto_session_id: '',
              }},
              devPreview: {{ url: '', visible: false, scope_key: '', workspace_id: null, auto_session_id: '' }},
              browserActions: {{ session: {{}}, proposals: [], history: [], pending_count: 0 }},
              currentWorkspaceAutoSession() {{
                return null;
              }},
            }};
            Object.assign(app, mixin);

            app._detectDevServerUrl('ready on http://localhost:3000 and http://127.0.0.1:7734');
            const captured = {{ ...app.devPreview }};
            app.chatProjectId = '9';
            app.chatProject = {{ id: 9, name: 'Axon', path: '/home/edp/.devbrain' }};

            console.log(JSON.stringify({{
              captured,
              currentScopedUrl: app.scopedDevPreview().url,
              currentFrameUrl: app.browserFrameUrl(),
              panelBrowserOpen: app.panelBrowserOpen,
            }}));
            """
        )

        self.assertEqual(payload["captured"]["url"], "http://localhost:3000")
        self.assertEqual(payload["captured"]["scope_key"], "7:")
        self.assertEqual(payload["currentScopedUrl"], "")
        self.assertEqual(payload["currentFrameUrl"], "")
        self.assertTrue(payload["panelBrowserOpen"])


if __name__ == "__main__":
    unittest.main()
