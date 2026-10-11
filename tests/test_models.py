"""Parsing tests against payloads shaped like the real API."""

from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.eon_drive.models import (
    Session,
    normalize_status,
    parse_locations,
    summarize_month,
)

from .conftest import load

PRG = ZoneInfo("Europe/Prague")


def test_parse_locations():
    locations, tariffs = parse_locations(load("locations"))
    loc = locations["1001"]
    assert loc.name == "Test Hub"
    assert (loc.latitude, loc.longitude) == (50.1, 14.2)
    assert [e.status for e in loc.evses] == ["available", "out_of_order", "charging"]
    assert loc.available_count == 1
    assert loc.evses[0].max_power_kw == 90.0
    assert loc.evses[0].label == "CCS 2 90 kW"
    assert loc.evses[1].label == "CHAdeMO 62.5 kW"
    assert set(tariffs) == {"501", "502"}


def test_status_mapping():
    assert normalize_status("Out of Order") == "out_of_order"
    assert normalize_status("something new") == "unknown"
    assert normalize_status(None) == "unknown"


def test_tariff_time_of_day():
    _, tariffs = parse_locations(load("locations"))
    tod = tariffs["501"]
    assert tod.energy_price_at(datetime(2026, 10, 12, 7, 59, tzinfo=PRG)) == 8
    assert tod.energy_price_at(datetime(2026, 10, 12, 8, 0, tzinfo=PRG)) == 9.5
    assert tod.energy_price_at(datetime(2026, 10, 12, 19, 59, tzinfo=PRG)) == 9.5
    assert tod.energy_price_at(datetime(2026, 10, 12, 20, 0, tzinfo=PRG)) == 8
    flat = tariffs["502"]
    assert flat.energy_price_at(datetime(2026, 10, 12, 3, 0, tzinfo=PRG)) == 16


def test_session_history_item():
    s = Session.from_api(load("history")["data"][0])
    assert s.id == "9003"
    assert s.energy_kwh == 40.0
    assert s.amount == 320.0
    assert s.evse_identifier == "CZ*TST*E1*1"
    assert s.address == "Testovací 1"
    assert s.currency == "CZK"
    assert s.started_at.tzinfo is not None


def test_ongoing_bare_session():
    s = Session.from_api(load("ongoing")["data"][0])
    assert s.power_kw == 75.5
    assert s.energy_kwh == 12.345
    assert s.soc_percent == 42
    assert s.stopped_at is None


def test_month_summary_uses_local_month():
    sessions = [Session.from_api(i) for i in load("history")["data"]]
    # 9001 started 2026-09-30 22:30 UTC = 2026-10-01 00:30 in Prague -> October.
    energy, cost, count = summarize_month(sessions, datetime(2026, 10, 12, 12, 0, tzinfo=PRG))
    assert (energy, cost, count) == (70.5, 579.0, 3)
    energy, cost, count = summarize_month(sessions, datetime(2026, 9, 30, 12, 0, tzinfo=PRG))
    assert count == 0
