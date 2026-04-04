from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from axon_api.services import sentry_bridge


class _FakeResponse:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class _FakeClientSession:
    last_url = ""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        _FakeClientSession.last_url = url
        return _FakeResponse(
            [
                {
                    "id": "issue-1",
                    "title": "Org issue",
                    "level": "error",
                    "culprit": "app/main.py",
                    "permalink": "https://sentry.io/organizations/edudash-pro/issues/1/",
                    "project": {"slug": "dashpro-mobile"},
                }
            ]
        )


class SentryBridgeTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _fake_db(self):
        yield object()

    async def test_poll_sentry_issues_falls_back_to_org_issue_feed(self):
        async def fake_get_setting(_db, key: str):
            values = {
                "sentry_api_token": "sntrys-example-token",
                "sentry_org_slug": "edudash-pro",
                "sentry_project_slugs": "",
            }
            return values.get(key, "")

        with patch.object(sentry_bridge, "get_db", self._fake_db), \
             patch.object(sentry_bridge, "get_setting", AsyncMock(side_effect=fake_get_setting)), \
             patch.object(sentry_bridge.aiohttp, "ClientSession", _FakeClientSession), \
             patch.object(sentry_bridge, "resolve_workspace_for_connector_signal", AsyncMock(return_value=2)) as resolve_workspace, \
             patch.object(sentry_bridge, "ingest_error_event", AsyncMock(return_value=11)) as ingest_error_event, \
             patch.object(sentry_bridge, "ingest_attention_signal", AsyncMock(return_value=None)) as ingest_attention_signal:
            payload = await sentry_bridge.poll_sentry_issues()

        self.assertEqual(_FakeClientSession.last_url, "https://sentry.io/api/0/organizations/edudash-pro/issues/")
        resolve_workspace.assert_awaited_once_with(
            unittest.mock.ANY,
            external_system="sentry",
            external_id="dashpro-mobile",
            project_name="dashpro-mobile",
        )
        ingest_error_event.assert_awaited_once()
        ingest_attention_signal.assert_awaited_once()
        self.assertEqual(payload, [{"id": 11, "title": "Org issue"}])


if __name__ == "__main__":
    unittest.main()
