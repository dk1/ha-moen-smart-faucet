"""Base entity for Moen Smart Faucet."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MoenError
from .const import COMMAND_REFRESH_DELAY, DOMAIN, MANUFACTURER, MODEL
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

    async def async_send_command(self, command: Awaitable[None]) -> None:
        """Send a faucet command, then refresh once the faucet has reacted."""
        try:
            await command
        except MoenError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        async def _refresh(_: Any) -> None:
            await self.coordinator.async_request_refresh()

        self.async_on_remove(
            async_call_later(self.hass, COMMAND_REFRESH_DELAY, _refresh)
        )
