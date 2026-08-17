"""Config flow for Alexela."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client, selector

from .api import (
    AlexelaApi,
    AlexelaAuthError,
    AlexelaConnectionError,
    normalize_token,
)
from .const import CONF_CRM_ID, CONF_TOKEN, DOMAIN


def _schema(*, crm_id: str | None = None, token_only: bool = False) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if not token_only:
        fields[vol.Required(CONF_CRM_ID, default=crm_id or "")] = selector.TextSelector()
    fields[vol.Required(CONF_TOKEN)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    return vol.Schema(fields)


async def _validate(hass: HomeAssistant, crm_id: str, token: str) -> None:
    api = AlexelaApi(
        aiohttp_client.async_get_clientsession(hass),
        crm_id,
        token,
    )
    await api.async_get_contracts()


class AlexelaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Alexela config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up Alexela manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            crm_id = str(user_input[CONF_CRM_ID]).strip()
            token = normalize_token(user_input[CONF_TOKEN])

            try:
                await _validate(self.hass, crm_id, token)
            except AlexelaAuthError:
                errors["base"] = "invalid_auth"
            except (AlexelaConnectionError, ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config flows must not crash the UI
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(crm_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Alexela {crm_id}",
                    data={CONF_CRM_ID: crm_id, CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept a replacement JWT after the rotation chain expires."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        crm_id = entry.data[CONF_CRM_ID]

        if user_input is not None:
            token = normalize_token(user_input[CONF_TOKEN])
            try:
                await _validate(self.hass, crm_id, token)
            except AlexelaAuthError:
                errors["base"] = "invalid_auth"
            except (AlexelaConnectionError, ClientError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(token_only=True),
            errors=errors,
        )
