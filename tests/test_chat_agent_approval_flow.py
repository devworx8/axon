from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS_FILES = [
    ROOT / "ui/js/workspace-runs.js",
    ROOT / "ui/js/chat-console-commands.js",
    ROOT / "ui/js/chat-approvals.js",
    ROOT / "ui/js/chat.js",
]


def _run_chat_script(body: str):
    load_scripts = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(path))}, 'utf8'), ctx);"
        for path in CHAT_JS_FILES
    )
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          document: {{
            getElementById() {{ return null; }},
          }},
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          console,
          requestAnimationFrame: (fn) => fn(),
          setTimeout,
          clearTimeout,
          AbortController,
          TextDecoder,
          TextEncoder,
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


class ChatAgentApprovalFlowTests(unittest.TestCase):
    def test_agent_stream_open_uses_plan_event_not_result_event(self):
        payload = _run_chat_script(
            """
            (async () => {
              const encoder = new TextEncoder();
              const events = [
                { type: 'done' },
              ];
              ctx.fetch = async () => ({
                ok: true,
                status: 200,
                body: {
                  getReader() {
                    const chunks = events
                      .map((event) => `data: ${JSON.stringify(event)}\\n`)
                      .map((chunk) => encoder.encode(chunk));
                    let index = 0;
                    return {
                      async read() {
                        if (index >= chunks.length) return { done: true, value: undefined };
                        return { done: false, value: chunks[index++] };
                      },
                    };
                  },
                },
              });

              const liveEvents = [];
              const app = {
                chatProjectId: '7',
                chatMessages: [{
                  id: 99,
                  role: 'assistant',
                  content: '',
                  streaming: true,
                  mode: 'agent',
                  thinkingBlocks: [],
                  workingBlocks: [],
                  agentEvents: [],
                }],
                liveOperator: { phase: 'observe' },
                normalizedComposerOptions() { return {}; },
                authHeaders(headers) { return headers; },
                usesOllamaBackend() { return false; },
                setWorkspaceAbortController() {},
                setAgentStage() {},
                updateLiveOperator(_mode, data) { liveEvents.push(data); },
                clearLiveOperator() {},
                rememberOperatorOutcome() {},
                scrollChat() {},
                $nextTick(callback) { if (callback) callback(); return Promise.resolve(); },
                assistantProviderIdentity() { return { providerId: 'cli', modelLabel: 'Codex CLI · gpt-5.4' }; },
                assistantRuntimeLabel() { return 'Codex CLI · gpt-5.4'; },
                workspaceRunStateFor() { return { liveOperator: { phase: 'verify' } }; },
                ensureWorkspaceTab() {},
              };
              Object.assign(app, ctx.window.axonWorkspaceRunsMixin(), ctx.window.axonChatMixin());
              app.setAgentStage = () => {};
              app.updateLiveOperator = (_mode, data) => { liveEvents.push(data); };
              app.clearLiveOperator = () => {};
              app.rememberOperatorOutcome = () => {};
              await app.streamChatMessage('Inspect the stream path', 'agent', 99, [], {}, '7');
              console.log(JSON.stringify({
                firstType: liveEvents[0]?.type || '',
                lastType: liveEvents[liveEvents.length - 1]?.type || '',
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["firstType"], "stream_open")
        self.assertEqual(payload["lastType"], "done")

    def test_stream_chat_message_surfaces_pending_agent_approval(self):
        payload = _run_chat_script(
            """
            (async () => {
              const encoder = new TextEncoder();
              const events = [
                { type: 'tool_call', name: 'shell_cmd', args: { cmd: 'git add -A', cwd: '/tmp/demo' } },
                { type: 'tool_result', name: 'shell_cmd', result: 'BLOCKED_CMD:git:git add -A' },
                {
                  type: 'approval_required',
                  kind: 'command',
                  command: 'git',
                  full_command: 'git add -A',
                  message: 'Approval required before Axon can run `git add -A`.',
                  resume_task: 'Commit everything with commit message "feat: update tests".',
                  approval_action: {
                    action_fingerprint: 'approval-123',
                    action_type: 'git_add',
                    command_preview: 'git add -A',
                    repo_root: '/tmp/demo',
                    scope_options: ['once', 'task', 'session', 'persist'],
                    persist_allowed: true,
                    session_id: 'session-7',
                  },
                  scope_options: ['once', 'task', 'session', 'persist'],
                  persist_allowed: true,
                  summary: 'Stage changes',
                  workspace_id: 7,
                },
              ];
              ctx.fetch = async () => ({
                ok: true,
                status: 200,
                body: {
                  getReader() {
                    const chunks = events
                      .map((event) => `data: ${JSON.stringify(event)}\\n`)
                      .map((chunk) => encoder.encode(chunk));
                    let index = 0;
                    return {
                      async read() {
                        if (index >= chunks.length) return { done: true, value: undefined };
                        return { done: false, value: chunks[index++] };
                      },
                    };
                  },
                },
              });

              const app = {
                chatProjectId: '7',
                chatMessages: [{
                  id: 99,
                  role: 'assistant',
                  content: '',
                  streaming: true,
                  mode: 'agent',
                  thinkingBlocks: [],
                  workingBlocks: [],
                  agentEvents: [],
                }],
                liveOperator: { phase: 'observe' },
                normalizedComposerOptions() { return {}; },
                authHeaders(headers) { return headers; },
                usesOllamaBackend() { return false; },
                setWorkspaceAbortController() {},
                setAgentStage(stage) { this.lastStage = stage; },
                updateLiveOperator(_mode, data) { this.lastLiveEvent = data; },
                clearLiveOperator() {},
                rememberOperatorOutcome() {},
                scrollChat() {},
                $nextTick(callback) { if (callback) callback(); return Promise.resolve(); },
                assistantProviderIdentity() { return { providerId: 'cli', modelLabel: 'Codex CLI · gpt-5.4' }; },
                assistantRuntimeLabel() { return 'Codex CLI · gpt-5.4'; },
                workspaceRunStateFor() { return { liveOperator: { phase: 'recover' } }; },
                showToast(message) { this.toast = message; },
                ensureWorkspaceTab() {},
              };
              Object.assign(app, ctx.window.axonWorkspaceRunsMixin(), ctx.window.axonChatMixin());
              app.setAgentStage = (stage) => { app.lastStage = stage; };
              app.updateLiveOperator = (_mode, data) => { app.lastLiveEvent = data; };
              app.clearLiveOperator = () => {};
              app.rememberOperatorOutcome = () => {};
              await app.streamChatMessage('Stage and commit', 'agent', 99, [], {}, '7');
              console.log(JSON.stringify({
                pending: app.pendingAgentApproval,
                content: app.chatMessages[0].content,
                approvalRequired: app.chatMessages[0].approvalRequired === true,
                streaming: app.chatMessages[0].streaming === true,
                lastStage: app.lastStage || '',
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["pending"]["sessionId"], "session-7")
        self.assertEqual(payload["pending"]["workspaceId"], "7")
        self.assertEqual(payload["pending"]["commandPreview"], "git add -A")
        self.assertEqual(payload["pending"]["resumeTask"], 'Commit everything with commit message "feat: update tests".')
        self.assertIn("Approval required before Axon can run", payload["content"])
        self.assertTrue(payload["approvalRequired"])
        self.assertFalse(payload["streaming"])
        self.assertEqual(payload["lastStage"], "recover")

    def test_approve_pending_agent_action_posts_exact_action_and_resumes(self):
        payload = _run_chat_script(
            """
            (async () => {
              const apiCalls = [];
              const app = {
                chatProjectId: '7',
                pendingAgentApproval: {
                  id: 'approval-7',
                  workspaceId: '7',
                  sessionId: 'session-7',
                  resumeTask: 'Commit everything with commit message "feat: update tests".',
                  scopeOptions: ['once', 'task', 'session'],
                  action: {
                    action_fingerprint: 'approval-7',
                    action_type: 'git_add',
                    command_preview: 'git add -A',
                    session_id: 'session-7',
                  },
                },
                api(method, path, body) {
                  apiCalls.push({ method, path, body });
                  return Promise.resolve({ ok: true });
                },
                sendChatSilent(message, mode, extraPayload) {
                  this.resumeCall = { message, mode, extraPayload };
                  return Promise.resolve(true);
                },
                showToast(message) { this.toast = message; },
                activateWorkspaceTab() {},
                $nextTick(callback) { if (callback) callback(); return Promise.resolve(); },
              };
              Object.assign(app, ctx.window.axonChatMixin());
              app.sendChatSilent = (message, mode, extraPayload) => {
                app.resumeCall = { message, mode, extraPayload };
                return Promise.resolve(true);
              };
              await app.approvePendingAgentAction('session');
              console.log(JSON.stringify({
                apiCalls,
                resumeCall: app.resumeCall,
                pendingCleared: app.pendingAgentApproval === null,
                toast: app.toast || '',
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["apiCalls"][0]["method"], "POST")
        self.assertEqual(payload["apiCalls"][0]["path"], "/api/agent/approve-action")
        self.assertEqual(payload["apiCalls"][0]["body"]["scope"], "session")
        self.assertEqual(payload["resumeCall"]["message"], 'Commit everything with commit message "feat: update tests".')
        self.assertEqual(payload["resumeCall"]["mode"], "agent")
        self.assertEqual(payload["resumeCall"]["extraPayload"]["resume_session_id"], "session-7")
        self.assertEqual(payload["resumeCall"]["extraPayload"]["project_id"], 7)
        self.assertTrue(payload["pendingCleared"])
        self.assertIn("Approval granted", payload["toast"])


if __name__ == "__main__":
    unittest.main()
