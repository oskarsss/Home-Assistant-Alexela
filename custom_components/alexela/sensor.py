"""Sensors for Alexela electricity consumption."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import AlexelaConfigEntry
from .const import CONF_CRM_ID, DOMAIN, PROVIDER_MARKUP_EUR_PER_KWH
from .coordinator import AlexelaCoordinator
from .parsing import reference_datetime, sum_rows, total_block
from .statistics import NORD_POOL_SUMMARY_KEY

ValueFn = Callable[[dict[str, Any]], float | Decimal | None]


def _period_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the aggregate row for the latest month Alexela has data for.

    Alexela is roughly a day behind and occasionally skips a period, so the row
    for the current month can be missing entirely. Take the newest row that is
    not in the future instead of insisting on an exact match for today.
    """
    total = total_block(data)
    if not total:
        return None

    # Timestamps look like "2026-08-01T00:00:00", so they sort lexicographically.
    reference = reference_datetime().strftime("%Y-%m-01T00:00:00")
    candidates = [
        item
        for item in total.get("data", [])
        if isinstance(item.get("timestamp"), str)
        and item["timestamp"] <= reference
        and item.get("amount") is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["timestamp"])


def _period_start(data: dict[str, Any]) -> datetime | None:
    """Return the local start of the period the month sensors report."""
    block = _period_block(data)
    timestamp = block.get("timestamp") if block else None
    parsed = dt_util.parse_datetime(timestamp) if timestamp else None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.now().tzinfo)
    return parsed


def _ytd_energy(data: dict[str, Any]) -> float | None:
    total = total_block(data)
    value = total.get("totalAmount") if total else None
    if value is None:
        # A non-aggregate block has no yearly total; add the months up instead.
        return sum_rows(total, "amount")
    return float(value)


def _month_energy(data: dict[str, Any]) -> float | None:
    month = _period_block(data)
    value = month.get("amount") if month else None
    return float(value) if value is not None else None


def _ytd_cost(data: dict[str, Any]) -> float | None:
    total = total_block(data)
    value = total.get("totalPriceWithVat") if total else None
    if value is None:
        return sum_rows(total, "priceWithVat")
    return float(value)


def _month_cost(data: dict[str, Any]) -> float | None:
    month = _period_block(data)
    value = month.get("priceWithVat") if month else None
    return float(value) if value is not None else None


def _month_effective_price(data: dict[str, Any]) -> float | None:
    """Return current-month effective electricity price in EUR/kWh.

    Alexela's aggregate month row gives both total energy and total energy price.
    Dividing those values gives a price entity Home Assistant can use in the
    Energy Dashboard's "current price" mode. This is an effective monthly
    average, not necessarily an instantaneous Nord Pool price.
    """
    month = _period_block(data)
    if not month:
        return None

    amount = month.get("amount")
    price = month.get("priceWithVat")
    if amount in (None, 0) or price is None:
        return None

    return float(price) / float(amount)


def _nord_pool_summary_value(data: dict[str, Any], key: str) -> float | None:
    """Return one value calculated while importing Nord Pool statistics."""
    summary = data.get(NORD_POOL_SUMMARY_KEY)
    value = summary.get(key) if isinstance(summary, dict) else None
    return float(value) if value is not None else None


@dataclass(frozen=True, kw_only=True)
class AlexelaSensorDescription(SensorEntityDescription):
    """Describe an Alexela sensor."""

    value_fn: ValueFn


SENSORS: tuple[AlexelaSensorDescription, ...] = (
    AlexelaSensorDescription(
        key="electricity_ytd",
        name="Electricity consumption YTD",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=_ytd_energy,
    ),
    AlexelaSensorDescription(
        key="electricity_month",
        name="Electricity consumption this month",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=_month_energy,
    ),
    AlexelaSensorDescription(
        key="electricity_cost_ytd",
        name="Electricity cost YTD",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="EUR",
        suggested_display_precision=3,
        value_fn=_ytd_cost,
    ),
    AlexelaSensorDescription(
        key="electricity_cost_month",
        name="Electricity cost this month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="EUR",
        suggested_display_precision=3,
        value_fn=_month_cost,
    ),
    AlexelaSensorDescription(
        key="electricity_price_month",
        name="Electricity price this month",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=5,
        value_fn=_month_effective_price,
    ),
    AlexelaSensorDescription(
        key="nord_pool_price_latest",
        name="Latest Nord Pool price incl VAT",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=5,
        value_fn=lambda data: _nord_pool_summary_value(data, "latest_price"),
    ),
    AlexelaSensorDescription(
        key="nord_pool_reference_cost",
        name="Nord Pool plus provider markup reference cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=3,
        value_fn=lambda data: _nord_pool_summary_value(data, "reference_cost"),
    ),
    AlexelaSensorDescription(
        key="electricity_cost_difference_vs_nord_pool",
        name="Electricity cost difference vs comparison",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=3,
        value_fn=lambda data: _nord_pool_summary_value(data, "difference"),
    ),
)


async def async_setup_entry(
    hass,
    entry: AlexelaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alexela sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        AlexelaSensor(coordinator, entry, description) for description in SENSORS
    )


class AlexelaSensor(CoordinatorEntity[AlexelaCoordinator], SensorEntity):
    """An Alexela sensor backed by the shared coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AlexelaCoordinator,
        entry: AlexelaConfigEntry,
        description: AlexelaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        crm_id = entry.data[CONF_CRM_ID]
        self._attr_unique_id = f"{crm_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, crm_id)},
            name="Alexela",
            manufacturer="Alexela",
            configuration_url="https://my.alexela.lv/consumption",
        )

    @property
    def native_value(self) -> float | Decimal | None:
        """Return the current sensor value."""
        data = self.coordinator.data
        if not data:
            return None
        return self.entity_description.value_fn(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the period the value actually covers.

        Alexela lags about a day behind, so the reported month is not always the
        current calendar month. Publishing the period start makes it obvious
        which data Home Assistant is showing.
        """
        data = self.coordinator.data or {}
        if self.entity_description.key in (
            "nord_pool_price_latest",
            "nord_pool_reference_cost",
            "electricity_cost_difference_vs_nord_pool",
        ):
            summary = data.get(NORD_POOL_SUMMARY_KEY)
            if not isinstance(summary, dict) or not summary.get("data_through"):
                return None
            attributes: dict[str, Any] = {
                "data_through": summary["data_through"],
            }
            if self.entity_description.key == "nord_pool_price_latest":
                attributes["price_basis"] = (
                    "Nord Pool Latvia day-ahead price incl 21% VAT"
                )
            else:
                attributes["price_basis"] = (
                    "Nord Pool Latvia day-ahead price incl 21% VAT plus "
                    "provider markup incl VAT"
                )
                attributes["provider_markup_eur_per_kwh"] = (
                    PROVIDER_MARKUP_EUR_PER_KWH
                )
                attributes["comparison_scope"] = "all imported consumption"
            if (
                self.entity_description.key
                == "electricity_cost_difference_vs_nord_pool"
            ):
                attributes["interpretation"] = (
                    "positive means Alexela cost was higher; negative means savings"
                )
            return attributes

        period = _period_start(data)
        if period is None:
            return None
        return {"data_period_start": period.isoformat()}

    @property
    def last_reset(self) -> datetime | None:
        """Return reset boundary for Alexela monetary totals.

        Home Assistant's monetary device class supports the TOTAL state class,
        not TOTAL_INCREASING. Supplying the period reset makes monthly/yearly
        cost statistics reset cleanly when Alexela starts a new period. The
        boundary follows the period Alexela actually returned, not today, so a
        value that still covers the previous month or year is not attributed to
        the current one.
        """
        key = self.entity_description.key
        if key not in ("electricity_cost_ytd", "electricity_cost_month"):
            return None

        period = _period_start(self.coordinator.data or {}) or reference_datetime()
        period = period.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if key == "electricity_cost_ytd":
            return period.replace(month=1)
        return period
