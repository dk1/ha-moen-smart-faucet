"""Regression tests for issues found in the v0.2.0 code review."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.moen_smart_faucet.api import MoenAuthError
from custom_components.moen_smart_faucet.const import DOMAIN
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr

from .conftest import FAUCET_ID, faucets, load_devices, load_sessions

VALVE = "valve.kitchen_faucet"
FLOW = "number.kitchen_faucet_flow_rate"
RUN_TEMP = "number.kitchen_faucet_run_temperature"


async def _poll(hass, mock_client, freezer, state=None, seconds=31, **changes):
    devices = load_devices()
    if state:
        devices[0]["state"] = state
    devices[0].update(changes)
    mock_client.async_get_faucets.return_value = faucets(devices)
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _set(hass, entity_id, value):
    await hass.services.async_call(
        "number",
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )


async def _open(hass):
    await hass.services.async_call(
        "valve", "open_valve", {ATTR_ENTITY_ID: VALVE}, blocking=True
    )


async def test_dispense_button_ends_live_adjust(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #1: a slider change after Dispense must not turn the pour into a run."""
    await _open(hass)
    await _poll(hass, mock_client, freezer, "running")
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.kitchen_faucet_dispense"},
        blocking=True,
    )
    await _set(hass, FLOW, 50)
    assert mock_client.async_run.await_count == 1  # only the original open


async def test_handle_stop_within_grace_is_not_restarted(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #2: once the run was seen and then went idle, sliders never restart it."""
    await _open(hass)
    await _poll(hass, mock_client, freezer, "running", seconds=4)
    await _poll(hass, mock_client, freezer, "idle", seconds=5)  # stopped at the handle
    await _set(hass, FLOW, 50)
    await _set(hass, RUN_TEMP, 30)
    assert mock_client.async_run.await_count == 1


async def test_no_adjust_before_run_is_confirmed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #2: before the faucet reports running, a slider change only stores."""
    await _open(hass)
    await _poll(hass, mock_client, freezer, "idle", seconds=3)
    await _set(hass, FLOW, 50)
    assert mock_client.async_run.await_count == 1


async def test_live_adjust_keeps_run_settings(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #3: changing flow keeps the run's preset; changing temperature keeps its flow."""
    await hass.services.async_call(
        DOMAIN,
        "run",
        {ATTR_ENTITY_ID: VALVE, "preset": "coldest", "flow_rate": 70},
        blocking=True,
    )
    await _poll(hass, mock_client, freezer, "running")
    await _set(hass, FLOW, 40)
    mock_client.async_run.assert_awaited_with(FAUCET_ID, "coldest", 40)
    await _set(hass, RUN_TEMP, 30)
    mock_client.async_run.assert_awaited_with(FAUCET_ID, 30.0, 40)


async def test_valve_stays_open_while_faucet_lags(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #5: a slow 'running' report doesn't flip the valve to closed."""
    await _open(hass)
    await _poll(hass, mock_client, freezer, "idle", seconds=3)
    assert hass.states.get(VALVE).state == "open"
    # Polling stays fast while the run is pending.
    assert init_integration.runtime_data.coordinator.update_interval == timedelta(
        seconds=5
    )
    await _poll(hass, mock_client, freezer, "idle", seconds=16)
    assert hass.states.get(VALVE).state == "closed"


async def test_commands_reuse_one_refresh_timer(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Review #6: repeated commands don't pile up removal callbacks."""
    platform = hass.data["entity_components"]["valve"].get_entity(VALVE)
    before = len(platform._on_remove or [])
    for _ in range(5):
        await _open(hass)
    assert len(platform._on_remove or []) == before


async def test_session_retry_when_not_yet_recorded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Review #7: if the session isn't recorded when the shadow changes, retry."""
    calls = mock_client.async_get_sessions.await_count
    await _poll(hass, mock_client, freezer, volume=123)  # nothing new yet
    await _poll(hass, mock_client, freezer, volume=123)  # retried
    assert mock_client.async_get_sessions.await_count == calls + 2

    sessions = load_sessions()
    new = {
        **sessions[0],
        "timestamp": sessions[0]["timestamp"] + 60,
        "totalVolUl": 2_000_000,
    }
    mock_client.async_get_sessions.return_value = ([new, *sessions], True)
    await _poll(hass, mock_client, freezer, volume=123)
    assert hass.states.get("sensor.kitchen_faucet_water_usage").state == "2.0"


async def test_usage_backfills_long_outage(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Review #4: sessions beyond the first page after downtime are all counted."""
    last_counted = 1_000
    page = [{"timestamp": 2_000 + i, "totalVolUl": 1_000_000} for i in range(10, 0, -1)]
    older = [
        {"timestamp": 1_500, "totalVolUl": 500_000},
        {"timestamp": last_counted, "totalVolUl": 9},
    ]
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("sensor.kitchen_faucet_water_usage", "5.0"),
                {
                    "native_value": 5.0,
                    "native_unit_of_measurement": "L",
                    "last_session": last_counted,
                },
            )
        ],
    )

    async def sessions(client_id, limit=10, since=None, max_pages=10):
        if since is not None and since <= last_counted:
            return page + older, True
        return page, False

    mock_client.async_get_sessions.side_effect = sessions
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    # 10 x 1 L + 0.5 L on top of the restored 5 L.
    assert hass.states.get("sensor.kitchen_faucet_water_usage").state == "15.5"


async def test_preset_auth_error_does_not_start_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Review #12: the optional preset list can't trigger reauthentication."""
    mock_client.async_get_presets.side_effect = MoenAuthError
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_child_limit_and_hottest_clamped(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Review #9: child mode lowers the limit, and 'hottest' respects it."""
    devices = load_devices()
    devices[0]["childModeEnabled"] = True
    mock_client.async_get_faucets.return_value = faucets(devices)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(RUN_TEMP).attributes["max"] == 40
    await hass.services.async_call(
        DOMAIN, "run", {ATTR_ENTITY_ID: VALVE, "preset": "hottest"}, blocking=True
    )
    mock_client.async_run.assert_awaited_with(FAUCET_ID, 40.0, 100)


@pytest.mark.parametrize(
    ("unit", "volume", "expected"),
    [("mL", 250, 250_000), ("ML", 250, 250_000), ("L", 1, 1_000_000)],
)
async def test_unit_case_insensitive(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    unit: str,
    volume: float,
    expected: int,
) -> None:
    """The v0.2.0 rename to lowercase units keeps accepting mL and L."""
    await hass.services.async_call(
        DOMAIN,
        "dispense",
        {ATTR_ENTITY_ID: VALVE, "volume": volume, "unit": unit},
        blocking=True,
    )
    mock_client.async_dispense.assert_awaited_once_with(
        FAUCET_ID, expected, None, wait_for_wave=False
    )


async def test_device_removal_only_for_gone_faucets(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Faucets still on the account can't be deleted; stale ones can."""
    from custom_components.moen_smart_faucet import async_remove_config_entry_device

    present = device_registry.async_get_device_by_identifier(
        (DOMAIN, FAUCET_ID), init_integration.entry_id
    )
    assert not await async_remove_config_entry_device(hass, init_integration, present)
    stale = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id, identifiers={(DOMAIN, "999")}
    )
    assert await async_remove_config_entry_device(hass, init_integration, stale)


async def test_new_faucet_triggers_reload(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A faucet added to the account appears after an automatic reload."""
    devices = load_devices()
    devices.append({**devices[0], "clientId": "100000009", "nickname": "Bar sink"})
    mock_client.async_get_faucets.return_value = faucets(devices)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("valve.bar_sink") is not None


async def test_firmware_kept_current(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A firmware update shows up on the device."""
    await _poll(hass, mock_client, freezer, firmwareVersion="v1.2.0")
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, FAUCET_ID), init_integration.entry_id
    )
    assert device.sw_version == "v1.2.0"
