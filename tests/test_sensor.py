"""Tests für die Sensor-Plattform."""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from custom_components.danfoss_tlx.const import DOMAIN, CONF_PV_STRINGS
from custom_components.danfoss_tlx.etherlynx import TLX_PARAMETERS, OPERATION_MODES
from custom_components.danfoss_tlx.sensor import (
    async_setup_entry,
    DanfossSensor,
    DanfossOperationModeSensor,
    _device_info,
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
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        added_entities = []

        def capture_entities(entities):
            added_entities.extend(entities)

        await async_setup_entry(mock_hass, mock_config_entry, capture_entities)

        # All TLX_PARAMETERS sensors (minus pv_*_3 for 2 strings) + 1 operation_mode_text
        pv3_count = sum(1 for k in TLX_PARAMETERS if k.startswith("pv_") and "_3" in k)
        expected = len(TLX_PARAMETERS) - pv3_count + 1
        assert len(added_entities) == expected

    @pytest.mark.asyncio
    async def test_pv3_excluded_with_2_strings(self, mock_hass, mock_config_entry, mock_coordinator):
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
        mock_config_entry.data[CONF_PV_STRINGS] = 2
        added_entities = []

        await async_setup_entry(mock_hass, mock_config_entry, lambda e: added_entities.extend(e))

        sensor_keys = [e._key for e in added_entities if isinstance(e, DanfossSensor)]
        pv3_keys = [k for k in sensor_keys if k.startswith("pv_") and "_3" in k]
        assert len(pv3_keys) == 0

    @pytest.mark.asyncio
    async def test_pv3_included_with_3_strings(self, mock_hass, mock_config_entry, mock_coordinator):
        mock_hass.data[DOMAIN] = {mock_config_entry.entry_id: mock_coordinator}
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


class TestDanfossOperationModeSensor:
    def test_maps_mode_4(self, mock_coordinator, mock_config_entry):
        sensor = DanfossOperationModeSensor(mock_coordinator, mock_config_entry)
        assert sensor.native_value == "Produziert"

    def test_unknown_mode(self, mock_config_entry):
        coordinator = MagicMock()
        coordinator.data = {"operation_mode": 99.0}
        sensor = DanfossOperationModeSensor(coordinator, mock_config_entry)
        assert sensor.native_value == "Unbekannt (99.0)"

    def test_no_data(self, mock_coordinator_no_data, mock_config_entry):
        sensor = DanfossOperationModeSensor(mock_coordinator_no_data, mock_config_entry)
        assert sensor.native_value is None

    def test_attributes(self, mock_coordinator, mock_config_entry):
        sensor = DanfossOperationModeSensor(mock_coordinator, mock_config_entry)
        assert sensor._attr_name == "Betriebsmodus"
        assert "operation_mode_text" in sensor._attr_unique_id
        assert sensor._attr_icon == "mdi:solar-power"


class TestDeviceInfo:
    def test_with_serial(self, mock_coordinator, mock_config_entry):
        info = _device_info(mock_coordinator, mock_config_entry)
        assert (DOMAIN, mock_config_entry.entry_id) in info["identifiers"]
        assert "TLX123456" in info["name"]

    def test_without_serial(self, mock_coordinator_no_data, mock_config_entry):
        info = _device_info(mock_coordinator_no_data, mock_config_entry)
        assert mock_config_entry.entry_id in info["name"]
