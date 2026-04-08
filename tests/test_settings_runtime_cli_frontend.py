from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_RUNTIME_CLI_JS = ROOT / "ui/js/settings-runtime-cli.js"


def _run_settings_runtime_cli_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{
            open: (...args) => {{ ctx.openCalls.push(args); }},
          }},
          navigator: {{
            clipboard: {{
              writeText: async (value) => {{ ctx.copied.push(value); }},
            }},
          }},
          console,
          setTimeout: () => 1,
          clearTimeout: () => {{}},
          openCalls: [],
          copied: [],
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(SETTINGS_RUNTIME_CLI_JS))}, 'utf8'), ctx);
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


class SettingsRuntimeCliFrontendTests(unittest.TestCase):
    def test_refresh_runtime_cli_deck_loads_both_families(self):
        payload = _run_settings_runtime_cli_script(
            """
            const mixin = ctx.window.axonSettingsRuntimeCliMixin();
            const app = {
              calls: [],
              async api(method, path) {
                this.calls.push([method, path]);
                if (path === '/api/runtime/codex/status') {
                  return {
                    installed: true,
                    binary_name: 'codex',
                    version: '0.117.0',
                    auth: { logged_in: true, message: 'Signed in' },
                  };
                }
                return {
                  installed: true,
                  binary_name: 'claude',
                  version: '2.1.88',
                  auth: { logged_in: false, message: 'Needs sign-in' },
                };
              },
            };
            Object.assign(app, mixin);
            await app.refreshRuntimeCliDeck(true);
            console.log(JSON.stringify({
              cards: app.runtimeCliCards().map((card) => ({
                id: card.id,
                loggedIn: card.loggedIn,
                version: card.version,
              })),
              calls: app.calls,
            }));
            """
        )

        self.assertEqual(
            payload["cards"],
            [
                {"id": "claude", "loggedIn": False, "version": "2.1.88"},
                {"id": "codex", "loggedIn": True, "version": "0.117.0"},
            ],
        )
        self.assertEqual(
            payload["calls"],
            [
                ["GET", "/api/runtime/cli/status"],
                ["GET", "/api/runtime/codex/status"],
            ],
        )

    def test_start_runtime_cli_login_opens_browser_link_and_stores_session(self):
        payload = _run_settings_runtime_cli_script(
            """
            const mixin = ctx.window.axonSettingsRuntimeCliMixin();
            const app = {
              toasts: [],
              showToast(message) { this.toasts.push(message); },
              async api(method, path) {
                if (method === 'POST' && path === '/api/runtime/codex/login/start') {
                  return {
                    session: {
                      session_id: 'sess-1',
                      status: 'waiting',
                      browser_url: 'https://auth.openai.com/codex/device',
                      user_code: 'XF1T-RC1AX',
                      message: 'Continue sign-in in the browser.',
                      command_preview: 'codex login',
                    },
                  };
                }
                if (method === 'GET' && path === '/api/runtime/codex/status') {
                  return {
                    installed: true,
                    binary_name: 'codex',
                    version: '0.117.0',
                    auth: { logged_in: false, message: 'Not logged in' },
                  };
                }
                throw new Error('unexpected call: ' + method + ' ' + path);
              },
            };
            Object.assign(app, mixin);
            await app.startRuntimeCliLogin('codex');
            console.log(JSON.stringify({
              session: app.runtimeCliFamilyState('codex').session,
              openCalls: ctx.openCalls,
              toasts: app.toasts,
            }));
            """
        )

        self.assertEqual(payload["session"]["session_id"], "sess-1")
        self.assertEqual(payload["openCalls"][0][0], "https://auth.openai.com/codex/device")
        self.assertIn("Continue sign-in in the browser.", payload["toasts"][0])

    def test_logout_runtime_cli_refreshes_snapshot(self):
        payload = _run_settings_runtime_cli_script(
            """
            const mixin = ctx.window.axonSettingsRuntimeCliMixin();
            const app = {
              toasts: [],
              showToast(message) { this.toasts.push(message); },
              async api(method, path) {
                if (method === 'POST' && path === '/api/runtime/cli/logout') {
                  return {
                    status: 'completed',
                    message: 'Claude CLI signed out.',
                    cli_runtime: {
                      installed: true,
                      binary_name: 'claude',
                      version: '2.1.88',
                      auth: { logged_in: false, message: 'Signed out' },
                    },
                  };
                }
                if (method === 'GET' && path === '/api/runtime/cli/status') {
                  return {
                    installed: true,
                    binary_name: 'claude',
                    version: '2.1.88',
                    auth: { logged_in: false, message: 'Signed out' },
                  };
                }
                throw new Error('unexpected call: ' + method + ' ' + path);
              },
            };
            Object.assign(app, mixin);
            app.ensureRuntimeCliDeckState();
            app.runtimeCliFamilyState('claude').snapshot = {
              installed: true,
              binary_name: 'claude',
              version: '2.1.88',
              auth: { logged_in: true, message: 'Signed in' },
            };
            await app.logoutRuntimeCli('claude');
            console.log(JSON.stringify({
              loggedIn: app.runtimeCliCards()[0].loggedIn,
              toasts: app.toasts,
            }));
            """
        )

        self.assertFalse(payload["loggedIn"])
        self.assertIn("Claude CLI signed out.", payload["toasts"][0])


if __name__ == "__main__":
    unittest.main()
