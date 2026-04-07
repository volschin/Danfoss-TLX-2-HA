"""Sensor-Plattform für Danfoss TLX Pro."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_PV_STRINGS, DEFAULT_PV_STRINGS
from .coordinator import DanfossCoordinator
from .etherlynx import TLX_PARAMETERS, get_operation_mode_text, get_event_text, ParameterDef

if TYPE_CHECKING:
    from . import DanfossTLXConfigEntry

# Sensor-Updates werden vom Coordinator koordiniert
PARALLEL_UPDATES = 0

# Temperatur-Sentinel: Werte >= 120°C bedeuten "kein Sensor angeschlossen"
TEMP_SENTINEL_THRESHOLD = 120

# Parameter die einen optionalen externen Sensor erfordern
_OPTIONAL_SENSOR_KEYS = {"ambient_temp", "pv_array_temp", "irradiance", "hardware_type"}

# Diagnose-Sensoren (Status/System-Info)
_DIAGNOSTIC_KEYS = {
    "operation_mode", "latest_event", "hardware_type",
    "nominal_power", "sw_version",
}

_PRECISION_MAP: dict[str, int] = {}
for _key, _param in TLX_PARAMETERS.items():
    if _param.scale in (0.001, 0.01):
        _PRECISION_MAP[_key] = 2
    elif _param.scale == 0.1:
        _PRECISION_MAP[_key] = 1
    elif _param.scale == 1.0 and _param.unit in ("W", "Wh", "W/m²", "mA"):
        _PRECISION_MAP[_key] = 0


async def async_setup_entry(
    hass: Any,
    entry: DanfossTLXConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet Sensor-Entities ein."""
    coordinator: DanfossCoordinator = entry.runtime_data
    pv_strings = entry.options.get(CONF_PV_STRINGS, entry.data.get(CONF_PV_STRINGS, DEFAULT_PV_STRINGS))

    entities: list[SensorEntity] = []

    for key, param in TLX_PARAMETERS.items():
        # String 3 überspringen wenn nur 2 Strings konfiguriert
        if pv_strings < 3 and "_3" in key and key.startswith("pv_"):
            continue
        entities.append(DanfossSensor(coordinator, entry, key, param))

    # Betriebsmodus als Text-Sensor
    entities.append(DanfossOperationModeSensor(coordinator, entry))

    # Letztes Ereignis als Text-Sensor
    entities.append(DanfossEventSensor(coordinator, entry))

    async_add_entities(entities)


def _device_info(coordinator: DanfossCoordinator, entry: DanfossTLXConfigEntry) -> DeviceInfo:
    """Gemeinsame Geräteinformationen für das HA-Geräteregister."""
    serial = coordinator.inverter_serial or entry.entry_id
    sw_version = None
    hw_version = None
    if coordinator.data:
        sw_value = coordinator.data.get("sw_version")
        hw_value = coordinator.data.get("hardware_type")
        if sw_value is not None:
            sw_version = str(sw_value)
        if hw_value is not None:
            hw_version = str(int(hw_value))

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Danfoss TLX Pro ({serial})",
        manufacturer="Danfoss Solar Inverters",
        model="TLX Pro",
        serial_number=coordinator.inverter_serial,
        sw_version=sw_version,
        hw_version=hw_version,
    )


class _DanfossBaseSensor(CoordinatorEntity[DanfossCoordinator], SensorEntity):
    """Gemeinsame Basis für alle Danfoss TLX Pro Sensor-Entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: DanfossTLXConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Geräteinformationen für das HA-Geräteregister."""
        return _device_info(self.coordinator, self._entry)


class DanfossSensor(_DanfossBaseSensor):
    """Sensor für einen Danfoss TLX Pro Parameter."""

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: DanfossTLXConfigEntry,
        key: str,
        param: ParameterDef,
    ) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"danfoss_tlx_{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = param.unit if param.unit else None
        if param.device_class:
            self._attr_device_class = param.device_class
        if param.state_class:
            self._attr_state_class = param.state_class
        # Nachkommastellen
        if key in _PRECISION_MAP:
            self._attr_suggested_display_precision = _PRECISION_MAP[key]
        # Diagnose-Sensoren
        if key in _DIAGNOSTIC_KEYS:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        # Optionale externe Sensoren standardmäßig ausblenden
        if key in _OPTIONAL_SENSOR_KEYS:
            self._attr_entity_registry_enabled_default = False

    @property
    def available(self) -> bool:
        """Sensor als unavailable markieren bei Sentinel-Werten."""
        if not super().available:
            return False
        # Temperatur-Sentinel: >= 120°C = kein physischer Sensor
        if self._key in ("ambient_temp", "pv_array_temp") and self.coordinator.data:
            value = self.coordinator.data.get(self._key)
            if value is not None and value >= TEMP_SENTINEL_THRESHOLD:
                return False
        return True

    @property
    def native_value(self) -> float | None:
        """Aktueller Sensorwert."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._key)
        return None


class DanfossOperationModeSensor(_DanfossBaseSensor):
    """Text-Sensor für den Betriebsmodus des Wechselrichters."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: DanfossTLXConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_translation_key = "operation_mode_text"
        self._attr_unique_id = f"danfoss_tlx_{entry.entry_id}_operation_mode_text"

    @property
    def native_value(self) -> str | None:
        """Betriebsmodus als lesbarer Text."""
        if self.coordinator.data:
            mode_id = self.coordinator.data.get("operation_mode")
            if mode_id is not None:
                return get_operation_mode_text(mode_id)
        return None


class DanfossEventSensor(_DanfossBaseSensor):
    """Text-Sensor für das letzte Ereignis/Fehlercode des Wechselrichters."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        entry: DanfossTLXConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_translation_key = "latest_event_text"
        self._attr_unique_id = f"danfoss_tlx_{entry.entry_id}_latest_event_text"

    @property
    def native_value(self) -> str | None:
        """Letztes Ereignis als lesbarer Text."""
        if self.coordinator.data:
            event_id = self.coordinator.data.get("latest_event")
            if event_id is not None:
                return get_event_text(event_id)
        return None
