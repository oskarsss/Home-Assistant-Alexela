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
from .const import CONF_CRM_ID, DOMAIN
from .coordinator import AlexelaCoordinator

ValueFn = Callable[[dict[str, Any]], float | Decimal | None]


def _total_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return Alexela's aggregate electricity block."""
    for item in data.get("electricityConsumption", []):
        if item.get("isTotal") is True:
            return item
    return None


def _current_month_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the aggregate row for the current month."""
    total = _total_block(data)
    if not total:
        return None

    target = dt_util.now().strftime("%Y-%m-01T00:00:00")
    for item in total.get("data", []):
        if item.get("timestamp") == target:
            return item
    return None


def _ytd_energy(data: dict[str, Any]) -> float | None:
    total = _total_block(data)
    value = total.get("totalAmount") if total else None
    return float(value) if value is not None else None


def _month_energy(data: dict[str, Any]) -> float | None:
    month = _current_month_block(data)
    value = month.get("amount") if month else None
    return float(value) if value is not None else None


def _ytd_cost(data: dict[str, Any]) -> float | None:
    total = _total_block(data)
    value = total.get("totalPriceWithVat") if total else None
    return float(value) if value is not None else None


def _month_cost(data: dict[str, Any]) -> float | None:
    month = _current_month_block(data)
    value = month.get("priceWithVat") if month else None
    return float(value) if value is not None else None


def _month_effective_price(data: dict[str, Any]) -> float | None:
    """Return current-month effective electricity price in EUR/kWh.

    Alexela's aggregate month row gives both total energy and total energy price.
    Dividing those values gives a price entity Home Assistant can use in the
    Energy Dashboard's "current price" mode. This is an effective monthly
    average, not necessarily an instantaneous Nord Pool price.
    """
    month = _current_month_block(data)
    if not month:
        return None

    amount = month.get("amount")
    price = month.get("priceWithVat")
    if amount in (None, 0) or price is None:
        return None

    return float(price) / float(amount)


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
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        """Return reset boundary for Alexela monetary totals.

        Home Assistant's monetary device class supports the TOTAL state class,
        not TOTAL_INCREASING. Supplying the period reset makes monthly/yearly
        cost statistics reset cleanly when Alexela starts a new period.
        """
        now = dt_util.now()
        if self.entity_description.key == "electricity_cost_ytd":
            return now.replace(
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        if self.entity_description.key == "electricity_cost_month":
            return now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        return None
