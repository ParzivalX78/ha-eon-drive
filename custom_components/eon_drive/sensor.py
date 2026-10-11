"""Sensors for E.ON Drive."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import EVSE_STATES
from .coordinator import EonDriveConfigEntry, EonDriveCoordinator, EonDriveData
from .entity import EonDriveAccountEntity, EonDriveLocationEntity
from .models import Evse, Location, Session


@dataclass(frozen=True, kw_only=True)
class AccountSensorDescription(SensorEntityDescription):
    """Describes an account level sensor."""

    value_fn: Callable[[EonDriveData], Any]
    monetary: bool = False
    attrs_fn: Callable[[EonDriveData], dict[str, Any]] | None = None


def _session_attrs(session: Session | None) -> dict[str, Any]:
    if session is None:
        return {}
    return {
        "session_id": session.id,
        "started_at": session.started_at,
        "stopped_at": session.stopped_at,
        "duration_minutes": round(session.duration_s / 60) if session.duration_s else None,
        "evse": session.evse_identifier,
        "address": session.address,
        "location_id": session.location_id,
    }


def _ongoing(fn: Callable[[Session], Any]) -> Callable[[EonDriveData], Any]:
    return lambda data: fn(data.ongoing) if data.ongoing else None


def _last(fn: Callable[[Session], Any]) -> Callable[[EonDriveData], Any]:
    return lambda data: fn(data.last_session) if data.last_session else None


ACCOUNT_SENSORS: tuple[AccountSensorDescription, ...] = (
    AccountSensorDescription(
        key="charging_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_ongoing(lambda s: s.power_kw),
    ),
    AccountSensorDescription(
        key="charging_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_ongoing(lambda s: s.energy_kwh),
        attrs_fn=lambda data: _session_attrs(data.ongoing),
    ),
    AccountSensorDescription(
        key="charging_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        monetary=True,
        value_fn=_ongoing(lambda s: s.amount),
    ),
    AccountSensorDescription(
        key="charging_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_ongoing(lambda s: s.soc_percent),
    ),
    AccountSensorDescription(
        key="last_session_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=_last(lambda s: s.energy_kwh),
        attrs_fn=lambda data: _session_attrs(data.last_session),
    ),
    AccountSensorDescription(
        key="last_session_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        monetary=True,
        value_fn=_last(lambda s: s.amount),
    ),
    AccountSensorDescription(
        key="last_session_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last(lambda s: s.started_at),
    ),
    AccountSensorDescription(
        key="month_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.month_energy_kwh,
        attrs_fn=lambda data: {"sessions": data.month_sessions},
    ),
    AccountSensorDescription(
        key="month_cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        monetary=True,
        value_fn=lambda data: data.month_cost,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EonDriveConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        EonDriveAccountSensor(coordinator, description) for description in ACCOUNT_SENSORS
    ]
    for location in coordinator.data.locations.values():
        entities.append(EonDriveAvailableCountSensor(coordinator, location))
        entities.extend(
            EonDriveEvseSensor(coordinator, location, evse) for evse in location.evses
        )
    async_add_entities(entities)


class EonDriveAccountSensor(EonDriveAccountEntity, SensorEntity):
    """Account level sensor (ongoing session, history)."""

    entity_description: AccountSensorDescription

    def __init__(
        self, coordinator: EonDriveCoordinator, description: AccountSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.monetary:
            return self.coordinator.data.currency or "CZK"
        return self.entity_description.native_unit_of_measurement

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.state_class is SensorStateClass.TOTAL:
            return dt_util.start_of_local_day().replace(day=1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class EonDriveAvailableCountSensor(EonDriveLocationEntity, SensorEntity):
    """Number of free charging points at a location."""

    _attr_translation_key = "available_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EonDriveCoordinator, location: Location) -> None:
        super().__init__(coordinator, location)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_location_{location.id}_available"
        )

    @property
    def native_value(self) -> int | None:
        location = self.location
        return location.available_count if location else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        location = self.location
        if location is None:
            return None
        return {
            "total": len(location.evses),
            "address": location.address,
            "city": location.city,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "location_id": location.id,
        }


class EonDriveEvseSensor(EonDriveLocationEntity, SensorEntity):
    """Status of one charging point."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = EVSE_STATES
    _attr_translation_key = "evse_status"

    def __init__(
        self, coordinator: EonDriveCoordinator, location: Location, evse: Evse
    ) -> None:
        super().__init__(coordinator, location)
        self._evse_id = evse.id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_evse_{evse.id}_status"
        suffix = evse.identifier.rsplit("*", 1)[-1] if evse.identifier else evse.id
        self._attr_translation_placeholders = {"evse": f"{evse.label} ({suffix})"}

    @property
    def available(self) -> bool:
        return super().available and self._evse(self._evse_id) is not None

    @property
    def native_value(self) -> str | None:
        evse = self._evse(self._evse_id)
        return evse.status if evse else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        evse = self._evse(self._evse_id)
        location = self.location
        if evse is None or location is None:
            return None
        attrs: dict[str, Any] = {
            "evse_id": evse.id,
            "identifier": evse.identifier,
            "raw_status": evse.raw_status,
            "max_power_kw": evse.max_power_kw,
            "current_type": evse.current_type,
            "connectors": evse.connectors,
        }
        tariff = self.coordinator.data.tariffs.get(evse.tariff_id or "")
        if tariff is not None:
            try:
                tz = ZoneInfo(location.timezone) if location.timezone else None
            except (ZoneInfoNotFoundError, ValueError):
                tz = None
            local_now = dt_util.now(tz) if tz else dt_util.now()
            attrs.update(
                {
                    "price_per_kwh_now": tariff.energy_price_at(local_now),
                    "price_per_kwh": tariff.price_energy,
                    "price_per_kwh_day": tariff.price_energy_day,
                    "price_per_kwh_night": tariff.price_energy_night,
                    "price_per_minute": tariff.price_duration,
                    "price_per_minute_day": tariff.price_duration_day,
                    "price_per_minute_night": tariff.price_duration_night,
                    "day_tariff_start": tariff.day_start.isoformat() if tariff.day_start else None,
                    "night_tariff_start": (
                        tariff.night_start.isoformat() if tariff.night_start else None
                    ),
                    "currency": tariff.currency,
                }
            )
        return attrs
