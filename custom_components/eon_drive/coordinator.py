"""Data update coordinator for E.ON Drive."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EonDriveAuthError, EonDriveClient, EonDriveError
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HISTORY_INTERVAL,
)
from .models import Location, Session, Tariff, parse_locations, summarize_month

_LOGGER = logging.getLogger(__name__)

type EonDriveConfigEntry = ConfigEntry[EonDriveCoordinator]


@dataclass(slots=True)
class EonDriveData:
    """Snapshot of everything the entities need."""

    locations: dict[str, Location] = field(default_factory=dict)
    tariffs: dict[str, Tariff] = field(default_factory=dict)
    ongoing: Session | None = None
    last_session: Session | None = None
    month_energy_kwh: float = 0.0
    month_cost: float = 0.0
    month_sessions: int = 0
    currency: str | None = None


def tracked_location_ids(entry: ConfigEntry) -> list[str]:
    """Return the location ids selected by the user."""
    return [str(i) for i in entry.options.get(CONF_LOCATIONS, entry.data.get(CONF_LOCATIONS, []))]


class EonDriveCoordinator(DataUpdateCoordinator[EonDriveData]):
    """Poll charger status, the ongoing session and charging history."""

    config_entry: EonDriveConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: EonDriveConfigEntry, client: EonDriveClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._history: list[Session] = []
        self._history_at: datetime | None = None
        self._had_ongoing = False

    async def _async_update_data(self) -> EonDriveData:
        now = dt_util.now()
        try:
            tracked = tracked_location_ids(self.config_entry)
            payload = await self.client.get_locations(tracked)
            ongoing_raw = await self.client.get_ongoing_sessions()
            ongoing = Session.from_api(ongoing_raw[0]) if ongoing_raw else None

            session_ended = self._had_ongoing and ongoing is None
            history_stale = (
                self._history_at is None or now - self._history_at >= HISTORY_INTERVAL
            )
            if history_stale or session_ended:
                # Go back far enough to always include the previous session.
                start = (now.replace(day=1) - timedelta(days=62)).date()
                raw = await self.client.get_session_history(start, now.date())
                self._history = [Session.from_api(item) for item in raw]
                self._history_at = now
            self._had_ongoing = ongoing is not None
        except EonDriveAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EonDriveError as err:
            raise UpdateFailed(str(err)) from err

        locations, tariffs = parse_locations(payload)
        # Only expose what the user selected, whatever the API decides to return.
        locations = {k: v for k, v in locations.items() if k in tracked}
        finished = sorted(
            (s for s in self._history if s.started_at is not None),
            key=lambda s: s.started_at,
            reverse=True,
        )
        energy, cost, count = summarize_month(finished, now)
        currency = next(
            (t.currency for t in tariffs.values() if t.currency),
            next((s.currency for s in finished if s.currency), None),
        )
        return EonDriveData(
            locations=locations,
            tariffs=tariffs,
            ongoing=ongoing,
            last_session=finished[0] if finished else None,
            month_energy_kwh=energy,
            month_cost=cost,
            month_sessions=count,
            currency=currency,
        )
