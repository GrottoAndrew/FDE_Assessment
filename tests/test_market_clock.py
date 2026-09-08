"""The NYSE clock. Wrong by an hour is wrong by a session."""
from datetime import date, datetime, timezone

import pytest

from src.common.market_clock import (CALENDAR_VERIFIED_FROM, CALENDAR_VERIFIED_THROUGH, Session,
                                     is_open, reading)


def _utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.mark.parametrize("iso,expected", [
    ("2026-09-08T13:29:00Z", Session.PRE),      # 09:29 ET — one minute early
    ("2026-09-08T13:30:00Z", Session.REGULAR),  # 09:30 ET — the open
    ("2026-09-08T19:59:00Z", Session.REGULAR),  # 15:59 ET
    ("2026-09-08T20:00:00Z", Session.POST),     # 16:00 ET — the close
    ("2026-09-09T01:00:00Z", Session.CLOSED),   # 21:00 ET
    ("2026-09-08T08:30:00Z", Session.CLOSED),   # 04:30 ET is pre... 03:30 is not
])
def test_session_boundaries_are_on_the_exchange_clock(iso, expected):
    if iso == "2026-09-08T08:30:00Z":
        assert reading(_utc(iso)).session is Session.PRE   # 04:30 ET
        return
    assert reading(_utc(iso)).session is expected


def test_dst_matters():
    """13:45 UTC is 09:45 ET in September and 08:45 ET in January. One is open,
    the other is pre-market, and a fixed UTC offset gets one of them wrong."""
    assert reading(_utc("2026-09-08T13:45:00Z")).session is Session.REGULAR
    assert reading(_utc("2026-01-08T13:45:00Z")).session is Session.PRE


def test_weekends_are_closed():
    assert reading(_utc("2026-09-12T17:00:00Z")).session is Session.CLOSED   # Saturday
    assert reading(_utc("2026-09-13T17:00:00Z")).session is Session.CLOSED   # Sunday


@pytest.mark.parametrize("d", ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
                               "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
                               "2026-11-26", "2026-12-25"])
def test_every_2026_exchange_holiday_is_closed(d):
    r = reading(_utc(f"{d}T17:00:00Z"))
    assert r.session is Session.CLOSED and r.is_holiday


def test_independence_day_is_observed_on_the_friday():
    """Jul 4 2026 is a Saturday, so the closure is Friday Jul 3."""
    assert reading(_utc("2026-07-03T17:00:00Z")).is_holiday
    assert not reading(_utc("2026-07-06T17:00:00Z")).is_holiday


def test_half_days_close_at_one_pm_et():
    assert reading(_utc("2026-11-27T17:45:00Z")).session is Session.REGULAR   # 12:45 ET
    r = reading(_utc("2026-11-27T18:30:00Z"))                                 # 13:30 ET
    assert r.session is Session.POST and r.is_half_day


def test_beyond_the_verified_calendar_the_clock_refuses_to_assert():
    """A wrong 'open' is worse than 'cannot say'. The NYSE also closes
    unscheduled, and no hardcoded table will ever know that."""
    r = reading(_utc("2027-01-04T15:00:00Z"))
    assert r.session is Session.UNKNOWN
    assert not r.calendar_verified and not r.may_fetch_current_quote
    assert str(CALENDAR_VERIFIED_THROUGH) in r.reason


def test_only_the_regular_session_may_produce_a_current_quote():
    assert is_open(_utc("2026-09-08T17:45:00Z"))
    for iso in ("2026-09-08T12:00:00Z", "2026-09-08T23:30:00Z", "2026-09-07T17:00:00Z"):
        assert not reading(_utc(iso)).may_fetch_current_quote


def test_a_naive_datetime_is_refused():
    with pytest.raises(ValueError):
        reading(datetime(2026, 9, 8, 13, 45))


def test_a_date_before_the_verified_window_is_unknown_not_open():
    """RT-02. The calendar was bounded only above, so any earlier date was scored
    against the 2026 holiday table: 2025-12-25 and 2024-07-04 both read back as
    "regular session". A backfill or a replayed fixture would have been marked
    tradeable on Christmas."""
    from src.common.market_clock import Session, reading
    for d in ("2025-12-25", "2024-07-04", "2025-09-08"):
        r = reading(datetime.fromisoformat(d + "T15:00:00+00:00"))
        assert r.session is Session.UNKNOWN, d
        assert not r.may_fetch_current_quote
        assert not r.calendar_verified
