"""Config Flow für Danfoss TLX Pro Integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
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


class DanfossConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config Flow für Danfoss TLX Pro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.FlowResult:
        """Schritt 1: IP-Adresse und Grundkonfiguration."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_INVERTER_IP].strip()
            serial = user_input.get(CONF_INVERTER_SERIAL, "").strip()

            # Inverter erreichbar prüfen und Seriennummer ermitteln
            try:
                discovered = await self.hass.async_add_executor_job(
                    self._try_connect, ip, serial
                )
                if discovered:
                    serial = discovered
                elif not serial:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Verbindungsfehler zu %s", ip)
                errors["base"] = "cannot_connect"

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

    @staticmethod
    def _try_connect(ip: str, serial: str) -> Optional[str]:
        """Versucht den Inverter zu erreichen und gibt die Seriennummer zurück."""
        with DanfossEtherLynx(ip) as client:
            if serial:
                client.inverter_serial = serial
                return serial
            return client.discover()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DanfossOptionsFlow:
        """Gibt den Options Flow zurück."""
        return DanfossOptionsFlow(config_entry)


class DanfossOptionsFlow(config_entries.OptionsFlow):
    """Options Flow für Danfoss TLX Pro."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.FlowResult:
        """Optionen bearbeiten."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(
                        CONF_SCAN_INTERVAL,
                        self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(int, vol.Range(min=5, max=3600)),
                vol.Optional(
                    CONF_PV_STRINGS,
                    default=current.get(
                        CONF_PV_STRINGS,
                        self._config_entry.data.get(CONF_PV_STRINGS, DEFAULT_PV_STRINGS),
                    ),
                ): vol.In([2, 3]),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
