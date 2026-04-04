from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from axon_api.routes import mobile_vault


class MobileVaultRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def test_mobile_vault_status_returns_session_state(self):
        @asynccontextmanager
        async def fake_get_db():
            yield object()

        with patch.object(mobile_vault, "require_companion_context", AsyncMock(return_value=(None, None, {"id": 7, "name": "Phone"}))), \
             patch.object(mobile_vault, "get_db", fake_get_db), \
             patch.object(mobile_vault.devvault, "vault_is_setup", AsyncMock(return_value=True)), \
             patch.object(mobile_vault, "vault_biometric_state", AsyncMock(return_value={"enabled": True, "available": True, "expires_at": "2026-05-01T00:00:00Z", "last_used_at": None})), \
             patch.object(mobile_vault.devvault.VaultSession, "is_unlocked", return_value=True), \
             patch.object(mobile_vault.devvault.VaultSession, "ttl_remaining", return_value=1800):
            result = await mobile_vault.mobile_vault_status(SimpleNamespace())

        self.assertTrue(result["is_setup"])
        self.assertTrue(result["is_unlocked"])
        self.assertEqual(result["ttl_remaining"], 1800)
        self.assertTrue(result["biometric_reunlock_available"])

    async def test_mobile_vault_unlock_raises_401_on_invalid_credentials(self):
        @asynccontextmanager
        async def fake_get_db():
            yield object()

        with patch.object(mobile_vault, "require_companion_context", AsyncMock(return_value=(None, None, {"id": 7, "name": "Phone"}))), \
             patch.object(mobile_vault, "get_db", fake_get_db), \
             patch.object(mobile_vault.devvault, "unlock_vault", AsyncMock(return_value=(False, "Invalid credentials"))):
            with self.assertRaises(HTTPException) as ctx:
                await mobile_vault.mobile_vault_unlock(
                    SimpleNamespace(),
                    mobile_vault.MobileVaultUnlockRequest(
                        master_password="bad",
                        totp_code="000000",
                        remember_me=False,
                    ),
                )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Invalid credentials", str(ctx.exception.detail))

    async def test_mobile_vault_biometric_unlock_requires_enabled_device_state(self):
        @asynccontextmanager
        async def fake_get_db():
            yield object()

        with patch.object(mobile_vault, "require_companion_context", AsyncMock(return_value=(None, None, {"id": 7, "name": "Phone"}))), \
             patch.object(mobile_vault, "get_db", fake_get_db), \
             patch.object(mobile_vault, "vault_biometric_state", AsyncMock(return_value={"enabled": False, "available": False})):
            with self.assertRaises(HTTPException) as ctx:
                await mobile_vault.mobile_vault_biometric_unlock(
                    SimpleNamespace(),
                    mobile_vault.MobileVaultBiometricUnlockRequest(
                        master_password="correct horse battery staple",
                        remember_me=False,
                        verified_via="biometric_local",
                    ),
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("not enabled", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
