"""Sensor-Plattform für Danfoss TLX Pro."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_PV_STRINGS
from .coordinator import DanfossCoordinator
from .etherlynx import TLX_PARAMETERS, OPERATION_MODES, ParameterDef


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet Sensor-Entities ein."""
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id]
    pv_strings = entry.data.get(CONF_PV_STRINGS, 2)

    entities: list[SensorEntity] = []

    for key, param in TLX_PARAMETERS.items():
        # String 3 überspringen wenn nur 2 Strings konfiguriert
        if pv_strings < 3 and "_3" in key and key.startswith("pv_"):
            continue
        entities.append(DanfossSensor(coordinator, entry, key, param))

    # Betriebsmodus als Text-Sensor
    entities.append(DanfossOperationModeSensor(coordinator, entry))

    async_add_entities(entities)


def _device_info(coordinator: DanfossCoordinator, entry: ConfigEntry) -> Dict[str, Any]:
    """Gemeinsame Geräteinformationen für das HA-Geräteregister."""
    serial = coordinator.inverter_serial or entry.entry_id
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": f"Danfoss TLX Pro ({serial})",
        "manufacturer": "Danfoss Solar Inverters",
        "model": "TLX Pro",
    }


class DanfossSensor(CoordinatorEntity, SensorEntity):
    """Sensor für einen Danfoss TLX Pro Parameter."""

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: ConfigEntry,
        key: str,
        param: ParameterDef,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._entry = entry
        self._attr_name = param.name
        self._attr_unique_id = f"danfoss_tlx_{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = param.unit if param.unit else None
        if param.device_class:
            self._attr_device_class = param.device_class
        if param.state_class:
            self._attr_state_class = param.state_class

    @property
    def native_value(self) -> Optional[float]:
        """Aktueller Sensorwert."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._key)
        return None

    @property
    def device_info(self) -> Dict[str, Any]:
        """Geräteinformationen für das HA-Geräteregister."""
        return _device_info(self.coordinator, self._entry)


class DanfossOperationModeSensor(CoordinatorEntity, SensorEntity):
    """Text-Sensor für den Betriebsmodus des Wechselrichters."""

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Betriebsmodus"
        self._attr_unique_id = f"danfoss_tlx_{entry.entry_id}_operation_mode_text"
        self._attr_icon = "mdi:solar-power"

    @property
    def native_value(self) -> Optional[str]:
        """Betriebsmodus als lesbarer Text."""
        if self.coordinator.data:
            mode_id = self.coordinator.data.get("operation_mode")
            if mode_id is not None:
                return OPERATION_MODES.get(int(mode_id), f"Unbekannt ({mode_id})")
        return None

    @property
    def device_info(self) -> Dict[str, Any]:
        """Geräteinformationen für das HA-Geräteregister."""
        return _device_info(self.coordinator, self._entry)
