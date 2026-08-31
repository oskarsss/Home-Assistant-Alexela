"""Unit tests for the Nord Pool client without a Home Assistant installation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest


def _load_nordpool_module():
    """Load nordpool.py with the small runtime surface it imports stubbed."""
    aiohttp = ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    dt_module = ModuleType("homeassistant.util.dt")
    dt_module.UTC = timezone.utc
    dt_module.parse_datetime = lambda value: datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    homeassistant = ModuleType("homeassistant")
    util = ModuleType("homeassistant.util")
    util.dt = dt_module
    homeassistant.util = util
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt_module

    package = ModuleType("custom_components.alexela")
    package.__path__ = []
    sys.modules["custom_components"] = ModuleType("custom_components")
    sys.modules["custom_components.alexela"] = package
    constants = ModuleType("custom_components.alexela.const")
    constants.NORD_POOL_API_HOST = "https://example.test"
    constants.NORD_POOL_DELIVERY_AREA = "LV"
    constants.LATVIA_VAT_MULTIPLIER = 1.21
    constants.PROVIDER_MARKUP_EUR_PER_KWH = 0.0087
    constants.REQUEST_TIMEOUT = 30
    sys.modules["custom_components.alexela.const"] = constants

    path = Path(__file__).parents[1] / "custom_components/alexela/nordpool.py"
    spec = importlib.util.spec_from_file_location(
        "custom_components.alexela.nordpool", path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    if not hasattr(module.asyncio, "timeout"):
        @asynccontextmanager
        async def timeout(_seconds):
            yield

        module.asyncio.timeout = timeout
    return module


NORDPOOL = _load_nordpool_module()


class FakeResponse:
    """Minimal aiohttp response context manager."""

    status = 200

    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self, content_type=None):
        return self._payload


class FakeSession:
    """Return one distinguishable interval per requested delivery date."""

    def __init__(self):
        self.requested_dates = []

    def get(self, _url, *, params, headers):
        delivery_date = date.fromisoformat(params["date"])
        self.requested_dates.append(delivery_date)
        start = datetime(
            2026, 8, delivery_date.day - 1, 22, tzinfo=timezone.utc
        )
        return FakeResponse(
            {
                "deliveryDateCET": delivery_date.isoformat(),
                "multiAreaEntries": [
                    {
                        "deliveryStart": start.isoformat(),
                        "deliveryEnd": start.replace(minute=15).isoformat(),
                        "entryPerArea": {"LV": float(delivery_date.day)},
                    }
                ],
            }
        )


class NordPoolApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_combines_previous_and_requested_delivery_dates(self):
        session = FakeSession()
        api = NORDPOOL.NordPoolApi(session)

        payload = await api.async_get_day_ahead_prices(date(2026, 8, 10))

        self.assertEqual(
            session.requested_dates,
            [date(2026, 8, 9), date(2026, 8, 10)],
        )
        self.assertEqual(payload["deliveryDateCET"], "2026-08-10")
        self.assertEqual(
            [entry["entryPerArea"]["LV"] for entry in payload["multiAreaEntries"]],
            [9.0, 10.0],
        )

    async def test_reuses_adjacent_delivery_date_during_backfill(self):
        session = FakeSession()
        api = NORDPOOL.NordPoolApi(session)

        await api.async_get_day_ahead_prices(date(2026, 8, 10))
        await api.async_get_day_ahead_prices(date(2026, 8, 11))

        self.assertEqual(
            session.requested_dates,
            [date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11)],
        )


class ReferencePriceTest(unittest.TestCase):
    def test_converts_spot_price_with_vat(self):
        self.assertAlmostEqual(
            NORDPOOL.spot_price_eur_per_kwh(100.0),
            0.121,
        )

    def test_adds_vat_and_vat_inclusive_provider_markup(self):
        self.assertAlmostEqual(
            NORDPOOL.reference_price_eur_per_kwh(100.0),
            0.1297,
        )

    def test_calculates_consumption_weighted_effective_price(self):
        self.assertAlmostEqual(
            NORDPOOL.effective_price_eur_per_kwh(1.25, 10.0),
            0.125,
        )

    def test_rejects_effective_price_without_consumption(self):
        with self.assertRaises(ValueError):
            NORDPOOL.effective_price_eur_per_kwh(0.0, 0.0)


if __name__ == "__main__":
    unittest.main()
