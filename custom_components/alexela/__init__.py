"""Alexela Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import AlexelaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


@dataclass
class AlexelaRuntimeData:
    """Runtime data for an Alexela config entry."""

    coordinator: AlexelaCoordinator


type AlexelaConfigEntry = ConfigEntry[AlexelaRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: AlexelaConfigEntry) -> bool:
    """Set up Alexela from a config entry."""
    coordinator = AlexelaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = AlexelaRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AlexelaConfigEntry) -> bool:
    """Unload an Alexela config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
