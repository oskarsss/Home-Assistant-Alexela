"""Data coordinator for Alexela."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlexelaApi, AlexelaAuthError, AlexelaConnectionError
from .const import CONF_CRM_ID, CONF_TOKEN, DOMAIN, UPDATE_INTERVAL
from .parsing import has_consumption_data, reference_datetime, unwrap_payload
from .statistics import AlexelaStatisticsImporter

_LOGGER = logging.getLogger(__name__)


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
        self.statistics = AlexelaStatisticsImporter(
            hass, self.api, entry.data[CONF_CRM_ID]
        )
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

        else:
            # Statistics carry the history and the Energy Dashboard data; the
            # sensors are only the live summary, so a failure here must not
            # take them down with it.
            try:
                await self.statistics.async_update(data)
            except Exception:  # noqa: BLE001 - statistics must not break polling
                _LOGGER.exception("Could not import Alexela statistics")

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
        payload = unwrap_payload(
            await self.api.async_get_consumption(f"{year}-01-01 00:00:00", "year")
        )
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
