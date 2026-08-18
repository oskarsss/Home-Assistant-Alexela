"""Long-term statistics import for Alexela.

Alexela publishes 15-minute consumption a day or so after the fact. Feeding
that into a Home Assistant sensor would attribute a whole day of energy to the
moment the integration happened to notice it, so the readings are written
straight into long-term statistics at the timestamps they belong to.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, tzinfo
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import AlexelaApi
from .const import DOMAIN, MAX_BACKFILL_DAYS, PORTAL_TIME_ZONE
from .parsing import (
    block_rows,
    cost_scale,
    parse_timestamp,
    reference_datetime,
    total_block,
    unwrap_payload,
)

try:  # Keep the metadata usable on cores predating StatisticMeanType.
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # pragma: no cover - older cores
    StatisticMeanType = None

_LOGGER = logging.getLogger(__name__)

# Alexela answers a burst of requests with empty payloads, so keep a gap
# between the day requests of a backfill.
REQUEST_DELAY = 1.0


def hourly_buckets(
    payload: dict[str, Any], zone: tzinfo
) -> list[tuple[datetime, float, float]]:
    """Fold a day of 15-minute readings into (hour, kWh, EUR) tuples.

    Home Assistant keeps statistics in hourly buckets, and Alexela reports each
    interval by its start, so an interval belongs to the hour it starts in.
    """
    block = total_block(payload)
    scale = cost_scale(block)

    buckets: dict[datetime, list[float]] = {}
    for row in block_rows(block):
        timestamp = parse_timestamp(row.get("timestamp"), zone)
        if timestamp is None:
            continue
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        bucket = buckets.setdefault(hour, [0.0, 0.0])
        bucket[0] += float(row["amount"])
        price = row.get("priceWithVat")
        if price is not None:
            bucket[1] += float(price) * scale

    return [
        (hour.astimezone(dt_util.UTC), *buckets[hour]) for hour in sorted(buckets)
    ]


def published_days(month_payload: dict[str, Any], zone: tzinfo) -> list[date]:
    """Return the days a monthly payload reports a reading for."""
    days = [
        timestamp.date()
        for row in block_rows(total_block(month_payload))
        if (timestamp := parse_timestamp(row.get("timestamp"), zone)) is not None
    ]
    return sorted(days)


class AlexelaStatisticsImporter:
    """Keep Home Assistant's statistics in step with Alexela's history."""

    def __init__(self, hass: HomeAssistant, api: AlexelaApi, crm_id: str) -> None:
        self.hass = hass
        self.api = api
        self.energy_id = f"{DOMAIN}:{crm_id}_electricity_energy"
        self.cost_id = f"{DOMAIN}:{crm_id}_electricity_cost"

    async def async_update(self, year_payload: dict[str, Any]) -> None:
        """Import every published day that is not in statistics yet."""
        zone = await dt_util.async_get_time_zone(PORTAL_TIME_ZONE) or dt_util.UTC
        last_energy = await self._async_last_statistic(self.energy_id)
        last_cost = await self._async_last_statistic(self.cost_id)

        imported_through = (
            last_energy[0].astimezone(zone).date() if last_energy else None
        )
        days = await self._async_pending_days(year_payload, zone, imported_through)
        if not days:
            return

        _LOGGER.debug("Alexela statistics: %s day(s) to import", len(days))
        energy_sum = last_energy[1] if last_energy else 0.0
        cost_sum = last_cost[1] if last_cost else 0.0
        energy_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []

        for index, day in enumerate(days):
            if index:
                await asyncio.sleep(REQUEST_DELAY)
            payload = unwrap_payload(
                await self.api.async_get_consumption(
                    f"{day.isoformat()} 00:00:00", "day"
                )
            )
            buckets = hourly_buckets(payload, zone)
            if not buckets:
                # Alexela answers HTTP 200 with an empty payload when it is
                # having a bad moment. Stop here rather than stepping over the
                # day: statistics must stay contiguous, and the next update
                # will pick this day up again.
                _LOGGER.warning(
                    "Alexela returned no readings for %s; pausing the "
                    "statistics import there and retrying later",
                    day,
                )
                break

            for hour, energy, cost in buckets:
                energy_sum += energy
                cost_sum += cost
                energy_stats.append(
                    StatisticData(start=hour, state=energy, sum=energy_sum)
                )
                cost_stats.append(StatisticData(start=hour, state=cost, sum=cost_sum))

        if not energy_stats:
            return

        async_add_external_statistics(
            self.hass,
            self._metadata(
                self.energy_id, "Alexela electricity", UnitOfEnergy.KILO_WATT_HOUR
            ),
            energy_stats,
        )
        async_add_external_statistics(
            self.hass,
            self._metadata(self.cost_id, "Alexela electricity cost", "EUR"),
            cost_stats,
        )
        _LOGGER.debug(
            "Alexela statistics: imported %s hour(s) up to %s",
            len(energy_stats),
            energy_stats[-1]["start"],
        )

    def _metadata(self, statistic_id: str, name: str, unit: str) -> StatisticMetaData:
        metadata: Any = {
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": "energy" if unit == UnitOfEnergy.KILO_WATT_HOUR else None,
            "unit_of_measurement": unit,
        }
        if StatisticMeanType is not None:
            metadata["mean_type"] = StatisticMeanType.NONE
        else:
            metadata["has_mean"] = False
        return metadata

    async def _async_last_statistic(
        self, statistic_id: str
    ) -> tuple[datetime, float] | None:
        """Return the newest imported hour and its running sum."""
        rows = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        entries = rows.get(statistic_id)
        if not entries:
            return None

        start = entries[0]["start"]
        if isinstance(start, (int, float)):
            start = dt_util.utc_from_timestamp(start)
        return start, float(entries[0].get("sum") or 0.0)

    async def _async_pending_days(
        self,
        year_payload: dict[str, Any],
        zone: tzinfo,
        imported_through: date | None,
    ) -> list[date]:
        """Return the published days still missing from statistics.

        The monthly view is what says which days exist, so a day Alexela never
        published is never waited for, while a day it does have is retried until
        it actually arrives.
        """
        newest = reference_datetime().date()  # Alexela is a day behind
        months = [
            timestamp.date()
            for row in block_rows(total_block(year_payload))
            if (timestamp := parse_timestamp(row.get("timestamp"), zone)) is not None
        ]

        days: list[date] = []
        for month in sorted(months):
            if imported_through is not None and month <= imported_through.replace(
                day=1
            ) - timedelta(days=1):
                continue  # fully covered by an earlier import

            await asyncio.sleep(REQUEST_DELAY)
            payload = unwrap_payload(
                await self.api.async_get_consumption(
                    f"{month.isoformat()} 00:00:00", "month"
                )
            )
            days.extend(published_days(payload, zone))

        pending = [
            day
            for day in sorted(days)
            if day <= newest
            and (imported_through is None or day > imported_through)
        ]
        return pending[:MAX_BACKFILL_DAYS]
