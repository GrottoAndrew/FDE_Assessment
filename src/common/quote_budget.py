"""
quote_budget.py — keep the free-tier quote source under its monthly call cap.

Deterministic. No network, no model, no database. This is tier-0 logic: the
cheapest model is no model, and a call not made costs nothing at all.

Three levers, in order of how much they save:

1. **Session-aware TTL.** A quote does not change while the market is closed.
   Serving a 09:00 snapshot at 09:15 on a closed market is not staleness, it is
   the same fact. Regular-hours TTL is short; closed-market TTL is long.
2. **Daily pacing.** A monthly cap spent in week one is a cap that fails at the
   worst moment. Remaining calls are paced across the remaining days.
3. **Symbol dedupe.** N advisors asking for AAPL inside one TTL window is one
   call, not N.

What it will not do: serve a stale quote labeled as current when the budget is
gone. That returns BUDGET_EXHAUSTED, the orchestrator returns FAILED, and a row
lands in ops.failure_log. A plausible partial presented as complete is the worst
outcome available (CLAUDE.md #6).
"""
from __future__ import annotations

import calendar
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# Session-aware TTLs in seconds. Tuned for call economy, not for latency.
DEFAULT_TTL_BY_SESSION = {
    "regular": 60,      # inside RTH a minute-old delayed quote is still delayed
    "pre": 300,
    "post": 300,
    "closed": 3600,     # nothing moves; refetching is pure waste
}


class Decision(str, Enum):
    SERVE_CACHE = "SERVE_CACHE"
    FETCH = "FETCH"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class CachedQuote:
    """What was fetched, and when the venue said it was true."""
    figi: str
    payload: dict
    as_of_epoch: float          # venue timestamp
    retrieved_epoch: float      # our fetch time
    source: str
    delay_seconds: int
    session: str


class QuoteBudget:
    """Call accounting plus a session-aware cache for one quote source."""

    def __init__(
        self,
        monthly_limit: int,
        source: str = "yahoo",
        ttl_by_session: dict[str, int] | None = None,
        enforce_daily_pacing: bool = True,
        clock=time.time,
    ) -> None:
        if monthly_limit <= 0:
            raise ValueError("monthly_limit must be positive")
        self.monthly_limit = monthly_limit
        self.source = source
        self.ttl_by_session = dict(ttl_by_session or DEFAULT_TTL_BY_SESSION)
        self.enforce_daily_pacing = enforce_daily_pacing
        self._clock = clock
        self._calls: dict[tuple[int, int], int] = {}          # (year, month) -> used
        self._calls_by_day: dict[tuple[int, int, int], int] = {}
        self._cache: dict[str, CachedQuote] = {}

    # --- period helpers ----------------------------------------------------
    @staticmethod
    def _period(now: float) -> tuple[int, int]:
        d = datetime.fromtimestamp(now, timezone.utc)
        return (d.year, d.month)

    @staticmethod
    def _day(now: float) -> tuple[int, int, int]:
        d = datetime.fromtimestamp(now, timezone.utc)
        return (d.year, d.month, d.day)

    def calls_used(self, now: float | None = None) -> int:
        now = self._clock() if now is None else now
        return self._calls.get(self._period(now), 0)

    def remaining(self, now: float | None = None) -> int:
        return self.monthly_limit - self.calls_used(now)

    def days_left_in_month(self, now: float | None = None) -> int:
        now = self._clock() if now is None else now
        d = datetime.fromtimestamp(now, timezone.utc)
        return calendar.monthrange(d.year, d.month)[1] - d.day + 1

    def daily_allowance(self, now: float | None = None) -> float:
        """Today's pace, computed from the balance at the START of today.

        Recomputing from the live balance after every spend shrinks the pace as
        the day is spent and starves the afternoon: 500 calls over 27 days gives
        18, but after 17 calls the same formula gives 17 and the 18th is refused.
        The day's cap has to be fixed when the day starts.
        """
        now = self._clock() if now is None else now
        start_of_day_balance = self.remaining(now) + self._calls_by_day.get(self._day(now), 0)
        return start_of_day_balance / self.days_left_in_month(now)

    def ttl(self, session: str) -> int:
        """Unknown sessions get the shortest TTL. Failing toward freshness is
        the safe direction for a price, and it is the expensive direction, which
        is why unknown sessions must not happen silently."""
        return self.ttl_by_session.get(session, min(self.ttl_by_session.values()))

    # --- the decision ------------------------------------------------------
    def decide(self, figi: str, session: str, now: float | None = None) -> Decision:
        now = self._clock() if now is None else now
        hit = self._cache.get(figi)
        if hit is not None and (now - hit.retrieved_epoch) < self.ttl(session):
            return Decision.SERVE_CACHE
        if self.remaining(now) <= 0:
            return Decision.BUDGET_EXHAUSTED
        if self.enforce_daily_pacing:
            spent_today = self._calls_by_day.get(self._day(now), 0)
            if spent_today >= max(1, int(self.daily_allowance(now))):
                # Paced out for today, not out of budget for the month. The
                # orchestrator still returns FAILED: a quote it cannot fetch is
                # a quote it cannot report, whatever the reason.
                return Decision.BUDGET_EXHAUSTED
        return Decision.FETCH

    def cached(self, figi: str) -> CachedQuote | None:
        return self._cache.get(figi)

    def record_fetch(self, quote: CachedQuote, now: float | None = None) -> None:
        """Charge one call and cache the result. Call this only after a FETCH
        decision and a successful fetch — a failed call that never reached the
        source is not budget spent, and a failed call that did is."""
        now = self._clock() if now is None else now
        self._calls[self._period(now)] = self.calls_used(now) + 1
        day = self._day(now)
        self._calls_by_day[day] = self._calls_by_day.get(day, 0) + 1
        self._cache[quote.figi] = quote

    def record_spent_call(self, now: float | None = None) -> None:
        """A call that reached the source but returned nothing usable. It still
        counts against the cap; pretending otherwise is how caps get blown."""
        now = self._clock() if now is None else now
        self._calls[self._period(now)] = self.calls_used(now) + 1
        day = self._day(now)
        self._calls_by_day[day] = self._calls_by_day.get(day, 0) + 1
