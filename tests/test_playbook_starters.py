from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCES_JS = ROOT / "ui/js/resources.js"
STARTERS_JSON = ROOT / "ui/js/playbook-starters.json"


def _run_resources_script(body: str):
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const ctx = {{
          window: {{}},
          console,
          fetch: async () => {{
            const payload = fs.readFileSync({json.dumps(str(STARTERS_JSON))}, 'utf8');
            return {{
              ok: true,
              async json() {{
                return JSON.parse(payload);
              }},
            }};
          }},
        }};
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(RESOURCES_JS))}, 'utf8'), ctx);
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


class PlaybookStarterTests(unittest.TestCase):
    def test_load_prompts_merges_virtual_starter_pack(self):
        payload = _run_resources_script(
            """
            (async () => {
              const mixin = ctx.window.axonResourcesMixin();
              const app = {
                prompts: [],
                api(method, path) {
                  if (method === 'GET' && path === '/api/prompts') {
                    return Promise.resolve([
                      {
                        id: 7,
                        title: 'Saved prompt',
                        content: 'Existing user prompt',
                        tags: 'custom',
                        project_name: '',
                        used_count: 2,
                        meta: {},
                      },
                    ]);
                  }
                  throw new Error(`Unexpected ${method} ${path}`);
                },
                showToast(message) {
                  this.toast = message;
                },
              };
              Object.assign(app, mixin);
              await app.loadPrompts();
              console.log(JSON.stringify({
                count: app.prompts.length,
                titles: app.prompts.map((item) => item.title),
                starterCount: app.prompts.filter((item) => item.meta?.starter).length,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertIn("Saved prompt", payload["titles"])
        self.assertIn("Execution playbook", payload["titles"])
        self.assertIn("Grounded brief", payload["titles"])
        self.assertIn("ECD visual layout", payload["titles"])
        self.assertGreaterEqual(payload["starterCount"], 8)
        self.assertEqual(payload["count"], payload["starterCount"] + 1)

    def test_seed_starter_playbook_loads_docs_drop_template(self):
        payload = _run_resources_script(
            """
            (async () => {
              const mixin = ctx.window.axonResourcesMixin();
              const app = {
                newPrompt: { title: '', content: '', tags: '' },
                showAddPrompt: false,
                toast: '',
                showToast(message) {
                  this.toast = message;
                },
              };
              Object.assign(app, mixin);
              await app.seedStarterPlaybook('docs-drop');
              console.log(JSON.stringify({
                title: app.newPrompt.title,
                tags: app.newPrompt.tags,
                content: app.newPrompt.content,
                showAddPrompt: app.showAddPrompt,
                toast: app.toast,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["title"], "Docs drop")
        self.assertIn("docs/*.md file", payload["content"])
        self.assertIn("docs,readme,handoff", payload["tags"])
        self.assertTrue(payload["showAddPrompt"])
        self.assertEqual(payload["toast"], "Starter playbook loaded")

    def test_seed_starter_playbook_loads_ecd_visual_layout_template(self):
        payload = _run_resources_script(
            """
            (async () => {
              const mixin = ctx.window.axonResourcesMixin();
              const app = {
                newPrompt: { title: '', content: '', tags: '' },
                showAddPrompt: false,
                toast: '',
                showToast(message) {
                  this.toast = message;
                },
              };
              Object.assign(app, mixin);
              await app.seedStarterPlaybook('ecd-visual-layout');
              console.log(JSON.stringify({
                title: app.newPrompt.title,
                tags: app.newPrompt.tags,
                content: app.newPrompt.content,
                showAddPrompt: app.showAddPrompt,
                toast: app.toast,
              }));
            })().catch(error => {
              console.error(error);
              process.exit(1);
            });
            """
        )

        self.assertEqual(payload["title"], "ECD visual layout")
        self.assertIn("design/ecd/", payload["content"])
        self.assertIn("single-page A4 PDF", payload["content"])
        self.assertIn("existing DOCX submission", payload["content"])
        self.assertIn("create_ecd_cover_page", payload["content"])
        self.assertIn("create_ecd_support_poster", payload["content"])
        self.assertIn("ecd,design,svg,pdf,education", payload["tags"])
        self.assertTrue(payload["showAddPrompt"])
        self.assertEqual(payload["toast"], "Starter playbook loaded")


if __name__ == "__main__":
    unittest.main()
