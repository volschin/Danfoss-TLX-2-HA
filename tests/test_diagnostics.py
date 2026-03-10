"""Tests für das Danfoss TLX Pro Diagnostics-Modul."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.danfoss_tlx.diagnostics import async_get_config_entry_diagnostics
from custom_components.danfoss_tlx.const import (
    DEFAULT_PV_STRINGS,
    DEFAULT_SCAN_INTERVAL,
)


@pytest.fixture
def mock_coordinator(sample_inverter_data):
    """Erstellt einen Mock-Coordinator mit Testdaten."""
    coordinator = MagicMock()
    coordinator.inverter_serial = "TLX123456"
    coordinator.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    coordinator.data = sample_inverter_data
    return coordinator


@pytest.fixture
def config_entry_with_coordinator(mock_config_entry, mock_coordinator):
    """Erstellt einen Config-Eintrag mit angehängtem Mock-Coordinator."""
    mock_config_entry.runtime_data = mock_coordinator
    return mock_config_entry


@pytest.mark.asyncio
async def test_diagnostics_returns_config_ip(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass die Inverter-IP in den Diagnostics enthalten ist."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["config"]["inverter_ip"] == "192.168.1.100"


@pytest.mark.asyncio
async def test_diagnostics_returns_pv_strings(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass pv_strings in den Diagnostics enthalten ist."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["config"]["pv_strings"] == DEFAULT_PV_STRINGS


@pytest.mark.asyncio
async def test_diagnostics_returns_scan_interval(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass scan_interval in den Diagnostics enthalten ist."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["config"]["scan_interval"] == DEFAULT_SCAN_INTERVAL


@pytest.mark.asyncio
async def test_diagnostics_redacts_inverter_serial(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass der Wechselrichter-Serial in den Diagnostics verschleiert wird."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["config"]["inverter_serial"] == "**REDACTED**"
    # Stellt sicher, dass die echte Seriennummer nicht im config-Abschnitt erscheint
    assert "TLX123456" not in str(result["config"])


@pytest.mark.asyncio
async def test_diagnostics_includes_coordinator_serial(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass der Coordinator-Serial in den Diagnostics enthalten ist."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["coordinator"]["serial"] == "TLX123456"


@pytest.mark.asyncio
async def test_diagnostics_includes_update_interval(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass das Update-Intervall in den Diagnostics enthalten ist."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["coordinator"]["update_interval_seconds"] == float(DEFAULT_SCAN_INTERVAL)


@pytest.mark.asyncio
async def test_diagnostics_includes_inverter_data(mock_hass, config_entry_with_coordinator, sample_inverter_data):
    """Stellt sicher, dass die Inverterdaten in den Diagnostics enthalten sind."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert result["inverter_data"] == sample_inverter_data
    assert result["inverter_data"]["grid_power_total"] == 2903.0


@pytest.mark.asyncio
async def test_diagnostics_handles_none_coordinator_data(mock_hass, mock_config_entry, mock_coordinator):
    """Stellt sicher, dass None-Daten im Coordinator korrekt behandelt werden."""
    mock_coordinator.data = None
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(mock_hass, mock_config_entry)

    assert result["inverter_data"] is None


@pytest.mark.asyncio
async def test_diagnostics_structure(mock_hass, config_entry_with_coordinator):
    """Stellt sicher, dass die Diagnostics-Ausgabe die erwartete Struktur hat."""
    result = await async_get_config_entry_diagnostics(mock_hass, config_entry_with_coordinator)

    assert "config" in result
    assert "coordinator" in result
    assert "inverter_data" in result

    config = result["config"]
    assert "inverter_ip" in config
    assert "inverter_serial" in config
    assert "pv_strings" in config
    assert "scan_interval" in config

    coordinator = result["coordinator"]
    assert "serial" in coordinator
    assert "update_interval_seconds" in coordinator
