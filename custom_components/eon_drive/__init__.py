"""The E.ON Drive integration (unofficial)."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EonDriveClient
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_DEVICE_ID
from .coordinator import EonDriveConfigEntry, EonDriveCoordinator, tracked_location_ids
from .entity import account_identifier, location_identifier

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


def create_client(hass: HomeAssistant, data: dict) -> EonDriveClient:
    """Build an API client from config entry data."""
    return EonDriveClient(
        async_get_clientsession(hass),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        client_id=data[CONF_CLIENT_ID],
        client_secret=data[CONF_CLIENT_SECRET],
        device_id=data[CONF_DEVICE_ID],
    )


async def async_setup_entry(hass: HomeAssistant, entry: EonDriveConfigEntry) -> bool:
    """Set up E.ON Drive from a config entry."""
    coordinator = EonDriveCoordinator(hass, entry, create_client(hass, dict(entry.data)))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _remove_stale_devices(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _remove_stale_devices(hass: HomeAssistant, entry: EonDriveConfigEntry) -> None:
    """Drop devices of locations the user no longer tracks."""
    keep = {account_identifier(entry.entry_id)} | {
        location_identifier(entry.entry_id, loc_id) for loc_id in tracked_location_ids(entry)
    }
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & keep:
            registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def _async_reload(hass: HomeAssistant, entry: EonDriveConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EonDriveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
