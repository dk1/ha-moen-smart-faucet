"""Data update coordinator for Moen Smart Faucet."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TEMPERATURE_HOTTEST, MoenAuthError, MoenClient, MoenError
from .const import (
    DOMAIN,
    LOGGER,
    MAX_RUN_TEMPERATURE,
    MIN_RUN_TEMPERATURE,
    PRESET_SCAN_INTERVAL,
    RUN_START_GRACE,
    RUNNING_SCAN_INTERVAL,
    SCAN_INTERVAL,
    SESSION_RETRIES,
    STATE_RUNNING,
)

type MoenConfigEntry = ConfigEntry[MoenRuntimeData]


@dataclass
class MoenRuntimeData:
    """Runtime data stored on the config entry."""

    client: MoenClient
    coordinator: MoenCoordinator
    presets: MoenPresetCoordinator


@dataclass
class ActiveRun:
    """A `run` command Home Assistant sent and that may still be going."""

    target: float | str
    flow: int
    sent: float
    seen_running: bool = False


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
        # Runs Home Assistant started, so the flow rate and run temperature can
        # adjust them live. Anything else (dispense, preset, stop) ends tracking.
        self.active_runs: dict[str, ActiveRun] = {}
        # Recent water-use sessions per faucet, newest first, and whether the
        # last fetch reached back as far as it was asked to (or to the start).
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.sessions_complete: dict[str, bool] = {}
        self._session_markers: dict[str, tuple[Any, ...]] = {}
        self._session_watermarks: dict[str, int] = {}
        self._session_retries: dict[str, int] = {}
        self._session_backfill: dict[str, int] = {}

    def temperature_limit(self, client_id: str) -> float | None:
        """Return the lowest active temperature limit (safety or child), if any."""
        device = self.data.get(client_id, {}) if self.data else {}
        limits = [
            float(math.floor(device[limit]))
            for mode, limit in (
                ("safetyModeEnabled", "safetyLimitTemp"),
                ("childModeEnabled", "childLimitTemp"),
            )
            if device.get(mode) and isinstance(device.get(limit), (int, float))
        ]
        return min(limits) if limits else None

    def run_temperature_range(self, client_id: str) -> tuple[float, float]:
        """Return the allowed run temperatures (°C) for a faucet.

        The top is the lowest active safety or child limit, in whole degrees.
        The faucet's learnedMinTemp/learnedMaxTemp are not used: learnedMinTemp
        rises after short runs of room-temperature pipe water, so it isn't a
        reliable floor.
        """
        limit = self.temperature_limit(client_id)
        high = MAX_RUN_TEMPERATURE if limit is None else min(limit, MAX_RUN_TEMPERATURE)
        return MIN_RUN_TEMPERATURE, high

    def clamp_run_temperature(self, client_id: str, value: float) -> float:
        """Limit a run temperature to the allowed range."""
        low, high = self.run_temperature_range(client_id)
        return min(max(value, low), high)

    def resolve_target(
        self, client_id: str, temperature: float | str | None
    ) -> float | str:
        """Turn a temperature, preset or nothing into a command target.

        "hottest" becomes the active temperature limit, if there is one, rather
        than relying on the faucet to enforce it.
        """
        if isinstance(temperature, str):
            limit = self.temperature_limit(client_id)
            if temperature == TEMPERATURE_HOTTEST and limit is not None:
                return limit
            return temperature
        return self.clamp_run_temperature(
            client_id,
            temperature
            if temperature is not None
            else self.run_temperatures[client_id],
        )

    async def async_run(
        self,
        client_id: str,
        temperature: float | str | None = None,
        flow_rate: int | None = None,
    ) -> None:
        """Start a run, filling in anything not given from the settings."""
        target = self.resolve_target(client_id, temperature)
        flow = int(flow_rate or self.flow_rates[client_id])
        await self.client.async_run(client_id, target, flow)
        self.active_runs[client_id] = ActiveRun(target, flow, time.monotonic())

    def can_adjust_run(self, client_id: str) -> bool:
        """Return whether a run HA started is confirmed to be going right now."""
        run = self.active_runs.get(client_id)
        state = (self.data or {}).get(client_id, {}).get("state")
        return run is not None and run.seen_running and state == STATE_RUNNING

    async def async_adjust_run(
        self,
        client_id: str,
        *,
        temperature: float | None = None,
        flow_rate: float | None = None,
    ) -> None:
        """Change one setting of a run HA started, keeping the others.

        Sends nothing unless that run is confirmed running right now.
        """
        if not self.can_adjust_run(client_id):
            return
        run = self.active_runs[client_id]
        target = (
            run.target
            if temperature is None
            else self.resolve_target(client_id, temperature)
        )
        flow = run.flow if flow_rate is None else int(flow_rate)
        await self.client.async_run(client_id, target, flow)
        run.target, run.flow = target, flow

    def end_run(self, client_id: str) -> None:
        """Stop treating the current run as adjustable (another command took over)."""
        self.active_runs.pop(client_id, None)

    def request_sessions_since(self, client_id: str, timestamp: int) -> None:
        """Ask the next refresh to page session history back to a timestamp."""
        self._session_backfill[client_id] = timestamp

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
        self._track_runs(faucets)
        # The faucet reports its temperature only when a run ends, so poll
        # quickly while any faucet is running (or about to) to catch that.
        running = self.active_runs or any(
            f.get("state") == STATE_RUNNING for f in faucets.values()
        )
        self.update_interval = RUNNING_SCAN_INTERVAL if running else SCAN_INTERVAL
        await self._async_update_sessions(faucets)
        self._update_devices(faucets)
        return faucets

    def _track_runs(self, faucets: dict[str, dict[str, Any]]) -> None:
        """Forget HA runs that have ended.

        A run counts as ended at the first idle report after it was seen
        running. Before that, it gets a short grace period to start.
        """
        now = time.monotonic()
        for client_id, run in list(self.active_runs.items()):
            if faucets.get(client_id, {}).get("state") == STATE_RUNNING:
                run.seen_running = True
            elif run.seen_running or now - run.sent >= RUN_START_GRACE:
                del self.active_runs[client_id]

    async def _async_update_sessions(self, faucets: dict[str, dict[str, Any]]) -> None:
        """Fetch session history for faucets that finished a session.

        The faucet's reported volume and temperatureLast describe its last
        session, so a change in either means there is a new session to fetch.
        Moen can record the session a little after the shadow changes, so a
        fetch that brings nothing new is retried on the next few polls. Fetches
        page back to the newest session already seen, so none are skipped.
        Session history is a nice-to-have: a failure here doesn't fail the update.
        """
        for client_id, faucet in faucets.items():
            marker = (faucet.get("volume"), faucet.get("temperatureLast"))
            backfill = self._session_backfill.get(client_id)
            changed = self._session_markers.get(client_id) != marker
            if not (changed or backfill or self._session_retries.get(client_id)):
                continue
            watermark = self._session_watermarks.get(client_id)
            since = (
                min(x for x in (backfill, watermark) if x is not None)
                if (backfill is not None or watermark is not None)
                else None
            )
            try:
                sessions, complete = await self.client.async_get_sessions(
                    client_id, since=since
                )
            except MoenError as err:
                LOGGER.debug("Could not fetch sessions for %s: %s", client_id, err)
                continue
            self._session_backfill.pop(client_id, None)
            newest = max((s.get("timestamp", 0) for s in sessions), default=0)
            if changed and watermark is not None and newest <= watermark:
                # The shadow moved but the session isn't recorded yet.
                retries = self._session_retries.get(client_id, SESSION_RETRIES + 1) - 1
                if retries > 0:
                    self._session_retries[client_id] = retries
                    continue
            self._session_retries.pop(client_id, None)
            self._session_markers[client_id] = marker
            if newest:
                self._session_watermarks[client_id] = max(newest, watermark or 0)
            if sessions or client_id not in self.sessions:
                self.sessions[client_id] = sessions
                self.sessions_complete[client_id] = complete

    def _update_devices(self, faucets: dict[str, dict[str, Any]]) -> None:
        """Keep device firmware versions current in the device registry."""
        registry = dr.async_get(self.hass)
        for client_id, faucet in faucets.items():
            device = registry.async_get_device_by_identifier(
                (DOMAIN, client_id), self.config_entry.entry_id
            )
            firmware = faucet.get("firmwareVersion")
            if device and firmware and device.sw_version != firmware:
                registry.async_update_device(device.id, sw_version=firmware)


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
        except MoenError as err:
            # Optional: even an auth error here only disables the buttons; the
            # main coordinator handles reauthentication.
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return {p["presetId"]: p for p in presets}
