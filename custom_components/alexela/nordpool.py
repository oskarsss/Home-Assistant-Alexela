"""Client and parsing helpers for Nord Pool day-ahead prices."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from aiohttp import ClientError, ClientSession

from homeassistant.util import dt as dt_util

from .const import (
    NORD_POOL_API_HOST,
    NORD_POOL_DELIVERY_AREA,
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

    async def async_get_day_ahead_prices(self, delivery_date: date) -> dict[str, Any]:
        """Return Latvia day-ahead prices for one local delivery date."""
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
        return payload


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
