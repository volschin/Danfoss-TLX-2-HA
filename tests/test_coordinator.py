"""Tests für den DanfossCoordinator."""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_tlx.const import (
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
        _make_coordinator(mock_hass, mock_config_entry)
        interval = mock_config_entry.options.get(
            CONF_SCAN_INTERVAL,
            mock_config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        assert interval == 60

    def test_inverter_serial_property(self, mock_hass, mock_config_entry):
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator.inverter_serial == "TLX123456"

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    async def test_fetch_data_with_serial(self, mock_cls, mock_hass, mock_config_entry):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.read_all = AsyncMock(return_value={"grid_power_total": 1500.0})
        mock_client.close = AsyncMock()
        mock_client.inverter_serial = "TLX123456"

        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        data = await coordinator._fetch_data()

        assert data["grid_power_total"] == 1500.0
        mock_client.discover.assert_not_called()

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    async def test_fetch_data_discovers_when_no_serial(self, mock_cls, mock_hass, mock_config_entry):
        mock_config_entry.data[CONF_INVERTER_SERIAL] = ""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.discover = AsyncMock(return_value="DISCOVERED_SER")
        mock_client.inverter_serial = "DISCOVERED_SER"
        mock_client.read_all = AsyncMock(return_value={"operation_mode": 60.0})
        mock_client.close = AsyncMock()

        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        data = await coordinator._fetch_data()

        mock_client.discover.assert_called_once()
        assert data["operation_mode"] == 60.0

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    async def test_fetch_data_resets_on_empty_result(self, mock_cls, mock_hass, mock_config_entry):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.read_all = AsyncMock(return_value={})
        mock_client.close = AsyncMock()
        mock_client.inverter_serial = "TLX123456"

        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with pytest.raises(HomeAssistantError):
            await coordinator._fetch_data()

        mock_client.close.assert_called_once()
        assert coordinator._client is None

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.coordinator.DanfossEtherLynx")
    async def test_fetch_data_raises_on_failed_discovery(self, mock_cls, mock_hass, mock_config_entry):
        mock_config_entry.data[CONF_INVERTER_SERIAL] = ""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.discover = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()

        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with pytest.raises(HomeAssistantError):
            await coordinator._fetch_data()

    @pytest.mark.asyncio
    async def test_warning_logged_on_first_failure(self, mock_hass, mock_config_entry):
        """WARNING wird beim ersten Fehler geloggt."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        coordinator.last_update_success = True

        with patch.object(
            coordinator, "_fetch_data", AsyncMock(side_effect=Exception("Timeout"))
        ):
            with patch("custom_components.danfoss_tlx.coordinator._LOGGER") as mock_logger:
                with pytest.raises(Exception):
                    await coordinator._async_update_data()
                mock_logger.warning.assert_called_once()
                assert "192.168.1.100" in mock_logger.warning.call_args[0][1]

    @pytest.mark.asyncio
    async def test_no_repeated_warning_on_consecutive_failures(self, mock_hass, mock_config_entry):
        """Kein weiteres WARNING bei aufeinanderfolgenden Fehlern."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        coordinator.last_update_success = False

        with patch.object(
            coordinator, "_fetch_data", AsyncMock(side_effect=Exception("Timeout"))
        ):
            with patch("custom_components.danfoss_tlx.coordinator._LOGGER") as mock_logger:
                with pytest.raises(Exception):
                    await coordinator._async_update_data()
                mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_info_logged_on_recovery(self, mock_hass, mock_config_entry):
        """INFO wird geloggt, wenn Inverter nach Fehler wieder erreichbar ist."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        coordinator.last_update_success = False

        sample_data = {"grid_power_total": 1500.0}
        with patch.object(
            coordinator, "_fetch_data", AsyncMock(return_value=sample_data)
        ):
            with patch("custom_components.danfoss_tlx.coordinator._LOGGER") as mock_logger:
                result = await coordinator._async_update_data()
                mock_logger.info.assert_called_once()
                assert "192.168.1.100" in mock_logger.info.call_args[0][1]

        assert result == sample_data
