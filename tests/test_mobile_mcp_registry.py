from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from axon_api.services import mobile_mcp_registry


class MobileMcpRegistryHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_health_summary_skips_seed_when_builtin_registry_exists(self):
        existing_servers = [
            {"server_key": str(server["server_key"]), "name": str(server["name"])}
            for server in mobile_mcp_registry.BUILTIN_SERVERS
        ]
        existing_capabilities = [
            {"capability_key": str(capability["capability_key"])}
            for capability in mobile_mcp_registry.BUILTIN_CAPABILITIES
        ]
        existing_sessions = [
            {"session_key": f"session:{server['server_key']}"}
            for server in mobile_mcp_registry.BUILTIN_SERVERS
        ]

        with patch.object(
            mobile_mcp_registry,
            "list_mcp_servers",
            AsyncMock(return_value=existing_servers),
        ), patch.object(
            mobile_mcp_registry,
            "list_mcp_capabilities",
            AsyncMock(return_value=existing_capabilities),
        ), patch.object(
            mobile_mcp_registry,
            "list_mcp_sessions",
            AsyncMock(return_value=existing_sessions),
        ), patch.object(
            mobile_mcp_registry,
            "seed_mcp_registry",
            AsyncMock(),
        ) as seed_registry, patch.object(
            mobile_mcp_registry,
            "get_all_settings",
            AsyncMock(return_value={"mobile_break_glass_enabled": "0"}),
        ):
            payload = await mobile_mcp_registry.registry_health_summary(object())

        seed_registry.assert_not_awaited()
        self.assertEqual(len(payload["servers"]), len(existing_servers))
        self.assertEqual(len(payload["capabilities"]), len(existing_capabilities))
        self.assertEqual(len(payload["sessions"]), len(existing_sessions))
        self.assertFalse(payload["break_glass_enabled"])

    async def test_registry_health_summary_seeds_when_builtin_session_is_missing(self):
        existing_servers = [
            {"server_key": str(server["server_key"]), "name": str(server["name"])}
            for server in mobile_mcp_registry.BUILTIN_SERVERS
        ]
        existing_capabilities = [
            {"capability_key": str(capability["capability_key"])}
            for capability in mobile_mcp_registry.BUILTIN_CAPABILITIES
        ]
        seeded_snapshot = {
            "servers": existing_servers,
            "capabilities": existing_capabilities,
            "sessions": [{"session_key": f"session:{server['server_key']}"} for server in mobile_mcp_registry.BUILTIN_SERVERS],
        }

        with patch.object(
            mobile_mcp_registry,
            "list_mcp_servers",
            AsyncMock(return_value=existing_servers),
        ), patch.object(
            mobile_mcp_registry,
            "list_mcp_capabilities",
            AsyncMock(return_value=existing_capabilities),
        ), patch.object(
            mobile_mcp_registry,
            "list_mcp_sessions",
            AsyncMock(return_value=[]),
        ), patch.object(
            mobile_mcp_registry,
            "seed_mcp_registry",
            AsyncMock(return_value=seeded_snapshot),
        ) as seed_registry, patch.object(
            mobile_mcp_registry,
            "get_all_settings",
            AsyncMock(return_value={"mobile_break_glass_enabled": "1"}),
        ):
            payload = await mobile_mcp_registry.registry_health_summary(object())

        seed_registry.assert_awaited_once()
        self.assertEqual(payload["sessions"], seeded_snapshot["sessions"])
        self.assertTrue(payload["break_glass_enabled"])


if __name__ == "__main__":
    unittest.main()
