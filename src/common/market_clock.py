"""
market_clock.py — the NYSE clock. Deterministic, no network, no model.

Two jobs:
  1. Answer "is the market open right now" against the exchange's clock, not the
     server's. A container in UTC and a desk in New York disagree by four or five
     hours depending on the month, and the DST boundary is not the same date in
     the US and the EU.
  2. Stop a fetch that cannot produce a current price. A quote pulled at 03:00 ET
     is yesterday's close wearing a fresh retrieved_at. Not fetching it is both
     the correct answer and the cheapest one — roughly two thirds of a 24-hour
     polling schedule is outside regular hours.

The holiday table is HARDCODED and dated. The NYSE also closes unscheduled, for
national days of mourning, and no hardcoded table will ever know that. Past
CALENDAR_VERIFIED_THROUGH the clock refuses to assert rather than guessing a
session, because a wrong "open" is worse than a "cannot say".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from enum import Enum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

CALENDAR_SOURCE = "NYSE published holiday calendar"
# The window is bounded at BOTH ends. RED TEAM RT-02: with only an upper bound,
# any earlier date was scored against the 2026 holiday table, so 2025-12-25 and
# 2024-07-04 both read back as "regular session". A backfill or a replayed
# fixture would have been marked tradeable on Christmas.
CALENDAR_VERIFIED_FROM = date(2026, 1, 1)
CALENDAR_VERIFIED_THROUGH = date(2026, 12, 31)

# Full closures.
NYSE_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Washington's Birthday
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day observed (Jul 4 falls on a Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas Day
})

# 13:00 ET close. Post-market ends at 17:00 ET on these days.
NYSE_HALF_DAYS_2026 = frozenset({
    date(2026, 11, 27),  # day after Thanksgiving
    date(2026, 12, 24),  # Christmas Eve
})

PRE_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
HALF_DAY_CLOSE = time(13, 0)
POST_CLOSE = time(20, 0)
HALF_DAY_POST_CLOSE = time(17, 0)


class Session(str, Enum):
    PRE = "pre"
    REGULAR = "regular"
    POST = "post"
    CLOSED = "closed"
    UNKNOWN = "unknown"       # beyond the verified calendar; assert nothing


@dataclass(frozen=True)
class ClockReading:
    """Everything a caller needs to justify fetching or not fetching."""
    now_utc: datetime
    now_et: datetime
    trade_date: date
    session: Session
    is_regular_open: bool
    is_half_day: bool
    is_holiday: bool
    calendar_verified: bool
    reason: str

    @property
    def may_fetch_current_quote(self) -> bool:
        """Only the regular session produces a price that can be called current.
        Pre and post are real sessions but thin, and the interim source does not
        return their prints anyway (includePrePost=false)."""
        return self.session is Session.REGULAR


def reading(now: datetime | None = None) -> ClockReading:
    now = (now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("naive datetime: the clock will not guess a timezone")
    now_utc = now.astimezone(timezone.utc)
    et = now_utc.astimezone(ET)
    d = et.date()

    if d < CALENDAR_VERIFIED_FROM or d > CALENDAR_VERIFIED_THROUGH:
        return ClockReading(now_utc, et, d, Session.UNKNOWN, False, False, False, False,
                            f"calendar verified only {CALENDAR_VERIFIED_FROM}..{CALENDAR_VERIFIED_THROUGH}; "
                            "refusing to assert a session")

    if et.weekday() >= 5:
        return ClockReading(now_utc, et, d, Session.CLOSED, False, False, False, True, "weekend")
    if d in NYSE_HOLIDAYS_2026:
        return ClockReading(now_utc, et, d, Session.CLOSED, False, False, True, True, "exchange holiday")

    half = d in NYSE_HALF_DAYS_2026
    close = HALF_DAY_CLOSE if half else REGULAR_CLOSE
    post_close = HALF_DAY_POST_CLOSE if half else POST_CLOSE
    t = et.time()

    if REGULAR_OPEN <= t < close:
        s, why = Session.REGULAR, "regular session"
    elif PRE_OPEN <= t < REGULAR_OPEN:
        s, why = Session.PRE, "pre-market"
    elif close <= t < post_close:
        s, why = Session.POST, "post-market"
    else:
        s, why = Session.CLOSED, "outside all sessions"

    return ClockReading(now_utc, et, d, s, s is Session.REGULAR, half, False, True,
                        why + (" (half day, 13:00 ET close)" if half else ""))


def is_open(now: datetime | None = None) -> bool:
    return reading(now).is_regular_open
