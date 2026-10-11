"""Config flow and entity tests with a mocked API client."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eon_drive.api import EonDriveAuthError
from custom_components.eon_drive.const import DOMAIN

from .conftest import load

USER_INPUT = {
    "username": "driver@example.com",
    "password": "not-a-real-password",
    "client_id": "1",
    "client_secret": "not-a-real-secret",
}
ENTRY_DATA = {**USER_INPUT, "device_id": "00000000-0000-0000-0000-000000000000"}


async def test_full_flow(hass: HomeAssistant, mock_client) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "search"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "test"})
    assert result["step_id"] == "select"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"locations": ["1001"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "driver@example.com"
    assert result["options"]["locations"] == ["1001"]
    assert len(result["data"]["device_id"]) == 36
    await hass.async_block_till_done()


async def test_flow_invalid_auth(hass: HomeAssistant, mock_client) -> None:
    mock_client.login.side_effect = EonDriveAuthError("nope")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_skip_locations(hass: HomeAssistant, mock_client) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["locations"] == []
    await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, locations=("1001",)) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"locations": list(locations), "scan_interval": 300},
        unique_id="driver@example.com",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique_suffix: str):
    registry = er.async_get(hass)
    entity_id = next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id == f"{entry.entry_id}_{unique_suffix}"
    )
    return hass.states.get(entity_id)


async def test_entities(
    hass: HomeAssistant, mock_client, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Europe/Prague")
    freezer.move_to("2026-10-12 10:00:00+00:00")  # noon in Prague -> day tariff
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    mock_client.get_locations.assert_awaited_with(["1001"])

    ccs = _state(hass, entry, "evse_11_status")
    assert ccs.state == "available"
    assert ccs.attributes["max_power_kw"] == 90.0
    assert ccs.attributes["price_per_kwh_now"] == 9.5
    assert ccs.attributes["currency"] == "CZK"
    assert ccs.name == "Test Hub CCS 2 90 kW (1)"
    assert _state(hass, entry, "evse_12_status").state == "out_of_order"
    assert _state(hass, entry, "evse_13_status").state == "charging"
    assert _state(hass, entry, "location_1001_available").state == "1"

    assert _state(hass, entry, "charging").state == "off"
    assert _state(hass, entry, "charging_power").state == "unknown"
    assert _state(hass, entry, "last_session_energy").state == "40.0"
    assert _state(hass, entry, "last_session_cost").state == "320.0"
    assert _state(hass, entry, "last_session_cost").attributes["unit_of_measurement"] == "CZK"
    assert _state(hass, entry, "month_energy").state == "70.5"
    assert _state(hass, entry, "month_cost").state == "579.0"

    # A session starts.
    mock_client.get_ongoing_sessions.return_value = load("ongoing")["data"]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, entry, "charging").state == "on"
    assert _state(hass, entry, "charging_power").state == "75.5"
    assert _state(hass, entry, "charging_energy").state == "12.345"
    assert _state(hass, entry, "charging_cost").state == "98.76"
    assert _state(hass, entry, "charging_soc").state == "42.0"

    # It ends: history must be refetched immediately, not after 30 minutes.
    calls = mock_client.get_session_history.await_count
    mock_client.get_ongoing_sessions.return_value = []
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert mock_client.get_session_history.await_count == calls + 1
    assert _state(hass, entry, "charging").state == "off"


async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_client) -> None:
    mock_client.get_locations.side_effect = EonDriveAuthError("expired")
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, options={"locations": ["1001"]})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flows and flows[0]["step_id"] == "reauth_confirm"

    mock_client.get_locations.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "new-password"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["password"] == "new-password"
    assert entry.state is ConfigEntryState.LOADED


async def test_options_add_and_remove(hass: HomeAssistant, mock_client) -> None:
    entry = await _setup(hass)
    device_reg = dr.async_get(hass)
    assert len(dr.async_entries_for_config_entry(device_reg, entry.entry_id)) == 2

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"locations": ["1001"], "query": "sec", "scan_interval": 120}
    )
    assert result["step_id"] == "add"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"locations": ["1002"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"locations": ["1001", "1002"], "scan_interval": 120}
    await hass.async_block_till_done()

    # Remove everything: location device must disappear, account stays.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"locations": [], "scan_interval": 120}
    )
    await hass.async_block_till_done()
    assert entry.options["locations"] == []
    assert len(dr.async_entries_for_config_entry(device_reg, entry.entry_id)) == 1
