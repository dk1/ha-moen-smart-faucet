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
    ATTR_FLOW_RATE,
    ATTR_PRESET,
    ATTR_START,
    ATTR_TEMPERATURE,
    ATTR_UNIT,
    ATTR_VOLUME,
    DOMAIN,
    MAX_FLOW_RATE,
    MAX_RUN_TEMPERATURE,
    MIN_FLOW_RATE,
    MIN_RUN_TEMPERATURE,
    SERVICE_DISPENSE,
    SERVICE_RUN,
    START_NOW,
    START_ON_WAVE,
    UNIT_TO_UL,
)
from .coordinator import MoenConfigEntry, MoenCoordinator, MoenRuntimeData

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.VALVE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TEMPERATURE = vol.All(
    vol.Coerce(float), vol.Range(min=MIN_RUN_TEMPERATURE, max=MAX_RUN_TEMPERATURE)
)
PRESET = vol.In([TEMPERATURE_HOTTEST, TEMPERATURE_COLDEST])

RUN_SCHEMA = vol.All(
    cv.make_entity_service_schema(
        {
            vol.Optional(ATTR_TEMPERATURE): TEMPERATURE,
            vol.Optional(ATTR_PRESET): PRESET,
            vol.Optional(ATTR_FLOW_RATE): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_FLOW_RATE, max=MAX_FLOW_RATE)
            ),
        }
    ),
    cv.has_at_most_one_key(ATTR_TEMPERATURE, ATTR_PRESET),
)

DISPENSE_SCHEMA = vol.All(
    cv.make_entity_service_schema(
        {
            vol.Required(ATTR_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional(ATTR_UNIT, default="mL"): vol.In(list(UNIT_TO_UL)),
            vol.Optional(ATTR_TEMPERATURE): TEMPERATURE,
            vol.Optional(ATTR_PRESET): PRESET,
            vol.Optional(ATTR_START, default=START_NOW): vol.In(
                [START_NOW, START_ON_WAVE]
            ),
        }
    ),
    cv.has_at_most_one_key(ATTR_TEMPERATURE, ATTR_PRESET),
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
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DISPENSE,
        entity_domain=VALVE_DOMAIN,
        schema=DISPENSE_SCHEMA,
        func="async_dispense",
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
