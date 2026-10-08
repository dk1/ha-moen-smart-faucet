"""Tests for setup, entities and actions."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.moen_smart_faucet.api import (
    MoenAuthError,
    MoenCommandError,
    MoenConnectionError,
)
from custom_components.moen_smart_faucet.const import DOMAIN
from custom_components.moen_smart_faucet.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.valve import (
    DOMAIN as VALVE_DOMAIN,
    SERVICE_CLOSE_VALVE,
    SERVICE_OPEN_VALVE,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import FAUCET_ID, OFFLINE_FAUCET_ID, faucets, load_devices

VALVE = "valve.kitchen_faucet"
RUN_TEMP = "number.kitchen_faucet_run_temperature"


async def test_setup_and_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Only faucets get entities, with the expected states."""
    assert init_integration.state is ConfigEntryState.LOADED

    assert hass.states.get(VALVE).state == "closed"
    assert (
        hass.states.get("sensor.kitchen_faucet_water_temperature").state == "35.867001"
    )
    assert hass.states.get("sensor.kitchen_faucet_cabinet_temperature").state == "17"
    assert hass.states.get("sensor.kitchen_faucet_battery").state == "100"
    assert (
        hass.states.get("binary_sensor.kitchen_faucet_connectivity").state == STATE_ON
    )
    assert (
        hass.states.get("binary_sensor.kitchen_faucet_freeze_risk").state == STATE_OFF
    )
    assert hass.states.get(RUN_TEMP).state == "38.0"
    assert hass.states.get(RUN_TEMP).attributes["max"] == 48.889999

    # Wi-Fi signal is disabled by default.
    assert hass.states.get("sensor.kitchen_faucet_signal_strength") is None
    assert entity_registry.async_get("sensor.kitchen_faucet_signal_strength").disabled

    # The offline faucet: unavailable except for connectivity and run temperature.
    assert hass.states.get("valve.old_faucet").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.old_faucet_connectivity").state == STATE_OFF
    assert hass.states.get("number.old_faucet_run_temperature").state == "38.0"

    # The non-faucet device gets nothing.
    assert not [
        e
        for e in er.async_entries_for_config_entry(
            entity_registry, init_integration.entry_id
        )
        if "water_monitor" in e.entity_id
    ]

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("side_effect", "state"),
    [
        (MoenAuthError, ConfigEntryState.SETUP_ERROR),
        (MoenConnectionError, ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    side_effect: type,
    state: ConfigEntryState,
) -> None:
    """Auth failures start reauth; connection failures retry."""
    mock_client.async_get_faucets.side_effect = side_effect
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is state
    if side_effect is MoenAuthError:
        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert flows and flows[0]["context"]["source"] == "reauth"


async def test_open_close(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Open runs at the run temperature; close stops; state follows the poll."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: RUN_TEMP, ATTR_VALUE: 41},
        blocking=True,
    )
    await hass.services.async_call(
        VALVE_DOMAIN, SERVICE_OPEN_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
    )
    mock_client.async_run.assert_awaited_once_with(FAUCET_ID, 41.0)
    assert hass.states.get(VALVE).state == "open"

    devices = load_devices()
    devices[0]["state"] = "running"
    mock_client.async_get_faucets.return_value = faucets(devices)
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(VALVE).state == "open"

    await hass.services.async_call(
        VALVE_DOMAIN, SERVICE_CLOSE_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
    )
    mock_client.async_stop.assert_awaited_once_with(FAUCET_ID)
    assert hass.states.get(VALVE).state == "closed"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"temperature": 30}, 30.0),
        ({"preset": "hottest"}, "hottest"),
        ({}, 38.0),
    ],
)
async def test_run_action(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    data: dict,
    expected: float | str,
) -> None:
    """The run action passes a temperature, a preset, or the run temperature."""
    await hass.services.async_call(
        DOMAIN, "run", {ATTR_ENTITY_ID: VALVE, **data}, blocking=True
    )
    mock_client.async_run.assert_awaited_once_with(FAUCET_ID, expected)


async def test_run_action_rejects_both(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Temperature and preset are mutually exclusive."""
    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN,
            "run",
            {ATTR_ENTITY_ID: VALVE, "temperature": 30, "preset": "coldest"},
            blocking=True,
        )


async def test_command_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A rejected command raises a translated error and leaves the state alone."""
    mock_client.async_run.side_effect = MoenCommandError("nope")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            VALVE_DOMAIN, SERVICE_OPEN_VALVE, {ATTR_ENTITY_ID: VALVE}, blocking=True
        )
    assert err.value.translation_key == "command_failed"
    assert hass.states.get(VALVE).state == "closed"


async def test_diagnostics(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Diagnostics redact credentials and identifiers."""
    diag = await async_get_config_entry_diagnostics(hass, init_integration)
    text = str(diag)
    for secret in (
        "user@example.com",
        "hunter2",
        FAUCET_ID,
        OFFLINE_FAUCET_ID,
        "example-ssid",
    ):
        assert secret not in text
    assert diag["faucets"][0]["temperature"] == 35.867001
