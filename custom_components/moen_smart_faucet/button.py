"""Button platform for Moen Smart Faucet: dispense the configured amount."""

from __future__ import annotations

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, MAX_DISPENSE_ML, MIN_DISPENSE_ML
from .coordinator import MoenConfigEntry, MoenCoordinator, MoenPresetCoordinator
from .entity import MoenEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the dispense button and a button per saved preset."""
    coordinator = entry.runtime_data.coordinator
    presets = entry.runtime_data.presets
    async_add_entities(
        MoenDispenseButton(coordinator, client_id) for client_id in coordinator.data
    )

    known: dict[str, str | None] = {}  # preset ID -> nickname
    registry = er.async_get(hass)

    @callback
    def _sync_presets() -> None:
        if not presets.last_update_success:
            return
        data = presets.data or {}
        current = set(data)
        # Presets renamed in the Moen app: entity names are fixed when entities
        # are created, so reload to pick up the new name.
        if any(
            data[preset_id].get("nickname") != name
            for preset_id, name in known.items()
            if preset_id in data
        ):
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        # Presets deleted in the Moen app: remove their buttons.
        for preset_id in set(known) - current:
            for client_id in coordinator.data:
                if entity_id := registry.async_get_entity_id(
                    BUTTON_DOMAIN, DOMAIN, f"{client_id}_preset_{preset_id}"
                ):
                    registry.async_remove(entity_id)
        for preset_id in set(known) - current:
            del known[preset_id]
        new = current - set(known)
        if new:
            known.update({p: data[p].get("nickname") for p in new})
            async_add_entities(
                MoenPresetButton(coordinator, presets, client_id, preset_id)
                for client_id in coordinator.data
                for preset_id in sorted(new)
            )

    _sync_presets()
    entry.async_on_unload(presets.async_add_listener(_sync_presets))


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
        temperature = coordinator.resolve_target(self.client_id, None)
        await self.async_send_command(
            coordinator.async_dispense(self.client_id, volume_ul, temperature)
        )


class MoenPresetButton(MoenEntity, ButtonEntity):
    """Run one of the account's saved Moen presets on this faucet.

    Presets added, renamed or deleted in the Moen app are picked up within
    30 minutes; deleted presets' buttons are removed.
    """

    _attr_translation_key = "preset"

    def __init__(
        self,
        coordinator: MoenCoordinator,
        presets: MoenPresetCoordinator,
        client_id: str,
        preset_id: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, client_id, f"preset_{preset_id}")
        self._presets = presets
        self._preset_id = preset_id
        self._attr_translation_placeholders = {
            "name": presets.data[preset_id].get("nickname") or preset_id
        }

    async def async_added_to_hass(self) -> None:
        """Follow preset list updates too."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._presets.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Return whether the faucet is online and the preset still exists."""
        return (
            super().available
            and self._presets.last_update_success
            and self._preset_id in (self._presets.data or {})
        )

    async def async_press(self) -> None:
        """Run the preset."""
        await self.async_send_command(
            self.coordinator.async_run_preset(self.client_id, self._preset_id)
        )
