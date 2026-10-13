"""Pure parsing helpers for E.ON Drive API payloads (no Home Assistant imports)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_STATUS_MAP = {
    "available": "available",
    "charging": "charging",
    "preparing": "preparing",
    "finishing": "finishing",
    "suspended": "suspended",
    "suspendedev": "suspended",
    "suspendedevse": "suspended",
    "reserved": "reserved",
    "occupied": "charging",
    "unavailable": "unavailable",
    "out of order": "out_of_order",
    "out_of_order": "out_of_order",
    "faulted": "out_of_order",
}


def normalize_status(raw: Any) -> str:
    """Map an API EVSE status to one of the integration's known states."""
    if not isinstance(raw, str):
        return "unknown"
    return _STATUS_MAP.get(raw.strip().lower(), "unknown")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_time(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp from the API into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


@dataclass(slots=True)
class Tariff:
    """Price information for an EVSE."""

    id: str
    currency: str | None
    price_energy: float | None
    price_energy_day: float | None
    price_energy_night: float | None
    price_duration: float | None
    price_duration_day: float | None
    price_duration_night: float | None
    day_start: time | None
    night_start: time | None
    price_type: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Tariff:
        return cls(
            id=str(data.get("id")),
            currency=data.get("currencyCode"),
            price_energy=_num(data.get("priceForEnergy")),
            price_energy_day=_num(data.get("priceForEnergyAtDay")),
            price_energy_night=_num(data.get("priceForEnergyAtNight")),
            price_duration=_num(data.get("priceForDuration")),
            price_duration_day=_num(data.get("priceForDurationAtDay")),
            price_duration_night=_num(data.get("priceForDurationAtNight")),
            day_start=_parse_time(data.get("dayTariffStart")),
            night_start=_parse_time(data.get("nightTariffStart")),
            price_type=data.get("priceType"),
        )

    def is_night(self, local_now: datetime) -> bool | None:
        """Return whether the night band applies, None if there are no bands."""
        if self.day_start is None or self.night_start is None:
            return None
        now = local_now.time()
        if self.day_start <= self.night_start:
            return not (self.day_start <= now < self.night_start)
        return self.night_start <= now < self.day_start

    def energy_price_at(self, local_now: datetime) -> float | None:
        """Price per kWh valid at the given local time."""
        if self.price_energy is not None:
            return self.price_energy
        night = self.is_night(local_now)
        if night is None:
            return self.price_energy_day or self.price_energy_night
        return self.price_energy_night if night else self.price_energy_day


@dataclass(slots=True)
class Evse:
    """A single charging point (one cable/socket) at a location."""

    id: str
    identifier: str | None
    status: str
    raw_status: str | None
    is_available: bool
    max_power_kw: float | None
    current_type: str | None
    connectors: list[str]
    tariff_id: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Evse:
        max_power = _num(data.get("maxPower"))
        return cls(
            id=str(data.get("id")),
            identifier=data.get("identifier"),
            status=normalize_status(data.get("status")),
            raw_status=data.get("status"),
            is_available=bool(data.get("isAvailable")),
            max_power_kw=round(max_power / 1000, 1) if max_power is not None else None,
            current_type=data.get("currentType"),
            connectors=[
                c["name"]
                for c in data.get("connectors") or []
                if isinstance(c, dict) and c.get("name")
            ],
            tariff_id=str(data["tariffId"]) if data.get("tariffId") is not None else None,
        )

    @property
    def label(self) -> str:
        """Human readable name, e.g. 'CCS 2 90 kW'."""
        parts = [" / ".join(self.connectors) or (self.current_type or "EVSE").upper()]
        if self.max_power_kw is not None:
            parts.append(f"{self.max_power_kw:g} kW")
        return " ".join(parts)


@dataclass(slots=True)
class Location:
    """A charging location with its EVSEs."""

    id: str
    name: str
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None
    timezone: str | None
    evses: list[Evse] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Location:
        lat = lon = None
        geo = data.get("location")
        if isinstance(geo, str) and "," in geo:
            try:
                lat_s, lon_s = geo.split(",", 1)
                lat, lon = float(lat_s), float(lon_s)
            except ValueError:
                lat = lon = None
        evses = [
            Evse.from_api(evse)
            for zone in data.get("zones") or []
            if isinstance(zone, dict)
            for evse in zone.get("evses") or []
            if isinstance(evse, dict)
        ]
        return cls(
            id=str(data.get("id")),
            name=(data.get("name") or f"Location {data.get('id')}").strip(),
            address=(data.get("address") or "").strip() or None,
            city=(data.get("city") or "").strip() or None,
            latitude=lat,
            longitude=lon,
            timezone=data.get("timezone"),
            evses=evses,
        )

    @property
    def available_count(self) -> int:
        return sum(1 for e in self.evses if e.status == "available")


def parse_locations(payload: dict[str, Any]) -> tuple[dict[str, Location], dict[str, Tariff]]:
    """Parse the POST /locations response."""
    locations = {
        loc.id: loc
        for loc in (
            Location.from_api(item)
            for item in payload.get("locations") or []
            if isinstance(item, dict)
        )
    }
    tariffs = {
        t.id: t
        for t in (
            Tariff.from_api(item)
            for item in payload.get("tariffs") or []
            if isinstance(item, dict)
        )
    }
    return locations, tariffs


@dataclass(slots=True)
class Session:
    """A charging session (ongoing or finished)."""

    id: str
    status: str | None
    started_at: datetime | None
    stopped_at: datetime | None
    energy_kwh: float | None
    power_kw: float | None
    amount: float | None
    soc_percent: float | None
    duration_s: int | None
    location_id: str | None
    evse_identifier: str | None
    address: str | None
    currency: str | None

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> Session:
        """Parse a session; accepts both bare and history-wrapped objects."""
        data = item.get("session") if isinstance(item.get("session"), dict) else item
        energy_wh = _num(data.get("energy"))
        power_w = _num(data.get("power"))
        amount = _num(data.get("totalAmount"))
        if amount is None:
            amount = _num(data.get("amount"))
        currency = data.get("currency")
        evse = item.get("evse") if isinstance(item.get("evse"), dict) else {}
        duration = _num(data.get("duration"))
        return cls(
            id=str(data.get("id")),
            status=data.get("status"),
            started_at=parse_dt(data.get("startedAt")),
            stopped_at=parse_dt(data.get("stoppedAt")),
            energy_kwh=round(energy_wh / 1000, 3) if energy_wh is not None else None,
            power_kw=round(power_w / 1000, 2) if power_w is not None else None,
            amount=amount,
            soc_percent=_num(data.get("carBatteryPercent")),
            duration_s=int(duration) if duration is not None else None,
            location_id=str(data["locationId"]) if data.get("locationId") is not None else None,
            evse_identifier=evse.get("identifier") or data.get("evseId"),
            address=item.get("address"),
            currency=currency.get("code") if isinstance(currency, dict) else None,
        )


def day_ends(first: datetime, local_now: datetime) -> list[datetime]:
    """23:00 local time of every day from `first` up to yesterday.

    Home Assistant takes the start of a period's change from the row of the hour
    before the period; a row at the last hour of every day gives every day, week,
    month and year that row, even when nothing was charged.
    """
    tz = local_now.tzinfo
    day = first.astimezone(tz).date()
    ends = []
    while day < local_now.date():
        ends.append(datetime.combine(day, time(23), tzinfo=tz))
        day += timedelta(days=1)
    return ends


def hourly_totals(
    sessions: Iterable[Session], extra_hours: Iterable[datetime] = ()
) -> list[tuple[datetime, float, float]]:
    """Return (UTC hour, kWh, cost) per hour in which sessions started, oldest first.

    `extra_hours` get a row too (with nothing added), see day_ends().
    """
    buckets: dict[datetime, list[float]] = {}

    def bucket(moment: datetime) -> list[float]:
        hour = moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        return buckets.setdefault(hour, [0.0, 0.0])

    for moment in extra_hours:
        bucket(moment)
    for session in sessions:
        if session.started_at is None:
            continue
        values = bucket(session.started_at)
        values[0] += session.energy_kwh or 0.0
        values[1] += session.amount or 0.0
    return [
        (hour, round(energy, 3), round(cost, 2))
        for hour, (energy, cost) in sorted(buckets.items())
    ]


def summarize_month(sessions: list[Session], local_now: datetime) -> tuple[float, float, int]:
    """Return (kWh, cost, count) of sessions started in the current local month."""
    energy = cost = 0.0
    count = 0
    for session in sessions:
        if session.started_at is None:
            continue
        started = session.started_at.astimezone(local_now.tzinfo)
        if (started.year, started.month) != (local_now.year, local_now.month):
            continue
        count += 1
        energy += session.energy_kwh or 0.0
        cost += session.amount or 0.0
    return round(energy, 3), round(cost, 2), count
