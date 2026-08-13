"""Vertrag für die unterstützte Home-Assistant-Mindestversion."""

import inspect

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


def test_config_entry_supports_runtime_data() -> None:
    """Der Coordinator kann typisiert am Config Entry gespeichert werden."""
    assert "runtime_data" in ConfigEntry.__annotations__


def test_coordinator_accepts_config_entry() -> None:
    """Der Coordinator kann den Config Entry explizit übernehmen."""
    assert (
        "config_entry" in inspect.signature(DataUpdateCoordinator.__init__).parameters
    )


def test_config_flow_supports_reconfigure_helpers() -> None:
    """Der Rekonfigurationspfad verwendet beide HA-Hilfsmethoden."""
    assert hasattr(ConfigFlow, "_get_reconfigure_entry")
    assert hasattr(ConfigFlow, "async_update_reload_and_abort")


def test_options_flow_exposes_config_entry() -> None:
    """Der Optionsdialog liest Daten und Optionen über config_entry."""
    assert hasattr(OptionsFlow, "config_entry")
