from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_LIVE_FEED_JS = ROOT / "ui/js/dashboard-live-feed.js"
CHAT_AUTO_STREAM_JS = ROOT / "ui/js/chat-auto-stream.js"
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"


def _run_node_script(script_body: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script_body)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class DashboardLiveFeedTests(unittest.TestCase):
    def test_live_feed_snapshot_syncs_auto_state_into_workspace_and_preview(self):
        payload = _run_node_script(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const ctx = {{
              window: {{}},
              console,
              queueMicrotask: (cb) => cb(),
              requestAnimationFrame: (cb) => cb(),
            }};
            ctx.window.requestAnimationFrame = ctx.requestAnimationFrame;
            vm.createContext(ctx);
            for (const path of [
              {json.dumps(str(WORKSPACE_RUNS_JS))},
              {json.dumps(str(CHAT_AUTO_STREAM_JS))},
              {json.dumps(str(DASHBOARD_LIVE_FEED_JS))},
            ]) {{
              vm.runInContext(fs.readFileSync(path, 'utf8'), ctx);
            }}

            const app = {{
              chatProjectId: '42',
              chatMessages: [],
              autoSessions: [],
              liveFeed: {{}},
              terminal: {{ sessions: [], activeSessionId: 99 }},
              browserActions: {{}},
              connectionState: {{}},
              dashRecentActivity: [],
              workspacePreview: {{ loading: false }},
              isMobile: false,
              currentWorkspaceAutoSession() {{
                return (this.autoSessions || []).find(
                  item => String(item?.workspace_id || '') === String(this.chatProjectId || '')
                ) || null;
              }},
              currentWorkspacePreview() {{
                return null;
              }},
              autonomousConsoleActive() {{
                return true;
              }},
              ensureWorkspacePreview() {{
                this.previewStarted = true;
              }},
              sortAutoSessions(rows) {{
                return rows;
              }},
              stopDesktopPreview() {{}},
              loadTerminalSessionDetail() {{
                this.terminalDetailLoaded = true;
              }},
              scrollChat() {{}},
              $nextTick(callback) {{
                if (callback) callback();
              }},
            }};

            Object.assign(
              app,
              ctx.window.axonWorkspaceRunsMixin(),
              ctx.window.axonChatAutoStreamMixin(),
              ctx.window.axonDashboardLiveFeedMixin(),
            );

            app.handleLiveFeedSnapshot({{
              connection: {{ state: 'connected', label: 'Connected' }},
              operator: {{
                active: true,
                mode: 'auto',
                phase: 'execute',
                title: 'Running Auto session',
                detail: 'Axon is applying a verified sandbox change.',
                workspace_id: '42',
                auto_session_id: 'auto-42',
                updated_at: '2026-04-06T00:05:00Z',
                feed: [
                  {{
                    id: 'feed-1',
                    phase: 'execute',
                    title: 'Running Auto session',
                    detail: 'Axon is applying a verified sandbox change.',
                    at: '2026-04-06T00:05:00Z',
                  }},
                ],
              }},
              auto_sessions: [
                {{
                  session_id: 'auto-42',
                  workspace_id: '42',
                  workspace_name: 'Hope',
                  status: 'running',
                  title: 'Repair the site shell',
                  detail: 'Axon is working in the sandbox.',
                  updated_at: '2026-04-06T00:05:00Z',
                  runtime: {{ label: 'CLI Agent', model: 'gpt-5.4' }},
                }},
              ],
              terminal: {{
                sessions: [{{ id: 7, title: 'npm run dev' }}],
                active_session_id: 7,
              }},
              activity: [
                {{ id: 9, event_type: 'note', summary: 'Auto session started' }},
              ],
            }});

            const runState = app.workspaceRunStateFor('42');
            console.log(JSON.stringify({{
              liveFeedConnected: app.liveFeed.connected,
              runLoading: runState.loading,
              runTitle: runState.liveOperator.title,
              autoSessionId: app.autoSessions[0]?.session_id || '',
              noticeStreaming: app.chatMessages[0]?.streaming || false,
              previewStarted: !!app.previewStarted,
              terminalDetailLoaded: !!app.terminalDetailLoaded,
              activityCount: app.dashRecentActivity.length,
            }}));
            """
        )

        self.assertTrue(payload["liveFeedConnected"])
        self.assertTrue(payload["runLoading"])
        self.assertEqual(payload["runTitle"], "Running Auto session")
        self.assertEqual(payload["autoSessionId"], "auto-42")
        self.assertTrue(payload["noticeStreaming"])
        self.assertTrue(payload["previewStarted"])
        self.assertFalse(payload["terminalDetailLoaded"])
        self.assertEqual(payload["activityCount"], 1)


if __name__ == "__main__":
    unittest.main()
