"""The E.ON Drive integration (unofficial)."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import EonDriveClient
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_DEVICE_ID, DOMAIN
from .coordinator import EonDriveConfigEntry, EonDriveCoordinator, tracked_location_ids
from .entity import account_identifier, location_identifier

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


STORAGE_VERSION = 1
PENDING_TOKENS = f"{DOMAIN}_pending_tokens"


def token_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, str]]:
    """Storage for the access token, so restarts do not trigger a new login."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}", private=True)


def create_client(
    hass: HomeAssistant,
    data: dict,
    *,
    token: str | None = None,
    on_token: Callable[[str], None] | None = None,
) -> EonDriveClient:
    """Build an API client from config entry data."""
    return EonDriveClient(
        async_get_clientsession(hass),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        client_id=data[CONF_CLIENT_ID],
        client_secret=data[CONF_CLIENT_SECRET],
        device_id=data[CONF_DEVICE_ID],
        token=token,
        on_token=on_token,
    )


async def async_setup_entry(hass: HomeAssistant, entry: EonDriveConfigEntry) -> bool:
    """Set up E.ON Drive from a config entry."""
    store = token_store(hass, entry.entry_id)
    # Token handed over by the config flow (fresh setup / reauth) wins over storage.
    pending: dict[str, str] = hass.data.get(PENDING_TOKENS, {})
    token = pending.pop(entry.entry_id, None) or pending.pop(entry.unique_id or "", None)
    if token:
        await store.async_save({"access_token": token})
    else:
        token = ((await store.async_load()) or {}).get("access_token")

    def _save_token(new_token: str) -> None:
        store.async_delay_save(lambda: {"access_token": new_token}, 1)

    client = create_client(hass, dict(entry.data), token=token, on_token=_save_token)
    coordinator = EonDriveCoordinator(hass, entry, client)
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


async def async_remove_entry(hass: HomeAssistant, entry: EonDriveConfigEntry) -> None:
    """Forget the stored token when the integration is removed."""
    await token_store(hass, entry.entry_id).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: EonDriveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
