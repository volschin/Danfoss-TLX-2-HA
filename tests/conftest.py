"""Gemeinsame Test-Fixtures für Danfoss TLX Pro Tests."""
import struct
from unittest.mock import MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx.etherlynx import (
    ETHERLYNX_HEADER_SIZE,
    MASTER_SERIAL,
    Flag,
    MessageID,
    ParameterDef,
    DataType,
    MODULE_COMM_BOARD,
    TLX_PARAMETERS,
    _pad_serial,
)
from custom_components.danfoss_tlx.const import (
    DOMAIN,
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_PV_STRINGS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PV_STRINGS,
)


@pytest.fixture
def mock_hass():
    """Erstellt ein Mock-HomeAssistant-Objekt."""
    hass = MagicMock()
    hass.data = {}

    async def run_in_executor(executor, func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: run_in_executor(None, func, *a))
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Erstellt einen Mock-ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.data = {
        CONF_INVERTER_IP: "192.168.1.100",
        CONF_INVERTER_SERIAL: "TLX123456",
        CONF_PV_STRINGS: DEFAULT_PV_STRINGS,
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
    }
    entry.options = {}
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=lambda: None)
    return entry


@pytest.fixture
def sample_inverter_data():
    """Realistische Inverterdaten für alle ~40 Parameter."""
    return {
        "total_energy": 12345678.0,
        "energy_today": 5432.0,
        "pv_voltage_1": 35.2,
        "pv_voltage_2": 34.8,
        "pv_voltage_3": 35.0,
        "pv_current_1": 8.5,
        "pv_current_2": 8.3,
        "pv_current_3": 8.4,
        "pv_power_1": 2990.0,
        "pv_power_2": 2880.0,
        "pv_power_3": 2940.0,
        "pv_energy_1": 4100000.0,
        "pv_energy_2": 4050000.0,
        "pv_energy_3": 4075000.0,
        "grid_voltage_l1": 230.5,
        "grid_voltage_l2": 231.2,
        "grid_voltage_l3": 229.8,
        "grid_voltage_l1_avg": 230.3,
        "grid_voltage_l2_avg": 231.0,
        "grid_voltage_l3_avg": 229.6,
        "grid_current_l1": 4.2,
        "grid_current_l2": 4.1,
        "grid_current_l3": 4.3,
        "grid_power_l1": 966.0,
        "grid_power_l2": 948.0,
        "grid_power_l3": 989.0,
        "grid_power_total": 2903.0,
        "grid_energy_today_l1": 1800.0,
        "grid_energy_today_l2": 1760.0,
        "grid_energy_today_l3": 1840.0,
        "grid_energy_today_total": 5400.0,
        "grid_dc_l1": 12.0,
        "grid_dc_l2": -5.0,
        "grid_dc_l3": 8.0,
        "grid_frequency_l1": 50.01,
        "grid_frequency_l2": 50.01,
        "grid_frequency_l3": 50.01,
        "grid_frequency_avg": 50.01,
        "irradiance": 850.0,
        "ambient_temp": 25.0,
        "pv_array_temp": 42.0,
        "operation_mode": 4.0,
        "latest_event": 0.0,
        "hardware_type": 7.0,
        "nominal_power": 12500.0,
        "sw_version": 3.45,
        "production_today_log": 5400.0,
        "production_this_week": 32000.0,
        "production_this_month": 145000.0,
        "production_this_year": 2500.0,
    }


@pytest.fixture
def make_ping_response():
    """Factory für gültige 52-Byte Ping-Response-Pakete."""
    def _make(serial: str = "TLX123456") -> bytes:
        header = bytearray(ETHERLYNX_HEADER_SIZE)
        # Source serial (Bytes 0-11)
        serial_bytes = serial.encode('ascii') + b'\x00'
        serial_bytes = serial_bytes.ljust(12, b'\x00')
        header[0:12] = serial_bytes[:12]
        # Flags: RESPONSE | FB | RES_NEEDED
        header[37] = Flag.RESPONSE | Flag.FB | Flag.RES_NEEDED
        # Message ID: PING
        header[39] = MessageID.PING
        return bytes(header)
    return _make


@pytest.fixture
def make_parameter_response():
    """Factory für Parameter-Response-Pakete.

    Args: Liste von (ParameterDef, raw_value_bytes) Tupeln.
    """
    def _make(params_with_values: list, error_indices: set = None) -> bytes:
        if error_indices is None:
            error_indices = set()

        header = bytearray(ETHERLYNX_HEADER_SIZE)
        header[37] = Flag.RESPONSE | Flag.SB | Flag.RES_NEEDED
        header[39] = MessageID.GET_SET_PARAMETER

        payload = bytearray()
        # Parameteranzahl
        payload.extend(struct.pack('>I', len(params_with_values)))

        for i, (param_def, raw_bytes) in enumerate(params_with_values):
            if i in error_indices:
                attr_byte = 0x01  # Error-Bit gesetzt
            else:
                attr_byte = (param_def.data_type & 0x0F) << 1
            module_byte = ((param_def.module_id & 0x0F) << 4) | (param_def.module_id & 0x0F)
            payload.extend(struct.pack('BBBB',
                attr_byte,
                module_byte,
                param_def.index & 0xFF,
                param_def.subindex & 0xFF,
            ))
            # raw value (4 bytes, pad if needed)
            value_bytes = raw_bytes[:4].ljust(4, b'\x00')
            payload.extend(value_bytes)

        # Data length in header
        header[40:44] = struct.pack('>I', len(payload))

        return bytes(header) + bytes(payload)
    return _make
