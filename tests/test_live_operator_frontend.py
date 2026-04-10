from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"
LIVE_OPERATOR_JS = ROOT / "ui/js/live-operator.js"


def _run_live_operator_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          console,
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        for (const path of [
          {json.dumps(str(WORKSPACE_RUNS_JS))},
          {json.dumps(str(LIVE_OPERATOR_JS))},
        ]) {{
          vm.runInContext(fs.readFileSync(path, 'utf8'), ctx);
        }}
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


class LiveOperatorFrontendTests(unittest.TestCase):
    def test_update_live_operator_syncs_voice_surfaces_after_state_patch(self):
        payload = _run_live_operator_script(
            """
            const app = {
              chatProjectId: '42',
              chatProject: { path: '/tmp/workspace' },
              liveOperator: { active: false, phase: '' },
              liveOperatorFeed: [],
              desktopPreview: { enabled: false },
              voiceRuntimePhases: [],
              surfacePhases: [],
              currentWorkspaceAutoSession() { return null; },
              browserSourcePath() { return '/tmp/workspace'; },
              prettyToolName(name = '') { return String(name || '').trim() || 'tool'; },
              resetVoiceFileRevealState() {},
              clearVoiceSurfaceHistory() {},
              hudResetOperatorTrace() {},
              setAgentStage() {},
              hudProcessAgentEvent() {},
              syncVoiceCommandCenterRuntime() {
                this.voiceRuntimePhases.push(String(this.liveOperator?.phase || ''));
              },
              syncVoiceSurfaceDirector() {
                this.surfacePhases.push(String(this.liveOperator?.phase || ''));
              },
            };

            Object.assign(
              app,
              ctx.window.axonWorkspaceRunsMixin(),
              ctx.window.axonLiveOperatorMixin(),
            );

            app.updateLiveOperator('agent', {
              type: 'thinking',
              chunk: 'Axon is analysing the request.',
            }, '42');

            const runState = app.workspaceRunStateFor('42');
            console.log(JSON.stringify({
              livePhase: runState.liveOperator.phase,
              feedPhase: runState.liveOperatorFeed[runState.liveOperatorFeed.length - 1]?.phase || '',
              runtimePhases: app.voiceRuntimePhases,
              surfacePhases: app.surfacePhases,
            }));
            """
        )

        self.assertEqual(payload["livePhase"], "plan")
        self.assertEqual(payload["feedPhase"], "plan")
        self.assertEqual(payload["runtimePhases"], ["plan"])
        self.assertEqual(payload["surfacePhases"], ["plan"])

    def test_repeated_thinking_updates_merge_into_single_feed_entry(self):
        payload = _run_live_operator_script(
            """
            const app = {
              chatProjectId: '42',
              liveOperator: { active: false, phase: '' },
              liveOperatorFeed: [],
              desktopPreview: { enabled: false },
              currentWorkspaceAutoSession() { return null; },
              prettyToolName(name = '') { return String(name || '').trim() || 'tool'; },
              resetVoiceFileRevealState() {},
              clearVoiceSurfaceHistory() {},
              hudResetOperatorTrace() {},
              setAgentStage() {},
              hudProcessAgentEvent() {},
              syncVoiceCommandCenterRuntime() {},
              syncVoiceSurfaceDirector() {},
            };

            Object.assign(
              app,
              ctx.window.axonWorkspaceRunsMixin(),
              ctx.window.axonLiveOperatorMixin(),
            );

            app.updateLiveOperator('agent', {
              type: 'thinking',
              chunk: 'Checking the live deck render path.',
            }, '42');
            app.updateLiveOperator('agent', {
              type: 'thinking',
              chunk: 'Narrowing the break to the stream subscriber.',
            }, '42');

            const runState = app.workspaceRunStateFor('42');
            console.log(JSON.stringify({
              feedCount: runState.liveOperatorFeed.length,
              detail: runState.liveOperatorFeed[runState.liveOperatorFeed.length - 1]?.detail || '',
              liveDetail: runState.liveOperator.detail || '',
            }));
            """
        )

        self.assertEqual(payload["feedCount"], 2)
        self.assertEqual(payload["detail"], "Narrowing the break to the stream subscriber.")
        self.assertEqual(payload["liveDetail"], payload["detail"])

    def test_text_updates_switch_operator_into_writing_result_state(self):
        payload = _run_live_operator_script(
            """
            const app = {
              chatProjectId: '42',
              liveOperator: { active: true, phase: 'plan', title: 'Thinking through the task', detail: 'Checking the task.' },
              liveOperatorFeed: [],
              desktopPreview: { enabled: false },
              currentWorkspaceAutoSession() { return null; },
              prettyToolName(name = '') { return String(name || '').trim() || 'tool'; },
              resetVoiceFileRevealState() {},
              clearVoiceSurfaceHistory() {},
              hudResetOperatorTrace() {},
              setAgentStage() {},
              hudProcessAgentEvent() {},
              syncVoiceCommandCenterRuntime() {},
              syncVoiceSurfaceDirector() {},
            };

            Object.assign(
              app,
              ctx.window.axonWorkspaceRunsMixin(),
              ctx.window.axonLiveOperatorMixin(),
            );

            app.patchWorkspaceLiveOperator('42', app.liveOperator);
            app.updateLiveOperator('agent', {
              type: 'text',
              chunk: 'Streaming the final answer now so the operator deck stays live.',
            }, '42');

            const runState = app.workspaceRunStateFor('42');
            const last = runState.liveOperatorFeed[runState.liveOperatorFeed.length - 1] || {};
            console.log(JSON.stringify({
              phase: runState.liveOperator.phase,
              title: runState.liveOperator.title,
              detail: runState.liveOperator.detail,
              feedPhase: last.phase || '',
              feedTitle: last.title || '',
              feedDetail: last.detail || '',
            }));
            """
        )

        self.assertEqual(payload["phase"], "verify")
        self.assertEqual(payload["title"], "Writing the result")
        self.assertEqual(payload["feedPhase"], "verify")
        self.assertEqual(payload["feedTitle"], "Writing the result")
        self.assertIn("Streaming the final answer now", payload["detail"])
        self.assertEqual(payload["feedDetail"], payload["detail"])


if __name__ == "__main__":
    unittest.main()
