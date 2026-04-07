from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_SLASH_COMMANDS_JS = ROOT / "ui/js/chat-slash-commands.js"
CHAT_CONSOLE_COMMANDS_JS = ROOT / "ui/js/chat-console-commands.js"
CHAT_WORKSPACE_MODES_JS = ROOT / "ui/js/chat-workspace-modes.js"


def _run_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          console,
        }};
        vm.createContext(ctx);
        for (const path of [
          {json.dumps(str(CHAT_WORKSPACE_MODES_JS))},
          {json.dumps(str(CHAT_SLASH_COMMANDS_JS))},
          {json.dumps(str(CHAT_CONSOLE_COMMANDS_JS))},
        ]) {{
          vm.runInContext(fs.readFileSync(path, 'utf8'), ctx);
        }}
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


class ChatSlashCommandsTests(unittest.TestCase):
    def test_send_chat_intercepts_slash_help_without_hitting_stream(self):
        payload = _run_script(
            """
            (async () => {
              const app = {
                chatInput: '/help',
                chatMessages: [],
                selectedResources: [],
                composerOptions: { pin_context: false },
                followUpSuggestions: ['one'],
                currentResearchPack() { return null; },
                mergeUniqueResources(rows = []) { return rows; },
                currentWorkspaceRunActive() { return false; },
                maybeHandleInteractiveConsoleCommand() { this.consoleChecked = true; return Promise.resolve(false); },
                runChatComposerMessage() { this.streamCalled = true; return Promise.resolve(true); },
                resetChatComposerHeight() {},
                rememberComposerHistory() {},
                scrollChat() {},
                showToast() {},
              };
              Object.assign(app, ctx.window.axonChatSlashCommandsMixin(), ctx.window.axonChatConsoleCommandsMixin());
              app.maybeHandleInteractiveConsoleCommand = () => {
                app.consoleChecked = true;
                return Promise.resolve(false);
              };
              await app.sendChat();
              console.log(JSON.stringify({
                consoleChecked: !!app.consoleChecked,
                streamCalled: !!app.streamCalled,
                messageCount: app.chatMessages.length,
                assistantContent: app.chatMessages[1]?.content || '',
              }));
            })().catch((error) => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertTrue(payload["consoleChecked"])
        self.assertFalse(payload["streamCalled"])
        self.assertEqual(payload["messageCount"], 2)
        self.assertIn("Slash commands:", payload["assistantContent"])

    def test_slash_agent_switches_modes_and_reports_status(self):
        payload = _run_script(
            """
            (async () => {
              const app = {
                chatInput: '/agent',
                chatMessages: [],
                selectedResources: [],
                composerOptions: { pin_context: false, intelligence_mode: 'ask', action_mode: '', agent_role: '' },
                liveOperator: {},
                settingsForm: { ai_backend: 'cli', runtime_permissions_mode: 'full_access', autonomy_profile: 'workspace_auto' },
                runtimeStatus: { cli_model: 'gpt-5.4' },
                chatProjectId: '42',
                chatProject: { id: 42, name: 'Hope' },
                agentMode: false,
                businessMode: false,
                currentRuntimeBackend() { return 'cli'; },
                assistantRuntimeLabel() { return 'CLI Agent'; },
                permissionPresetLabel() { return 'Full access'; },
                workspaceTabLabel() { return 'Hope'; },
                persistConversationModePreference() {},
                resetChatComposerHeight() {},
                rememberComposerHistory() {},
                scrollChat() {},
                showToast() {},
              };
              Object.assign(app, ctx.window.axonChatWorkspaceModesMixin(), ctx.window.axonChatSlashCommandsMixin());
              await app.maybeHandleSlashCommand('/agent');
              const activeMode = app.activePrimaryConversationMode();
              await app.maybeHandleSlashCommand('/status');
              console.log(JSON.stringify({
                activeMode,
                assistantMessages: app.chatMessages.filter((item) => item.role === 'assistant').map((item) => item.content),
              }));
            })().catch((error) => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["activeMode"], "agent")
        self.assertIn("Agent mode armed.", payload["assistantMessages"][0])
        self.assertIn("Workspace: Hope", payload["assistantMessages"][1])
        self.assertIn("Permissions: Full access", payload["assistantMessages"][1])

    def test_slash_deploy_expo_uses_expo_lane_helper(self):
        payload = _run_script(
            """
            (async () => {
              const app = {
                chatInput: '/deploy expo',
                chatMessages: [],
                selectedResources: [],
                composerOptions: { pin_context: false, intelligence_mode: 'ask', action_mode: '', agent_role: '' },
                settingsForm: { ai_backend: 'cli', runtime_permissions_mode: 'default', autonomy_profile: 'workspace_auto' },
                runtimeStatus: { cli_model: 'gpt-5.4' },
                prepareExpoDeployLane() {
                  this.expoPrepared = true;
                  return Promise.resolve(true);
                },
                resetChatComposerHeight() {},
                rememberComposerHistory() {},
                scrollChat() {},
                showToast() {},
              };
              Object.assign(app, ctx.window.axonChatSlashCommandsMixin());
              await app.maybeHandleSlashCommand('/deploy expo');
              console.log(JSON.stringify({
                expoPrepared: !!app.expoPrepared,
                assistantContent: app.chatMessages[1]?.content || '',
              }));
            })().catch((error) => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertTrue(payload["expoPrepared"])
        self.assertIn("Expo lane prepared.", payload["assistantContent"])


if __name__ == "__main__":
    unittest.main()
