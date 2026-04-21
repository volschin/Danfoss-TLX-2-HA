"""Tests für den DanfossCoordinator."""
from datetime import timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.danfoss_tlx.const import (
    CONF_INVERTER_SERIAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)


def _make_coordinator(mock_hass, mock_config_entry, capture_super: bool = False):
    """Erstellt einen DanfossCoordinator.

    Der super().__init__-Aufruf wird gepatcht, weil DataUpdateCoordinator in
    neueren HA-Versionen einen Frame-Helper erwartet. Wenn capture_super=True,
    wird der Mock zurückgegeben, um die an super() übergebenen Argumente zu
    verifizieren.
    """
    with patch(
        "custom_components.danfoss_tlx.coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ) as mock_super_init:
        from custom_components.danfoss_tlx.coordinator import DanfossCoordinator
        coordinator = DanfossCoordinator(mock_hass, mock_config_entry)
        coordinator.hass = mock_hass
    if capture_super:
        return coordinator, mock_super_init
    return coordinator


class TestDanfossCoordinator:
    def test_init_reads_config(self, mock_hass, mock_config_entry):
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        assert coordinator._ip == "192.168.1.100"
        assert coordinator._inverter_serial == "TLX123456"

    def test_init_options_override_interval(self, mock_hass, mock_config_entry):
        """options[scan_interval] wird tatsächlich an DataUpdateCoordinator übergeben."""
        mock_config_entry.options = {CONF_SCAN_INTERVAL: 60}
        _, mock_super_init = _make_coordinator(
            mock_hass, mock_config_entry, capture_super=True
        )
        # Eine super().__init__-Invocation
        mock_super_init.assert_called_once()
        kwargs = mock_super_init.call_args.kwargs
        assert kwargs["update_interval"] == timedelta(seconds=60)

    def test_init_data_interval_used_when_no_options(self, mock_hass, mock_config_entry):
        """Wenn options leer: scan_interval aus entry.data wird verwendet."""
        mock_config_entry.options = {}
        mock_config_entry.data[CONF_SCAN_INTERVAL] = 45
        _, mock_super_init = _make_coordinator(
            mock_hass, mock_config_entry, capture_super=True
        )
        kwargs = mock_super_init.call_args.kwargs
        assert kwargs["update_interval"] == timedelta(seconds=45)

    def test_init_default_interval_as_last_fallback(self, mock_hass, mock_config_entry):
        """Wenn weder options noch data scan_interval enthalten: DEFAULT_SCAN_INTERVAL."""
        mock_config_entry.options = {}
        mock_config_entry.data.pop(CONF_SCAN_INTERVAL, None)
        _, mock_super_init = _make_coordinator(
            mock_hass, mock_config_entry, capture_super=True
        )
        kwargs = mock_super_init.call_args.kwargs
        assert kwargs["update_interval"] == timedelta(seconds=DEFAULT_SCAN_INTERVAL)

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
    async def test_fetch_data_resets_on_read_all_exception(self, mock_cls, mock_hass, mock_config_entry):
        """Client wird bei unerwarteter Exception in read_all geschlossen und zurückgesetzt."""
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.read_all = AsyncMock(side_effect=OSError("Netzwerkfehler"))
        mock_client.close = AsyncMock()
        mock_client.inverter_serial = "TLX123456"

        coordinator = _make_coordinator(mock_hass, mock_config_entry)

        with pytest.raises(OSError):
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
    async def test_homeassistant_error_propagates_unchanged(self, mock_hass, mock_config_entry):
        """HomeAssistantError aus _fetch_data wird unverändert weitergegeben."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        coordinator.last_update_success = True

        ha_error = HomeAssistantError(translation_domain="danfoss_tlx", translation_key="inverter_unreachable")
        with patch.object(
            coordinator, "_fetch_data", AsyncMock(side_effect=ha_error)
        ):
            with pytest.raises(HomeAssistantError) as exc_info:
                await coordinator._async_update_data()
            assert exc_info.value is ha_error

    @pytest.mark.asyncio
    async def test_warning_logged_on_first_failure(self, mock_hass, mock_config_entry):
        """WARNING wird beim ersten Fehler geloggt."""
        coordinator = _make_coordinator(mock_hass, mock_config_entry)
        coordinator.last_update_success = True

        with patch.object(
            coordinator, "_fetch_data", AsyncMock(side_effect=Exception("Timeout"))
        ):
            with patch("custom_components.danfoss_tlx.coordinator._LOGGER") as mock_logger:
                with pytest.raises(UpdateFailed):
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
                with pytest.raises(UpdateFailed):
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
