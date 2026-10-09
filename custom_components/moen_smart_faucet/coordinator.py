"""Data update coordinator for Moen Smart Faucet."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoenAuthError, MoenClient, MoenError
from .const import (
    DOMAIN,
    LOGGER,
    MAX_RUN_TEMPERATURE,
    MIN_RUN_TEMPERATURE,
    RUNNING_SCAN_INTERVAL,
    SCAN_INTERVAL,
    STATE_RUNNING,
)

type MoenConfigEntry = ConfigEntry[MoenRuntimeData]


@dataclass
class MoenRuntimeData:
    """Runtime data stored on the config entry."""

    client: MoenClient
    coordinator: MoenCoordinator


class MoenCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll every faucet on the account with a single API call."""

    config_entry: MoenConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: MoenConfigEntry, client: MoenClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        # Per-faucet run temperature (°C), owned by the number platform.
        self.run_temperatures: dict[str, float] = {}

    def run_temperature_range(self, client_id: str) -> tuple[float, float]:
        """Return the allowed run temperatures (°C) for a faucet.

        The top is the faucet's safety limit (whole degrees, rounded down) while
        safety mode is on. The faucet's learnedMinTemp/learnedMaxTemp are not
        used: learnedMinTemp rises after short runs of room-temperature pipe
        water, so it isn't a reliable floor.
        """
        device = self.data.get(client_id, {}) if self.data else {}
        high = MAX_RUN_TEMPERATURE
        limit = device.get("safetyLimitTemp")
        if device.get("safetyModeEnabled") and isinstance(limit, (int, float)):
            high = min(high, float(math.floor(limit)))
        return MIN_RUN_TEMPERATURE, high

    def clamp_run_temperature(self, client_id: str, value: float) -> float:
        """Limit a run temperature to what the faucet can deliver."""
        low, high = self.run_temperature_range(client_id)
        return min(max(value, low), high)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            faucets = await self.client.async_get_faucets()
        except MoenAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except MoenError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The faucet reports its temperature only when a run ends, so poll
        # quickly while any faucet is running to catch that moment.
        running = any(f.get("state") == STATE_RUNNING for f in faucets.values())
        self.update_interval = RUNNING_SCAN_INTERVAL if running else SCAN_INTERVAL
        return faucets
