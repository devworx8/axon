from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = ROOT / "ui/js/dashboard.js"
RUNTIME_SELECTOR_JS = ROOT / "ui/js/runtime_selector.js"


def _run_runtime_selector_script(body: str):
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
        vm.runInContext(fs.readFileSync({json.dumps(str(RUNTIME_SELECTOR_JS))}, 'utf8'), ctx);
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


class RuntimeSelectorFrontendTests(unittest.TestCase):
    def test_runtime_picker_can_preview_ollama_backend_from_cli_state(self):
        payload = _run_runtime_selector_script(
            """
            const mixin = ctx.window.axonRuntimeSelectorMixin();
            const app = {
              settingsForm: {
                ai_backend: 'cli',
                api_provider: 'deepseek',
                cli_runtime_model: 'gpt-5.4',
              },
              runtimeStatus: {
                local_models_enabled: true,
                selected_api_provider: { provider_id: 'deepseek' },
                cli_model: 'gpt-5.4',
              },
              ollamaModels: [],
              loadCalls: 0,
              loadOllamaModels() { this.loadCalls += 1; },
              providerValue() { return ''; },
              selectedApiProviderModel() { return ''; },
            };
            Object.assign(app, mixin);
            app.prepareRuntimePicker();
            app.selectRuntimePickerBackend('ollama');
            console.log(JSON.stringify({
              backend: app.runtimePickerBackend(),
              loadCalls: app.loadCalls,
              backends: app.runtimePickerBackends().map((item) => item.id),
            }));
            """
        )

        self.assertEqual(payload["backend"], "ollama")
        self.assertEqual(payload["loadCalls"], 1)
        self.assertEqual(payload["backends"], ["ollama", "cli", "api"])

    def test_runtime_picker_hides_ollama_backend_when_local_models_disabled(self):
        payload = _run_runtime_selector_script(
            """
            const mixin = ctx.window.axonRuntimeSelectorMixin();
            const app = {
              settingsForm: {
                ai_backend: 'api',
                api_provider: 'deepseek',
              },
              runtimeStatus: {
                local_models_enabled: false,
                selected_api_provider: { provider_id: 'deepseek' },
              },
              ollamaModels: [],
              loadCalls: 0,
              loadOllamaModels() { this.loadCalls += 1; },
              providerValue() { return ''; },
              selectedApiProviderModel() { return 'deepseek-reasoner'; },
            };
            Object.assign(app, mixin);
            app.prepareRuntimePicker();
            app.selectRuntimePickerBackend('ollama');
            console.log(JSON.stringify({
              backend: app.runtimePickerBackend(),
              loadCalls: app.loadCalls,
              backends: app.runtimePickerBackends().map((item) => item.id),
            }));
            """
        )

        self.assertEqual(payload["backend"], "api")
        self.assertEqual(payload["loadCalls"], 0)
        self.assertEqual(payload["backends"], ["cli", "api"])

    def test_runtime_picker_saves_deepseek_model_through_shared_provider_mapping(self):
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');

            const ctx = {{
              window: {{}},
              console,
              axonDashboardPreviewMixin: () => ({{}}),
            }};
            ctx.globalThis = ctx;
            vm.createContext(ctx);
            for (const path of [
              {json.dumps(str(DASHBOARD_JS))},
              {json.dumps(str(RUNTIME_SELECTOR_JS))},
            ]) {{
              vm.runInContext(fs.readFileSync(path, 'utf8'), ctx);
            }}
            (async () => {{
              const app = {{
                chatModelOpen: true,
                settingsForm: {{
                  ai_backend: 'api',
                  api_provider: 'deepseek',
                  deepseek_api_model: 'deepseek-reasoner',
                }},
                runtimeStatus: {{
                  selected_api_provider: {{
                    provider_id: 'deepseek',
                    api_model: 'deepseek-reasoner',
                  }},
                  api_providers: [
                    {{
                      id: 'deepseek',
                      model: 'deepseek-reasoner',
                    }},
                  ],
                }},
                apiCalls: [],
                async api(method, path, payload) {{
                  this.apiCalls.push({{ method, path, payload }});
                  return {{ updated: Object.keys(payload || {{}}) }};
                }},
                async loadRuntimeStatus() {{
                  this.loadCount = (this.loadCount || 0) + 1;
                }},
                showToast() {{}},
              }};
              Object.assign(
                app,
                ctx.window.axonDashboardMixin(),
                ctx.window.axonRuntimeSelectorMixin(),
              );
              app.loadRuntimeStatus = async function() {{
                this.loadCount = (this.loadCount || 0) + 1;
              }};
              app.runtimePickerDraftModel = 'deepseek-chat';
              await app.saveApiRuntimeModel();
              console.log(JSON.stringify({{
                modelField: app.providerModelField('deepseek'),
                savedModel: app.settingsForm.deepseek_api_model,
                payload: app.apiCalls[0]?.payload || {{}},
                loadCount: app.loadCount || 0,
                chatModelOpen: app.chatModelOpen,
              }}));
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
        payload = json.loads(result.stdout)

        self.assertEqual(payload["modelField"], "deepseek_api_model")
        self.assertEqual(payload["savedModel"], "deepseek-chat")
        self.assertEqual(
            payload["payload"],
            {
                "ai_backend": "api",
                "api_provider": "deepseek",
                "deepseek_api_model": "deepseek-chat",
            },
        )
        self.assertEqual(payload["loadCount"], 1)
        self.assertFalse(payload["chatModelOpen"])


if __name__ == "__main__":
    unittest.main()
