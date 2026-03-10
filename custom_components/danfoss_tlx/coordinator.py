"""DataUpdateCoordinator für Danfoss TLX Pro."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)
from .etherlynx import DanfossEtherLynx

_LOGGER = logging.getLogger(__name__)


class DanfossCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordiniert Datenabfragen vom Danfoss TLX Pro Inverter."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._ip: str = entry.data[CONF_INVERTER_IP]
        self._inverter_serial: str | None = entry.data.get(CONF_INVERTER_SERIAL)
        self._client: DanfossEtherLynx | None = None

        interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )

    @property
    def inverter_serial(self) -> str | None:
        """Seriennummer des Inverters."""
        return self._inverter_serial

    async def _async_update_data(self) -> dict[str, Any]:
        """Holt Daten vom Inverter (wird im Executor-Thread ausgeführt)."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except Exception as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    def _fetch_data(self) -> dict[str, Any]:
        """Synchrone Datenabfrage (läuft im Thread-Pool)."""
        # Client initialisieren falls nötig
        if self._client is None:
            self._client = DanfossEtherLynx(self._ip)
            if self._inverter_serial:
                self._client.inverter_serial = self._inverter_serial
            else:
                serial = self._client.discover()
                if not serial:
                    self._client = None
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="inverter_unreachable",
                        translation_placeholders={"ip": self._ip},
                    )

        self._inverter_serial = self._client.inverter_serial

        data = self._client.read_all()
        if not data:
            # Verbindung zurücksetzen, nächster Versuch mit Discovery
            self._client.close()
            self._client = None
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_data_received",
            )

        return data
