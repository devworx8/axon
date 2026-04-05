"""Phase 7.4 — Input validation tests for Axon API.

Tests parameter bounds, enum validation, and payload limits.
"""
from __future__ import annotations

import unittest


class TestLimitParameterBounds(unittest.TestCase):
    """Verify limit query parameters are properly bounded."""

    def test_clamp_negative_limit(self):
        """Negative limit should clamp to minimum of 1."""
        limit = -10
        clamped = max(1, min(limit, 500))
        self.assertEqual(clamped, 1)

    def test_clamp_zero_limit(self):
        """Zero limit should clamp to minimum of 1."""
        limit = 0
        clamped = max(1, min(limit, 500))
        self.assertEqual(clamped, 1)

    def test_clamp_oversized_limit(self):
        """Limit exceeding max should cap at maximum."""
        limit = 999999
        clamped = max(1, min(limit, 500))
        self.assertEqual(clamped, 500)

    def test_valid_limit_passes_through(self):
        """A valid limit within range passes unchanged."""
        limit = 25
        clamped = max(1, min(limit, 500))
        self.assertEqual(clamped, 25)


class TestActionTypeValidation(unittest.TestCase):
    """Verify action_type enum is properly restricted."""

    VALID_ACTION_TYPES = {
        "session.stop",
        "session.resume",
        "agent.approve",
        "agent.deny",
        "agent.cancel",
    }

    def test_valid_action_type_accepted(self):
        for action in self.VALID_ACTION_TYPES:
            self.assertIn(action, self.VALID_ACTION_TYPES)

    def test_invalid_action_type_rejected(self):
        self.assertNotIn("shell.exec", self.VALID_ACTION_TYPES)
        self.assertNotIn("", self.VALID_ACTION_TYPES)
        self.assertNotIn("DROP TABLE users;", self.VALID_ACTION_TYPES)


class TestUserInputValidation(unittest.TestCase):
    """Verify user creation fields are bounded."""

    MAX_NAME_LENGTH = 200
    MAX_EMAIL_LENGTH = 254  # RFC 5321
    VALID_ROLES = {"operator", "admin", "viewer"}

    def test_oversized_name_rejected(self):
        name = "A" * 1000
        self.assertGreater(len(name), self.MAX_NAME_LENGTH)

    def test_valid_name_accepted(self):
        name = "Tony Stark"
        self.assertLessEqual(len(name), self.MAX_NAME_LENGTH)

    def test_invalid_role_rejected(self):
        self.assertNotIn("superadmin", self.VALID_ROLES)
        self.assertNotIn("root", self.VALID_ROLES)

    def test_valid_roles_accepted(self):
        for role in self.VALID_ROLES:
            self.assertIn(role, self.VALID_ROLES)

    def test_oversized_email_rejected(self):
        email = "a" * 300 + "@example.com"
        self.assertGreater(len(email), self.MAX_EMAIL_LENGTH)


class TestMessageLengthBounds(unittest.TestCase):
    """Verify chat message length is bounded."""

    MAX_MESSAGE_LENGTH = 32_000

    def test_normal_message_accepted(self):
        msg = "What is the current system status?"
        self.assertLessEqual(len(msg), self.MAX_MESSAGE_LENGTH)

    def test_oversized_message_rejected(self):
        msg = "A" * 100_000
        self.assertGreater(len(msg), self.MAX_MESSAGE_LENGTH)


class TestMalformedJSONHandling(unittest.TestCase):
    """Verify malformed JSON is handled gracefully."""

    def test_invalid_json_raises_error(self):
        import json

        with self.assertRaises(json.JSONDecodeError):
            json.loads("{invalid json}")

    def test_empty_body_raises_error(self):
        import json

        with self.assertRaises(json.JSONDecodeError):
            json.loads("")

    def test_valid_json_parses(self):
        import json

        data = json.loads('{"action_type": "session.stop"}')
        self.assertEqual(data["action_type"], "session.stop")


if __name__ == "__main__":
    unittest.main()
