"""Sensor platform for Moen Smart Faucet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorExtraStoredData,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MoenConfigEntry, MoenCoordinator
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


@dataclass(frozen=True, kw_only=True)
class MoenSessionSensorDescription(SensorEntityDescription):
    """Describes a sensor about the faucet's most recent water use."""

    value_fn: Callable[[dict[str, Any]], float | None]


SESSION_SENSORS: tuple[MoenSessionSensorDescription, ...] = (
    MoenSessionSensorDescription(
        key="last_use_volume",
        translation_key="last_use_volume",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=2,
        value_fn=lambda s: s["totalVolUl"] / 1_000_000,
    ),
    MoenSessionSensorDescription(
        key="last_use_duration",
        translation_key="last_use_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        value_fn=lambda s: s["durationMs"] / 1000,
    ),
    MoenSessionSensorDescription(
        key="last_use_temperature",
        translation_key="last_use_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s["avgTempC"],
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
    async_add_entities(
        MoenSessionSensor(coordinator, client_id, description)
        for client_id in coordinator.data
        for description in SESSION_SENSORS
    )
    async_add_entities(
        MoenWaterUsageSensor(coordinator, client_id) for client_id in coordinator.data
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


class MoenSessionSensor(MoenEntity, SensorEntity):
    """A fact about the faucet's most recent water use."""

    entity_description: MoenSessionSensorDescription
    _requires_connection = False

    def __init__(
        self,
        coordinator: MoenCoordinator,
        client_id: str,
        description: MoenSessionSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, client_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the value for the latest session."""
        sessions = self.coordinator.sessions.get(self.client_id)
        if not sessions:
            return None
        try:
            return self.entity_description.value_fn(sessions[0])
        except KeyError, TypeError:
            return None


@dataclass
class _UsageData(SensorExtraStoredData):
    """Restored state for the water usage total."""

    last_session: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {**super().as_dict(), "last_session": self.last_session}


class MoenWaterUsageSensor(MoenEntity, RestoreSensor):
    """Total water through the faucet since this sensor was created.

    Adds each new session's volume once, keyed by session timestamp. It starts
    at zero rather than backfilling history.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1
    _attr_translation_key = "water_usage"
    _requires_connection = False

    def __init__(self, coordinator: MoenCoordinator, client_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, client_id, "water_usage")
        self._total = 0.0
        self._last_session: int | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the running total."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_extra_data()) is not None:
            data = last.as_dict()
            if isinstance(value := data.get("native_value"), (int, float)):
                self._total = float(value)
            self._last_session = data.get("last_session")
        self._add_new_sessions()

    @property
    def extra_restore_state_data(self) -> _UsageData:
        """Store the total and the last counted session."""
        return _UsageData(
            self._total,
            self._attr_native_unit_of_measurement,
            self._last_session,
        )

    @property
    def native_value(self) -> float:
        """Return the total in litres."""
        return round(self._total, 3)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._add_new_sessions()
        super()._handle_coordinator_update()

    def _add_new_sessions(self) -> None:
        sessions = self.coordinator.sessions.get(self.client_id)
        if not sessions:
            return
        stamps = [s["timestamp"] for s in sessions if "timestamp" in s]
        if not stamps:
            return
        if self._last_session is None:
            # First run: count from now on.
            self._last_session = max(stamps)
            return
        covered = min(
            stamps
        ) <= self._last_session or self.coordinator.sessions_complete.get(
            self.client_id, False
        )
        if not covered:
            # More sessions happened than one page holds (e.g. Home Assistant
            # was down): page back to the last counted one before adding any.
            self.coordinator.request_sessions_since(self.client_id, self._last_session)
            self.hass.async_create_task(self.coordinator.async_request_refresh())
            return
        new = [
            s
            for s in sessions
            if s.get("timestamp", 0) > self._last_session and "totalVolUl" in s
        ]
        if new:
            self._total += sum(s["totalVolUl"] for s in new) / 1_000_000
            self._last_session = max(s["timestamp"] for s in new)
