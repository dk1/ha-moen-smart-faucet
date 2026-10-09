"""Tests for the API client, against a mocked HTTP layer."""

from http import HTTPStatus

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.moen_smart_faucet.api import (
    CLIENT_ID,
    INVOKER_URL,
    TOKEN_URL,
    MoenAuthError,
    MoenClient,
    MoenCommandError,
    MoenConnectionError,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .conftest import FAUCET_ID, load_devices

TOKEN = {"token": {"access_token": "a1", "refresh_token": "r1", "expires_in": "3600"}}


def client(hass: HomeAssistant) -> MoenClient:
    return MoenClient(async_get_clientsession(hass), "user@example.com", "pw")


async def test_login_and_faucets(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Login uses the app's grant type; faucets are filtered by device type."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json=load_devices())

    result = await client(hass).async_get_faucets()
    assert set(result) == {"100000001", "100000002"}

    _, _, login_body, _ = aioclient_mock.mock_calls[0]
    assert login_body == {
        "client_id": CLIENT_ID,
        "grant_type": "client_credentials",
        "username": "user@example.com",
        "password": "pw",
    }
    _, _, invoke_body, headers = aioclient_mock.mock_calls[1]
    assert invoke_body == {
        "fn": "smartwater-app-device-api-prod-list",
        "parse": True,
        "escape": True,
    }
    assert headers["Authorization"] == "Bearer a1"


@pytest.mark.parametrize("status", [HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED])
async def test_login_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status: HTTPStatus
) -> None:
    """Rejected credentials raise MoenAuthError."""
    aioclient_mock.post(TOKEN_URL, status=status)
    with pytest.raises(MoenAuthError):
        await client(hass).async_login()


async def test_login_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Server errors raise MoenConnectionError."""
    aioclient_mock.post(TOKEN_URL, status=HTTPStatus.NOT_IMPLEMENTED)
    with pytest.raises(MoenConnectionError):
        await client(hass).async_login()


async def test_unauthorized_invoke_refreshes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 from the invoker refreshes the token and retries once."""
    moen = client(hass)
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    await moen.async_login()

    aioclient_mock.clear_requests()
    aioclient_mock.post(INVOKER_URL, status=HTTPStatus.UNAUTHORIZED)
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    with pytest.raises(MoenAuthError):
        await moen.async_get_devices()
    # invoke, refresh, invoke again
    assert [str(c[1]) for c in aioclient_mock.mock_calls] == [
        INVOKER_URL,
        TOKEN_URL,
        INVOKER_URL,
    ]
    assert aioclient_mock.mock_calls[1][2]["grant_type"] == "refresh_token"


async def test_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Run and stop write the documented shadow payloads."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": True})
    moen = client(hass)

    await moen.async_run(FAUCET_ID, 38.04)
    await moen.async_run(FAUCET_ID, "coldest")
    await moen.async_stop(FAUCET_ID)

    bodies = [c[2] for c in aioclient_mock.mock_calls if str(c[1]) == INVOKER_URL]
    assert [b["fn"] for b in bodies] == ["smartwater-app-shadow-api-prod-update"] * 3
    assert [b["body"] for b in bodies] == [
        {
            "clientId": FAUCET_ID,
            "payload": {"command": "run", "commandSrc": "app", "temperature": 38.0},
        },
        {
            "clientId": FAUCET_ID,
            "payload": {
                "command": "run",
                "commandSrc": "app",
                "temperature": "coldest",
            },
        },
        {"clientId": FAUCET_ID, "payload": {"command": "stop"}},
    ]


async def test_command_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A response without status true is a command error."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": False})
    with pytest.raises(MoenCommandError):
        await client(hass).async_stop(FAUCET_ID)


async def test_run_with_flow_rate(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """FlowRate is only sent when given."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": True})
    await client(hass).async_run(FAUCET_ID, 40, 60)
    body = aioclient_mock.mock_calls[-1][2]["body"]
    assert body["payload"] == {
        "command": "run",
        "commandSrc": "app",
        "temperature": 40.0,
        "flowRate": 60,
        "purge": False,
        "wait": False,
    }


@pytest.mark.parametrize(
    ("temperature", "wait", "expected"),
    [
        (None, False, {"command": "dispense_no_wait", "purge": False, "wait": False}),
        (None, True, {"command": "dispense", "purge": False, "wait": True}),
        (
            40,
            False,
            {
                "command": "dispense_no_wait",
                "purge": False,
                "wait": False,
                "temperature": 40.0,
            },
        ),
        (
            40,
            True,
            {"command": "dispense", "purge": True, "wait": True, "temperature": 40.0},
        ),
    ],
)
async def test_dispense_payloads(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    temperature: float | None,
    wait: bool,
    expected: dict,
) -> None:
    """Dispense mirrors the Moen app's preset payloads."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": True})
    await client(hass).async_dispense(
        FAUCET_ID, 250_000, temperature, wait_for_wave=wait
    )
    body = aioclient_mock.mock_calls[-1][2]["body"]
    assert body["payload"] == {"commandSrc": "app", "volume": 250_000, **expected}


async def test_dispense_range(hass: HomeAssistant) -> None:
    """Volumes outside the app's limits are refused locally."""
    with pytest.raises(ValueError):
        await client(hass).async_dispense(FAUCET_ID, 1000)


async def test_sessions(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sessions come back from the data key."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"data": [{"timestamp": 1}]})
    assert await client(hass).async_get_sessions(FAUCET_ID, 5) == (
        [{"timestamp": 1}],
        True,
    )
    body = aioclient_mock.mock_calls[-1][2]
    assert body == {
        "fn": "smartwater-app-session-api-prod-get-v1",
        "parse": True,
        "escape": True,
        "body": {"clientId": FAUCET_ID, "limit": 5, "deviceType": "VAK"},
    }


async def test_presets(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Presets come back as a list; entries without an ID are dropped."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(
        INVOKER_URL, json=[{"presetId": "a", "nickname": "tea"}, {"nickname": "broken"}]
    )
    assert await client(hass).async_get_presets() == [
        {"presetId": "a", "nickname": "tea"}
    ]
    assert aioclient_mock.mock_calls[-1][2] == {
        "fn": "smartwater-app-preset-api-prod-list",
        "parse": True,
        "escape": True,
    }


async def test_run_preset_and_freeze(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Preset runs and the freeze setting use the documented payloads."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": True})
    moen = client(hass)
    await moen.async_run_preset(FAUCET_ID, "p1")
    await moen.async_set_freeze_protection(FAUCET_ID, True)
    bodies = [c[2] for c in aioclient_mock.mock_calls if str(c[1]) == INVOKER_URL]
    assert bodies[0]["fn"] == "smartwater-app-preset-api-prod-run"
    assert bodies[0]["body"] == {"clientId": FAUCET_ID, "presetId": "p1"}
    assert bodies[1]["body"] == {
        "clientId": FAUCET_ID,
        "payload": {"freezeEnable": True},
    }


async def test_expired_token_refreshes_first(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An expired access token is refreshed before the call, not after a 401."""
    moen = client(hass)
    aioclient_mock.post(
        TOKEN_URL,
        json={"token": {"access_token": "a1", "refresh_token": "r1", "expires_in": 0}},
    )
    await moen.async_login()
    aioclient_mock.clear_requests()
    aioclient_mock.post(
        TOKEN_URL, json={"token": {"access_token": "a2", "expires_in": "3600"}}
    )
    aioclient_mock.post(INVOKER_URL, json=[])
    await moen.async_get_devices()
    calls = aioclient_mock.mock_calls
    assert calls[0][2]["grant_type"] == "refresh_token"
    assert calls[1][3]["Authorization"] == "Bearer a2"
    # A refresh response without a refresh token keeps the old one.
    assert moen._tokens.refresh_token == "r1"


async def test_rejected_refresh_falls_back_to_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """If the refresh token is rejected, the client logs in again."""
    moen = client(hass)
    aioclient_mock.post(
        TOKEN_URL,
        json={"token": {"access_token": "a1", "refresh_token": "r1", "expires_in": 0}},
    )
    await moen.async_login()
    aioclient_mock.clear_requests()

    grants = []

    async def token(method, url, data):
        grants.append(data["grant_type"])
        if data["grant_type"] == "refresh_token":
            return AiohttpClientMockResponse(
                method, url, status=HTTPStatus.UNAUTHORIZED
            )
        return AiohttpClientMockResponse(method, url, json=TOKEN)

    aioclient_mock.post(TOKEN_URL, side_effect=token)
    aioclient_mock.post(INVOKER_URL, json=[])
    await moen.async_get_devices()
    assert grants == ["refresh_token", "client_credentials"]


@pytest.mark.parametrize(
    "response",
    [
        {"json": {"unexpected": True}},
        {"exc": aiohttp.ClientError},
        {"exc": TimeoutError},
    ],
)
async def test_login_bad_responses(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, response: dict
) -> None:
    """Malformed responses and network errors are connection errors."""
    aioclient_mock.post(TOKEN_URL, **response)
    with pytest.raises(MoenConnectionError):
        await client(hass).async_login()


@pytest.mark.parametrize(
    ("method", "args", "response"),
    [
        ("async_get_devices", (), {"json": {"not": "a list"}}),
        ("async_get_sessions", (FAUCET_ID,), {"json": ["not", "a dict"]}),
        ("async_get_presets", (), {"json": {"not": "a list"}}),
        ("async_get_devices", (), {"status": HTTPStatus.INTERNAL_SERVER_ERROR}),
        ("async_get_devices", (), {"exc": aiohttp.ClientError}),
    ],
)
async def test_invoke_bad_responses(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    method: str,
    args: tuple,
    response: dict,
) -> None:
    """Unexpected invoker responses raise MoenConnectionError."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, **response)
    with pytest.raises(MoenConnectionError):
        await getattr(client(hass), method)(*args)


async def test_bad_expires_in_defaults(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-numeric expires_in falls back to an hour."""
    aioclient_mock.post(TOKEN_URL, json={"access_token": "flat", "expires_in": "soon"})
    moen = client(hass)
    await moen.async_login()
    assert moen._tokens.access_token == "flat"


async def test_run_preset_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Review #11: a preset run answered with status false is an error."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    aioclient_mock.post(INVOKER_URL, json={"status": False, "errorMessage": "offline"})
    with pytest.raises(MoenCommandError, match="offline"):
        await client(hass).async_run_preset(FAUCET_ID, "p1")


async def test_sessions_paging(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Review #4: with `since`, pages back via lastEvaluatedKey until reaching it."""
    aioclient_mock.post(TOKEN_URL, json=TOKEN)
    pages = iter(
        [
            {
                "data": [{"timestamp": 30}, {"timestamp": 25}],
                "lastEvaluatedKey": {"k": 1},
            },
            {
                "data": [{"timestamp": 20}, {"timestamp": 10}],
                "lastEvaluatedKey": {"k": 2},
            },
        ]
    )

    async def respond(method, url, data):
        return AiohttpClientMockResponse(method, url, json=next(pages))

    aioclient_mock.post(INVOKER_URL, side_effect=respond)
    sessions, complete = await client(hass).async_get_sessions(FAUCET_ID, 2, since=15)
    assert [s["timestamp"] for s in sessions] == [30, 25, 20, 10]
    assert complete
    second = [c[2] for c in aioclient_mock.mock_calls if str(c[1]) == INVOKER_URL][1]
    assert second["body"]["lastEvaluatedKey"] == {"k": 1}
