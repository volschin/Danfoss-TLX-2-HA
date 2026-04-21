"""Tests für das Integration-Setup."""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx import async_setup_entry, async_unload_entry, PLATFORMS, _async_reload_entry


class TestIntegrationSetup:
    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.DanfossCoordinator")
    async def test_setup_entry(self, mock_coordinator_cls, mock_hass, mock_config_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_cls.return_value = mock_coordinator

        result = await async_setup_entry(mock_hass, mock_config_entry)

        assert result is True
        assert mock_config_entry.runtime_data is mock_coordinator
        # First-Refresh muss beim Setup tatsächlich erfolgen
        mock_coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            mock_config_entry, PLATFORMS
        )
        mock_config_entry.async_on_unload.assert_called_once()

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.DanfossCoordinator")
    async def test_setup_entry_propagates_first_refresh_error(
        self, mock_coordinator_cls, mock_hass, mock_config_entry
    ):
        """Ein Fehler beim First-Refresh muss propagiert werden, damit HA den Entry als fehlgeschlagen markiert."""
        from homeassistant.exceptions import ConfigEntryNotReady

        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock(
            side_effect=ConfigEntryNotReady("Inverter unreachable")
        )
        mock_coordinator_cls.return_value = mock_coordinator

        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(mock_hass, mock_config_entry)

        # Plattformen dürfen nach gescheitertem Refresh nicht geladen werden
        mock_hass.config_entries.async_forward_entry_setups.assert_not_called()

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.DanfossCoordinator")
    async def test_unload_entry(self, mock_coordinator_cls, mock_hass, mock_config_entry):
        # Setup first
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_cls.return_value = mock_coordinator
        await async_setup_entry(mock_hass, mock_config_entry)

        # Now unload
        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is True
        # Plattform-Unload muss tatsächlich an HA delegiert werden
        mock_hass.config_entries.async_unload_platforms.assert_awaited_once_with(
            mock_config_entry, PLATFORMS
        )

    @pytest.mark.asyncio
    async def test_unload_entry_returns_false_when_platforms_fail(
        self, mock_hass, mock_config_entry
    ):
        """Wenn HA das Plattform-Unload ablehnt, gibt async_unload_entry False zurück."""
        mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        result = await async_unload_entry(mock_hass, mock_config_entry)

        assert result is False

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.DanfossCoordinator")
    async def test_update_listener_registered(self, mock_coordinator_cls, mock_hass, mock_config_entry):
        mock_coordinator = MagicMock()
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()
        mock_coordinator_cls.return_value = mock_coordinator

        await async_setup_entry(mock_hass, mock_config_entry)

        mock_config_entry.async_on_unload.assert_called_once()
        # The unload callback came from add_update_listener
        mock_config_entry.add_update_listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_reload_entry(self, mock_hass, mock_config_entry):
        """_async_reload_entry ruft async_reload mit entry_id auf."""
        mock_hass.config_entries.async_reload = AsyncMock()

        await _async_reload_entry(mock_hass, mock_config_entry)

        mock_hass.config_entries.async_reload.assert_awaited_once_with(
            mock_config_entry.entry_id
        )
