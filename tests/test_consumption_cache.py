"""Cached consumption must survive restarts and expired tokens; bills must not."""
import ast
from datetime import datetime, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo
import unittest

SOURCE = Path(__file__).parents[1] / "custom_components/alexela/coordinator.py"
METHODS = {
    "_async_update_data", "_has_snapshot", "_start_reauth", "_cached",
    "_async_load_snapshot", "_async_update_consumption",
}


class AuthError(Exception):
    pass


class ConnectionError_(Exception):
    pass


class ConfigEntryAuthFailed(Exception):
    pass


class UpdateFailed(Exception):
    pass


def has_consumption_data(data):
    return bool(data) and any(
        row.get("amount") is not None
        for block in data.get("electricityConsumption", [])
        for row in block.get("data", [])
    )


tree = ast.parse(SOURCE.read_text())
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name in METHODS]
assert {m.name for m in methods} == METHODS
namespace: dict[str, Any] = {
    "Any": Any, "datetime": datetime, "ZoneInfo": ZoneInfo,
    "AlexelaAuthError": AuthError, "AlexelaConnectionError": ConnectionError_,
    "ConfigEntryAuthFailed": ConfigEntryAuthFailed, "UpdateFailed": UpdateFailed,
    "has_consumption_data": has_consumption_data,
    "dt_util": SimpleNamespace(utcnow=lambda: datetime(2026, 11, 5, tzinfo=timezone.utc)),
    "_LOGGER": logging.getLogger("alexela-test"), "CONF_TOKEN": "token",
    "SNAPSHOT_KEY": "consumption_snapshot", "SNAPSHOT_SAVE_DELAY": 60,
    "NORD_POOL_SUMMARY_KEY": "nord_pool", "INVOICE_SUMMARY_KEY": "invoices",
    "INVOICE_PERIOD_START": "2000-01-01", "PORTAL_TIME_ZONE": "Europe/Riga",
    "summarize_invoices": lambda items, today: {"unpaid_count": len(items)},
}
exec(compile(ast.Module(body=methods, type_ignores=[]), "<coordinator>", "exec"), namespace)
Coordinator = type("Coordinator", (), {name: namespace[name] for name in METHODS})
Coordinator._async_fetch_consumption = lambda self: self.fetch()
Coordinator._async_invoice_reminders = AsyncMock()

PAYLOAD = {"electricityConsumption": [{"isTotal": True, "data": [
    {"timestamp": "2026-10-01T00:00:00", "amount": 120.5}]}]}


def make(stored=None):
    client = Coordinator()
    client._last_valid = None
    client._last_valid_at = None
    client._snapshot_loaded = False
    client.auth_failed = False
    client._snapshot_store = SimpleNamespace(
        async_load=AsyncMock(return_value=stored), async_delay_save=Mock())
    client.entry = SimpleNamespace(async_start_reauth=Mock(), data={})
    client.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    client.api = SimpleNamespace(
        async_refresh_jwt=AsyncMock(return_value=False),
        async_get_invoices=AsyncMock(return_value=[{"unpaid": 1}]), token="t")
    client.statistics = SimpleNamespace(
        async_update=AsyncMock(return_value={"interval_readings": [1, 2]}))
    client.fetch = AsyncMock(return_value=dict(PAYLOAD))
    return client


class ConsumptionCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_persists_snapshot(self):
        client = make()
        data = await client._async_update_data()
        self.assertFalse(data["consumption_snapshot"]["stale"])
        self.assertEqual(data["invoices"], {"unpaid_count": 1})
        saved = client._snapshot_store.async_delay_save.call_args.args[0]()
        self.assertEqual(saved["fetched_at"], "2026-11-05T00:00:00+00:00")
        self.assertEqual(saved["data"]["nord_pool"], {"interval_readings": [1, 2]})
        self.assertNotIn("invoices", saved["data"])
        self.assertNotIn("consumption_snapshot", saved["data"])

    async def test_expired_token_at_startup_keeps_stored_history(self):
        stored = {"fetched_at": "2026-11-04T10:00:00+00:00",
                  "data": {**PAYLOAD, "nord_pool": {"interval_readings": [3]}}}
        client = make(stored)
        client.fetch.side_effect = AuthError("401")
        data = await client._async_update_data()
        self.assertEqual(data["nord_pool"], {"interval_readings": [3]})
        self.assertEqual(data["consumption_snapshot"], {
            "fetched_at": "2026-11-04T10:00:00+00:00", "stale": True,
            "stale_reason": "authentication"})
        self.assertNotIn("invoices", data)
        client.api.async_get_invoices.assert_not_awaited()
        client.entry.async_start_reauth.assert_called_once()
        self.assertTrue(client.auth_failed)
        # The next poll still fails; the cache is still served.
        data = await client._async_update_data()
        self.assertTrue(data["consumption_snapshot"]["stale"])

    async def test_expired_token_without_cache_still_fails_setup(self):
        client = make()
        client.fetch.side_effect = AuthError("401")
        with self.assertRaises(ConfigEntryAuthFailed):
            await client._async_update_data()

    async def test_outage_after_restart_uses_stored_history(self):
        client = make({"fetched_at": "x", "data": PAYLOAD})
        client.fetch.side_effect = ConnectionError_("down")
        data = await client._async_update_data()
        self.assertEqual(data["consumption_snapshot"]["stale_reason"], "connection")
        client.entry.async_start_reauth.assert_not_called()

    async def test_invoice_auth_failure_keeps_consumption(self):
        client = make()
        client.api.async_get_invoices.side_effect = AuthError("401")
        await client._async_update_data()  # first success seeds the cache
        data = await client._async_update_data()
        self.assertNotIn("invoices", data)
        self.assertEqual(data["consumption_snapshot"]["stale_reason"], "authentication")
        client.entry.async_start_reauth.assert_called()

    async def test_auth_failure_during_statistics_keeps_chart_data(self):
        stored = {"fetched_at": "old", "data": {**PAYLOAD, "nord_pool": {"interval_readings": [3]}}}
        client = make(stored)
        client.statistics.async_update.side_effect = AuthError("401")
        data = await client._async_update_data()
        self.assertEqual(data["nord_pool"], {"interval_readings": [3]})
        self.assertEqual(data["consumption_snapshot"]["stale_reason"], "authentication")
        client._snapshot_store.async_delay_save.assert_not_called()

    async def test_statistics_error_keeps_previous_chart_data(self):
        stored = {"fetched_at": "old", "data": {**PAYLOAD, "nord_pool": {"interval_readings": [3]}}}
        client = make(stored)
        client.statistics.async_update.side_effect = RuntimeError("boom")
        await client._async_update_data()
        saved = client._snapshot_store.async_delay_save.call_args.args[0]()
        self.assertEqual(saved["data"]["nord_pool"], {"interval_readings": [3]})

    async def test_recovery_clears_auth_failure(self):
        client = make({"fetched_at": "x", "data": PAYLOAD})
        client.fetch.side_effect = AuthError("401")
        await client._async_update_data()
        client.fetch.side_effect = None
        data = await client._async_update_data()
        self.assertFalse(client.auth_failed)
        self.assertFalse(data["consumption_snapshot"]["stale"])
        self.assertIn("invoices", data)


if __name__ == "__main__":
    unittest.main()
