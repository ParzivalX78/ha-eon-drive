"""Client for the E.ON Drive (AMPECO) mobile app API.

This is an unofficial, read-only client. It only issues the requests the
mobile app itself makes when browsing chargers and charging history.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import aiohttp

from .const import (
    APP_BUNDLE_ID,
    APP_INTERNAL_VERSION,
    APP_PLATFORM,
    APP_USER_AGENT,
    BASE_URL,
    OPERATOR_COUNTRY,
    REQUEST_TIMEOUT,
)


class EonDriveError(Exception):
    """Generic API error."""


class EonDriveAuthError(EonDriveError):
    """Credentials were rejected."""


class EonDriveConnectionError(EonDriveError):
    """The API could not be reached."""


class EonDriveClient:
    """Minimal async client for the E.ON Drive app API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        username: str,
        password: str,
        client_id: str,
        client_secret: str,
        device_id: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._client_id = client_id
        self._client_secret = client_secret
        self._device_id = device_id
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "cs",
            "User-Agent": APP_USER_AGENT,
            "x-operator-country": OPERATOR_COUNTRY,
            "x-mobile-app-bundle-id": APP_BUNDLE_ID,
            "x-device-id": self._device_id,
            "x-platform": APP_PLATFORM,
            "x-internal-app-version": APP_INTERNAL_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _raw(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> tuple[int, Any]:
        try:
            async with self._session.request(
                method,
                f"{BASE_URL}{path}",
                params=params,
                json=json,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                if status == 204:
                    return status, None
                try:
                    data = await resp.json(content_type=None)
                except ValueError:
                    data = None
                return status, data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EonDriveConnectionError(str(err) or type(err).__name__) from err

    async def login(self) -> None:
        """Obtain a new access token with the password grant."""
        async with self._login_lock:
            self._token = None
            status, data = await self._raw(
                "POST",
                "/oauth/token",
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "username": self._username,
                    "password": self._password,
                    "grant_type": "password",
                },
            )
            if status in (400, 401, 403, 422):
                raise EonDriveAuthError(f"Login rejected (HTTP {status})")
            if status != 200 or not isinstance(data, dict) or "access_token" not in data:
                raise EonDriveError(f"Unexpected login response (HTTP {status})")
            self._token = data["access_token"]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        if self._token is None:
            await self.login()
        status, data = await self._raw(method, path, params=params, json=json)
        if status == 401:
            # Token expired or was revoked: log in once more and retry.
            await self.login()
            status, data = await self._raw(method, path, params=params, json=json)
            if status == 401:
                raise EonDriveAuthError("Token rejected after re-login")
        if status >= 400:
            raise EonDriveError(f"{method} {path} failed (HTTP {status})")
        return data

    async def search_locations(self, query: str) -> list[dict[str, Any]]:
        """Search charging locations by name/city."""
        data = await self._request("GET", "/locations/search", params={"query": query})
        return data if isinstance(data, list) else []

    async def get_locations(self, location_ids: list[str]) -> dict[str, Any]:
        """Return details (EVSEs, status, tariffs) for the given locations."""
        if not location_ids:
            return {"locations": [], "tariffs": []}
        data = await self._request(
            "POST",
            "/locations",
            params={"operatorCountry": OPERATOR_COUNTRY},
            json={"locations": {str(loc_id): "" for loc_id in location_ids}},
        )
        return data if isinstance(data, dict) else {"locations": [], "tariffs": []}

    async def get_ongoing_sessions(self) -> list[dict[str, Any]]:
        """Return sessions currently in progress."""
        data = await self._request("GET", "/session/ongoing")
        items = data.get("data", []) if isinstance(data, dict) else []
        return [i for i in items if isinstance(i, dict)]

    async def get_session(self, session_id: str) -> dict[str, Any]:
        """Return a single session."""
        data = await self._request("GET", f"/session/{session_id}")
        if isinstance(data, dict):
            return data.get("session", data)
        return {}

    async def get_session_history(
        self, start: date, end: date, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """Return finished sessions between two dates (first page)."""
        data = await self._request(
            "GET",
            "/profile/session_history",
            params={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "page": 1,
                "perPage": per_page,
            },
        )
        items = data.get("data", []) if isinstance(data, dict) else []
        return [i for i in items if isinstance(i, dict)]
