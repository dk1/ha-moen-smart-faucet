"""Fixtures for Moen Smart Faucet tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

from custom_components.moen_smart_faucet.const import DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

USERNAME = "user@example.com"
PASSWORD = "hunter2"
FAUCET_ID = "100000001"
OFFLINE_FAUCET_ID = "100000002"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use Home Assistant's snapshot format and tests/snapshots folder.

    The test harness and syrupy both define `snapshot`; which wins depends on
    plugin load order, so pin it here as Home Assistant core does.
    """
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading the custom integration."""


def load_devices() -> list[dict[str, Any]]:
    """Return the device list fixture."""
    return json.loads((Path(__file__).parent / "fixtures" / "devices.json").read_text())


def load_sessions() -> list[dict[str, Any]]:
    """Return the session history fixture (newest first)."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "sessions.json").read_text()
    )


def load_presets() -> list[dict[str, Any]]:
    """Return the saved-presets fixture."""
    return json.loads((Path(__file__).parent / "fixtures" / "presets.json").read_text())


def faucets(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Filter a device list the way the client does."""
    return {d["clientId"]: d for d in devices if d["deviceType"] == "VAK"}


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Create entities that are disabled by default as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
        new_callable=PropertyMock,
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=USERNAME,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Mock the Moen API client everywhere it is constructed."""
    with (
        patch(
            "custom_components.moen_smart_faucet.MoenClient", autospec=True
        ) as client_cls,
        patch(
            "custom_components.moen_smart_faucet.config_flow.MoenClient",
            new=client_cls,
        ),
    ):
        client = client_cls.return_value
        devices = load_devices()
        client.async_get_devices.return_value = devices
        client.async_get_faucets.return_value = faucets(devices)
        client.async_get_sessions.return_value = (load_sessions(), True)
        client.async_get_presets.return_value = load_presets()
        yield client


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_client: AsyncMock
) -> MockConfigEntry:
    """Set up the integration."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
