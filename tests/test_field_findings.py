"""Tests for behaviour found testing on a real faucet (2026-10-13)."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .conftest import FAUCET_ID, faucets, load_devices, load_presets

VALVE = "valve.kitchen_faucet"
STATUS = "sensor.kitchen_faucet_status"


async def _poll(hass, mock_client, freezer, state, seconds=31):
    devices = load_devices()
    devices[0]["state"] = state
    mock_client.async_get_faucets.return_value = faucets(devices)
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("state", "valve", "status"),
    [
        ("dispensing", "open", "dispensing"),
        ("purging", "open", "purging"),
        ("purged", "closed", "purged"),
        ("running", "open", "running"),
        ("something_new", "closed", STATE_UNKNOWN),
    ],
)
async def test_faucet_states(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
    state: str,
    valve: str,
    status: str,
) -> None:
    """Dispensing shows the water as on; 'purged' (waiting for a wave) as off."""
    await _poll(hass, mock_client, freezer, state)
    assert hass.states.get(VALVE).state == valve
    assert hass.states.get(STATUS).state == status
    # Any non-idle state polls fast to catch the end of it.
    assert init_integration.runtime_data.coordinator.update_interval == timedelta(
        seconds=5
    )


async def test_last_use_source(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The last session's source is shown."""
    assert hass.states.get("sensor.kitchen_faucet_last_use_source").state == "app"


async def test_command_flags_cleared_when_idle(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """purge/wait flags are cleared once the faucet is idle, not while it runs."""
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.kitchen_faucet_dispense"},
        blocking=True,
    )
    await _poll(hass, mock_client, freezer, "dispensing", seconds=5)
    mock_client.async_clear_command_flags.assert_not_awaited()
    await _poll(hass, mock_client, freezer, "idle", seconds=5)
    mock_client.async_clear_command_flags.assert_awaited_once_with(FAUCET_ID)
    # Only once.
    await _poll(hass, mock_client, freezer, "idle")
    mock_client.async_clear_command_flags.assert_awaited_once()


async def test_flags_kept_while_run_tracked(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A just-opened run isn't cleaned up before the faucet reports it."""
    await hass.services.async_call(
        "valve", "open_valve", {ATTR_ENTITY_ID: VALVE}, blocking=True
    )
    await _poll(hass, mock_client, freezer, "idle", seconds=3)
    mock_client.async_clear_command_flags.assert_not_awaited()
    await _poll(hass, mock_client, freezer, "running", seconds=5)
    await _poll(hass, mock_client, freezer, "idle", seconds=5)
    mock_client.async_clear_command_flags.assert_awaited_once_with(FAUCET_ID)


async def test_preset_rename(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A preset renamed in the Moen app is renamed in Home Assistant (via reload)."""
    presets = load_presets()
    presets[1]["nickname"] = "Green tea"
    mock_client.async_get_presets.return_value = presets
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    state = hass.states.get("button.kitchen_faucet_preset_tea")
    assert state.attributes["friendly_name"] == "Kitchen Faucet Preset Green tea"
