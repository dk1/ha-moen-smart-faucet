"""Sensor platform for Moen Smart Faucet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoenConfigEntry
from .entity import MoenEntity

PARALLEL_UPDATES = 0


def _number(key: str) -> Callable[[dict[str, Any]], float | None]:
    def get(device: dict[str, Any]) -> float | None:
        value = device.get(key)
        return value if isinstance(value, (int, float)) and value >= 0 else None

    return get


@dataclass(frozen=True, kw_only=True)
class MoenSensorDescription(SensorEntityDescription):
    """Describes a Moen faucet sensor."""

    value_fn: Callable[[dict[str, Any]], float | None]


SENSORS: tuple[MoenSensorDescription, ...] = (
    MoenSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda d: d.get("temperature"),
    ),
    MoenSensorDescription(
        key="cabinet_temperature",
        translation_key="cabinet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value_fn=lambda d: d.get("assemblyAirTemp"),
    ),
    MoenSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_number("batteryPercentage"),
    ),
    MoenSensorDescription(
        key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("wifiRssi"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up faucet sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenSensor(coordinator, client_id, description)
        for client_id in coordinator.data
        for description in SENSORS
    )


class MoenSensor(MoenEntity, SensorEntity):
    """A faucet sensor."""

    entity_description: MoenSensorDescription

    def __init__(
        self, coordinator, client_id: str, description: MoenSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, client_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.device)
