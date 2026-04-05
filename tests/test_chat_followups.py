from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOLLOWUPS_JS = ROOT / "ui/js/chat-followups.js"


def _build_followups(response: str) -> list[str]:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync({json.dumps(str(FOLLOWUPS_JS))}, 'utf8');
        const ctx = {{}};
        vm.createContext(ctx);
        vm.runInContext(code, ctx);
        const result = ctx.axonBuildFollowUpSuggestions({json.dumps(response)}, '');
        console.log(JSON.stringify(result));
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


class ChatFollowUpSuggestionTests(unittest.TestCase):
    def test_extracts_explicit_reply_prompt_without_false_continue_chip(self):
        suggestions = _build_followups(
            "If you want that, reply with `use CLI fallback` and I will continue."
        )

        self.assertEqual(suggestions, ["use CLI fallback", "Inspect related files", "Check blockers"])

    def test_recognizes_standalone_continue_response(self):
        suggestions = _build_followups("Continue.")

        self.assertEqual(suggestions, ["→ Continue", "Inspect related files", "Check blockers"])


if __name__ == "__main__":
    unittest.main()
