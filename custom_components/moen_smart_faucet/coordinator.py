"""Data update coordinator for Moen Smart Faucet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoenAuthError, MoenClient, MoenError
from .const import (
    DOMAIN,
    LOGGER,
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
