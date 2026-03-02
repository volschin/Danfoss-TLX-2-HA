"""Tests für das Integration-Setup."""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx import async_setup_entry, async_unload_entry, PLATFORMS


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
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            mock_config_entry, PLATFORMS
        )
        mock_config_entry.async_on_unload.assert_called_once()

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
