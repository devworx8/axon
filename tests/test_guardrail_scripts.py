from __future__ import annotations

from datetime import date
import unittest

from scripts.guardrails import common


class GuardrailCommonTests(unittest.TestCase):
    def test_ratcheted_file_budget_detects_growth_and_stale_manifest(self):
        self.assertIsNone(common.evaluate_ratcheted_file("server.py", 10, 10))
        self.assertIn(
            "exceeds ratchet budget 10",
            common.evaluate_ratcheted_file("server.py", 11, 10) or "",
        )
        self.assertIn(
            "lower the manifest to 9",
            common.evaluate_ratcheted_file("server.py", 9, 10) or "",
        )

    def test_critical_hotspot_change_requires_shrink_or_active_waiver(self):
        self.assertIsNone(
            common.evaluate_critical_hotspot_change(
                "server.py",
                lines=9,
                budget=10,
                has_active_waiver=False,
            )
        )
        self.assertIsNone(
            common.evaluate_critical_hotspot_change(
                "server.py",
                lines=10,
                budget=10,
                has_active_waiver=True,
            )
        )
        self.assertIn(
            "without shrinking below ratchet budget 10",
            common.evaluate_critical_hotspot_change(
                "server.py",
                lines=10,
                budget=10,
                has_active_waiver=False,
            )
            or "",
        )
        self.assertIn(
            "exceeds ratchet budget 10",
            common.evaluate_critical_hotspot_change(
                "server.py",
                lines=11,
                budget=10,
                has_active_waiver=True,
            )
            or "",
        )

    def test_active_waiver_files_accepts_only_non_expired_critical_hotspots(self):
        active, errors = common.active_waiver_files(
            {
                "waivers": [
                    {
                        "file": "server.py",
                        "reason": "urgent production fix",
                        "expiry": "2026-04-10",
                        "follow_up": "Extract the agent routes",
                    }
                ]
            },
            {"server.py": {"max_lines": 10}},
            today=date(2026, 4, 3),
        )

        self.assertEqual(errors, [])
        self.assertEqual(set(active.keys()), {"server.py"})

    def test_active_waiver_files_rejects_expired_and_unknown_entries(self):
        active, errors = common.active_waiver_files(
            {
                "waivers": [
                    {
                        "file": "server.py",
                        "reason": "urgent production fix",
                        "expiry": "2026-04-01",
                        "follow_up": "Extract the agent routes",
                    },
                    {
                        "file": "unknown.py",
                        "reason": "urgent production fix",
                        "expiry": "2026-04-10",
                        "follow_up": "Extract the unknown module",
                    },
                ]
            },
            {"server.py": {"max_lines": 10}},
            today=date(2026, 4, 3),
        )

        self.assertEqual(active, {})
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("expired on 2026-04-01" in err for err in errors))
        self.assertTrue(any("not a critical hotspot" in err for err in errors))
