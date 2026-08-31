"""Client and parsing helpers for Nord Pool day-ahead prices."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from aiohttp import ClientError, ClientSession

from homeassistant.util import dt as dt_util

from .const import (
    LATVIA_VAT_MULTIPLIER,
    NORD_POOL_API_HOST,
    NORD_POOL_DELIVERY_AREA,
    PROVIDER_MARKUP_EUR_PER_KWH,
    REQUEST_TIMEOUT,
)


class NordPoolError(Exception):
    """Nord Pool data could not be fetched or parsed."""


@dataclass(frozen=True)
class NordPoolPriceInterval:
    """One UTC delivery interval and its raw day-ahead price."""

    start: datetime
    end: datetime
    eur_per_mwh: float


class NordPoolApi:
    """Read the public data backing Nord Pool's Data Portal."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._payload_cache: dict[date, dict[str, Any]] = {}

    async def async_get_day_ahead_prices(self, delivery_date: date) -> dict[str, Any]:
        """Return prices covering one complete Latvian local day.

        Nord Pool groups intervals by the CET/CEST delivery date, while
        Alexela timestamps use Europe/Riga. Riga is one hour ahead, so the
        first hour of a Latvian day belongs to Nord Pool's previous delivery
        date. Merge both payloads so every Alexela interval can be matched.
        """
        payloads = [
            await self._async_get_delivery_date(delivery_date - timedelta(days=1)),
            await self._async_get_delivery_date(delivery_date),
        ]
        payload = dict(payloads[-1])
        entries: list[dict[str, Any]] = []
        for source in payloads:
            source_entries = source.get("multiAreaEntries")
            if isinstance(source_entries, list):
                entries.extend(
                    entry for entry in source_entries if isinstance(entry, dict)
                )
        payload["multiAreaEntries"] = entries
        return payload

    async def _async_get_delivery_date(self, delivery_date: date) -> dict[str, Any]:
        """Fetch one Nord Pool CET/CEST delivery-date payload."""
        if (cached := self._payload_cache.get(delivery_date)) is not None:
            return cached

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    f"{NORD_POOL_API_HOST}/api/DayAheadPrices",
                    params={
                        "date": delivery_date.isoformat(),
                        "market": "DayAhead",
                        "deliveryArea": NORD_POOL_DELIVERY_AREA,
                        "currency": "EUR",
                    },
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Origin": "https://data.nordpoolgroup.com",
                        "Referer": "https://data.nordpoolgroup.com/",
                    },
                ) as response:
                    if response.status < 200 or response.status >= 300:
                        text = await response.text()
                        raise NordPoolError(
                            f"Nord Pool returned HTTP {response.status}: {text[:200]}"
                        )
                    payload = await response.json(content_type=None)
        except NordPoolError:
            raise
        except (TimeoutError, ClientError, ValueError) as err:
            raise NordPoolError(str(err)) from err

        if not isinstance(payload, dict):
            raise NordPoolError("Unexpected Nord Pool response")

        self._payload_cache[delivery_date] = payload
        if len(self._payload_cache) > 2:
            del self._payload_cache[min(self._payload_cache)]
        return payload


def spot_price_eur_per_kwh(eur_per_mwh: float) -> float:
    """Convert a Nord Pool price to VAT-inclusive EUR/kWh."""
    return eur_per_mwh / 1000 * LATVIA_VAT_MULTIPLIER


def reference_price_eur_per_kwh(eur_per_mwh: float) -> float:
    """Convert a Nord Pool price to the provider-inclusive reference price."""
    return spot_price_eur_per_kwh(eur_per_mwh) + PROVIDER_MARKUP_EUR_PER_KWH


def effective_price_eur_per_kwh(cost: float, energy: float) -> float:
    """Return the consumption-weighted unit price for a period."""
    if energy <= 0:
        raise ValueError("Energy must be positive when calculating a unit price")
    return cost / energy


def price_intervals(payload: dict[str, Any]) -> list[NordPoolPriceInterval]:
    """Parse usable Latvia delivery intervals from a Data Portal response."""
    intervals: list[NordPoolPriceInterval] = []
    for entry in payload.get("multiAreaEntries", []):
        if not isinstance(entry, dict):
            continue
        start = dt_util.parse_datetime(entry.get("deliveryStart"))
        end = dt_util.parse_datetime(entry.get("deliveryEnd"))
        values = entry.get("entryPerArea")
        value = (
            values.get(NORD_POOL_DELIVERY_AREA)
            if isinstance(values, dict)
            else None
        )
        if start is None or end is None or value is None or end <= start:
            continue
        intervals.append(
            NordPoolPriceInterval(
                start=start.astimezone(dt_util.UTC),
                end=end.astimezone(dt_util.UTC),
                eur_per_mwh=float(value),
            )
        )
    return sorted(intervals, key=lambda interval: interval.start)
