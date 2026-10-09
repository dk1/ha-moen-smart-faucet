"""Button platform for Moen Smart Faucet: dispense the configured amount."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_DISPENSE_ML, MIN_DISPENSE_ML
from .coordinator import MoenConfigEntry, MoenCoordinator
from .entity import MoenEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the dispense buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenDispenseButton(coordinator, client_id) for client_id in coordinator.data
    )


class MoenDispenseButton(MoenEntity, ButtonEntity):
    """Pour the dispense amount at the run temperature, straight away."""

    _attr_translation_key = "dispense"

    def __init__(self, coordinator: MoenCoordinator, client_id: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator, client_id, "dispense")

    async def async_press(self) -> None:
        """Dispense."""
        coordinator = self.coordinator
        amount_ml = min(
            max(coordinator.dispense_amounts_ml[self.client_id], MIN_DISPENSE_ML),
            MAX_DISPENSE_ML,
        )
        volume_ul = round(amount_ml * 1000)
        temperature = coordinator.clamp_run_temperature(
            self.client_id, coordinator.run_temperatures[self.client_id]
        )
        await self.async_send_command(
            coordinator.client.async_dispense(self.client_id, volume_ul, temperature)
        )
