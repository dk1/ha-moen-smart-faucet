"""Number platform for Moen Smart Faucet: the temperature used when opening."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DEFAULT_RUN_TEMPERATURE, MAX_RUN_TEMPERATURE, MIN_RUN_TEMPERATURE
from .coordinator import MoenConfigEntry
from .entity import MoenEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the run temperature numbers."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenRunTemperature(coordinator, client_id) for client_id in coordinator.data
    )


class MoenRunTemperature(MoenEntity, RestoreNumber):
    """Temperature the faucet runs to when its valve is opened.

    Stored in Home Assistant, not on the faucet. It is capped at the faucet's
    safety limit while safety mode is on.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "run_temperature"
    _requires_connection = False

    def __init__(self, coordinator, client_id: str) -> None:
        """Initialize the number."""
        super().__init__(coordinator, client_id, "run_temperature")
        coordinator.run_temperatures.setdefault(client_id, DEFAULT_RUN_TEMPERATURE)

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            self.coordinator.run_temperatures[self.client_id] = last.native_value

    @property
    def native_min_value(self) -> float:
        """Return the minimum run temperature."""
        return MIN_RUN_TEMPERATURE

    @property
    def native_max_value(self) -> float:
        """Return the maximum run temperature, honouring the safety limit."""
        limit = self.device.get("safetyLimitTemp")
        if self.device.get("safetyModeEnabled") and isinstance(limit, (int, float)):
            return min(float(limit), MAX_RUN_TEMPERATURE)
        return MAX_RUN_TEMPERATURE

    @property
    def native_value(self) -> float:
        """Return the run temperature."""
        return self.coordinator.run_temperatures[self.client_id]

    async def async_set_native_value(self, value: float) -> None:
        """Set the run temperature."""
        self.coordinator.run_temperatures[self.client_id] = value
        self.async_write_ha_state()
