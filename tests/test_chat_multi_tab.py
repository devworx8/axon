from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"
CHAT_CONSOLE_COMMANDS_JS = ROOT / "ui/js/chat-console-commands.js"
CHAT_JS = ROOT / "ui/js/chat.js"


def _run_chat_script(body: str):
    load_scripts = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(path))}, 'utf8'), ctx);"
        for path in [WORKSPACE_RUNS_JS, CHAT_CONSOLE_COMMANDS_JS, CHAT_JS]
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          console,
          requestAnimationFrame: (fn) => fn(),
          setTimeout,
          clearTimeout,
        }};
        vm.createContext(ctx);
        {load_scripts}
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


class ChatMultiTabTests(unittest.TestCase):
    def test_send_chat_allows_second_workspace_run_while_first_is_active(self):
        payload = _run_chat_script(
            """
            (async () => {
              let resolvePending = null;
              const pendingStream = new Promise((resolve) => {
                resolvePending = resolve;
              });

              const app = {
                chatProjectId: '1',
                chatInput: '',
                chatMessages: [],
                chatLoading: false,
                businessMode: false,
                agentMode: false,
                selectedResources: [],
                composerOptions: { pin_context: false },
                desktopPreview: { enabled: false },
                currentResearchPack() { return null; },
                mergeUniqueResources(items) { return items; },
                resolveChatMode() { return 'agent'; },
                usesOllamaBackend() { return true; },
                rememberComposerHistory(msg) {
                  this.history = [...(this.history || []), msg];
                },
                resetChatComposerHeight() {},
                scrollChat() {},
                showToast() {},
                setAgentStage(stage) {
                  this.lastStage = stage;
                },
                createAssistantPlaceholder(respId, mode, retryResources = []) {
                  return {
                    id: respId,
                    role: 'assistant',
                    content: '',
                    streaming: true,
                    mode,
                    retryResources,
                  };
                },
                streamChatMessage(msg, mode, respId) {
                  this.streamCalls = [...(this.streamCalls || []), {
                    msg,
                    mode,
                    respId,
                    workspaceId: this.chatProjectId,
                  }];
                  return pendingStream;
                },
              };

              Object.assign(
                app,
                ctx.window.axonWorkspaceRunsMixin(),
                ctx.window.axonChatMixin(),
              );

              app.currentResearchPack = () => null;
              app.mergeUniqueResources = (items) => items;
              app.resolveChatMode = () => 'agent';
              app.usesOllamaBackend = () => true;
              app.rememberComposerHistory = (msg) => {
                app.history = [...(app.history || []), msg];
              };
              app.resetChatComposerHeight = () => {};
              app.scrollChat = () => {};
              app.showToast = () => {};
              app.setAgentStage = (stage) => {
                app.lastStage = stage;
              };
              app.createAssistantPlaceholder = (respId, mode, retryResources = []) => ({
                id: respId,
                role: 'assistant',
                content: '',
                streaming: true,
                mode,
                retryResources,
              });
              app.streamChatMessage = (msg, mode, respId) => {
                app.streamCalls = [...(app.streamCalls || []), {
                  msg,
                  mode,
                  respId,
                  workspaceId: app.chatProjectId,
                }];
                return pendingStream;
              };
              app.beginLiveOperator = () => {};
              app.updateLiveOperator = () => {};
              app.clearLiveOperator = () => {};

              app.setWorkspaceRunLoading('1', true);
              app.chatProjectId = '2';
              app.chatInput = 'continue in workspace two';

              app.sendChat();
              await Promise.resolve();

              console.log(JSON.stringify({
                streamCallCount: (app.streamCalls || []).length,
                secondWorkspaceId: app.streamCalls?.[0]?.workspaceId || '',
                mode: app.streamCalls?.[0]?.mode || '',
                workspaceOneActive: app.workspaceRunIsActive('1'),
                workspaceTwoActive: app.workspaceRunIsActive('2'),
                activeCount: app.activeWorkspaceRunCount(),
                chatLoading: app.chatLoading === true,
                currentWorkspaceActive: app.currentWorkspaceRunActive(),
                history: app.history || [],
              }));

              resolvePending();
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["streamCallCount"], 1)
        self.assertEqual(payload["secondWorkspaceId"], "2")
        self.assertEqual(payload["mode"], "agent")
        self.assertTrue(payload["workspaceOneActive"])
        self.assertTrue(payload["workspaceTwoActive"])
        self.assertEqual(payload["activeCount"], 2)
        self.assertTrue(payload["chatLoading"])
        self.assertTrue(payload["currentWorkspaceActive"])
        self.assertEqual(payload["history"], ["continue in workspace two"])


if __name__ == "__main__":
    unittest.main()
