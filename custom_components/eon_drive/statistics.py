"""Long-term statistics of charged energy and cost.

Every finished session is kept in an archive in `.storage`, and the hourly sums
are written as external statistics. Monthly charts therefore reach back to the
first session on the account, not just to the day the integration was added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import Session, day_ends, hourly_totals

STAT_ENERGY = f"{DOMAIN}:charged_energy"
STAT_COST = f"{DOMAIN}:charging_cost"

STORAGE_VERSION = 1

_NAMES = {
    "cs": ("E.ON Drive – nabitá energie", "E.ON Drive – cena nabíjení"),
    "en": ("E.ON Drive charged energy", "E.ON Drive charging cost"),
}


class SessionArchive:
    """All finished sessions of the account, keyed by session id."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.sessions", private=True
        )
        self._items: dict[str, dict[str, Any]] = {}
        self.complete = False

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._items = data.get("items") or {}
        self.complete = bool(data.get("complete"))

    def merge(self, items: list[dict[str, Any]], *, complete: bool = False) -> bool:
        """Add new sessions and refresh known ones; return whether anything changed."""
        merged = dict(self._items)
        for item in items:
            session = Session.from_api(item)
            if session.started_at is not None:
                merged[session.id] = item
        changed = merged != self._items or (complete and not self.complete)
        self._items = merged
        self.complete = self.complete or complete
        if changed:
            self._store.async_delay_save(
                lambda: {"complete": self.complete, "items": self._items}, 1
            )
        return changed

    def sessions(self) -> list[Session]:
        """Archived sessions, newest first."""
        sessions = [Session.from_api(item) for item in self._items.values()]
        return sorted(
            (s for s in sessions if s.started_at is not None),
            key=lambda s: s.started_at,
            reverse=True,
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()


def recorder_available(hass: HomeAssistant) -> bool:
    return "recorder" in hass.config.components


@callback
def async_import_statistics(
    hass: HomeAssistant, sessions: list[Session], currency: str, local_now: datetime
) -> None:
    """Write cumulative hourly energy and cost of all sessions (plus a row per day)."""
    if not recorder_available(hass):
        return
    started = [s.started_at for s in sessions if s.started_at is not None]
    extra = day_ends(min(started), local_now) if started else []
    energy_rows: list[StatisticData] = []
    cost_rows: list[StatisticData] = []
    energy_sum = cost_sum = 0.0
    for hour, energy, cost in hourly_totals(sessions, extra):
        energy_sum += energy
        cost_sum += cost
        energy_rows.append(StatisticData(start=hour, state=energy, sum=round(energy_sum, 3)))
        cost_rows.append(StatisticData(start=hour, state=cost, sum=round(cost_sum, 2)))
    if not energy_rows:
        return

    language = (hass.config.language or "en").split("-")[0]
    energy_name, cost_name = _NAMES.get(language, _NAMES["en"])
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=energy_name,
            source=DOMAIN,
            statistic_id=STAT_ENERGY,
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        ),
        energy_rows,
    )
    async_add_external_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=cost_name,
            source=DOMAIN,
            statistic_id=STAT_COST,
            unit_class=None,
            unit_of_measurement=currency,
        ),
        cost_rows,
    )


@callback
def async_clear_statistics(hass: HomeAssistant) -> None:
    """Remove the imported statistics (integration removed)."""
    if recorder_available(hass):
        get_instance(hass).async_clear_statistics([STAT_ENERGY, STAT_COST])
