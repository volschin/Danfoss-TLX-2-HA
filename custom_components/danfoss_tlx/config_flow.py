"""Config Flow für Danfoss TLX Pro Integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)

try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_PV_STRINGS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PV_STRINGS,
)
from .etherlynx import DanfossEtherLynx

_LOGGER = logging.getLogger(__name__)


class ParameterReadError(RuntimeError):
    """Inverter erreichbar, aber Parameter-Lesen fehlgeschlagen."""


class DanfossConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config Flow für Danfoss TLX Pro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: IP-Adresse und Grundkonfiguration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_INVERTER_IP].strip()
            serial = user_input.get(CONF_INVERTER_SERIAL, "").strip()

            serial, errors = await self._async_try_connect(ip, serial)

            if not errors:
                await self.async_set_unique_id(f"danfoss_tlx_{serial or ip}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Danfoss TLX Pro ({serial or ip})",
                    data={
                        CONF_INVERTER_IP: ip,
                        CONF_INVERTER_SERIAL: serial,
                        CONF_PV_STRINGS: user_input.get(CONF_PV_STRINGS, DEFAULT_PV_STRINGS),
                        CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_INVERTER_IP): str,
                vol.Optional(CONF_INVERTER_SERIAL, default=""): str,
                vol.Optional(CONF_PV_STRINGS, default=DEFAULT_PV_STRINGS): vol.In([2, 3]),
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): vol.All(int, vol.Range(min=5, max=3600)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rekonfiguration: IP-Adresse und Seriennummer ändern."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is not None:
            ip = user_input[CONF_INVERTER_IP].strip()
            serial = user_input.get(CONF_INVERTER_SERIAL, "").strip()

            serial, errors = await self._async_try_connect(ip, serial)

            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data={
                        **reconfigure_entry.data,
                        CONF_INVERTER_IP: ip,
                        CONF_INVERTER_SERIAL: serial,
                    },
                )

        current = reconfigure_entry.data
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INVERTER_IP, default=current.get(CONF_INVERTER_IP, "")
                ): str,
                vol.Optional(
                    CONF_INVERTER_SERIAL, default=current.get(CONF_INVERTER_SERIAL, "")
                ): str,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    async def _async_try_connect(
        self, ip: str, serial: str
    ) -> tuple[str, dict[str, str]]:
        """Führt Verbindungsversuch durch und gibt (serial, errors) zurück."""
        errors: dict[str, str] = {}
        try:
            discovered = await self.hass.async_add_executor_job(
                self._try_connect, ip, serial
            )
            if discovered:
                serial = discovered
            elif not serial:
                errors["base"] = "cannot_connect"
        except ParameterReadError:
            _LOGGER.warning(
                "Inverter %s erreichbar, aber Parameter-Lesen fehlgeschlagen", ip
            )
            errors["base"] = "cannot_read_parameters"
        except Exception:
            _LOGGER.exception("Verbindungsfehler zu %s", ip)
            errors["base"] = "cannot_connect"
        return serial, errors

    @staticmethod
    def _try_connect(ip: str, serial: str) -> str | None:
        """Versucht den Inverter zu erreichen und gibt die Seriennummer zurück.

        Wirft ParameterReadError wenn Discovery klappt aber Parameter-Lesen
        fehlschlägt.
        """
        with DanfossEtherLynx(ip) as client:
            if serial:
                client.inverter_serial = serial
            else:
                serial = client.discover()
                if not serial:
                    return None

            test_data = client.read_parameters(
                ["grid_power_total", "operation_mode", "nominal_power"]
            )
            if not test_data:
                raise ParameterReadError

            return serial

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DanfossOptionsFlow:
        """Gibt den Options Flow zurück."""
        return DanfossOptionsFlow()


class DanfossOptionsFlow(OptionsFlow):
    """Options Flow für Danfoss TLX Pro."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionen bearbeiten."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(
                        CONF_SCAN_INTERVAL,
                        self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(int, vol.Range(min=5, max=3600)),
                vol.Optional(
                    CONF_PV_STRINGS,
                    default=current.get(
                        CONF_PV_STRINGS,
                        self.config_entry.data.get(CONF_PV_STRINGS, DEFAULT_PV_STRINGS),
                    ),
                ): vol.In([2, 3]),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
