"""The Moen Smart Faucet integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.valve import DOMAIN as VALVE_DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TEMPERATURE_COLDEST, TEMPERATURE_HOTTEST, MoenClient
from .const import (
    ATTR_PRESET,
    ATTR_TEMPERATURE,
    DOMAIN,
    MAX_RUN_TEMPERATURE,
    MIN_RUN_TEMPERATURE,
    SERVICE_RUN,
)
from .coordinator import MoenConfigEntry, MoenCoordinator, MoenRuntimeData

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.VALVE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RUN_SCHEMA = vol.All(
    cv.has_at_most_one_key(ATTR_TEMPERATURE, ATTR_PRESET),
    cv.make_entity_service_schema(
        {
            vol.Optional(ATTR_TEMPERATURE): vol.All(
                vol.Coerce(float),
                vol.Range(min=MIN_RUN_TEMPERATURE, max=MAX_RUN_TEMPERATURE),
            ),
            vol.Optional(ATTR_PRESET): vol.In(
                [TEMPERATURE_HOTTEST, TEMPERATURE_COLDEST]
            ),
        }
    ),
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RUN,
        entity_domain=VALVE_DOMAIN,
        schema=RUN_SCHEMA,
        func="async_run",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MoenConfigEntry) -> bool:
    """Set up Moen Smart Faucet from a config entry."""
    client = MoenClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = MoenCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = MoenRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MoenConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
