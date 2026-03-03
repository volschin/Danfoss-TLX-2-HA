"""Tests für die Sensor-Plattform."""
from unittest.mock import MagicMock

import pytest

from homeassistant.const import EntityCategory
from custom_components.danfoss_tlx.const import DOMAIN, CONF_PV_STRINGS
from custom_components.danfoss_tlx.etherlynx import TLX_PARAMETERS
from custom_components.danfoss_tlx.sensor import (
    async_setup_entry,
    DanfossSensor,
    DanfossOperationModeSensor,
    DanfossEventSensor,
    _device_info,
    _OPTIONAL_SENSOR_KEYS,
    _DIAGNOSTIC_KEYS,
    PARALLEL_UPDATES,
)


@pytest.fixture
def mock_coordinator(sample_inverter_data):
    """Mock-Coordinator mit Testdaten."""
    coordinator = MagicMock()
    coordinator.data = sample_inverter_data
    coordinator.inverter_serial = "TLX123456"
    return coordinator


@pytest.fixture
def mock_coordinator_no_data():
    """Mock-Coordinator ohne Daten."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.inverter_serial = None
    return coordinator


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_creates_sensors(self, mock_hass, mock_config_entry, mock_coordinator):
        mock_config_entry.runtime_data = mock_coordinator
        added_entities = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(mock_hass, mock_config_entry, capture_entities)

        # All TLX_PARAMETERS sensors (minus pv_*_3 for 2 strings) + 2 text sensors
        pv3_count = sum(1 for k in TLX_PARAMETERS if k.startswith("pv_") and "_3" in k)
        expected = len(TLX_PARAMETERS) - pv3_count + 2
        assert len(added_entities) == expected

    @pytest.mark.asyncio
    async def test_pv3_excluded_with_2_strings(self, mock_hass, mock_config_entry, mock_coordinator):
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.data[CONF_PV_STRINGS] = 2
        added_entities = []

        await async_setup_entry(mock_hass, mock_config_entry, lambda e: added_entities.extend(e))

        sensor_keys = [e._key for e in added_entities if isinstance(e, DanfossSensor)]
        pv3_keys = [k for k in sensor_keys if k.startswith("pv_") and "_3" in k]
        assert len(pv3_keys) == 0

    @pytest.mark.asyncio
    async def test_pv3_included_with_3_strings(self, mock_hass, mock_config_entry, mock_coordinator):
        mock_config_entry.runtime_data = mock_coordinator
        mock_config_entry.data[CONF_PV_STRINGS] = 3
        added_entities = []

        await async_setup_entry(mock_hass, mock_config_entry, lambda e: added_entities.extend(e))

        sensor_keys = [e._key for e in added_entities if isinstance(e, DanfossSensor)]
        pv3_keys = [k for k in sensor_keys if k.startswith("pv_") and "_3" in k]
        assert len(pv3_keys) >= 3


class TestDanfossSensor:
    def test_native_value(self, mock_coordinator, mock_config_entry):
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_power_total", param)
        assert sensor.native_value == 2903.0

    def test_native_value_none_when_no_data(self, mock_coordinator_no_data, mock_config_entry):
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator_no_data, mock_config_entry, "grid_power_total", param)
        assert sensor.native_value is None

    def test_attributes(self, mock_coordinator, mock_config_entry):
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_power_total", param)
        assert sensor._attr_name == "Netzleistung Gesamt"
        assert "grid_power_total" in sensor._attr_unique_id
        assert sensor._attr_native_unit_of_measurement == "W"
        assert sensor._attr_device_class == "power"
        assert sensor._attr_state_class == "measurement"

    def test_no_unit_when_empty(self, mock_coordinator, mock_config_entry):
        param = TLX_PARAMETERS["operation_mode"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "operation_mode", param)
        assert sensor._attr_native_unit_of_measurement is None

    def test_temp_sentinel_unavailable(self, mock_config_entry):
        """Temperatur >= 120°C wird als unavailable markiert."""
        coordinator = MagicMock()
        coordinator.data = {"ambient_temp": 124.0}
        param = TLX_PARAMETERS["ambient_temp"]
        sensor = DanfossSensor(coordinator, mock_config_entry, "ambient_temp", param)
        assert sensor.available is False

    def test_temp_normal_value_available(self, mock_coordinator, mock_config_entry):
        """Plausible Temperatur (25°C) ist available."""
        param = TLX_PARAMETERS["ambient_temp"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "ambient_temp", param)
        assert sensor.available is True

    def test_temp_sentinel_127_unavailable(self, mock_config_entry):
        """Temperatur-Sentinel 127°C ist unavailable."""
        coordinator = MagicMock()
        coordinator.data = {"pv_array_temp": 127.0}
        param = TLX_PARAMETERS["pv_array_temp"]
        sensor = DanfossSensor(coordinator, mock_config_entry, "pv_array_temp", param)
        assert sensor.available is False

    def test_optional_sensors_disabled_by_default(self, mock_coordinator, mock_config_entry):
        """Optionale externe Sensoren sind standardmäßig ausgeblendet."""
        for key in _OPTIONAL_SENSOR_KEYS:
            param = TLX_PARAMETERS[key]
            sensor = DanfossSensor(mock_coordinator, mock_config_entry, key, param)
            assert sensor._attr_entity_registry_enabled_default is False

    def test_normal_sensor_enabled_by_default(self, mock_coordinator, mock_config_entry):
        """Normale Sensoren haben kein entity_registry_enabled_default gesetzt."""
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_power_total", param)
        assert not hasattr(sensor, "_attr_entity_registry_enabled_default")

    def test_diagnostic_sensors_have_entity_category(self, mock_coordinator, mock_config_entry):
        """Diagnose-Parameter haben EntityCategory.DIAGNOSTIC."""
        for key in _DIAGNOSTIC_KEYS:
            param = TLX_PARAMETERS[key]
            sensor = DanfossSensor(mock_coordinator, mock_config_entry, key, param)
            assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_measurement_sensors_no_entity_category(self, mock_coordinator, mock_config_entry):
        """Normale Messsensoren haben keine EntityCategory."""
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_power_total", param)
        assert not hasattr(sensor, "_attr_entity_category")

    def test_suggested_display_precision_voltage(self, mock_coordinator, mock_config_entry):
        """Spannungssensoren (scale=0.1) haben precision=1."""
        param = TLX_PARAMETERS["grid_voltage_l1"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_voltage_l1", param)
        assert sensor._attr_suggested_display_precision == 1

    def test_suggested_display_precision_frequency(self, mock_coordinator, mock_config_entry):
        """Frequenzsensoren (scale=0.001) haben precision=2."""
        param = TLX_PARAMETERS["grid_frequency_l1"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_frequency_l1", param)
        assert sensor._attr_suggested_display_precision == 2

    def test_suggested_display_precision_power(self, mock_coordinator, mock_config_entry):
        """Leistungssensoren (ganzzahlig) haben precision=0."""
        param = TLX_PARAMETERS["grid_power_total"]
        sensor = DanfossSensor(mock_coordinator, mock_config_entry, "grid_power_total", param)
        assert sensor._attr_suggested_display_precision == 0

    def test_parallel_updates_zero(self):
        """PARALLEL_UPDATES muss 0 sein (Coordinator-basiert)."""
        assert PARALLEL_UPDATES == 0


class TestDanfossOperationModeSensor:
    def test_maps_mode_60_on_grid(self, mock_coordinator, mock_config_entry):
        """Rohwert 60 = Produziert (On Grid)."""
        sensor = DanfossOperationModeSensor(mock_coordinator, mock_config_entry)
        assert sensor.native_value == "Produziert (On Grid)"

    def test_maps_mode_0_off(self, mock_config_entry):
        """Rohwert 0 = Aus (Off Grid)."""
        coordinator = MagicMock()
        coordinator.data = {"operation_mode": 0.0}
        sensor = DanfossOperationModeSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Aus (Off Grid)"

    def test_maps_mode_50_connecting(self, mock_config_entry):
        """Rohwert 50 = Verbindet (Connecting)."""
        coordinator = MagicMock()
        coordinator.data = {"operation_mode": 50.0}
        sensor = DanfossOperationModeSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Verbindet (Connecting)"

    def test_unknown_mode(self, mock_config_entry):
        coordinator = MagicMock()
        coordinator.data = {"operation_mode": 99.0}
        sensor = DanfossOperationModeSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Unbekannt (99)"

    def test_no_data(self, mock_coordinator_no_data, mock_config_entry):
        sensor = DanfossOperationModeSensor(mock_coordinator_no_data, mock_config_entry)
        assert sensor.native_value is None

    def test_attributes(self, mock_coordinator, mock_config_entry):
        sensor = DanfossOperationModeSensor(mock_coordinator, mock_config_entry)
        assert sensor._attr_name == "Betriebsmodus"
        assert "operation_mode_text" in sensor._attr_unique_id
        assert sensor._attr_icon == "mdi:solar-power"

    def test_entity_category_diagnostic(self, mock_coordinator, mock_config_entry):
        """OperationModeSensor hat EntityCategory.DIAGNOSTIC."""
        sensor = DanfossOperationModeSensor(mock_coordinator, mock_config_entry)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


class TestDanfossEventSensor:
    def test_maps_event_0_no_event(self, mock_coordinator, mock_config_entry):
        """Rohwert 0 = Kein Ereignis."""
        sensor = DanfossEventSensor(mock_coordinator, mock_config_entry)
        assert sensor.native_value == "Kein Ereignis"

    def test_maps_event_115_isolation(self, mock_config_entry):
        """Rohwert 115 = Isolationswiderstand PV-Erde zu niedrig."""
        coordinator = MagicMock()
        coordinator.data = {"latest_event": 115.0}
        sensor = DanfossEventSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Isolationswiderstand PV-Erde zu niedrig"

    def test_maps_event_1_voltage_low(self, mock_config_entry):
        """Rohwert 1 = Netzspannung L1 zu niedrig."""
        coordinator = MagicMock()
        coordinator.data = {"latest_event": 1.0}
        sensor = DanfossEventSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Netzspannung L1 zu niedrig"

    def test_unknown_event(self, mock_config_entry):
        """Unbekannter Ereignis-Code wird als 'Ereignis X' angezeigt."""
        coordinator = MagicMock()
        coordinator.data = {"latest_event": 999.0}
        sensor = DanfossEventSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Ereignis 999"

    def test_no_data(self, mock_coordinator_no_data, mock_config_entry):
        sensor = DanfossEventSensor(mock_coordinator_no_data, mock_config_entry)
        assert sensor.native_value is None

    def test_attributes(self, mock_coordinator, mock_config_entry):
        sensor = DanfossEventSensor(mock_coordinator, mock_config_entry)
        assert sensor._attr_name == "Letztes Ereignis"
        assert "latest_event_text" in sensor._attr_unique_id
        assert sensor._attr_icon == "mdi:alert-circle-outline"

    def test_entity_category_diagnostic(self, mock_coordinator, mock_config_entry):
        """EventSensor hat EntityCategory.DIAGNOSTIC."""
        sensor = DanfossEventSensor(mock_coordinator, mock_config_entry)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC


class TestDeviceInfo:
    def test_with_serial(self, mock_coordinator, mock_config_entry):
        info = _device_info(mock_coordinator, mock_config_entry)
        assert (DOMAIN, mock_config_entry.entry_id) in info["identifiers"]
        assert "TLX123456" in info["name"]
        assert info["manufacturer"] == "Danfoss Solar Inverters"
        assert info["serial_number"] == "TLX123456"
        assert info["sw_version"] == "3.45"
        assert info["hw_version"] == "7"

    def test_without_serial(self, mock_coordinator_no_data, mock_config_entry):
        info = _device_info(mock_coordinator_no_data, mock_config_entry)
        assert mock_config_entry.entry_id in info["name"]
        assert info["serial_number"] is None
        assert info["sw_version"] is None
        assert info["hw_version"] is None
