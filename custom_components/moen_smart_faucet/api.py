"""Async client for the Moen smart water cloud API used by the Moen app.

This module has no Home Assistant dependencies so it can be lifted into a
standalone library later.

All device traffic goes through one endpoint, ``/v1/invoker``, which runs a
named AWS Lambda function on Moen's side. Faucet state lives in an AWS IoT
device shadow; commands are written to the shadow and the faucet picks them up.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://api.prod.iot.moen.com/v1"
TOKEN_URL = f"{API_BASE}/oauth2/token"
INVOKER_URL = f"{API_BASE}/invoker"

# Public app client ID from the Moen Android app (also used by the Flo by Moen
# integrations). Login needs only this, not the app's client secret.
CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"

# The app sends "client_credentials" together with the user's username and
# password; "password" is rejected with HTTP 501.
GRANT_LOGIN = "client_credentials"
GRANT_REFRESH = "refresh_token"

USER_AGENT = "Smartwater-Android-prod-3.60.0.7869"

FN_DEVICE_LIST = "smartwater-app-device-api-prod-list"
FN_SHADOW_GET = "smartwater-app-shadow-api-prod-get"
FN_SHADOW_UPDATE = "smartwater-app-shadow-api-prod-update"

DEVICE_TYPE_FAUCET = "VAK"

TEMPERATURE_HOTTEST = "hottest"
TEMPERATURE_COLDEST = "coldest"

# Refresh this many seconds before the access token actually expires.
_EXPIRY_MARGIN = 120
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class MoenError(Exception):
    """Base error for the Moen API."""


class MoenAuthError(MoenError):
    """Credentials were rejected."""


class MoenConnectionError(MoenError):
    """The API could not be reached or returned an unexpected response."""


class MoenCommandError(MoenError):
    """The API did not accept a command."""


@dataclass(slots=True)
class MoenTokens:
    """OAuth tokens returned by the Moen API."""

    access_token: str
    refresh_token: str | None
    expires_at: float


class MoenClient:
    """Client for the Moen smart water cloud API."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._username = username
        self._password = password
        self._tokens: MoenTokens | None = None
        self._lock = asyncio.Lock()

    async def async_login(self) -> None:
        """Log in with username and password."""
        await self._async_token_request(
            {
                "client_id": CLIENT_ID,
                "grant_type": GRANT_LOGIN,
                "username": self._username,
                "password": self._password,
            }
        )

    async def _async_refresh(self) -> None:
        """Refresh the access token, falling back to a full login."""
        if self._tokens and self._tokens.refresh_token:
            try:
                await self._async_token_request(
                    {
                        "client_id": CLIENT_ID,
                        "grant_type": GRANT_REFRESH,
                        "refresh_token": self._tokens.refresh_token,
                    }
                )
            except MoenAuthError:
                _LOGGER.debug("Refresh token rejected, logging in again")
            else:
                return
        await self.async_login()

    async def _async_token_request(self, body: dict[str, str]) -> None:
        try:
            async with self._session.post(
                TOKEN_URL,
                json=body,
                headers={"User-Agent": USER_AGENT},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise MoenAuthError(f"Login rejected (HTTP {resp.status})")
                if resp.status != 200:
                    raise MoenConnectionError(f"Login failed (HTTP {resp.status})")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise MoenConnectionError(f"Error talking to Moen: {err}") from err

        token = data.get("token", data) if isinstance(data, dict) else None
        if not isinstance(token, dict) or "access_token" not in token:
            raise MoenConnectionError("Login response did not contain a token")
        try:
            expires_in = int(token.get("expires_in", 3600))
        except TypeError, ValueError:
            expires_in = 3600
        self._tokens = MoenTokens(
            access_token=token["access_token"],
            # A refresh response may omit the refresh token; keep the old one.
            refresh_token=token.get("refresh_token")
            or (self._tokens.refresh_token if self._tokens else None),
            expires_at=time.monotonic() + expires_in - _EXPIRY_MARGIN,
        )

    async def _async_access_token(self) -> str:
        async with self._lock:
            if self._tokens is None:
                await self.async_login()
            elif time.monotonic() >= self._tokens.expires_at:
                await self._async_refresh()
            assert self._tokens is not None
            return self._tokens.access_token

    async def _async_invoke(self, fn: str, body: dict[str, Any] | None = None) -> Any:
        """Run a named function through the invoker, retrying once on auth failure."""
        payload: dict[str, Any] = {"fn": fn, "parse": True, "escape": True}
        if body is not None:
            payload["body"] = body
        for attempt in range(2):
            token = await self._async_access_token()
            try:
                async with self._session.post(
                    INVOKER_URL,
                    json=payload,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status in (401, 403) and attempt == 0:
                        async with self._lock:
                            await self._async_refresh()
                        continue
                    if resp.status in (401, 403):
                        raise MoenAuthError(f"{fn} unauthorized (HTTP {resp.status})")
                    if resp.status != 200:
                        raise MoenConnectionError(f"{fn} failed (HTTP {resp.status})")
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise MoenConnectionError(f"Error talking to Moen: {err}") from err
        raise MoenAuthError(f"{fn} unauthorized")  # pragma: no cover

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return all devices on the account, with reported state flattened in."""
        data = await self._async_invoke(FN_DEVICE_LIST)
        if not isinstance(data, list):
            raise MoenConnectionError("Unexpected device list response")
        return data

    async def async_get_faucets(self) -> dict[str, dict[str, Any]]:
        """Return faucets keyed by their IoT client ID."""
        return {
            str(device["clientId"]): device
            for device in await self.async_get_devices()
            if device.get("deviceType") == DEVICE_TYPE_FAUCET and device.get("clientId")
        }

    async def async_get_shadow(self, client_id: str) -> dict[str, Any]:
        """Return the raw AWS IoT shadow document for a device."""
        return await self._async_invoke(FN_SHADOW_GET, {"clientId": client_id})

    async def _async_command(self, client_id: str, payload: dict[str, Any]) -> None:
        data = await self._async_invoke(
            FN_SHADOW_UPDATE, {"clientId": client_id, "payload": payload}
        )
        if not (isinstance(data, dict) and data.get("status") is True):
            raise MoenCommandError(f"Command not accepted: {data!r}")

    async def async_run(self, client_id: str, temperature: float | str) -> None:
        """Start the water at a temperature in °C, or "hottest"/"coldest"."""
        if not isinstance(temperature, str):
            temperature = round(float(temperature), 1)
        await self._async_command(
            client_id,
            {"command": "run", "commandSrc": "app", "temperature": temperature},
        )

    async def async_stop(self, client_id: str) -> None:
        """Stop the water."""
        await self._async_command(client_id, {"command": "stop"})
