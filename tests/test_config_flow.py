"""Tests für den Config Flow."""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx.const import (
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_PV_STRINGS,
    CONF_SCAN_INTERVAL,
)
from custom_components.danfoss_tlx.config_flow import DanfossConfigFlow, DanfossOptionsFlow, ParameterReadError


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
            mock_client.read_parameters.return_value = {"grid_power_total": 1000}
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = DanfossConfigFlow._try_connect("192.168.1.100", "KNOWN_SER")

            assert result == "KNOWN_SER"
            mock_client.discover.assert_not_called()
            mock_client.read_parameters.assert_called_once()

    def test_try_connect_without_serial(self):
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_client.discover.return_value = "DISCOVERED"
            mock_client.read_parameters.return_value = {"grid_power_total": 1000}
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = DanfossConfigFlow._try_connect("192.168.1.100", "")

            mock_client.discover.assert_called_once()
            mock_client.read_parameters.assert_called_once()
            assert result == "DISCOVERED"

    def test_try_connect_parameter_read_fails(self):
        """Parameter-Read schlägt fehl → ParameterReadError."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_client.discover.return_value = "DISCOVERED"
            mock_client.read_parameters.return_value = {}
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(ParameterReadError):
                DanfossConfigFlow._try_connect("192.168.1.100", "")

    @pytest.mark.asyncio
    async def test_parameter_read_failure_shows_error(self, mock_hass):
        """Parameter-Read-Fehler zeigt cannot_read_parameters Error."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=ParameterReadError()
        )

        flow = DanfossConfigFlow()
        flow.hass = mock_hass

        result = await flow.async_step_user({
            CONF_INVERTER_IP: "192.168.1.100",
            CONF_INVERTER_SERIAL: "",
            CONF_PV_STRINGS: 2,
            CONF_SCAN_INTERVAL: 15,
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_read_parameters"

    def test_try_connect_with_serial_parameter_read_fails(self):
        """Parameter-Read schlägt fehl bei bekannter Seriennummer."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_client.read_parameters.return_value = {}
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(ParameterReadError):
                DanfossConfigFlow._try_connect("192.168.1.100", "KNOWN_SER")


class TestDanfossReconfigureFlow:
    @pytest.mark.asyncio
    async def test_reconfigure_shows_form(self, mock_hass, mock_config_entry):
        """Reconfigure-Step zeigt Formular mit aktuellen Werten."""
        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

        result = await flow.async_step_reconfigure(None)

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_reconfigure_updates_entry(self, mock_hass, mock_config_entry):
        """Erfolgreiche Rekonfiguration aktualisiert den Eintrag."""
        mock_hass.async_add_executor_job = AsyncMock(return_value="NEW_SER")

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)
        flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort"})

        await flow.async_step_reconfigure({
            CONF_INVERTER_IP: "192.168.1.200",
            CONF_INVERTER_SERIAL: "",
        })

        flow.async_update_reload_and_abort.assert_called_once()
        call_kwargs = flow.async_update_reload_and_abort.call_args
        new_data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert new_data[CONF_INVERTER_IP] == "192.168.1.200"
        assert new_data[CONF_INVERTER_SERIAL] == "NEW_SER"

    @pytest.mark.asyncio
    async def test_reconfigure_connection_failure(self, mock_hass, mock_config_entry):
        """Verbindungsfehler bei Rekonfiguration zeigt Fehler."""
        mock_hass.async_add_executor_job = AsyncMock(return_value=None)

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

        result = await flow.async_step_reconfigure({
            CONF_INVERTER_IP: "192.168.1.200",
            CONF_INVERTER_SERIAL: "",
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"


class TestDanfossConfigFlowErrors:
    @pytest.mark.asyncio
    async def test_user_generic_runtime_error(self, mock_hass):
        """User step: RuntimeError (nicht parameter_read_failed) zeigt cannot_connect."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=RuntimeError("some other error")
        )

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

    @pytest.mark.asyncio
    async def test_user_generic_exception(self, mock_hass):
        """User step: Unerwarteter Fehler zeigt cannot_connect."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=Exception("unexpected error")
        )

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

    @pytest.mark.asyncio
    async def test_reconfigure_generic_runtime_error(self, mock_hass, mock_config_entry):
        """Reconfigure: RuntimeError (nicht parameter_read_failed) zeigt cannot_connect."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=RuntimeError("some other error")
        )

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

        result = await flow.async_step_reconfigure({
            CONF_INVERTER_IP: "192.168.1.200",
            CONF_INVERTER_SERIAL: "",
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_reconfigure_generic_exception(self, mock_hass, mock_config_entry):
        """Reconfigure: Unerwarteter Fehler zeigt cannot_connect."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=Exception("unexpected error")
        )

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

        result = await flow.async_step_reconfigure({
            CONF_INVERTER_IP: "192.168.1.200",
            CONF_INVERTER_SERIAL: "",
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_reconfigure_parameter_read_failed(self, mock_hass, mock_config_entry):
        """Reconfigure: ParameterReadError zeigt cannot_read_parameters."""
        mock_hass.async_add_executor_job = AsyncMock(
            side_effect=ParameterReadError()
        )

        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

        result = await flow.async_step_reconfigure({
            CONF_INVERTER_IP: "192.168.1.200",
            CONF_INVERTER_SERIAL: "",
        })

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_read_parameters"

    def test_try_connect_without_serial_discover_returns_none(self):
        """_try_connect ohne Serial: discover() gibt None zurück → return None."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = MagicMock()
            mock_client.discover.return_value = None
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = DanfossConfigFlow._try_connect("192.168.1.100", "")

            assert result is None
            mock_client.discover.assert_called_once()
            mock_client.read_parameters.assert_not_called()

    def test_options_flow_factory(self, mock_config_entry):
        """Options Flow Factory gibt DanfossOptionsFlow zurück."""
        result = DanfossConfigFlow.async_get_options_flow(mock_config_entry)
        assert isinstance(result, DanfossOptionsFlow)


class TestDanfossOptionsFlow:
    @pytest.mark.asyncio
    async def test_shows_form_with_defaults(self, mock_config_entry):
        flow = DanfossOptionsFlow()
        flow._config_entry = mock_config_entry
        # OptionsFlow greift über self.config_entry zu; setzen wir als Property
        type(flow).config_entry = property(lambda self: self._config_entry)
        result = await flow.async_step_init(None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_saves_updates(self, mock_config_entry):
        flow = DanfossOptionsFlow()
        flow._config_entry = mock_config_entry
        type(flow).config_entry = property(lambda self: self._config_entry)
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        await flow.async_step_init({
            CONF_SCAN_INTERVAL: 30,
            CONF_PV_STRINGS: 3,
        })

        flow.async_create_entry.assert_called_once_with(
            title="",
            data={CONF_SCAN_INTERVAL: 30, CONF_PV_STRINGS: 3},
        )
