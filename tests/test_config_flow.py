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


def _make_mock_client(discover_return="SER_FOUND", read_return=None):
    """Hilfsfunktion: erstellt einen AsyncMock-Client für DanfossEtherLynx."""
    if read_return is None:
        read_return = {"grid_power_total": 1500.0}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.discover = AsyncMock(return_value=discover_return)
    mock_client.read_parameters = AsyncMock(return_value=read_return)
    return mock_client


class TestDanfossConfigFlow:
    @pytest.mark.asyncio
    async def test_step_user_shows_form(self, mock_hass):
        flow = DanfossConfigFlow()
        flow.hass = mock_hass
        result = await flow.async_step_user(None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_successful_connection(self, mock_hass):
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return="SER_FOUND")
            mock_cls.return_value = mock_client

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

            # Unique-ID-Schutz muss greifen: discover-Seriennummer als ID
            flow.async_set_unique_id.assert_awaited_once_with("danfoss_tlx_SER_FOUND")
            flow._abort_if_unique_id_configured.assert_called_once_with()

            flow.async_create_entry.assert_called_once()
            call_kwargs = flow.async_create_entry.call_args[1]
            assert call_kwargs["data"][CONF_INVERTER_IP] == "192.168.1.100"
            assert call_kwargs["data"][CONF_INVERTER_SERIAL] == "SER_FOUND"

    @pytest.mark.asyncio
    async def test_successful_connection_with_known_serial(self, mock_hass):
        """Wenn Serial bekannt, wird discover() nicht aufgerufen."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client()
            mock_cls.return_value = mock_client

            flow = DanfossConfigFlow()
            flow.hass = mock_hass
            flow.async_set_unique_id = AsyncMock()
            flow._abort_if_unique_id_configured = MagicMock()
            flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

            await flow.async_step_user({
                CONF_INVERTER_IP: "192.168.1.100",
                CONF_INVERTER_SERIAL: "KNOWN_SER",
                CONF_PV_STRINGS: 2,
                CONF_SCAN_INTERVAL: 15,
            })

            mock_client.discover.assert_not_called()
            # Unique-ID basiert auf der bekannten Seriennummer
            flow.async_set_unique_id.assert_awaited_once_with("danfoss_tlx_KNOWN_SER")
            flow._abort_if_unique_id_configured.assert_called_once_with()
            flow.async_create_entry.assert_called_once()
            call_kwargs = flow.async_create_entry.call_args[1]
            assert call_kwargs["data"][CONF_INVERTER_SERIAL] == "KNOWN_SER"

    @pytest.mark.asyncio
    async def test_duplicate_entry_aborts(self, mock_hass):
        """Ein bereits konfigurierter Inverter (gleicher Unique-ID) führt zum Abort."""
        from homeassistant.data_entry_flow import AbortFlow

        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return="SER_FOUND")
            mock_cls.return_value = mock_client

            flow = DanfossConfigFlow()
            flow.hass = mock_hass
            flow.async_set_unique_id = AsyncMock()
            # Simuliere: Unique-ID bereits konfiguriert → AbortFlow
            flow._abort_if_unique_id_configured = MagicMock(
                side_effect=AbortFlow("already_configured")
            )
            flow.async_create_entry = MagicMock()

            with pytest.raises(AbortFlow):
                await flow.async_step_user({
                    CONF_INVERTER_IP: "192.168.1.100",
                    CONF_INVERTER_SERIAL: "",
                    CONF_PV_STRINGS: 2,
                    CONF_SCAN_INTERVAL: 15,
                })

            # Bei Duplikat darf kein Entry erzeugt werden
            flow.async_create_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_failure_discover_returns_none(self, mock_hass):
        """discover() gibt None zurück → cannot_connect."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return=None)
            mock_cls.return_value = mock_client

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
    async def test_parameter_read_failure_shows_error(self, mock_hass):
        """Parameter-Read-Fehler zeigt cannot_read_parameters Error."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return="SER_FOUND", read_return={})
            mock_cls.return_value = mock_client

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

    @pytest.mark.asyncio
    async def test_parameter_read_failure_with_known_serial(self, mock_hass):
        """Parameter-Read schlägt fehl bei bekannter Seriennummer."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(read_return={})
            mock_cls.return_value = mock_client

            flow = DanfossConfigFlow()
            flow.hass = mock_hass

            result = await flow.async_step_user({
                CONF_INVERTER_IP: "192.168.1.100",
                CONF_INVERTER_SERIAL: "KNOWN_SER",
                CONF_PV_STRINGS: 2,
                CONF_SCAN_INTERVAL: 15,
            })

            assert result["type"] == "form"
            assert result["errors"]["base"] == "cannot_read_parameters"

    def test_options_flow_factory(self, mock_config_entry):
        """Options Flow Factory gibt DanfossOptionsFlow zurück."""
        result = DanfossConfigFlow.async_get_options_flow(mock_config_entry)
        assert isinstance(result, DanfossOptionsFlow)


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
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return="NEW_SER")
            mock_cls.return_value = mock_client

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
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return=None)
            mock_cls.return_value = mock_client

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
        """User step: RuntimeError beim Verbinden zeigt cannot_connect."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client()
            mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("some other error"))
            mock_cls.return_value = mock_client

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
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client()
            mock_client.__aenter__ = AsyncMock(side_effect=Exception("unexpected error"))
            mock_cls.return_value = mock_client

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
        """Reconfigure: RuntimeError beim Verbinden zeigt cannot_connect."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client()
            mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("some other error"))
            mock_cls.return_value = mock_client

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
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client()
            mock_client.__aenter__ = AsyncMock(side_effect=Exception("unexpected error"))
            mock_cls.return_value = mock_client

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
        """Reconfigure: leeres read_parameters zeigt cannot_read_parameters."""
        with patch("custom_components.danfoss_tlx.config_flow.DanfossEtherLynx") as mock_cls:
            mock_client = _make_mock_client(discover_return="NEW_SER", read_return={})
            mock_cls.return_value = mock_client

            flow = DanfossConfigFlow()
            flow.hass = mock_hass
            flow._get_reconfigure_entry = MagicMock(return_value=mock_config_entry)

            result = await flow.async_step_reconfigure({
                CONF_INVERTER_IP: "192.168.1.200",
                CONF_INVERTER_SERIAL: "",
            })

            assert result["type"] == "form"
            assert result["errors"]["base"] == "cannot_read_parameters"


class _OptionsFlowForTest(DanfossOptionsFlow):
    """Test-Subklasse: stellt config_entry über das Konstruktor-Argument bereit.

    Vermeidet die Klassen-Mutation `type(flow).config_entry = property(...)`,
    die sonst in andere Tests überlaufen würde.
    """

    def __init__(self, entry):
        self._test_entry = entry

    @property
    def config_entry(self):
        return self._test_entry


class TestDanfossOptionsFlow:
    @pytest.mark.asyncio
    async def test_shows_form_with_defaults(self, mock_config_entry):
        flow = _OptionsFlowForTest(mock_config_entry)
        result = await flow.async_step_init(None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_saves_updates(self, mock_config_entry):
        flow = _OptionsFlowForTest(mock_config_entry)
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

        await flow.async_step_init({
            CONF_SCAN_INTERVAL: 30,
            CONF_PV_STRINGS: 3,
        })

        flow.async_create_entry.assert_called_once_with(
            title="",
            data={CONF_SCAN_INTERVAL: 30, CONF_PV_STRINGS: 3},
        )

    def test_base_class_property_not_mutated(self):
        """Sicherheitsnetz: DanfossOptionsFlow.config_entry darf keine eingepflanzte Property haben."""
        # config_entry kommt aus der HA-Basisklasse, nicht aus DanfossOptionsFlow oder Tests
        assert "config_entry" not in DanfossOptionsFlow.__dict__
