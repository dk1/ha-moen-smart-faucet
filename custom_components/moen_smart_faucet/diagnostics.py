"""Diagnostics for Moen Smart Faucet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import MoenConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "clientId",
    "duid",
    "federatedIdentity",
    "lastConnect",
    "locationId",
    "nickname",
    "roomId",
    "wifiNetwork",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MoenConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        # Faucets are keyed by client ID, so re-key them by position.
        "faucets": [
            async_redact_data(device, TO_REDACT) for device in coordinator.data.values()
        ],
        "run_temperatures": list(coordinator.run_temperatures.values()),
    }
