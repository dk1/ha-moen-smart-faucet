"""Base entity for Moen Smart Faucet."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import MoenCoordinator


class MoenEntity(CoordinatorEntity[MoenCoordinator]):
    """An entity belonging to one faucet."""

    _attr_has_entity_name = True
    # Most entities are meaningless while the faucet is offline; the
    # connectivity sensor overrides this.
    _requires_connection = True

    def __init__(self, coordinator: MoenCoordinator, client_id: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.client_id = client_id
        self._attr_unique_id = f"{client_id}_{key}"
        device = coordinator.data[client_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            model_id=device.get("sku"),
            name=device.get("nickname") or f"{MODEL} {client_id}",
            serial_number=client_id,
            sw_version=device.get("firmwareVersion"),
        )

    @property
    def device(self) -> dict[str, Any]:
        """Return the latest data for this faucet."""
        return self.coordinator.data[self.client_id]

    @property
    def available(self) -> bool:
        """Return whether the faucet is present and, if required, online."""
        if not super().available or self.client_id not in self.coordinator.data:
            return False
        return not self._requires_connection or bool(self.device.get("connected"))
