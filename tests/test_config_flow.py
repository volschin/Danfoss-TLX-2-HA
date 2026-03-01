"""Tests für den Config Flow."""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx.const import (
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_PV_STRINGS,
    CONF_SCAN_INTERVAL,
)
from custom_components.danfoss_tlx.config_flow import DanfossConfigFlow, DanfossOptionsFlow


class TestDanfossConfigFlow:
    @pytest.mark.asyncio
    async def test_step_user_shows_form(self, mock_hass):
        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        result = await flow.async_step_user(None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    @patch("custom_components.danfoss_tlx.config_flow.DanfossConfigFlow._try_connect")
    async def test_successful_connection(self, mock_connect, mock_hass):
        mock_connect.return_value = "SER_FOUND"
        mock_hass.async_add_executor_job = AsyncMock(return_value="SER_FOUND")

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        await flow.async_step_user({
            CONF_INVERTER_IP: "192.168.1.100",
            CONF_INVERTER_SERIAL: "",
            CONF_PV_STRINGS: 2,
            CONF_SCAN_INTERVAL: 15,
        })

        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args[1]
        assert call_kwargs["data"][CONF_INVERTER_IP] == "192.168.1.100"
        assert call_kwargs["data"][CONF_INVERTER_SERIAL] == "SER_FOUND"

    @pytest.mark.asyncio
    async def test_connection_failure(self, mock_hass):
        mock_hass.async_add_executor_job = AsyncMock(return_value=None)

        flow = DanfossConfigFlow()
        flow.hass = mock_hass

        result = await flow.async_step_user({
            CONF_INVERTER_IP: "192.168.1.100",
            CONF_INVERTER_SERIAL: "",
            CONF_PV_STRINGS: 2,
            CONF_SCAN_INTERVAL: 15,
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    def test_try_connect_with_serial(self):
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = DanfossConfigFlow._try_connect("192.168.1.100", "KNOWN_SER")

            assert result == "KNOWN_SER"
            mock_client.discover.assert_not_called()

    def test_try_connect_without_serial(self):
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_client.discover.return_value = "DISCOVERED"
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = DanfossConfigFlow._try_connect("192.168.1.100", "")

            mock_client.discover.assert_called_once()
            assert result == "DISCOVERED"


class TestDanfossOptionsFlow:
    @pytest.mark.asyncio
    async def test_shows_form_with_defaults(self, mock_config_entry):
        flow = DanfossOptionsFlow(mock_config_entry)
        result = await flow.async_step_init(None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_saves_updates(self, mock_config_entry):
        flow = DanfossOptionsFlow(mock_config_entry)
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        await flow.async_step_init({
            CONF_SCAN_INTERVAL: 30,
            CONF_PV_STRINGS: 3,
        })

        flow.async_create_entry.assert_called_once_with(
            title="",
            data={CONF_SCAN_INTERVAL: 30, CONF_PV_STRINGS: 3},
        )
