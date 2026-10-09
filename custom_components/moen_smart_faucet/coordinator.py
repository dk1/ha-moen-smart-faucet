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
        """Return the run temperatures (°C) this faucet can actually deliver.

        Bounded by the coldest and hottest water the faucet has learned, and by
        its safety limit while safety mode is on, in whole degrees inside those
        bounds. A target outside this range is never reached, so the faucet
        runs until it times out.
        """
        device = self.data.get(client_id, {}) if self.data else {}
        low, high = MIN_RUN_TEMPERATURE, MAX_RUN_TEMPERATURE
        if isinstance(learned := device.get("learnedMinTemp"), (int, float)):
            low = max(low, float(math.ceil(learned)))
        if isinstance(learned := device.get("learnedMaxTemp"), (int, float)):
            high = min(high, float(math.floor(learned)))
        limit = device.get("safetyLimitTemp")
        if device.get("safetyModeEnabled") and isinstance(limit, (int, float)):
            high = min(high, float(math.floor(limit)))
        return (
            (low, high) if low <= high else (MIN_RUN_TEMPERATURE, MAX_RUN_TEMPERATURE)
        )

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
