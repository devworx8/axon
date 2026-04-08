from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_DEPLOY_GUIDANCE_JS = ROOT / "ui/js/chat-deploy-guidance.js"
WORKSPACE_RUNS_JS = ROOT / "ui/js/workspace-runs.js"
COMPANION_JS = ROOT / "ui/js/companion.js"


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
          {json.dumps(str(WORKSPACE_RUNS_JS))},
          {json.dumps(str(CHAT_DEPLOY_GUIDANCE_JS))},
          {json.dumps(str(COMPANION_JS))},
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


class ChatDeployGuidanceTests(unittest.TestCase):
    def test_mission_helpers_prefer_active_global_run_when_no_workspace_is_selected(self):
        payload = _run_script(
            """
            const app = {
              chatProjectId: '',
              chatProject: null,
              projects: [{ id: 7, name: 'Hope' }],
              dashTopProjects: [{ id: 7, name: 'Hope', health: 58 }],
              liveOperator: {},
              liveOperatorFeed: [],
              workspaceTabLabel(id) {
                if (String(id) === '42') return 'Companion Native';
                return `Workspace ${id}`;
              },
              dashboardWeakestWorkspace() {
                return this.dashTopProjects[0];
              },
            };
            Object.assign(app, ctx.window.axonWorkspaceRunsMixin(), ctx.window.axonCompanionMixin());
            app.setWorkspaceRunLoading('', true);
            app.beginWorkspaceLiveOperator('', 'agent', 'Inspect runtime health');
            app.patchWorkspaceLiveOperator('', {
              active: true,
              phase: 'plan',
              title: 'Inspecting the task',
              detail: 'Axon is checking the runtime lane before acting.',
            });

            console.log(JSON.stringify({
              missionWorkspaceId: app.missionWorkspaceId(),
              missionWorkspaceLabel: app.missionWorkspaceLabel(),
              missionWorkspaceRunActive: app.missionWorkspaceRunActive(),
              missionLiveOperator: app.missionLiveOperator(),
            }));
            """
        )

        self.assertIsNone(payload["missionWorkspaceId"])
        self.assertEqual(payload["missionWorkspaceLabel"], "Global")
        self.assertTrue(payload["missionWorkspaceRunActive"])
        self.assertEqual(payload["missionLiveOperator"]["title"], "Inspecting the task")
        self.assertEqual(payload["missionLiveOperator"]["workspaceName"], "Global")

    def test_mission_helpers_follow_active_workspace_run_when_present(self):
        payload = _run_script(
            """
            const app = {
              chatProjectId: '',
              chatProject: null,
              projects: [{ id: 42, name: 'Companion Native' }],
              dashTopProjects: [{ id: 7, name: 'Hope', health: 58 }],
              liveOperator: {},
              liveOperatorFeed: [],
              workspaceTabLabel(id) {
                if (String(id) === '42') return 'Companion Native';
                return `Workspace ${id}`;
              },
              dashboardWeakestWorkspace() {
                return this.dashTopProjects[0];
              },
            };
            Object.assign(app, ctx.window.axonWorkspaceRunsMixin(), ctx.window.axonCompanionMixin());
            app.setWorkspaceRunLoading('42', true);
            app.beginWorkspaceLiveOperator('42', 'agent', 'Inspect workspace');
            app.patchWorkspaceLiveOperator('42', {
              active: true,
              phase: 'execute',
              title: 'Running workspace verification',
              detail: 'Axon is validating the selected workspace.',
              workspaceId: '42',
            });

            console.log(JSON.stringify({
              missionWorkspaceId: app.missionWorkspaceId(),
              missionWorkspaceLabel: app.missionWorkspaceLabel(),
              missionWorkspaceRunActive: app.missionWorkspaceRunActive(),
              missionLiveOperator: app.missionLiveOperator(),
            }));
            """
        )

        self.assertEqual(payload["missionWorkspaceId"], 42)
        self.assertEqual(payload["missionWorkspaceLabel"], "Companion Native")
        self.assertTrue(payload["missionWorkspaceRunActive"])
        self.assertEqual(payload["missionLiveOperator"]["title"], "Running workspace verification")
        self.assertEqual(payload["missionLiveOperator"]["workspaceName"], "Companion Native")

    def test_prepare_deploy_lane_promotes_agent_cli_and_full_access(self):
        payload = _run_script(
            """
            const app = {
              chatInput: '',
              chatMessages: [
                { role: 'user', content: 'can you please start a project on vercel and deploy the project' },
              ],
              chatProjectId: '7',
              chatProject: { id: 7, name: 'Hope' },
              mode: 'auto',
              backend: 'api',
              permission: 'default',
              settingsForm: {},
              runtimeStatus: { cli_model: 'gpt-5.4' },
              _calls: [],
              _toasts: [],
              activePrimaryConversationMode() { return this.mode; },
              currentRuntimeBackend() { return this.backend; },
              permissionPresetKey() { return this.permission; },
              currentCliRuntimeModel() { return 'gpt-5.4'; },
              chooseConversationModeAgent() { this.mode = 'agent'; this._calls.push('mode'); },
              async applyCliRuntimeModel(model) { this.backend = 'cli'; this._calls.push(`cli:${model}`); },
              async setPermissionPreset(preset) { this.permission = preset; this._calls.push(`perm:${preset}`); },
              workspaceTabLabel() { return 'Hope'; },
              switchTab(tab) { this._calls.push(`tab:${tab}`); },
              showToast(message) { this._toasts.push(message); },
              $refs: { chatComposer: { focus() {} } },
              $nextTick(callback) { if (callback) callback(); },
            };
            Object.assign(app, ctx.window.axonChatDeployGuidanceMixin());

            app.prepareVercelDeployLane().then((result) => {
              console.log(JSON.stringify({
                result,
                visible: app.vercelDeployGuidanceVisible(),
                ready: app.vercelDeployLaneReady(),
                chatInput: app.chatInput,
                calls: app._calls,
                toasts: app._toasts,
              }));
            });
            """
        )

        self.assertTrue(payload["result"])
        self.assertTrue(payload["visible"])
        self.assertTrue(payload["ready"])
        self.assertIn("Vercel project", payload["chatInput"])
        self.assertIn("mode", payload["calls"])
        self.assertIn("cli:gpt-5.4", payload["calls"])
        self.assertIn("perm:full_access", payload["calls"])
        self.assertIn("Deploy lane ready: Agent + CLI + Full access.", payload["toasts"])

    def test_prepare_expo_lane_adds_terminal_approval_and_eas_prompt(self):
        payload = _run_script(
            """
            const app = {
              chatInput: '',
              chatMessages: [
                { role: 'user', content: 'Deploy the mobile companion app to EAS' },
              ],
              chatProjectId: '9',
              chatProject: { id: 9, name: 'Companion Native' },
              mode: 'auto',
              backend: 'api',
              permission: 'default',
              settingsForm: { terminal_default_mode: 'read_only' },
              runtimeStatus: { cli_model: 'gpt-5.4' },
              _calls: [],
              _toasts: [],
              _settingsPayloads: [],
              activePrimaryConversationMode() { return this.mode; },
              currentRuntimeBackend() { return this.backend; },
              permissionPresetKey() { return this.permission; },
              currentCliRuntimeModel() { return 'gpt-5.4'; },
              chooseConversationModeAgent() { this.mode = 'agent'; this._calls.push('mode'); },
              async applyCliRuntimeModel(model) { this.backend = 'cli'; this._calls.push(`cli:${model}`); },
              async setPermissionPreset(preset) { this.permission = preset; this._calls.push(`perm:${preset}`); },
              async api(method, url, payload = {}) {
                this._settingsPayloads.push({ method, url, payload });
                if (url === '/api/settings' && payload.terminal_default_mode) {
                  this.settingsForm.terminal_default_mode = payload.terminal_default_mode;
                }
                return {};
              },
              async loadRuntimeStatus() { this._calls.push('runtime'); },
              workspaceTabLabel() { return 'Companion Native'; },
              switchTab(tab) { this._calls.push(`tab:${tab}`); },
              showToast(message) { this._toasts.push(message); },
              $refs: { chatComposer: { focus() {} } },
              $nextTick(callback) { if (callback) callback(); },
            };
            Object.assign(app, ctx.window.axonChatDeployGuidanceMixin());

            app.prepareExpoDeployLane().then((result) => {
              console.log(JSON.stringify({
                result,
                visible: app.expoDeployGuidanceVisible(),
                ready: app.expoDeployLaneReady(),
                chatInput: app.chatInput,
                terminalMode: app.settingsForm.terminal_default_mode,
                calls: app._calls,
                settingsPayloads: app._settingsPayloads,
                toasts: app._toasts,
              }));
            });
            """
        )

        self.assertTrue(payload["result"])
        self.assertTrue(payload["visible"])
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["terminalMode"], "approval_required")
        self.assertIn("EAS_NO_VCS=1", payload["chatInput"])
        self.assertIn("mode", payload["calls"])
        self.assertIn("cli:gpt-5.4", payload["calls"])
        self.assertIn("perm:full_access", payload["calls"])
        self.assertIn("runtime", payload["calls"])
        self.assertEqual(payload["settingsPayloads"][0]["payload"]["terminal_default_mode"], "approval_required")
        self.assertIn("Expo lane ready: Agent + CLI + Full access + terminal approval.", payload["toasts"])

    def test_companion_deploy_quick_op_prepares_then_prompts(self):
        payload = _run_script(
            """
            const app = {
              chatInput: '',
              chatMessages: [],
              chatProjectId: '7',
              chatProject: { id: 7, name: 'Hope' },
              mode: 'ask',
              backend: 'api',
              permission: 'default',
              _calls: [],
              _prompts: [],
              activePrimaryConversationMode() { return this.mode; },
              currentRuntimeBackend() { return this.backend; },
              permissionPresetKey() { return this.permission; },
              currentCliRuntimeModel() { return 'gpt-5.4'; },
              workspaceTabLabel() { return 'Hope'; },
              attentionBucketCount() { return 0; },
              canQuickResume() { return false; },
              previewReadyForCurrentWorkspace() { return false; },
              chooseConversationModeAgent() { this.mode = 'agent'; this._calls.push('mode'); },
              async applyCliRuntimeModel(model) { this.backend = 'cli'; this._calls.push(`cli:${model}`); },
              async setPermissionPreset(preset) { this.permission = preset; this._calls.push(`perm:${preset}`); },
              async runChatQuickAction(action = {}) { this._prompts.push(action.prompt || ''); return true; },
              showToast() {},
              $refs: { chatComposer: { focus() {} } },
              $nextTick(callback) { if (callback) callback(); },
            };
            Object.assign(app, ctx.window.axonChatDeployGuidanceMixin(), ctx.window.axonCompanionMixin());

            const firstDeploy = app.missionQuickOps().find((item) => item.id === 'mission-deploy');
            app.runMissionQuickOp(firstDeploy).then(() => {
              const readyDeploy = app.missionQuickOps().find((item) => item.id === 'mission-deploy');
              app.runMissionQuickOp(readyDeploy).then(() => {
                console.log(JSON.stringify({
                  firstLabel: firstDeploy.label,
                  readyLabel: readyDeploy.label,
                  calls: app._calls,
                  chatInput: app.chatInput,
                  prompts: app._prompts,
                }));
              });
            });
            """
        )

        self.assertEqual(payload["firstLabel"], "Prepare deploy lane")
        self.assertEqual(payload["readyLabel"], "Deploy via Axon")
        self.assertIn("mode", payload["calls"])
        self.assertIn("cli:gpt-5.4", payload["calls"])
        self.assertIn("perm:full_access", payload["calls"])
        self.assertIn("Vercel project", payload["chatInput"])
        self.assertEqual(len(payload["prompts"]), 1)
        self.assertIn("deploy it from the real workspace", payload["prompts"][0].lower())


if __name__ == "__main__":
    unittest.main()
