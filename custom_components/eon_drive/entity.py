"""Base entities for E.ON Drive."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EonDriveCoordinator
from .models import Evse, Location


def account_identifier(entry_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_account")


def location_identifier(entry_id: str, location_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_location_{location_id}")


class EonDriveEntity(CoordinatorEntity[EonDriveCoordinator]):
    """Common base."""

    _attr_has_entity_name = True
    _attr_attribution = "Data: E.ON Drive (unofficial)"


class EonDriveAccountEntity(EonDriveEntity):
    """Entity attached to the user's account (sessions, history)."""

    def __init__(self, coordinator: EonDriveCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={account_identifier(entry_id)},
            name="E.ON Drive",
            manufacturer="E.ON Drive",
            entry_type=DeviceEntryType.SERVICE,
        )


class EonDriveLocationEntity(EonDriveEntity):
    """Entity attached to a charging location."""

    def __init__(self, coordinator: EonDriveCoordinator, location: Location) -> None:
        super().__init__(coordinator)
        self._location_id = location.id
        entry_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={location_identifier(entry_id, location.id)},
            name=location.name,
            manufacturer="E.ON Drive",
            model=", ".join(p for p in (location.address, location.city) if p) or None,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def location(self) -> Location | None:
        return self.coordinator.data.locations.get(self._location_id)

    @property
    def available(self) -> bool:
        return super().available and self.location is not None

    def _evse(self, evse_id: str) -> Evse | None:
        location = self.location
        if location is None:
            return None
        return next((e for e in location.evses if e.id == evse_id), None)
