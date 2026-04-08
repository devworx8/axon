from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_SURFACE_DIRECTOR_JS = ROOT / "ui/js/voice-surface-director.js"


def _run_voice_surface_director_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{ open: (...args) => {{ ctx.openCalls.push(args); }} }},
          console,
          setInterval: () => 1,
          clearInterval: () => {{}},
          setTimeout: () => 1,
          clearTimeout: () => {{}},
          openCalls: [],
        }};
        ctx.globalThis = ctx;
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(VOICE_SURFACE_DIRECTOR_JS))}, 'utf8'), ctx);
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


class VoiceSurfaceDirectorFrontendTests(unittest.TestCase):
    def test_sync_surface_director_auto_focuses_browser_surface_once(self):
        payload = _run_voice_surface_director_script(
            """
            const mixin = ctx.window.axonVoiceSurfaceDirectorMixin();
            const app = {
              showVoiceOrb: true,
              focusCalls: [],
              voiceOperatorSurfaceCards() {
                return [
                  {
                    key: 'browser:https://preview.axon.local',
                    kind: 'web',
                    path: 'https://preview.axon.local',
                    eyebrow: 'Browser surface',
                    title: 'Preview',
                    detail: 'Axon attached a live workspace page.',
                    status: 'Live',
                    action: 'Open live page',
                  },
                ];
              },
              voiceArtifactEntries() { return []; },
              ensureWorkspacePreviewLayout(forceWide) {
                this.focusCalls.push(forceWide);
              },
            };
            Object.assign(app, mixin);
            app.syncVoiceSurfaceDirector({ force: true });
            app.syncVoiceSurfaceDirector({ force: true });
            console.log(JSON.stringify({
              spotlight: app.voiceSurfaceSpotlight(),
              focusCalls: app.focusCalls,
            }));
            """
        )

        self.assertEqual(payload["spotlight"]["type"], "browser")
        self.assertEqual(payload["focusCalls"], [True])

    def test_sync_surface_director_auto_opens_new_artifact_when_viewer_is_closed(self):
        payload = _run_voice_surface_director_script(
            """
            const mixin = ctx.window.axonVoiceSurfaceDirectorMixin();
            const app = {
              showVoiceOrb: true,
              chatLoading: true,
              opened: [],
              voiceFileViewer: { open: false },
              voiceOperatorSurfaceCards() { return []; },
              voiceArtifactEntries() {
                return [
                  {
                    key: 'pdf:/tmp/report.pdf',
                    kind: 'pdf',
                    path: '/tmp/report.pdf',
                    title: 'report.pdf',
                    detail: '/tmp/report.pdf',
                  },
                ];
              },
              openVoiceFileViewer(path, kind) {
                this.opened.push({ path, kind });
              },
            };
            Object.assign(app, mixin);
            app.syncVoiceSurfaceDirector({ force: true });
            app.syncVoiceSurfaceDirector({ force: true });
            console.log(JSON.stringify({ opened: app.opened }));
            """
        )

        self.assertEqual(payload["opened"], [{"path": "/tmp/report.pdf", "kind": "pdf"}])

    def test_sync_surface_director_prioritizes_approval_gate(self):
        payload = _run_voice_surface_director_script(
            """
            const mixin = ctx.window.axonVoiceSurfaceDirectorMixin();
            const app = {
              showVoiceOrb: true,
              terminal: { approvalRequired: true },
              voiceApprovalSummary() {
                return 'Terminal approval required before Axon can continue.';
              },
              voiceOperatorSurfaceCards() {
                return [
                  {
                    key: 'terminal:/tmp/project',
                    kind: 'folder',
                    path: '/tmp/project',
                    eyebrow: 'Console terminal',
                    title: 'Live PTY shell',
                    detail: 'npm run build',
                    status: 'Running',
                    action: 'Open folder',
                  },
                ];
              },
              voiceArtifactEntries() { return []; },
            };
            Object.assign(app, mixin);
            app.syncVoiceSurfaceDirector({ force: true });
            console.log(JSON.stringify(app.voiceSurfaceSpotlight()));
            """
        )

        self.assertEqual(payload["type"], "approval")
        self.assertEqual(payload["title"], "Approval required")

    def test_sync_surface_director_phase_drives_terminal_then_artifact(self):
        payload = _run_voice_surface_director_script(
            """
            const mixin = ctx.window.axonVoiceSurfaceDirectorMixin();
            const app = {
              showVoiceOrb: true,
              chatLoading: true,
              liveOperator: { active: true, phase: 'execute', detail: 'Running npm test before verification.' },
              voiceConversation: {},
              opened: [],
              focusCalls: [],
              runtimeSyncs: 0,
              voiceTerminalSessionActive() { return true; },
              voiceTerminalTraceActive() { return true; },
              syncVoiceCommandCenterRuntime() { this.runtimeSyncs += 1; },
              focusInteractiveTerminalViewport(view) { this.focusCalls.push(view); },
              voiceOperatorSurfaceCards() {
                return [
                  {
                    key: 'terminal:/tmp/project',
                    kind: 'folder',
                    path: '/tmp/project',
                    eyebrow: 'Console terminal',
                    title: 'Live PTY shell',
                    detail: 'npm test',
                    status: 'Running',
                    action: 'Open folder',
                  },
                ];
              },
              voiceArtifactEntries() { return []; },
              openVoiceFileViewer(path, kind) {
                this.opened.push({ path, kind });
              },
            };
            Object.assign(app, mixin);
            const executeSpotlight = app.syncVoiceSurfaceDirector({ force: true });
            const pinnedAfterExecute = app.voiceConversation.terminalPinned === true;
            app.liveOperator.phase = 'verify';
            app.liveOperator.detail = 'Axon surfaced a verification artifact.';
            app.voiceArtifactEntries = () => [
              {
                key: 'pdf:/tmp/report.pdf',
                kind: 'pdf',
                path: '/tmp/report.pdf',
                title: 'report.pdf',
                detail: '/tmp/report.pdf',
              },
            ];
            const verifySpotlight = app.syncVoiceSurfaceDirector({ force: true });
            console.log(JSON.stringify({
              executeType: executeSpotlight.type,
              verifyType: verifySpotlight.type,
              pinnedAfterExecute,
              pinnedAfterVerify: app.voiceConversation.terminalPinned === true,
              opened: app.opened,
              focusCalls: app.focusCalls,
              runtimeSyncs: app.runtimeSyncs,
            }));
            """
        )

        self.assertEqual(payload["executeType"], "terminal")
        self.assertEqual(payload["verifyType"], "artifact")
        self.assertTrue(payload["pinnedAfterExecute"])
        self.assertFalse(payload["pinnedAfterVerify"])
        self.assertEqual(payload["opened"], [{"path": "/tmp/report.pdf", "kind": "pdf"}])
        self.assertEqual(payload["focusCalls"], ["voice"])
        self.assertGreaterEqual(payload["runtimeSyncs"], 2)

    def test_focus_voice_surface_spotlight_handles_terminal_without_path(self):
        payload = _run_voice_surface_director_script(
            """
            const mixin = ctx.window.axonVoiceSurfaceDirectorMixin();
            const app = {
              voiceConversation: {},
              focusCalls: [],
              runtimeSyncs: 0,
              syncVoiceCommandCenterRuntime() { this.runtimeSyncs += 1; },
              focusInteractiveTerminalViewport(view) { this.focusCalls.push(view); },
            };
            Object.assign(app, mixin);
            app.focusVoiceSurfaceSpotlight({
              type: 'terminal',
              key: 'terminal:/tmp/project',
              title: 'Live PTY shell',
            });
            console.log(JSON.stringify({
              pinned: app.voiceConversation.terminalPinned === true,
              focusCalls: app.focusCalls,
              runtimeSyncs: app.runtimeSyncs,
            }));
            """
        )

        self.assertTrue(payload["pinned"])
        self.assertEqual(payload["focusCalls"], ["voice"])
        self.assertEqual(payload["runtimeSyncs"], 1)


if __name__ == "__main__":
    unittest.main()
