from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExpoJsContractTests(unittest.TestCase):
    def test_load_expo_overview_force_refresh_appends_query_flag(self):
        script = textwrap.dedent(
            """
            const fs = require('fs');
            const vm = require('vm');

            const source = fs.readFileSync(process.argv[1], 'utf8');
            const context = { window: {}, console, setTimeout, clearTimeout };
            vm.createContext(context);
            vm.runInContext(source, context);

            const mixin = context.window.axonExpoMixin();
            const calls = [];
            mixin.api = async (method, url) => {
              calls.push({ method, url });
              return { status: 'ready', projects: [], builds: [], active_builds: [] };
            };
            mixin.timeAgo = () => 'now';
            mixin.expoLoading = false;
            mixin.expoError = '';
            mixin.expoOverview = {};

            (async () => {
              await mixin.loadExpoOverview(false);
              await mixin.loadExpoOverview(true);
              process.stdout.write(JSON.stringify(calls));
            })().catch((error) => {
              console.error(error && error.stack ? error.stack : String(error));
              process.exit(1);
            });
            """
        )

        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "ui/js/expo.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        calls = json.loads(result.stdout.strip())

        self.assertEqual(calls[0]["url"], "/api/devops/expo/overview")
        self.assertEqual(calls[1]["url"], "/api/devops/expo/overview?force_refresh=true")


if __name__ == "__main__":
    unittest.main()
