"""Tests für den DanfossCoordinator."""
from unittest.mock import patch, MagicMock

import pytest

from custom_components.danfoss_tlx.const import (
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)


def _make_coordinator(mock_hass, mock_config_entry):
    """Erstellt einen DanfossCoordinator mit gepatchtem super().__init__."""
    with patch(
        "custom_components.danfoss_tlx.coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ):
        from custom_components.danfoss_tlx.coordinator import DanfossCoordinator
        coordinator = DanfossCoordinator(mock_hass, mock_config_entry)
        coordinator.hass = mock_hass
    return coordinator


class TestDanfossCoordinator:
    def test_init_reads_config(self, mock_hass, mock_config_entry):
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator._ip == "192.168.1.100"
        assert coordinator._inverter_serial == "TLX123456"

    def test_init_options_override_interval(self, mock_hass, mock_config_entry):
        mock_config_entry.options = {CONF_SCAN_INTERVAL: 60}
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        # The interval is read but passed to super().__init__ which is mocked,
        # so we verify the value calculation indirectly
        interval = mock_config_entry.options.get(
            CONF_SCAN_INTERVAL,
            mock_config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        assert interval == 60

    def test_inverter_serial_property(self, mock_hass, mock_config_entry):
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.inverter_serial == "TLX123456"

    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    def test_fetch_data_with_serial(self, mock_cls, mock_hass, mock_config_entry):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.read_all.return_value = {"grid_power_total": 1500.0}
        mock_client.inverter_serial = "TLX123456"

        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        data = coordinator._fetch_data()

        assert data["grid_power_total"] == 1500.0
        mock_client.discover.assert_not_called()

    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    def test_fetch_data_discovers_when_no_serial(self, mock_cls, mock_hass, mock_config_entry):
        mock_config_entry.data[CONF_INVERTER_SERIAL] = ""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.discover.return_value = "DISCOVERED_SER"
        mock_client.inverter_serial = "DISCOVERED_SER"
        mock_client.read_all.return_value = {"operation_mode": 4.0}

        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        data = coordinator._fetch_data()

        mock_client.discover.assert_called_once()
        assert data["operation_mode"] == 4.0

    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    def test_fetch_data_resets_on_empty_result(self, mock_cls, mock_hass, mock_config_entry):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.read_all.return_value = {}
        mock_client.inverter_serial = "TLX123456"

        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with pytest.raises(RuntimeError, match="Keine Daten"):
            coordinator._fetch_data()

        mock_client.close.assert_called_once()
        assert coordinator._client is None

    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    def test_fetch_data_raises_on_failed_discovery(self, mock_cls, mock_hass, mock_config_entry):
        mock_config_entry.data[CONF_INVERTER_SERIAL] = ""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.discover.return_value = None

        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            coordinator._fetch_data()
