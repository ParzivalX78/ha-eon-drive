"""Data update coordinator for E.ON Drive."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    EonDriveAuthError,
    EonDriveClient,
    EonDriveConnectionError,
    EonDriveError,
    EonDriveRateLimitError,
)
from .const import (
    CONF_LOCATIONS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FULL_HISTORY_RETRY,
    HISTORY_INTERVAL,
    HISTORY_MAX_PAGES,
    HISTORY_START,
    MAX_BACKOFF,
)
from .models import Location, Session, Tariff, parse_locations, summarize_month
from .statistics import SessionArchive, async_import_statistics

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
        self.archive = SessionArchive(hass, entry.entry_id)
        self._base_interval = self.update_interval
        self._history_at: datetime | None = None
        self._full_history_retry: datetime | None = None
        self._statistics_current = False
        self._statistics_day: date | None = None
        self._had_ongoing = False

    async def _async_setup(self) -> None:
        await self.archive.async_load()

    def _back_off(self, retry_after: int | None) -> None:
        """Slow down after a failure: double the interval, honour Retry-After."""
        current = (self.update_interval or self._base_interval).total_seconds()
        seconds = max(current * 2, retry_after or 0)
        self.update_interval = timedelta(seconds=min(seconds, MAX_BACKOFF))

    async def _fetch_history(self, now: datetime) -> tuple[list[dict[str, Any]], bool]:
        """Download the whole history once, afterwards only the recent window.

        Returns the sessions and whether they are the complete history.
        """
        if not self.archive.complete and (
            self._full_history_retry is None or now >= self._full_history_retry
        ):
            try:
                raw = await self.client.get_session_history(
                    HISTORY_START, now.date(), max_pages=HISTORY_MAX_PAGES
                )
            except (EonDriveAuthError, EonDriveRateLimitError, EonDriveConnectionError):
                raise
            except EonDriveError as err:
                # The server may refuse such a long range; keep working with the
                # recent window and try again later.
                _LOGGER.warning(
                    "Downloading the whole charging history failed (%s), "
                    "trying again in %s",
                    err,
                    FULL_HISTORY_RETRY,
                )
                self._full_history_retry = now + FULL_HISTORY_RETRY
            else:
                return raw, True
        # Go back far enough to always include the previous month.
        start = (now.replace(day=1) - timedelta(days=62)).date()
        return await self.client.get_session_history(start, now.date()), False

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
                raw, complete = await self._fetch_history(now)
                if self.archive.merge(raw, complete=complete):
                    self._statistics_current = False
                self._history_at = now
            self._had_ongoing = ongoing is not None
        except EonDriveAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EonDriveRateLimitError as err:
            self._back_off(err.retry_after)
            raise UpdateFailed(
                f"Rate limited, next attempt in {self.update_interval}"
            ) from err
        except EonDriveError as err:
            self._back_off(None)
            raise UpdateFailed(str(err)) from err
        self.update_interval = self._base_interval

        locations, tariffs = parse_locations(payload)
        # Only expose what the user selected, whatever the API decides to return.
        locations = {k: v for k, v in locations.items() if k in tracked}
        finished = self.archive.sessions()
        energy, cost, count = summarize_month(finished, now)
        currency = next(
            (t.currency for t in tariffs.values() if t.currency),
            next((s.currency for s in finished if s.currency), None),
        )
        # Again on a new day too, for that day's row (see models.day_ends()).
        if not self._statistics_current or self._statistics_day != now.date():
            async_import_statistics(self.hass, finished, currency or "CZK", now)
            self._statistics_current = True
            self._statistics_day = now.date()
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
