"""Binary sensor platform for Moen Smart Faucet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoenConfigEntry
from .entity import MoenEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MoenBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Moen faucet binary sensor."""

    value_fn: Callable[[dict[str, Any]], bool | None]
    requires_connection: bool = True


BINARY_SENSORS: tuple[MoenBinarySensorDescription, ...] = (
    MoenBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get("connected"),
        requires_connection=False,
    ),
    MoenBinarySensorDescription(
        key="freeze_risk",
        translation_key="freeze_risk",
        device_class=BinarySensorDeviceClass.COLD,
        value_fn=lambda d: d.get("isFreezing"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up faucet binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenBinarySensor(coordinator, client_id, description)
        for client_id in coordinator.data
        for description in BINARY_SENSORS
    )


class MoenBinarySensor(MoenEntity, BinarySensorEntity):
    """A faucet binary sensor."""

    entity_description: MoenBinarySensorDescription

    def __init__(
        self, coordinator, client_id: str, description: MoenBinarySensorDescription
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, client_id, description.key)
        self.entity_description = description
        self._requires_connection = description.requires_connection

    @property
    def is_on(self) -> bool | None:
        """Return the sensor state."""
        return self.entity_description.value_fn(self.device)
