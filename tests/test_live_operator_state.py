from __future__ import annotations

import copy
import unittest

from axon_api.services import live_operator_state


class LiveOperatorStateTests(unittest.TestCase):
    def test_set_live_operator_merges_rapid_repeated_phase_updates(self):
        snapshot = copy.deepcopy(live_operator_state.LIVE_OPERATOR_SNAPSHOT)

        live_operator_state.set_live_operator(
            active=True,
            mode="agent",
            phase="plan",
            title="Thinking through the task",
            detail="Checking the live deck stream path.",
            workspace_id=42,
            preserve_started=True,
            live_operator_snapshot=snapshot,
        )
        started_at = snapshot["started_at"]

        live_operator_state.set_live_operator(
            active=True,
            mode="agent",
            phase="plan",
            title="Thinking through the task",
            detail="Narrowing the issue to repeated plan updates.",
            workspace_id=42,
            preserve_started=True,
            live_operator_snapshot=snapshot,
        )

        self.assertEqual(len(snapshot["feed"]), 1)
        self.assertEqual(snapshot["feed"][0]["detail"], "Narrowing the issue to repeated plan updates.")
        self.assertEqual(snapshot["detail"], "Narrowing the issue to repeated plan updates.")
        self.assertEqual(snapshot["started_at"], started_at)

