"""Switch platform for Moen Smart Faucet: freeze protection."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoenConfigEntry, MoenCoordinator
from .entity import MoenEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the freeze protection switches."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenFreezeProtectionSwitch(coordinator, client_id)
        for client_id in coordinator.data
    )


class MoenFreezeProtectionSwitch(MoenEntity, SwitchEntity):
    """Freeze protection: the faucet trickles water when its cabinet gets cold."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "freeze_protection"

    def __init__(self, coordinator: MoenCoordinator, client_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, client_id, "freeze_protection")
        self._optimistic: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return whether freeze protection is on."""
        if self._optimistic is not None:
            return self._optimistic
        value = self.device.get("freezeEnable")
        return value if isinstance(value, bool) else None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn freeze protection on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn freeze protection off."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        await self.async_send_command(
            self.coordinator.client.async_set_freeze_protection(self.client_id, enabled)
        )
        self._optimistic = enabled
        self.async_write_ha_state()
