"""Binary sensors for E.ON Drive."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EonDriveConfigEntry
from .entity import EonDriveAccountEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EonDriveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    async_add_entities([EonDriveChargingSensor(entry.runtime_data, "charging")])


class EonDriveChargingSensor(EonDriveAccountEntity, BinarySensorEntity):
    """On while a charging session is in progress on the account."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.ongoing is not None
