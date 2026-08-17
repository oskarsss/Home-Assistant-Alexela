"""Data coordinator for Alexela."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AlexelaApi, AlexelaAuthError, AlexelaConnectionError
from .const import CONF_CRM_ID, CONF_TOKEN, DOMAIN, UPDATE_INTERVAL

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

            return await self.api.async_get_consumption(dt_util.now().year)

        except AlexelaAuthError as err:
            raise ConfigEntryAuthFailed(
                "Alexela token is expired or no longer valid"
            ) from err
        except AlexelaConnectionError as err:
            raise UpdateFailed(f"Error communicating with Alexela: {err}") from err
