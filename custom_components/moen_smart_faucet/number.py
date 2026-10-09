"""Number platform for Moen Smart Faucet: settings used when running or dispensing.

These values live in Home Assistant, not on the faucet. They're restored after a
restart and read by the valve and button entities and the faucet actions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    DEFAULT_DISPENSE_ML,
    DEFAULT_FLOW_RATE,
    DEFAULT_RUN_TEMPERATURE,
    MAX_DISPENSE_ML,
    MAX_FLOW_RATE,
    MIN_DISPENSE_ML,
    MIN_FLOW_RATE,
)
from .coordinator import MoenConfigEntry, MoenCoordinator
from .entity import MoenEntity

# Setting a value can send `run`; keep those in order.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class MoenNumberDescription(NumberEntityDescription):
    """Describes a faucet setting stored in Home Assistant."""

    store: Callable[[MoenCoordinator], dict[str, float]]
    default: Callable[[MoenCoordinator, str], float]
    # (min, max) for this faucet; static unless the faucet constrains it.
    limits: Callable[[MoenCoordinator, str], tuple[float, float]]
    # Re-send `run` when changed during a run Home Assistant started.
    adjusts_run: bool = False


def _default_flow_rate(coordinator: MoenCoordinator, client_id: str) -> float:
    value = coordinator.data[client_id].get("defaultFlowRate")
    if isinstance(value, (int, float)) and MIN_FLOW_RATE <= value <= MAX_FLOW_RATE:
        return float(value)
    return float(DEFAULT_FLOW_RATE)


NUMBERS: tuple[MoenNumberDescription, ...] = (
    MoenNumberDescription(
        key="run_temperature",
        translation_key="run_temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=1,
        mode=NumberMode.SLIDER,
        store=lambda c: c.run_temperatures,
        default=lambda c, _: DEFAULT_RUN_TEMPERATURE,
        limits=lambda c, client_id: c.run_temperature_range(client_id),
        adjusts_run=True,
    ),
    MoenNumberDescription(
        key="flow_rate",
        translation_key="flow_rate",
        native_unit_of_measurement=PERCENTAGE,
        native_step=1,
        mode=NumberMode.SLIDER,
        store=lambda c: c.flow_rates,
        default=_default_flow_rate,
        limits=lambda c, _: (MIN_FLOW_RATE, MAX_FLOW_RATE),
        adjusts_run=True,
    ),
    MoenNumberDescription(
        key="dispense_amount",
        translation_key="dispense_amount",
        device_class=NumberDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        native_step=5,
        mode=NumberMode.BOX,
        store=lambda c: c.dispense_amounts_ml,
        default=lambda c, _: DEFAULT_DISPENSE_ML,
        limits=lambda c, _: (MIN_DISPENSE_ML, MAX_DISPENSE_ML),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MoenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the faucet settings."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MoenNumber(coordinator, client_id, description)
        for client_id in coordinator.data
        for description in NUMBERS
    )


class MoenNumber(MoenEntity, RestoreNumber):
    """A faucet setting kept in Home Assistant."""

    entity_description: MoenNumberDescription
    _requires_connection = False

    def __init__(
        self,
        coordinator: MoenCoordinator,
        client_id: str,
        description: MoenNumberDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator, client_id, description.key)
        self.entity_description = description
        self._store.setdefault(client_id, description.default(coordinator, client_id))

    @property
    def _store(self) -> dict[str, float]:
        return self.entity_description.store(self.coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            self._store[self.client_id] = last.native_value

    @property
    def native_min_value(self) -> float:
        """Return the minimum."""
        return self.entity_description.limits(self.coordinator, self.client_id)[0]

    @property
    def native_max_value(self) -> float:
        """Return the maximum."""
        return self.entity_description.limits(self.coordinator, self.client_id)[1]

    @property
    def native_value(self) -> float:
        """Return the current value, kept inside the allowed range."""
        return min(
            max(self._store[self.client_id], self.native_min_value),
            self.native_max_value,
        )

    async def async_set_native_value(self, value: float) -> None:
        """Store a new value, and apply it to a run Home Assistant started."""
        self._store[self.client_id] = value
        self.async_write_ha_state()
        if self.entity_description.adjusts_run and self.coordinator.can_adjust_run(
            self.client_id
        ):
            key = self.entity_description.key
            await self.async_send_command(
                self.coordinator.async_adjust_run(
                    self.client_id,
                    temperature=value if key == "run_temperature" else None,
                    flow_rate=value if key == "flow_rate" else None,
                )
            )
