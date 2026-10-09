"""Data update coordinator for Moen Smart Faucet."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
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
    PRESET_SCAN_INTERVAL,
    RUN_START_GRACE,
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
    presets: MoenPresetCoordinator


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
        # Per-faucet settings kept in Home Assistant, owned by the number platform.
        self.run_temperatures: dict[str, float] = {}
        self.flow_rates: dict[str, float] = {}
        self.dispense_amounts_ml: dict[str, float] = {}
        # Faucets currently running a `run` that Home Assistant started, so that
        # changing the flow rate or run temperature can adjust it live.
        # Maps client ID to when the run was sent (monotonic seconds).
        self.ha_runs: dict[str, float] = {}
        # Recent water-use sessions per faucet, newest first.
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self._session_markers: dict[str, tuple[Any, ...]] = {}

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

    async def async_run(
        self,
        client_id: str,
        temperature: float | str | None = None,
        flow_rate: int | None = None,
    ) -> None:
        """Run the water, filling in anything not given from the settings."""
        target: float | str = (
            temperature
            if isinstance(temperature, str)
            else self.clamp_run_temperature(
                client_id, temperature or self.run_temperatures[client_id]
            )
        )
        flow = int(flow_rate or self.flow_rates[client_id])
        await self.client.async_run(client_id, target, flow)
        # Keep the original start time when adjusting a run already going.
        self.ha_runs.setdefault(client_id, time.monotonic())

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
        # Forget runs that have ended, allowing the faucet a few seconds to
        # report that a just-sent run has started.
        now = time.monotonic()
        self.ha_runs = {
            cid: sent
            for cid, sent in self.ha_runs.items()
            if faucets.get(cid, {}).get("state") == STATE_RUNNING
            or now - sent < RUN_START_GRACE
        }
        self.update_interval = RUNNING_SCAN_INTERVAL if running else SCAN_INTERVAL
        await self._async_update_sessions(faucets)
        return faucets

    async def _async_update_sessions(self, faucets: dict[str, dict[str, Any]]) -> None:
        """Fetch session history for faucets that finished a session.

        The faucet's reported volume and temperatureLast describe its last
        session, so a change in either means there is a new session to fetch.
        Session history is a nice-to-have: a failure here doesn't fail the update.
        """
        for client_id, faucet in faucets.items():
            marker = (faucet.get("volume"), faucet.get("temperatureLast"))
            if self._session_markers.get(client_id) == marker:
                continue
            try:
                self.sessions[client_id] = await self.client.async_get_sessions(
                    client_id
                )
            except MoenError as err:
                LOGGER.debug("Could not fetch sessions for %s: %s", client_id, err)
                continue
            self._session_markers[client_id] = marker


class MoenPresetCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """The account's saved presets, keyed by preset ID.

    Presets change rarely and are optional, so they're polled slowly and a
    failure only makes the preset buttons unavailable.
    """

    config_entry: MoenConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: MoenConfigEntry, client: MoenClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_presets",
            update_interval=PRESET_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            presets = await self.client.async_get_presets()
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
        return {p["presetId"]: p for p in presets}
