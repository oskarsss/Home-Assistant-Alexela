"""Data coordinator for Alexela."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlexelaApi, AlexelaAuthError, AlexelaConnectionError
from .const import CONF_CRM_ID, CONF_TOKEN, DOMAIN, PORTAL_TIME_ZONE, UPDATE_INTERVAL
from .invoices import (
    INVOICE_PERIOD_START,
    INVOICE_SUMMARY_KEY,
    plan_reminders,
    summarize_invoices,
)
from .nordpool import NordPoolApi
from .parsing import has_consumption_data, reference_datetime, unwrap_payload
from .statistics import AlexelaStatisticsImporter, NORD_POOL_SUMMARY_KEY

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
        self._invoice_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.invoice_reminders")
        self._invoice_history: dict[str, Any] | None = None
        self._invoice_startup_pending = False
        self.statistics = AlexelaStatisticsImporter(
            hass,
            self.api,
            NordPoolApi(aiohttp_client.async_get_clientsession(hass)),
            entry.data[CONF_CRM_ID],
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        data = dict(await self._async_update_consumption())
        # Billing failures must not affect consumption, nor show an old bill as
        # still unpaid after a failed refresh. Unknown is not a zero balance.
        data.pop(INVOICE_SUMMARY_KEY, None)
        try:
            today = datetime.now(ZoneInfo(PORTAL_TIME_ZONE)).date()
            items = await self.api.async_get_invoices(
                INVOICE_PERIOD_START, today.isoformat()
            )
            data[INVOICE_SUMMARY_KEY] = summarize_invoices(items, today)
        except AlexelaAuthError as err:
            raise ConfigEntryAuthFailed("Alexela token is expired or no longer valid") from err
        except (AlexelaConnectionError, ValueError):
            _LOGGER.warning("Could not refresh Alexela invoices; bill data is unavailable")
        if INVOICE_SUMMARY_KEY in data:
            try:
                await self._async_invoice_reminders(data[INVOICE_SUMMARY_KEY], today)
            except Exception:  # noqa: BLE001 - reminders must not break sensors
                _LOGGER.exception("Could not update Alexela bill reminders")
        return data

    async def _async_invoice_reminders(
        self, summary: dict[str, Any], today: date
    ) -> None:
        # First refresh runs during setup, before notification-forwarding
        # automations are listening. Do not mark discovery delivered yet.
        if not self.hass.is_running:
            if not self._invoice_startup_pending:
                self._invoice_startup_pending = True

                async def send_after_start(_event) -> None:
                    self._invoice_startup_pending = False
                    latest = (self.data or {}).get(INVOICE_SUMMARY_KEY)
                    if latest is not None:
                        await self._async_invoice_reminders(
                            latest, datetime.now(ZoneInfo(PORTAL_TIME_ZONE)).date()
                        )

                self.entry.async_on_unload(self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, send_after_start
                ))
            return
        if self._invoice_history is None:
            self._invoice_history = await self._invoice_store.async_load() or {}
        actions, history = plan_reminders(summary, self._invoice_history, today)
        for action in actions:
            notification_id = f"alexela_{self.api.crm_id}_invoice_{action['id']}"
            if action["action"] == "create":
                persistent_notification.async_create(
                    self.hass, action["message"], title=action["title"],
                    notification_id=notification_id,
                )
            else:
                persistent_notification.async_dismiss(self.hass, notification_id)
        if history != self._invoice_history:
            await self._invoice_store.async_save(history)
            self._invoice_history = history

    async def _async_update_consumption(self) -> dict[str, Any]:
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
                summary = await self.statistics.async_update(data)
                data[NORD_POOL_SUMMARY_KEY] = summary
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
