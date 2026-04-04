from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from axon_api.services import vault_secret_lookup


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _FakeCursor(self._rows)


class VaultSecretLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_named_secret_when_vault_is_unlocked(self):
        db = _FakeDb([{"id": 9, "name": "AXON_VERCEL_TOKEN"}])

        with patch.object(vault_secret_lookup.devvault.VaultSession, "get_key", return_value=b"vault-key"), \
             patch.object(
                 vault_secret_lookup.devvault,
                 "vault_get_secret",
                 AsyncMock(return_value={"password": "vercel_secret_token"}),
             ) as vault_get_secret:
            value = await vault_secret_lookup.vault_secret_value_by_name(
                db,
                secret_names=("AXON_VERCEL_TOKEN",),
            )

        vault_get_secret.assert_awaited_once_with(db, 9, b"vault-key")
        self.assertEqual(value, "vercel_secret_token")

    async def test_returns_empty_string_when_vault_is_locked(self):
        db = _FakeDb([{"id": 9, "name": "AXON_VERCEL_TOKEN"}])

        with patch.object(vault_secret_lookup.devvault.VaultSession, "get_key", return_value=None), \
             patch.object(vault_secret_lookup.devvault, "vault_get_secret", AsyncMock()) as vault_get_secret:
            value = await vault_secret_lookup.vault_secret_value_by_name(
                db,
                secret_names=("AXON_VERCEL_TOKEN",),
            )

        vault_get_secret.assert_not_awaited()
        self.assertEqual(value, "")


if __name__ == "__main__":
    unittest.main()
