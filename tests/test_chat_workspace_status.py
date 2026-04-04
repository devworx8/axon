from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_WORKSPACE_STATUS_JS = ROOT / "ui/js/chat-workspace-status.js"


def _run_status_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync({json.dumps(str(CHAT_WORKSPACE_STATUS_JS))}, 'utf8');
        const ctx = {{
          window: {{}},
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


class ChatWorkspaceStatusTests(unittest.TestCase):
    def test_branch_prefers_repo_branch_in_agent_mode_and_worktree_branch_in_auto_mode(self):
        payload = _run_status_script(
            """
            const mixin = ctx.window.axonChatWorkspaceStatusMixin();
            const app = {
              chatProjectId: '7',
              chatProject: { id: 7, name: 'dashpro', git_branch: 'main' },
              _workspaceEnv: { git_branch: 'feature/live-branch' },
              agentMode: true,
              liveOperator: { workspaceId: '7' },
              currentWorkspaceRunActive() { return true; },
              autonomousConsoleActive() { return false; },
              currentWorkspaceAutoSession() {
                return { session_id: 'auto-7', branch_name: 'auto/patch-7' };
              },
            };
            Object.assign(app, mixin);

            const agentBranch = app.currentWorkspaceBranchName();
            const agentTitle = app.workspaceBranchTitle();
            app.autonomousConsoleActive = () => true;
            const autoBranch = app.currentWorkspaceBranchName();
            const autoTitle = app.workspaceBranchTitle();

            console.log(JSON.stringify({
              agentBranch,
              agentTitle,
              autoBranch,
              autoTitle,
              visible: app.shouldShowWorkspaceBranch(),
            }));
            """
        )

        self.assertEqual(payload["agentBranch"], "feature/live-branch")
        self.assertIn("Repo branch", payload["agentTitle"])
        self.assertEqual(payload["autoBranch"], "auto/patch-7")
        self.assertIn("Auto worktree branch", payload["autoTitle"])
        self.assertTrue(payload["visible"])


if __name__ == "__main__":
    unittest.main()
