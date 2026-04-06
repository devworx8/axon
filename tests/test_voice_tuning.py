from __future__ import annotations

import unittest

from axon_api.services import voice_tuning


class VoiceTuningTests(unittest.TestCase):
    def test_normalized_voice_rate_accepts_percent_delta(self):
        self.assertAlmostEqual(voice_tuning.normalized_voice_rate("+5%"), 1.05)

    def test_normalized_voice_pitch_accepts_percent_delta(self):
        self.assertAlmostEqual(voice_tuning.normalized_voice_pitch("+4%"), 1.04)

    def test_azure_voice_attrs_preserve_legacy_percent_payloads(self):
        self.assertEqual(voice_tuning.azure_voice_rate_attr("+5%"), "+5%")
        self.assertEqual(voice_tuning.azure_voice_pitch_attr("+4%"), "+4%")


if __name__ == "__main__":
    unittest.main()
