from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_AUTO_STREAM_JS = ROOT / "ui/js/chat-auto-stream.js"
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"


def _run_node_script(script_body: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script_body)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "node script failed")
    return json.loads(result.stdout)


class ChatAutoStreamTests(unittest.TestCase):
    def test_auto_notice_renders_live_steps_and_streaming_state(self):
        payload = _run_node_script(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const code = fs.readFileSync({json.dumps(str(CHAT_AUTO_STREAM_JS))}, 'utf8');
            const ctx = {{
              window: {{}},
              console,
              encodeURIComponent,
              requestAnimationFrame: (cb) => cb(),
            }};
            ctx.window.requestAnimationFrame = ctx.requestAnimationFrame;
            vm.createContext(ctx);
            vm.runInContext(code, ctx);

            const mixin = ctx.window.axonChatAutoStreamMixin();
            const app = {{
              chatProjectId: '42',
              chatMessages: [],
              autoSessions: [{{
                session_id: 'auto-42',
                workspace_id: '42',
                workspace_name: 'bkkinnovationhub',
                status: 'running',
                title: 'Scan the project and advice',
                detail: 'Axon is checking the current stack and safeguards.',
                branch_name: 'auto/scan-project',
                runtime: {{ label: 'Codex CLI', model: 'gpt-5.4' }},
                updated_at: '2026-04-03T20:17:00Z',
              }}],
              currentWorkspaceAutoSession() {{
                return this.autoSessions[0];
              }},
              autoSessionLiveFeed() {{
                return [
                  {{
                    phase: 'plan',
                    title: 'Planning inside Auto sandbox',
                    detail: 'Checking the repo and picking the safest first move.',
                    at: '2026-04-03T20:17:01Z',
                  }},
                  {{
                    phase: 'execute',
                    title: 'Applying file change',
                    detail: 'Updating the dashboard copy and controls.',
                    at: '2026-04-03T20:17:02Z',
                  }},
                ];
              }},
              autoSessionThreadMode(session) {{
                return String(session.status || '') === 'running' ? 'auto' : 'recover';
              }},
              liveOperatorWorkspaceName() {{
                return 'bkkinnovationhub';
              }},
              scrollChat() {{
                this.scrolled = true;
              }},
              $nextTick(callback) {{
                if (callback) callback();
              }},
            }};
            Object.assign(app, mixin);
            app.syncAutoSessionNoticeForCurrentWorkspace();

            console.log(JSON.stringify(app.chatMessages[0]));
            """
        )

        self.assertTrue(payload["streaming"])
        self.assertEqual(payload["threadMode"], "auto")
        self.assertEqual(payload["modelLabel"], "Codex CLI · gpt-5.4")
        self.assertEqual(len(payload["workingBlocks"]), 2)
        self.assertEqual(payload["workingBlocks"][-1]["status"], "running")
        self.assertIn("auto/scan-project", payload["content"])
        self.assertIn("Scan the project and advice", payload["content"])

    def test_workspace_run_snapshot_keeps_auto_feed_after_review_handoff(self):
        payload = _run_node_script(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const code = fs.readFileSync({json.dumps(str(WORKSPACE_RUNS_JS))}, 'utf8');
            const ctx = {{
              window: {{}},
              console,
            }};
            vm.createContext(ctx);
            vm.runInContext(code, ctx);

            const mixin = ctx.window.axonWorkspaceRunsMixin();
            const app = {{
              chatProjectId: '42',
              stopDesktopPreview() {{}},
            }};
            Object.assign(app, mixin);

            app.syncWorkspaceLiveOperatorSnapshot({{
              active: false,
              mode: 'auto',
              phase: 'verify',
              title: 'Auto session ready for review',
              detail: 'Axon finished the sandbox pass and prepared a reviewable handoff.',
              workspace_id: '42',
              auto_session_id: 'auto-42',
              updated_at: '2026-04-03T20:20:00Z',
              feed: [
                {{
                  id: 'feed-1',
                  phase: 'verify',
                  title: 'Auto session ready for review',
                  detail: 'Axon finished the sandbox pass and prepared a reviewable handoff.',
                  at: '2026-04-03T20:20:00Z',
                }},
              ],
            }});

            const state = app.workspaceRunStateFor('42');
            console.log(JSON.stringify({{
              active: state.liveOperator.active,
              autoSessionId: state.liveOperator.autoSessionId,
              title: state.liveOperator.title,
              feedCount: state.liveOperatorFeed.length,
              feedTitle: state.liveOperatorFeed[0]?.title || '',
            }}));
            """
        )

        self.assertFalse(payload["active"])
        self.assertEqual(payload["autoSessionId"], "auto-42")
        self.assertEqual(payload["title"], "Auto session ready for review")
        self.assertEqual(payload["feedCount"], 1)
        self.assertEqual(payload["feedTitle"], "Auto session ready for review")

    def test_stop_active_workspace_run_stops_auto_session_and_stream_state(self):
        payload = _run_node_script(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const code = fs.readFileSync({json.dumps(str(CHAT_AUTO_STREAM_JS))}, 'utf8');
            const ctx = {{ window: {{}}, console, encodeURIComponent }};
            vm.createContext(ctx);
            vm.runInContext(code, ctx);

            const mixin = ctx.window.axonChatAutoStreamMixin();
            const controller = {{ aborted: false, abort() {{ this.aborted = true; }} }};
            const app = {{
              chatProjectId: '42',
              chatLoading: true,
              _chatAbortController: controller,
              liveOperator: {{ autoSessionId: 'auto-42' }},
              chatMessages: [{{ id: 'm1', streaming: true }}, {{ id: 'm2', streaming: false }}],
              autoSessions: [{{ session_id: 'auto-42', workspace_id: '42', status: 'running' }}],
              workspaceAutoSessionFor() {{ return this.autoSessions[0]; }},
              currentWorkspaceAutoSession() {{ return this.autoSessions[0]; }},
              async api(method, path) {{
                this.stopCall = {{ method, path }};
                return {{ session: {{ session_id: 'auto-42', workspace_id: '42', status: 'error', last_error: 'Stopped by user.' }} }};
              }},
              updateAutoSessionRecord(session) {{ this.updatedSession = session; this.autoSessions[0] = session; }},
              stopWorkspaceRun() {{ this.workspaceRunStopped = true; this.chatLoading = false; }},
              clearLiveOperator(delay, workspaceId) {{ this.cleared = {{ delay, workspaceId }}; }},
              showToast(message) {{ this.toast = message; }},
              loadWorkspacePreview() {{ this.previewReloaded = true; }},
            }};
            Object.assign(app, mixin);
            (async () => {{
              await app.stopActiveWorkspaceRun('42');
              console.log(JSON.stringify({{
                aborted: controller.aborted,
                apiPath: app.stopCall?.path || '',
                workspaceRunStopped: !!app.workspaceRunStopped,
                streamingCleared: app.chatMessages[0].streaming,
                toast: app.toast || '',
                sessionStatus: app.autoSessions[0]?.status || '',
                clearedWorkspaceId: app.cleared?.workspaceId || '',
              }}));
            }})().catch((error) => {{
              console.error(error);
              process.exit(1);
            }});
            """
        )

        self.assertTrue(payload["aborted"])
        self.assertEqual(payload["apiPath"], "/api/auto/auto-42/stop")
        self.assertTrue(payload["workspaceRunStopped"])
        self.assertFalse(payload["streamingCleared"])
        self.assertEqual(payload["toast"], "Run stopped")
        self.assertEqual(payload["sessionStatus"], "error")
        self.assertEqual(payload["clearedWorkspaceId"], "42")


if __name__ == "__main__":
    unittest.main()
