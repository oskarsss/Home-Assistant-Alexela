"""Data coordinator for Alexela."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AlexelaApi, AlexelaAuthError, AlexelaConnectionError
from .const import CONF_CRM_ID, CONF_TOKEN, DATA_LAG, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


def reference_datetime() -> datetime:
    """Return the most recent local time Alexela is expected to have data for.

    The portal publishes consumption with about a day of delay, so anchoring on
    today would ask for a period that does not exist yet on the first day of a
    month or year.
    """
    return dt_util.now() - DATA_LAG


def unwrap_payload(payload: Any) -> dict[str, Any]:
    """Return the object that carries the consumption blocks.

    Some Alexela endpoints answer with an envelope such as
    {"result": {...}, "value": null}, so the consumption blocks are not always
    at the top level of the response.
    """
    if not isinstance(payload, dict):
        return {}
    if "electricityConsumption" in payload:
        return payload
    for key in ("result", "value", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict) and "electricityConsumption" in inner:
            return inner
    return payload


def has_consumption_data(data: dict[str, Any] | None) -> bool:
    """Return True when the payload carries at least one usable period."""
    if not data:
        return False
    return any(
        row.get("amount") is not None
        for block in data.get("electricityConsumption", [])
        if isinstance(block, dict)
        for row in block.get("data", [])
        if isinstance(row, dict)
    )


class AlexelaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refresh Alexela JWT and consumption data together."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.api = AlexelaApi(
            aiohttp_client.async_get_clientsession(hass),
            entry.data[CONF_CRM_ID],
            entry.data[CONF_TOKEN],
        )
        self._last_valid: dict[str, Any] | None = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            rotated = await self.api.async_refresh_jwt()
            if rotated:
                # Persist the latest token so a Home Assistant restart continues
                # the same rotation chain instead of loading a stale JWT.
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_TOKEN: self.api.token},
                )
                _LOGGER.debug("Alexela JWT rotated and persisted")

            data = await self._async_fetch_consumption()

        except AlexelaAuthError as err:
            raise ConfigEntryAuthFailed(
                "Alexela token is expired or no longer valid"
            ) from err
        except AlexelaConnectionError as err:
            # The portal is regularly unavailable for short periods. Keep the
            # last known values instead of dropping every sensor to unavailable.
            if self._last_valid is not None:
                _LOGGER.warning(
                    "Alexela request failed (%s); keeping the previously "
                    "received consumption data",
                    err,
                )
                return self._last_valid
            raise UpdateFailed(f"Error communicating with Alexela: {err}") from err

        if not has_consumption_data(data):
            if self._last_valid is not None:
                _LOGGER.warning(
                    "Alexela returned no consumption data; keeping the "
                    "previously received consumption data"
                )
                return self._last_valid

        self._last_valid = data
        return data

    async def _async_fetch_consumption(self) -> dict[str, Any]:
        """Fetch the year that holds Alexela's most recent published data."""
        reference = reference_datetime()
        data = await self._async_get_year(reference.year)
        if has_consumption_data(data):
            return data

        # Around New Year the new year is still empty, so the latest published
        # data belongs to the previous year.
        previous = await self._async_get_year(reference.year - 1)
        return previous if has_consumption_data(previous) else data

    async def _async_get_year(self, year: int) -> dict[str, Any]:
        """Fetch and unwrap one year, logging what Alexela actually returned."""
        payload = unwrap_payload(await self.api.async_get_consumption(year))
        _LOGGER.debug("Alexela consumption response for %s: %s", year, payload)
        if not has_consumption_data(payload):
            _LOGGER.warning(
                "Alexela returned no usable consumption data for %s. Top-level "
                "keys: %s. Electricity blocks: %s. Enable debug logging for "
                "custom_components.alexela to see the full response",
                year,
                ", ".join(sorted(payload)) or "none",
                [
                    {k: v for k, v in block.items() if k != "data"}
                    for block in payload.get("electricityConsumption", [])
                    if isinstance(block, dict)
                ],
            )
        return payload
