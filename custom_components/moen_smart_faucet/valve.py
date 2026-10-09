"""Valve platform for Moen Smart Faucet: start and stop the water."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import MoenError
from .const import COMMAND_REFRESH_DELAY, DOMAIN, STATE_RUNNING
from .coordinator import MoenConfigEntry
from .entity import MoenEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the faucet valves."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenFaucetValve(coordinator, client_id) for client_id in coordinator.data
    )


class MoenFaucetValve(MoenEntity, ValveEntity):
    """The faucet's water flow.

    Opening runs the water at the faucet's run temperature. The faucet decides
    when to stop on its own (the Moen app describes it running until the water
    reaches temperature); closing stops it immediately.
    """

    _attr_device_class = ValveDeviceClass.WATER
    _attr_name = None
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_translation_key = "water"

    def __init__(self, coordinator, client_id: str) -> None:
        """Initialize the valve."""
        super().__init__(coordinator, client_id, "water")
        self._optimistic_closed: bool | None = None

    @property
    def is_closed(self) -> bool:
        """Return whether the water is off."""
        if self._optimistic_closed is not None:
            return self._optimistic_closed
        return self.device.get("state") != STATE_RUNNING

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_closed = None
        super()._handle_coordinator_update()

    async def async_open_valve(self) -> None:
        """Run the water at the configured run temperature."""
        await self.async_run()

    async def async_close_valve(self) -> None:
        """Stop the water."""
        await self._async_send(self.coordinator.client.async_stop(self.client_id), True)

    async def async_run(
        self, temperature: float | None = None, preset: str | None = None
    ) -> None:
        """Run the water at a temperature (°C) or a preset (hottest/coldest)."""
        target: float | str
        if preset:
            target = preset
        else:
            target = self.coordinator.clamp_run_temperature(
                self.client_id,
                temperature or self.coordinator.run_temperatures[self.client_id],
            )
        await self._async_send(
            self.coordinator.client.async_run(self.client_id, target), False
        )

    async def _async_send(self, command: Awaitable[None], closed: bool) -> None:
        try:
            await command
        except MoenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self._optimistic_closed = closed
        self.async_write_ha_state()

        async def _refresh(_: Any) -> None:
            await self.coordinator.async_request_refresh()

        self.async_on_remove(
            async_call_later(self.hass, COMMAND_REFRESH_DELAY, _refresh)
        )
