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
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import AlexelaApi
from .analytics import constant_daily_average
from .const import (
    DOMAIN,
    MAX_BACKFILL_DAYS,
    NORD_POOL_INITIAL_BACKFILL_DAYS,
    PORTAL_TIME_ZONE,
)
from .nordpool import (
    NordPoolApi,
    NordPoolError,
    price_intervals,
    reference_price_eur_per_kwh,
    spot_price_eur_per_kwh,
)
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

# Stored in coordinator data for the three user-facing summary sensors. The
# leading underscore avoids colliding with any Alexela response field.
NORD_POOL_SUMMARY_KEY = "_nord_pool_summary"


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


def nord_pool_hourly_buckets(
    consumption_payload: dict[str, Any],
    price_payload: dict[str, Any],
    zone: tzinfo,
) -> list[tuple[datetime, float, float, float]]:
    """Return (hour, average price, reference cost, actual-minus-reference).

    Nord Pool changed from hourly to 15-minute day-ahead products, so each
    Alexela reading is matched against an interval range. Prices are converted
    from EUR/MWh excluding VAT to EUR/kWh including Latvian VAT, then the
    VAT-inclusive provider markup is added before costs are compared with
    Alexela's priceWithVat.
    """
    block = total_block(consumption_payload)
    scale = cost_scale(block)
    intervals = price_intervals(price_payload)
    if not intervals:
        raise NordPoolError("Nord Pool returned no Latvia price intervals")

    buckets: dict[datetime, dict[str, Any]] = {}
    for row in block_rows(block):
        timestamp = parse_timestamp(row.get("timestamp"), zone)
        actual_price = row.get("priceWithVat")
        if timestamp is None or actual_price is None:
            raise NordPoolError("An Alexela interval has no timestamp or cost")

        reading_start = timestamp.astimezone(dt_util.UTC)
        interval = next(
            (
                candidate
                for candidate in intervals
                if candidate.start <= reading_start < candidate.end
            ),
            None,
        )
        if interval is None:
            raise NordPoolError(
                f"Nord Pool has no price covering {reading_start.isoformat()}"
            )

        spot_price = spot_price_eur_per_kwh(interval.eur_per_mwh)
        reference_price = reference_price_eur_per_kwh(interval.eur_per_mwh)
        energy = float(row["amount"])
        reference_cost = energy * reference_price
        actual_cost = float(actual_price) * scale
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        bucket = buckets.setdefault(
            hour,
            {"prices": [], "reference_cost": 0.0, "difference": 0.0},
        )
        bucket["prices"].append(spot_price)
        bucket["reference_cost"] += reference_cost
        bucket["difference"] += actual_cost - reference_cost

    return [
        (
            hour.astimezone(dt_util.UTC),
            sum(buckets[hour]["prices"]) / len(buckets[hour]["prices"]),
            buckets[hour]["reference_cost"],
            buckets[hour]["difference"],
        )
        for hour in sorted(buckets)
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

    def __init__(
        self,
        hass: HomeAssistant,
        api: AlexelaApi,
        nord_pool_api: NordPoolApi,
        crm_id: str,
    ) -> None:
        self.hass = hass
        self.api = api
        self.nord_pool_api = nord_pool_api
        self.energy_id = f"{DOMAIN}:{crm_id}_electricity_energy"
        self.cost_id = f"{DOMAIN}:{crm_id}_electricity_cost"
        self.daily_average_id = (
            f"{DOMAIN}:{crm_id}_electricity_daily_average_all_history"
        )
        self.nord_pool_price_id = f"{DOMAIN}:{crm_id}_nord_pool_price"
        # v0.3.2 uses new statistic IDs so existing spot-only v0.3.0/v0.3.1
        # history is not silently mixed with the provider-inclusive formula.
        # Home Assistant then backfills these new series from their own cursor.
        self.nord_pool_cost_id = (
            f"{DOMAIN}:{crm_id}_nord_pool_provider_reference_cost"
        )
        self.nord_pool_difference_id = (
            f"{DOMAIN}:{crm_id}_electricity_cost_difference_vs_nord_pool_provider"
        )

    async def async_update(self, year_payload: dict[str, Any]) -> dict[str, Any]:
        """Import every published day that is not in statistics yet."""
        zone = await dt_util.async_get_time_zone(PORTAL_TIME_ZONE) or dt_util.UTC
        last_energy = await self._async_last_statistic(self.energy_id)
        last_cost = await self._async_last_statistic(self.cost_id)
        last_nord_pool_cost = await self._async_last_statistic(self.nord_pool_cost_id)
        last_difference = await self._async_last_statistic(
            self.nord_pool_difference_id
        )
        last_nord_pool_price = await self._async_last_statistic(
            self.nord_pool_price_id, "mean"
        )
        last_daily_average = await self._async_last_statistic(
            self.daily_average_id, "mean"
        )

        imported_through = (
            last_energy[0].astimezone(zone).date() if last_energy else None
        )
        comparison_through = (
            last_nord_pool_cost[0].astimezone(zone).date()
            if last_nord_pool_cost
            else None
        )
        # Nord Pool's unauthenticated portal does not provide a full year of
        # interval history. On first run, begin at the oldest date safely
        # available there rather than repeatedly failing on January.
        comparison_cursor = comparison_through or (
            reference_datetime().date()
            - timedelta(days=NORD_POOL_INITIAL_BACKFILL_DAYS + 1)
        )
        oldest_through = (
            min(imported_through, comparison_cursor)
            if imported_through is not None
            else None
        )
        days = await self._async_pending_days(year_payload, zone, oldest_through)
        if not days:
            if last_daily_average is None:
                self._async_write_daily_average(await self._async_daily_energy())
            return self._comparison_summary(
                last_nord_pool_cost, last_difference, last_nord_pool_price
            )

        _LOGGER.debug("Alexela statistics: %s day(s) to import", len(days))
        daily_energy = await self._async_daily_energy()
        energy_sum = last_energy[1] if last_energy else 0.0
        cost_sum = last_cost[1] if last_cost else 0.0
        nord_pool_cost_sum = last_nord_pool_cost[1] if last_nord_pool_cost else 0.0
        difference_sum = last_difference[1] if last_difference else 0.0
        energy_stats: list[StatisticData] = []
        cost_stats: list[StatisticData] = []
        nord_pool_price_stats: list[StatisticData] = []
        nord_pool_cost_stats: list[StatisticData] = []
        difference_stats: list[StatisticData] = []
        comparison_paused = False

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

            if imported_through is None or day > imported_through:
                daily_energy.append(
                    (buckets[0][0], sum(energy for _, energy, _ in buckets))
                )
                for hour, energy, cost in buckets:
                    energy_sum += energy
                    cost_sum += cost
                    energy_stats.append(
                        StatisticData(start=hour, state=energy, sum=energy_sum)
                    )
                    cost_stats.append(
                        StatisticData(start=hour, state=cost, sum=cost_sum)
                    )

            if not comparison_paused and day > comparison_cursor:
                try:
                    prices = await self.nord_pool_api.async_get_day_ahead_prices(day)
                    comparison_buckets = nord_pool_hourly_buckets(payload, prices, zone)
                except NordPoolError as err:
                    comparison_paused = True
                    _LOGGER.warning(
                        "Could not import Nord Pool comparison for %s (%s); "
                        "pausing there and retrying later",
                        day,
                        err,
                    )
                else:
                    for hour, price, reference_cost, difference in comparison_buckets:
                        nord_pool_cost_sum += reference_cost
                        difference_sum += difference
                        nord_pool_price_stats.append(
                            StatisticData(
                                start=hour,
                                mean=price,
                                min=price,
                                max=price,
                            )
                        )
                        nord_pool_cost_stats.append(
                            StatisticData(
                                start=hour,
                                state=reference_cost,
                                sum=nord_pool_cost_sum,
                            )
                        )
                        difference_stats.append(
                            StatisticData(
                                start=hour,
                                state=difference,
                                sum=difference_sum,
                            )
                        )

        if energy_stats:
            async_add_external_statistics(
                self.hass,
                self._sum_metadata(
                    self.energy_id,
                    "Alexela electricity",
                    UnitOfEnergy.KILO_WATT_HOUR,
                ),
                energy_stats,
            )
            async_add_external_statistics(
                self.hass,
                self._sum_metadata(self.cost_id, "Alexela electricity cost", "EUR"),
                cost_stats,
            )
            _LOGGER.debug(
                "Alexela statistics: imported %s consumption hour(s) up to %s",
                len(energy_stats),
                energy_stats[-1]["start"],
            )
            self._async_write_daily_average(daily_energy)
        elif last_daily_average is None:
            self._async_write_daily_average(daily_energy)

        if nord_pool_cost_stats:
            async_add_external_statistics(
                self.hass,
                self._mean_metadata(
                    self.nord_pool_price_id,
                    "Nord Pool Latvia spot price incl VAT",
                    "EUR/kWh",
                ),
                nord_pool_price_stats,
            )
            async_add_external_statistics(
                self.hass,
                self._sum_metadata(
                    self.nord_pool_cost_id,
                    "Nord Pool plus provider markup reference cost",
                    "EUR",
                ),
                nord_pool_cost_stats,
            )
            async_add_external_statistics(
                self.hass,
                self._sum_metadata(
                    self.nord_pool_difference_id,
                    "Alexela cost difference vs Nord Pool plus provider markup",
                    "EUR",
                ),
                difference_stats,
            )
            _LOGGER.debug(
                "Alexela statistics: imported %s Nord Pool comparison hour(s) up to %s",
                len(nord_pool_cost_stats),
                nord_pool_cost_stats[-1]["start"],
            )

        latest_cost = (
            (nord_pool_cost_stats[-1]["start"], nord_pool_cost_sum)
            if nord_pool_cost_stats
            else last_nord_pool_cost
        )
        latest_difference = (
            (difference_stats[-1]["start"], difference_sum)
            if difference_stats
            else last_difference
        )
        latest_price = (
            (nord_pool_price_stats[-1]["start"], nord_pool_price_stats[-1]["mean"])
            if nord_pool_price_stats
            else last_nord_pool_price
        )
        return self._comparison_summary(latest_cost, latest_difference, latest_price)

    def _sum_metadata(
        self, statistic_id: str, name: str, unit: str
    ) -> StatisticMetaData:
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

    def _mean_metadata(
        self,
        statistic_id: str,
        name: str,
        unit: str,
        unit_class: str | None = None,
    ) -> StatisticMetaData:
        metadata: Any = {
            "has_sum": False,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": unit_class,
            "unit_of_measurement": unit,
        }
        if StatisticMeanType is not None:
            metadata["mean_type"] = StatisticMeanType.ARITHMETIC
        else:
            metadata["has_mean"] = True
        return metadata

    async def _async_last_statistic(
        self, statistic_id: str, value_field: str = "sum"
    ) -> tuple[datetime, float] | None:
        """Return the newest imported hour and its running sum."""
        rows = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {value_field}
        )
        entries = rows.get(statistic_id)
        if not entries:
            return None

        start = entries[0]["start"]
        if isinstance(start, (int, float)):
            start = dt_util.utc_from_timestamp(start)
        value = entries[0].get(value_field)
        return (start, float(value)) if value is not None else None

    async def _async_daily_energy(self) -> list[tuple[datetime, float]]:
        """Return every complete daily energy change already in the recorder."""
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            datetime(1970, 1, 1, tzinfo=dt_util.UTC),
            None,
            {self.energy_id},
            "day",
            None,
            {"change"},
        )

        daily: list[tuple[datetime, float]] = []
        for row in rows.get(self.energy_id, []):
            value = row.get("change")
            if value is None:
                continue
            timestamp = row["start"]
            if isinstance(timestamp, (int, float)):
                timestamp = dt_util.utc_from_timestamp(timestamp)
            daily.append((timestamp, float(value)))
        return daily

    def _async_write_daily_average(
        self, daily_energy: list[tuple[datetime, float]]
    ) -> None:
        """Publish a horizontal average across all complete collected days."""
        points = constant_daily_average(sorted(daily_energy))
        if not points:
            return

        average_stats = [
            StatisticData(start=start, mean=value, min=value, max=value)
            for start, value in points
        ]
        async_add_external_statistics(
            self.hass,
            self._mean_metadata(
                self.daily_average_id,
                "Alexela average daily electricity usage (all history)",
                UnitOfEnergy.KILO_WATT_HOUR,
                unit_class="energy",
            ),
            average_stats,
        )
        _LOGGER.debug(
            "Alexela statistics: updated all-history daily average across %s day(s)",
            len(points),
        )

    def _comparison_summary(
        self,
        cost: tuple[datetime, float] | None,
        difference: tuple[datetime, float] | None,
        price: tuple[datetime, float] | None,
    ) -> dict[str, Any]:
        """Build values shown by the lightweight summary sensors."""
        through = cost[0] if cost else None
        return {
            "reference_cost": cost[1] if cost else None,
            "difference": difference[1] if difference else None,
            "latest_price": price[1] if price else None,
            "data_through": through.isoformat() if through else None,
        }

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
