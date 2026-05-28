"""Danfoss TLX Pro Integration für Home Assistant."""
from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import DanfossCoordinator

if TYPE_CHECKING:
    DanfossTLXConfigEntry = ConfigEntry[DanfossCoordinator]
else:
    DanfossTLXConfigEntry = ConfigEntry

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: DanfossTLXConfigEntry) -> bool:
    """Richtet die Integration ein."""
    coordinator = DanfossCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: DanfossTLXConfigEntry) -> bool:
    """Entfernt die Integration und schließt den UDP-Endpoint."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: DanfossTLXConfigEntry) -> None:
    """Lädt die Integration neu wenn Optionen geändert werden."""
    await hass.config_entries.async_reload(entry.entry_id)
