from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_RESUME_JS = ROOT / "ui/js/chat-resume.js"


def _run_resume_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync({json.dumps(str(CHAT_RESUME_JS))}, 'utf8');
        const ctx = {{
          window: {{}},
          setInterval: () => 1,
          clearInterval: () => {{}},
          requestAnimationFrame: (fn) => fn(),
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


class ChatResumeTests(unittest.TestCase):
    def test_resolve_resume_workspace_prefers_interrupted_session_workspace(self):
        payload = _run_resume_script(
            """
            const workspaceId = ctx.window.axonResolveResumeWorkspaceId(
              { workspace_id: 17 },
              { workspace_id: 22 },
              '9'
            );
            console.log(JSON.stringify({ workspaceId }));
            """
        )

        self.assertEqual(payload["workspaceId"], "17")

    def test_quick_resume_switches_to_restored_workspace_before_continue(self):
        payload = _run_resume_script(
            """
            (async () => {
              const mixin = ctx.window.axonChatResumeMixin();
              const app = {
                chatProjectId: '',
                interruptedSession: {
                  session_id: 'sess-17',
                  workspace_id: 17,
                  project_name: 'dashpro',
                },
                projects: [{ id: 17, name: 'dashpro' }],
                chatMessages: [],
                currentWorkspaceRunActive() { return false; },
                preferredResumeAutoSession() { return null; },
                ensureWorkspaceTab(id) {
                  this.ensuredWorkspace = String(id || '');
                  return this.ensuredWorkspace;
                },
                activateWorkspaceTab(id) {
                  this.chatProjectId = String(id || '');
                  this.activatedWorkspace = this.chatProjectId;
                },
                $nextTick() { return Promise.resolve(); },
                isExplicitResumeText() { return true; },
                removeInterruptedSessionMessages() {
                  this.removedInterruptedMessages = true;
                },
                sendChatSilent(message, mode, extraPayload) {
                  this.sent = { message, mode, extraPayload };
                  return Promise.resolve();
                },
              };
              Object.assign(app, mixin);
              await app.quickResume();
              console.log(JSON.stringify({
                chatProjectId: app.chatProjectId,
                ensuredWorkspace: app.ensuredWorkspace,
                activatedWorkspace: app.activatedWorkspace,
                sent: app.sent,
                resumeBannerDismissed: app.resumeBannerDismissed === true,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["chatProjectId"], "17")
        self.assertEqual(payload["ensuredWorkspace"], "17")
        self.assertEqual(payload["activatedWorkspace"], "17")
        self.assertEqual(payload["sent"]["message"], "please continue")
        self.assertEqual(payload["sent"]["mode"], "agent")
        self.assertEqual(payload["sent"]["extraPayload"]["resume_session_id"], "sess-17")
        self.assertEqual(payload["sent"]["extraPayload"]["project_id"], 17)
        self.assertTrue(payload["resumeBannerDismissed"])

    def test_choose_initial_workspace_restore_candidate_prefers_newest_running_auto_session(self):
        payload = _run_resume_script(
            """
            const mixin = ctx.window.axonChatResumeMixin();
            const app = {
              windowPinnedProjectId: '',
              workspaceTabLabel(id) {
                return id === '1' ? 'bkkinnovationhub' : `Workspace ${id}`;
              },
            };
            Object.assign(app, mixin);
            const candidate = app.chooseInitialWorkspaceRestoreCandidate({
              autoSessions: [
                { session_id: 'older', workspace_id: '2', status: 'running', updated_at: '2026-04-04T09:00:00Z' },
                { session_id: 'newer', workspace_id: '1', status: 'running', updated_at: '2026-04-04T11:00:00Z' },
              ],
              interruptedSession: { session_id: 'paused', workspace_id: '3' },
              savedProjectId: '2',
            });
            console.log(JSON.stringify(candidate));
            """
        )

        self.assertEqual(payload["workspaceId"], "1")
        self.assertEqual(payload["source"], "auto_session")
        self.assertIn("bkkinnovationhub", payload["reason"])

    def test_choose_initial_workspace_restore_candidate_skips_autoswitch_for_pinned_workspace_window(self):
        payload = _run_resume_script(
            """
            const mixin = ctx.window.axonChatResumeMixin();
            const app = {
              windowPinnedProjectId: '2',
            };
            Object.assign(app, mixin);
            const candidate = app.chooseInitialWorkspaceRestoreCandidate({
              autoSessions: [
                { session_id: 'auto-bkk', workspace_id: '1', status: 'running', updated_at: '2026-04-04T11:00:00Z' },
              ],
              interruptedSession: { session_id: 'paused', workspace_id: '3' },
              savedProjectId: '2',
            });
            console.log(JSON.stringify({ candidate }));
            """
        )

        self.assertIsNone(payload["candidate"])

    def test_shared_console_prefers_newest_running_auto_workspace_on_boot_restore(self):
        payload = _run_resume_script(
            """
            const mixin = ctx.window.axonChatResumeMixin();
            const app = {
              windowPinnedProjectId: '',
              workspaceTabLabel(id) {
                return id === '1' ? 'bkkinnovationhub' : (id === '2' ? 'dashpro' : `Workspace ${id}`);
              },
            };
            Object.assign(app, mixin);
            const candidate = app.chooseInitialWorkspaceRestoreCandidate({
              savedProjectId: '2',
              interruptedSession: { workspace_id: '2', updated_at: '2026-04-04T17:00:00Z' },
              autoSessions: [
                { workspace_id: '1', workspace_name: 'bkkinnovationhub', status: 'running', updated_at: '2026-04-04T18:00:00Z' },
              ],
            });
            console.log(JSON.stringify(candidate));
            """
        )

        self.assertEqual(payload["workspaceId"], "1")
        self.assertEqual(payload["source"], "auto_session")
        self.assertIn("latest active run", payload["reason"])

    def test_pinned_workspace_console_does_not_autoswitch_on_boot_restore(self):
        payload = _run_resume_script(
            """
            const mixin = ctx.window.axonChatResumeMixin();
            const app = {
              windowPinnedProjectId: '2',
            };
            Object.assign(app, mixin);
            const candidate = app.chooseInitialWorkspaceRestoreCandidate({
              savedProjectId: '2',
              interruptedSession: { workspace_id: '1' },
              autoSessions: [
                { workspace_id: '1', status: 'running', updated_at: '2026-04-04T18:00:00Z' },
              ],
            });
            console.log(JSON.stringify({ candidate }));
            """
        )

        self.assertIsNone(payload["candidate"])


if __name__ == "__main__":
    unittest.main()
