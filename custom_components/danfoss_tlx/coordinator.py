"""DataUpdateCoordinator für Danfoss TLX Pro."""
import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_INVERTER_IP,
    CONF_INVERTER_SERIAL,
    CONF_PV_STRINGS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)
from .etherlynx import DanfossEtherLynx

_LOGGER = logging.getLogger(__name__)


class DanfossCoordinator(DataUpdateCoordinator):
    """Koordiniert Datenabfragen vom Danfoss TLX Pro Inverter."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._ip: str = entry.data[CONF_INVERTER_IP]
        self._preset_serial: str = entry.data.get(CONF_INVERTER_SERIAL, "")
        self.inverter_serial: Optional[str] = self._preset_serial or None
        self._client: Optional[DanfossEtherLynx] = None

        interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Holt Daten vom Inverter (wird im Executor-Thread ausgeführt)."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except Exception as err:
            raise UpdateFailed(f"Fehler beim Abrufen der Inverterdaten: {err}") from err

    def _fetch_data(self) -> Dict[str, Any]:
        """Synchrone Datenabfrage (läuft im Thread-Pool)."""
        # Client initialisieren falls nötig
        if self._client is None:
            self._client = DanfossEtherLynx(self._ip)
            if self._preset_serial:
                self._client.inverter_serial = self._preset_serial
            else:
                serial = self._client.discover()
                if not serial:
                    self._client = None
                    raise RuntimeError(
                        f"Inverter unter {self._ip} nicht erreichbar"
                    )

        self.inverter_serial = self._client.inverter_serial

        data = self._client.read_all()
        if not data:
            # Verbindung zurücksetzen, nächster Versuch mit Discovery
            self._client.close()
            self._client = None
            raise RuntimeError("Keine Daten vom Inverter empfangen")

        # Betriebsmodus-Text hinzufügen
        if "operation_mode" in data:
            data["operation_mode_text"] = self._client.get_status_text(
                data["operation_mode"]
            )

        return data
