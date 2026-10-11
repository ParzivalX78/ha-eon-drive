"""API client tests using a fake aiohttp session."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.eon_drive.api import (
    EonDriveAuthError,
    EonDriveClient,
    EonDriveRateLimitError,
)
from custom_components.eon_drive.const import BASE_URL


class _Resp:
    def __init__(self, status, data, headers=None):
        self.status, self._data, self.headers = status, data, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data


class _Session:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return _Resp(*self.replies.pop(0))


def _client(session):
    return EonDriveClient(
        session, username="u@example.com", password="p", client_id="1",
        client_secret="s", device_id="DEV",
    )


async def test_login_and_locations_request_shape():
    session = _Session([(200, {"access_token": "tok"}), (200, {"locations": [], "tariffs": []})])
    client = _client(session)
    await client.get_locations(["1348", "23279"])

    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", f"{BASE_URL}/oauth/token")
    assert kw["json"]["grant_type"] == "password"
    assert set(kw["json"]) == {"client_id", "client_secret", "username", "password", "grant_type"}
    assert "Authorization" not in kw["headers"]

    method, url, kw = session.calls[1]
    assert (method, url) == ("POST", f"{BASE_URL}/locations")
    assert kw["params"] == {"operatorCountry": "CZ"}
    assert kw["json"] == {"locations": {"1348": "", "23279": ""}}
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert kw["headers"]["x-device-id"] == "DEV"


async def test_relogin_on_401():
    session = _Session(
        [(200, {"access_token": "old"}), (401, {}), (200, {"access_token": "new"}), (200, {"data": []})]
    )
    client = _client(session)
    assert await client.get_ongoing_sessions() == []
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer new"


async def test_bad_credentials():
    client = _client(_Session([(401, {"error": "invalid_grant"})]))
    with pytest.raises(EonDriveAuthError):
        await client.login()


async def test_history_params():
    session = _Session([(200, {"access_token": "t"}), (200, {"data": [{"session": {}}]})])
    client = _client(session)
    await client.get_session_history(date(2026, 9, 1), date(2026, 10, 12))
    assert session.calls[1][2]["params"] == {
        "start_date": "2026-09-01", "end_date": "2026-10-12", "page": 1, "perPage": 100,
    }


async def test_no_locations_makes_no_request():
    session = _Session([])
    assert await _client(session).get_locations([]) == {"locations": [], "tariffs": []}
    assert session.calls == []


async def test_rate_limit_is_reported_with_retry_after():
    session = _Session([(200, {"access_token": "t"}), (429, {}, {"Retry-After": "120"})])
    with pytest.raises(EonDriveRateLimitError) as err:
        await _client(session).get_ongoing_sessions()
    assert err.value.retry_after == 120
    assert len(session.calls) == 2  # no retry storm


async def test_existing_token_skips_login_and_new_token_is_reported():
    seen = []
    session = _Session([(200, {"data": []}), (401, {}), (200, {"access_token": "fresh"}), (200, {"data": []})])
    client = EonDriveClient(
        session, username="u", password="p", client_id="1", client_secret="s",
        device_id="DEV", token="stored", on_token=seen.append,
    )
    await client.get_ongoing_sessions()
    assert len(session.calls) == 1 and session.calls[0][2]["headers"]["Authorization"] == "Bearer stored"
    await client.get_ongoing_sessions()
    assert seen == ["fresh"]
