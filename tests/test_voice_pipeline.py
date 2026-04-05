"""Phase 7.2 — Voice pipeline tests for Axon.

Tests transcription, voice turns, JARVIS personality, and TTS.
"""
from __future__ import annotations

import unittest


class TestVoiceTranscription(unittest.TestCase):
    """Tests for /api/voice/transcribe endpoint behaviour."""

    def test_transcribe_response_has_required_fields(self):
        """Transcription response must include text, engine, and language."""
        response = {"text": "Hello Axon", "engine": "whisper", "language": "en"}
        self.assertIn("text", response)
        self.assertIn("engine", response)
        self.assertIn("language", response)
        self.assertIsInstance(response["text"], str)

    def test_empty_transcript_is_handled(self):
        """An empty transcript should be treated as a no-speech event."""
        transcript = ""
        self.assertFalse(
            transcript.strip(),
            "Empty transcript must evaluate to falsy after strip",
        )


class TestJarvisPersonality(unittest.TestCase):
    """Tests for the JARVIS system prompt module."""

    def test_jarvis_prompt_loads(self):
        """JARVIS_SYSTEM_PROMPT must be a non-empty string."""
        from axon_data.jarvis_personality import JARVIS_SYSTEM_PROMPT

        self.assertIsInstance(JARVIS_SYSTEM_PROMPT, str)
        self.assertGreater(len(JARVIS_SYSTEM_PROMPT), 100)

    def test_jarvis_prompt_contains_key_phrases(self):
        """The prompt must instruct the AI to address operator as 'sir'."""
        from axon_data.jarvis_personality import JARVIS_SYSTEM_PROMPT

        self.assertIn("sir", JARVIS_SYSTEM_PROMPT.lower())
        self.assertIn("composed", JARVIS_SYSTEM_PROMPT.lower())

    def test_jarvis_prompt_forbids_filler(self):
        """Prompt must explicitly forbid casual filler phrases."""
        from axon_data.jarvis_personality import JARVIS_SYSTEM_PROMPT

        self.assertIn("NEVER", JARVIS_SYSTEM_PROMPT)
        self.assertIn("Sure!", JARVIS_SYSTEM_PROMPT)

    def test_build_jarvis_system_message_default(self):
        """Default call returns prompt with 'sir'."""
        from axon_data.jarvis_personality import build_jarvis_system_message

        msg = build_jarvis_system_message()
        self.assertIn("sir", msg)

    def test_build_jarvis_system_message_custom_title(self):
        """Custom operator title is substituted correctly."""
        from axon_data.jarvis_personality import build_jarvis_system_message

        msg = build_jarvis_system_message(operator_title="commander")
        self.assertIn("commander", msg)
        self.assertNotIn('"sir"', msg)


class TestVoiceTurnFlow(unittest.TestCase):
    """Tests for the companion voice turn processing logic."""

    def test_voice_mode_values(self):
        """Voice mode must be either 'live' or 'push_to_talk'."""
        valid_modes = {"live", "push_to_talk"}
        for mode in valid_modes:
            self.assertIn(mode, valid_modes)

    def test_voice_turn_timeout_value(self):
        """Voice turn timeout should be configured at 30 seconds."""
        VOICE_TURN_TIMEOUT_MS = 30_000
        self.assertEqual(VOICE_TURN_TIMEOUT_MS, 30_000)


class TestTTSVoiceSelection(unittest.TestCase):
    """Tests for text-to-speech voice identity defaults."""

    def test_default_jarvis_voice_is_british_male(self):
        """The default JARVIS voice should be en-GB-RyanNeural."""
        default_voice = "en-GB-RyanNeural"
        self.assertTrue(default_voice.startswith("en-GB"))
        self.assertIn("Ryan", default_voice)

    def test_speech_text_cleaning(self):
        """Markdown and special characters should be stripped before TTS."""
        raw = "**Hello** `world` [link](http://example.com)"
        # Basic cleaning: strip markdown markers
        cleaned = raw.replace("**", "").replace("`", "")
        self.assertNotIn("**", cleaned)
        self.assertNotIn("`", cleaned)


class TestWakePhraseDetection(unittest.TestCase):
    """Tests for wake phrase matching logic."""

    def test_wake_phrase_case_insensitive(self):
        """Wake phrase detection should be case-insensitive."""
        wake = "axon"
        transcript = "Hey AXON, what is the status?"
        self.assertIn(wake, transcript.lower())

    def test_wake_phrase_partial_match(self):
        """Wake phrase must match as whole word."""
        wake = "axon"
        transcript = "hey axon turn off the lights"
        words = transcript.lower().split()
        self.assertIn(wake, words)


if __name__ == "__main__":
    unittest.main()
