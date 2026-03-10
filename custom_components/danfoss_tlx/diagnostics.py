"""Diagnostics für die Danfoss TLX Pro Integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import DanfossTLXConfigEntry
from .const import CONF_INVERTER_IP, CONF_PV_STRINGS, CONF_SCAN_INTERVAL


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: DanfossTLXConfigEntry,
) -> dict[str, Any]:
    """Gibt Diagnostics-Daten für den Config-Eintrag zurück."""
    coordinator = entry.runtime_data

    return {
        "config": {
            "inverter_ip": entry.data.get(CONF_INVERTER_IP),
            "inverter_serial": "**REDACTED**",
            "pv_strings": entry.data.get(CONF_PV_STRINGS),
            "scan_interval": entry.data.get(CONF_SCAN_INTERVAL),
        },
        "coordinator": {
            "serial": coordinator.inverter_serial,
            "update_interval_seconds": coordinator.update_interval.total_seconds(),
        },
        "inverter_data": dict(coordinator.data) if coordinator.data else None,
    }
