"""Tests for preset buttons and the freeze protection switch."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.moen_smart_faucet.api import (
    MoenCommandError,
    MoenConnectionError,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import FAUCET_ID, faucets, load_devices, load_presets

SOUP = "button.kitchen_faucet_preset_soup"
TEA = "button.kitchen_faucet_preset_tea"
FREEZE = "switch.kitchen_faucet_freeze_protection"


async def test_preset_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Each saved preset gets a button per faucet that runs it."""
    assert hass.states.get(SOUP) is not None
    assert hass.states.get(TEA) is not None
    assert hass.states.get("button.old_faucet_preset_tea").state == STATE_UNAVAILABLE

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: TEA}, blocking=True
    )
    mock_client.async_run_preset.assert_awaited_once_with(FAUCET_ID, "preset-tea")


async def test_presets_added_and_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """New presets appear on the next refresh; deleted ones are removed."""
    presets = load_presets()
    mock_client.async_get_presets.return_value = [
        presets[1],
        {"presetId": "preset-new", "nickname": "Pasta pot", "caseNumber": "5b"},
    ]
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("button.kitchen_faucet_preset_pasta_pot") is not None
    assert hass.states.get(SOUP) is None
    assert hass.states.get(TEA).state != STATE_UNAVAILABLE


async def test_preset_failure_does_not_block_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """If presets can't be fetched, the faucet still loads, without preset buttons."""
    mock_client.async_get_presets.side_effect = MoenConnectionError
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("valve.kitchen_faucet").state == "closed"
    assert hass.states.get(SOUP) is None


async def test_preset_run_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A failed preset run raises a translated error."""
    mock_client.async_run_preset.side_effect = MoenConnectionError("down")
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: SOUP}, blocking=True
        )
    assert err.value.translation_key == "command_failed"


async def test_freeze_protection(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The switch follows freezeEnable and writes it."""
    assert hass.states.get(FREEZE).state == STATE_OFF

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: FREEZE}, blocking=True
    )
    mock_client.async_set_freeze_protection.assert_awaited_once_with(FAUCET_ID, True)
    assert hass.states.get(FREEZE).state == STATE_ON

    # The next poll reports the faucet's real value.
    devices = load_devices()
    devices[0]["freezeEnable"] = True
    mock_client.async_get_faucets.return_value = faucets(devices)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(FREEZE).state == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: FREEZE}, blocking=True
    )
    mock_client.async_set_freeze_protection.assert_awaited_with(FAUCET_ID, False)
    assert hass.states.get(FREEZE).state == STATE_OFF


async def test_freeze_protection_failure(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A rejected setting leaves the switch where it was."""
    mock_client.async_set_freeze_protection.side_effect = MoenCommandError("no")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: FREEZE}, blocking=True
        )
    assert hass.states.get(FREEZE).state == STATE_OFF
