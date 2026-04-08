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
        """Holt Daten vom Inverter."""
        try:
            data = await self._fetch_data()
        except HomeAssistantError:
            raise
        except Exception as err:
            if self.last_update_success:
                _LOGGER.warning(
                    "Inverter %s nicht mehr erreichbar: %s", self._ip, err
                )
            raise UpdateFailed(f"Fehler beim Lesen der Inverterdaten: {err}") from err

        if not self.last_update_success:
            _LOGGER.info("Inverter %s wieder erreichbar", self._ip)
        return data

    async def _fetch_data(self) -> dict[str, Any]:
        """Asynchrone Datenabfrage direkt im Event-Loop."""
        if self._client is None:
            self._client = DanfossEtherLynx(self._ip)
            if self._inverter_serial:
                self._client.inverter_serial = self._inverter_serial
            else:
                serial = await self._client.discover()
                if not serial:
                    await self._client.close()
                    self._client = None
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="inverter_unreachable",
                        translation_placeholders={"ip": self._ip},
                    )

        try:
            self._inverter_serial = self._client.inverter_serial
            data = await self._client.read_all()
        except Exception:
            await self._client.close()
            self._client = None
            raise
        if not data:
            await self._client.close()
            self._client = None
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_data_received",
            )
        return data
