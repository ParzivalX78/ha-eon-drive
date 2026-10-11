"""Shared fixtures. All data here is synthetic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def mock_client():
    """Patch the API client so no network access happens."""
    with patch("custom_components.eon_drive.EonDriveClient", autospec=True) as cls:
        client = cls.return_value
        client.login = AsyncMock()
        client.search_locations = AsyncMock(return_value=load("search"))
        client.get_locations = AsyncMock(return_value=load("locations"))
        client.get_ongoing_sessions = AsyncMock(return_value=[])
        client.get_session_history = AsyncMock(return_value=load("history")["data"])
        yield client
