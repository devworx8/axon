from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps/companion-native"
VOICE_COMMAND_UTILS_TS = APP_ROOT / "src/features/axon/voiceCommandUtils.ts"
LOCAL_TSC = APP_ROOT / "node_modules/.bin/tsc"


def _compile_voice_command_utils() -> Path:
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        subprocess.run(
            [
                str(LOCAL_TSC),
                "--target",
                "ES2020",
                "--module",
                "commonjs",
                "--moduleResolution",
                "node",
                "--outDir",
                str(output_dir),
                str(VOICE_COMMAND_UTILS_TS),
            ],
            cwd=APP_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        compiled = next(output_dir.rglob("voiceCommandUtils.js"))
        persisted = Path(tempfile.mkdtemp()) / "voiceCommandUtils.js"
        persisted.write_text(compiled.read_text(encoding="utf-8"), encoding="utf-8")
        return persisted


def _run_voice_command_script(body: str):
    compiled_path = _compile_voice_command_utils()
    script = textwrap.dedent(
        f"""
        const utils = require({json.dumps(str(compiled_path))});
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


class MobileVoiceCommandUtilsTests(unittest.TestCase):
    def test_detect_wake_phrase_accepts_common_lead_in_words_and_punctuation(self):
        payload = _run_voice_command_script(
            """
            const result = utils.detectWakePhrase('Hey Axon, open the dashboard', 'Axon');
            process.stdout.write(JSON.stringify(result));
            """
        )

        self.assertTrue(payload["matched"])
        self.assertEqual(payload["command"], "open the dashboard")

    def test_detect_wake_phrase_opens_follow_up_window_for_wake_only_utterance(self):
        payload = _run_voice_command_script(
            """
            const result = utils.detectWakePhrase('Axon', 'Axon');
            process.stdout.write(JSON.stringify(result));
            """
        )

        self.assertTrue(payload["matched"])
        self.assertEqual(payload["command"], "")

    def test_detect_wake_phrase_rejects_non_prefix_mentions(self):
        payload = _run_voice_command_script(
            """
            const result = utils.detectWakePhrase('Can you ask Axon to open the dashboard', 'Axon');
            process.stdout.write(JSON.stringify(result));
            """
        )

        self.assertFalse(payload["matched"])
        self.assertEqual(payload["command"], "")

    def test_no_speech_error_is_treated_as_non_fatal(self):
        payload = _run_voice_command_script(
            """
            const result = utils.isNoSpeechTranscriptError(new Error('Axon could not detect speech in that recording.'));
            process.stdout.write(JSON.stringify({ result }));
            """
        )

        self.assertTrue(payload["result"])


if __name__ == "__main__":
    unittest.main()
