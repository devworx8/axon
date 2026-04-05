from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS_FILES = [
    ROOT / "ui/js/chat-workspace-modes.js",
    ROOT / "ui/js/chat-workspace-status.js",
    ROOT / "ui/js/chat-auto-stream.js",
    ROOT / "ui/js/chat-console-commands.js",
    ROOT / "ui/js/chat-browser-surface.js",
    ROOT / "ui/js/chat-resume.js",
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
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          console,
          requestAnimationFrame: (fn) => fn(),
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


class ChatAutoResumeScopeTests(unittest.TestCase):
    def test_preferred_resume_auto_session_stays_on_current_workspace(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              chatProjectId: '2',
              autoSessions: [
                { session_id: 'auto-bkk', workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running' },
              ],
              isExplicitResumeText() { return true; },
            };
            Object.assign(app, mixin);

            const current = app.currentWorkspaceAutoSession();
            const active = app.activeAutoSession();
            const preferred = app.preferredResumeAutoSession('please continue', 'typed_continue');

            console.log(JSON.stringify({
              current: current ? current.session_id : null,
              active: active ? active.session_id : null,
              preferred: preferred ? preferred.session_id : null,
            }));
            """
        )

        self.assertIsNone(payload["current"])
        self.assertEqual(payload["active"], "auto-bkk")
        self.assertIsNone(payload["preferred"])

    def test_preferred_resume_auto_session_can_fall_back_when_no_workspace_is_selected(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              chatProjectId: '',
              autoSessions: [
                { session_id: 'auto-bkk', workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running' },
              ],
              isExplicitResumeText() { return true; },
            };
            Object.assign(app, mixin);

            const preferred = app.preferredResumeAutoSession('please continue', 'quick_resume');
            console.log(JSON.stringify({
              preferred: preferred ? preferred.session_id : null,
              workspace: preferred ? preferred.workspace_id : null,
            }));
            """
        )

        self.assertEqual(payload["preferred"], "auto-bkk")
        self.assertEqual(payload["workspace"], "1")

    def test_load_auto_sessions_does_not_restore_auto_mode_from_other_workspace(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {
                chatProjectId: '2',
                autoSessions: [],
                restoredAuto: false,
                api(method, path) {
                  if (method === 'GET' && path === '/api/auto/sessions') {
                    return Promise.resolve({
                      sessions: [
                        { session_id: 'auto-bkk', workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running' },
                      ],
                    });
                  }
                  throw new Error(`Unexpected ${method} ${path}`);
                },
                currentBackendSupportsAgent() { return true; },
                readWindowPref(key, fallback = '') {
                  if (key === 'consoleAutoIntent') return 'true';
                  return fallback;
                },
                setConversationModeAuto() {
                  this.restoredAuto = true;
                },
                syncAutoSessionNoticeForCurrentWorkspace() {},
                loadWorkspacePreview() {},
                maybeStartAutoWorkspacePreview() {},
              };
              Object.assign(app, mixin);
              await app.loadAutoSessions();
              console.log(JSON.stringify({
                restoredAuto: app.restoredAuto,
                current: app.currentWorkspaceAutoSession(),
                active: app.activeAutoSession()?.session_id || null,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertFalse(payload["restoredAuto"])
        self.assertIsNone(payload["current"])
        self.assertEqual(payload["active"], "auto-bkk")

    def test_send_chat_silent_does_not_activate_foreign_auto_workspace(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {
                chatProjectId: '2',
                chatMessages: [],
                autoSessions: [
                  { session_id: 'auto-bkk', workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running' },
                ],
                isExplicitResumeText() { return true; },
                currentWorkspaceRunActive() { return false; },
                effectiveChatMode() { return 'agent'; },
                currentBackendSupportsAgent() { return true; },
                setConversationModeAuto() {
                  this.setAutoCalled = true;
                },
                setWorkspaceRunLoading(_workspaceId, loading) {
                  this.loadingStates = this.loadingStates || [];
                  this.loadingStates.push(!!loading);
                },
                autonomousConsoleActive() { return false; },
                scrollChat() {},
                _processQueue() {
                  this.queueProcessed = true;
                },
                continueAutoSession() {
                  this.continuedAuto = true;
                  return Promise.resolve(null);
                },
                activateWorkspaceTab(id) {
                  this.activatedWorkspace = String(id || '');
                  this.chatProjectId = this.activatedWorkspace;
                },
              };
              Object.assign(app, mixin);
              app.beginLiveOperator = () => {};
              app.setAgentStage = () => {};
              app.autonomousConsoleActive = () => false;
              app.createAssistantPlaceholder = (respId, mode) => ({ id: respId, role: 'assistant', mode, content: '' });
              app.scrollChat = () => {};
              app.streamChatMessage = async (msg, mode) => {
                app.streamCalled = { msg, mode, workspaceId: app.chatProjectId };
              };
              await app.sendChatSilent('please continue', 'agent', {});
              console.log(JSON.stringify({
                activatedWorkspace: app.activatedWorkspace || '',
                continuedAuto: !!app.continuedAuto,
                streamCalled: app.streamCalled || null,
                finalWorkspace: app.chatProjectId,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["activatedWorkspace"], "")
        self.assertFalse(payload["continuedAuto"])
        self.assertEqual(payload["finalWorkspace"], "2")
        self.assertEqual(payload["streamCalled"]["mode"], "agent")
        self.assertEqual(payload["streamCalled"]["workspaceId"], "2")

    def test_send_chat_silent_appends_user_request_before_assistant_placeholder(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {
                chatProjectId: '2',
                chatMessages: [],
                autoSessions: [],
                currentWorkspaceRunActive() { return false; },
                effectiveChatMode() { return 'agent'; },
                currentBackendSupportsAgent() { return true; },
                setWorkspaceRunLoading() {},
                autonomousConsoleActive() { return false; },
                scrollChat() {},
                _processQueue() {},
              };
              Object.assign(app, mixin);
              app.beginLiveOperator = () => {};
              app.$nextTick = (callback) => {
                if (callback) callback();
              };
              app.scrollChat = () => {};
              app.createAssistantPlaceholder = (respId, mode) => ({ id: respId, role: 'assistant', mode, content: '', streaming: true });
              app.streamChatMessage = async () => {};
              await app.sendChatSilent('please inspect the workspace', 'agent', {});
              console.log(JSON.stringify(app.chatMessages.map(message => ({
                role: message.role,
                content: message.content,
                mode: message.mode,
              }))));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["role"], "user")
        self.assertEqual(payload[0]["content"], "please inspect the workspace")
        self.assertEqual(payload[1]["role"], "assistant")
        self.assertEqual(payload[1]["mode"], "agent")

    def test_workspace_quick_actions_are_operator_focused(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              chatProjectId: '7',
              chatProject: { id: '7', name: 'bkkinnovationhub' },
              interruptedSession: null,
              autoSessions: [],
              chatMessages: [],
              pendingAgentApproval: { workspaceId: '7', id: 'approval-1' },
              previewReadyForCurrentWorkspace() { return false; },
              currentWorkspaceAutoSession() { return null; },
              chooseInitialWorkspaceRestoreCandidate() { return null; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify(app.chatQuickActions()));
            """
        )

        labels = [item["label"] for item in payload]
        self.assertIn("Inspect this workspace", labels)
        self.assertIn("Scan repo and surface blockers", labels)
        self.assertIn("Start live page", labels)
        self.assertIn("Check approvals", labels)
        self.assertNotIn("Create an invoice for Khanyisa with line items, discount, due date, and client details...", labels)

    def test_global_quick_actions_include_resume_for_latest_active_workspace(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              chatProjectId: '',
              autoSessions: [
                { session_id: 'auto-bkk', workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running' },
              ],
              interruptedSession: null,
              newestRestorableAutoSession(rows) {
                return rows[0] || null;
              },
              chooseInitialWorkspaceRestoreCandidate() {
                return {
                  workspaceId: '1',
                  label: 'bkkinnovationhub',
                  source: 'auto_session',
                };
              },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify(app.chatQuickActions()));
            """
        )

        self.assertEqual(payload[0]["label"], "Resume bkkinnovationhub")
        self.assertEqual(payload[0]["action"], "resume_active_workspace")
        self.assertEqual(payload[1]["action"], "clear_stale_resumable_session")

    def test_workspace_quick_actions_prioritize_resume_then_operator_actions(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              chatProjectId: '7',
              chatProject: { id: '7', name: 'bkkinnovationhub' },
              interruptedSession: { session_id: 'sess-7', workspace_id: 7 },
              autoSessions: [
                { session_id: 'auto-7', workspace_id: '7', status: 'approval_required' },
              ],
              pendingAgentApproval: { workspaceId: '7', id: 'approval-1' },
              currentWorkspaceAutoSession() {
                return this.autoSessions[0];
              },
              previewReadyForCurrentWorkspace() { return false; },
            };
            Object.assign(app, mixin);
            console.log(JSON.stringify(app.chatQuickActions().map(item => item.id)));
            """
        )

        self.assertEqual(payload[:6], [
            "resume-last-run",
            "clear-stale-run",
            "inspect-workspace",
            "scan-blockers",
            "workspace-preview",
            "check-approvals",
        ])

    def test_run_chat_quick_action_can_clear_stale_resumable_session(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {};
              Object.assign(app, mixin);
              app.discardedSessionId = '';
              app.discardAutoSession = function (sessionId) {
                this.discardedSessionId = String(sessionId || '');
                return Promise.resolve();
              };
              await app.runChatQuickAction({
                type: 'action',
                action: 'clear_stale_resumable_session',
                sessionId: 'auto-stale-1',
              });
              console.log(JSON.stringify({
                discardedSessionId: app.discardedSessionId,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["discardedSessionId"], "auto-stale-1")

    def test_auto_session_helpers_mark_error_session_as_clearable(self):
        payload = _run_chat_script(
            """
            const mixin = ctx.window.axonChatMixin();
            const app = {
              autoSessions: [
                { session_id: 'auto-stale-1', status: 'error' },
              ],
            };
            Object.assign(app, mixin);
            const session = app.autoSessionForMessage({ autoSessionId: 'auto-stale-1' });
            console.log(JSON.stringify({
              canContinue: app.autoSessionCanContinue(session),
              canClear: app.autoSessionCanClear(session),
              discardLabel: app.autoSessionDiscardLabel(session),
            }));
            """
        )

        self.assertTrue(payload["canContinue"])
        self.assertTrue(payload["canClear"])
        self.assertEqual(payload["discardLabel"], "Clear stale run")

    def test_start_auto_session_from_chat_uses_explicit_workspace_id(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {
                chatProjectId: '2',
                currentBackendSupportsAgent() { return true; },
                setConversationModeAuto() {},
                autoSessionRuntimePayload() { return {}; },
                api(method, path, payload) {
                  this.sentPayload = { method, path, payload };
                  return Promise.resolve({ started: true, session: { session_id: 'auto-1', workspace_id: '1' } });
                },
                updateAutoSessionRecord() {},
                loadWorkspacePreview() {},
                showToast() {},
              };
              Object.assign(app, mixin);
              await app.startAutoSessionFromChat('scan repo', [], {}, { workspaceId: '1' });
              console.log(JSON.stringify(app.sentPayload));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["method"], "POST")
        self.assertEqual(payload["path"], "/api/auto/start")
        self.assertEqual(payload["payload"]["project_id"], 1)

    def test_continue_auto_session_uses_explicit_workspace_id(self):
        payload = _run_chat_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatMixin();
              const app = {
                chatProjectId: '2',
                currentBackendSupportsAgent() { return true; },
                setConversationModeAuto() {},
                normalizedComposerOptions() { return {}; },
                autoSessionRuntimePayload() { return {}; },
                api(method, path, payload) {
                  this.sentPayload = { method, path, payload };
                  return Promise.resolve({ started: true, session: { session_id: 'auto-1', workspace_id: '1' } });
                },
                updateAutoSessionRecord() {},
                loadWorkspacePreview() {},
                showToast() {},
              };
              Object.assign(app, mixin);
              await app.continueAutoSession('auto-1', { message: 'please continue', workspaceId: '1' });
              console.log(JSON.stringify(app.sentPayload));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["method"], "POST")
        self.assertEqual(payload["path"], "/api/auto/auto-1/continue")
        self.assertEqual(payload["payload"]["project_id"], 1)


if __name__ == "__main__":
    unittest.main()
