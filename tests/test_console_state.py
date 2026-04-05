from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONSOLE_STATE_JS = ROOT / "ui/js/console-state.js"


def _run_console_state_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync({json.dumps(str(CONSOLE_STATE_JS))}, 'utf8');
        const localStore = new Map();
        const sessionStore = new Map();
        const ctx = {{
          window: {{
            location: {{ href: 'http://localhost:7734/?view=chat&window=console-test' }},
            innerWidth: 1440,
            open() {{}},
            addEventListener() {{}},
            removeEventListener() {{}},
          }},
          localStorage: {{
            getItem(key) {{ return localStore.has(key) ? localStore.get(key) : null; }},
            setItem(key, value) {{ localStore.set(key, String(value)); }},
            removeItem(key) {{ localStore.delete(key); }},
          }},
          sessionStorage: {{
            getItem(key) {{ return sessionStore.has(key) ? sessionStore.get(key) : null; }},
            setItem(key, value) {{ sessionStore.set(key, String(value)); }},
            removeItem(key) {{ sessionStore.delete(key); }},
          }},
          URL,
          BroadcastChannel: function () {{ return {{ postMessage() {{}}, close() {{}} }}; }},
          console,
        }};
        vm.createContext(ctx);
        vm.runInContext(code, ctx);
        {body}
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


class ConsoleStateTests(unittest.TestCase):
    def test_restore_console_window_state_rehydrates_tabs_and_workspace(self):
        payload = _run_console_state_script(
            """
            const mixin = ctx.window.axonConsoleStateMixin();
            const app = {
              activeTab: 'dashboard',
              chatInput: '',
              chatProjectId: '',
              chatProject: null,
              showConsoleDetails: false,
              projects: [
                { id: 2, name: 'dashpro' },
                { id: 202, name: 'axon-online' },
              ],
              updateChatProject() {
                this.chatProject = this.projects.find((project) => String(project.id) === String(this.chatProjectId)) || null;
                this.updatedWorkspace = this.chatProjectId;
              },
              restoreConversationModePreference() {
                this.restoreModeCalled = true;
              },
              $watch() {},
              $nextTick(callback) { if (typeof callback === 'function') callback(); },
              resetChatComposerHeight() {},
            };
            Object.assign(app, mixin);
            app.initConsoleWindowScope();
            app.writeWindowPref('workspaceTabs', JSON.stringify(['', '2', '202']));
            app.writeWindowPref('selectedWorkspaceId', '202');
            app.writeWindowPref('showConsoleDetails', 'true');
            app.restoreConsoleWindowState();
            console.log(JSON.stringify({
              activeTab: app.activeTab,
              chatProjectId: app.chatProjectId,
              chatProjectName: app.chatProject?.name || '',
              tabs: app.consoleWorkspaceTabs,
              showConsoleDetails: app.showConsoleDetails,
              updatedWorkspace: app.updatedWorkspace || '',
              restoreModeCalled: app.restoreModeCalled === true,
            }));
            """
        )

        self.assertEqual(payload["activeTab"], "chat")
        self.assertEqual(payload["chatProjectId"], "202")
        self.assertEqual(payload["chatProjectName"], "axon-online")
        self.assertEqual(payload["tabs"], ["", "2", "202"])
        self.assertTrue(payload["showConsoleDetails"])
        self.assertEqual(payload["updatedWorkspace"], "202")
        self.assertTrue(payload["restoreModeCalled"])

    def test_composer_history_recalls_last_inputs_with_arrow_keys(self):
        payload = _run_console_state_script(
            """
            const mixin = ctx.window.axonConsoleStateMixin();
            const composer = {
              selectionStart: 0,
              selectionEnd: 0,
              focus() {},
              setSelectionRange(start, end) {
                this.selectionStart = start;
                this.selectionEnd = end;
              },
            };
            const app = {
              activeTab: 'chat',
              chatInput: '',
              projects: [],
              $refs: { chatComposer: composer },
              $nextTick(callback) { if (typeof callback === 'function') callback(); },
              resetChatComposerHeight() {},
            };
            Object.assign(app, mixin);
            app.initConsoleWindowScope();
            app.rememberComposerHistory('first task');
            app.rememberComposerHistory('second task');
            const event = { preventDefault() { this.prevented = true; }, prevented: false };
            app.handleComposerHistoryKey(event, 'up');
            const firstRecall = app.chatInput;
            app.handleComposerHistoryKey(event, 'up');
            const secondRecall = app.chatInput;
            composer.selectionStart = app.chatInput.length;
            composer.selectionEnd = app.chatInput.length;
            app.handleComposerHistoryKey(event, 'down');
            const downRecall = app.chatInput;
            console.log(JSON.stringify({
              prevented: event.prevented === true,
              firstRecall,
              secondRecall,
              downRecall,
            }));
            """
        )

        self.assertTrue(payload["prevented"])
        self.assertEqual(payload["firstRecall"], "second task")
        self.assertEqual(payload["secondRecall"], "first task")
        self.assertEqual(payload["downRecall"], "second task")


if __name__ == "__main__":
    unittest.main()
