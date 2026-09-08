"""Call-budget behavior. Deterministic clock; no network, no DB, no model."""
import pytest

from src.common.quote_budget import CachedQuote, Decision, QuoteBudget

T0 = 1_757_000_000.0   # 2025-09-04T15:33:20Z — a Thursday, mid-month


def _q(figi="BBG000B9XRY4", at=T0, session="regular"):
    return CachedQuote(figi=figi, payload={"bid": "187.12", "ask": "187.14"},
                       as_of_epoch=at - 900, retrieved_epoch=at, source="yahoo",
                       delay_seconds=900, session=session)


def _budget(**kw):
    kw.setdefault("monthly_limit", 500)
    kw.setdefault("enforce_daily_pacing", False)
    return QuoteBudget(**kw)


def test_first_request_fetches():
    assert _budget().decide("X", "regular", now=T0) is Decision.FETCH


def test_second_request_inside_ttl_serves_cache():
    b = _budget()
    b.record_fetch(_q(figi="X"), now=T0)
    assert b.decide("X", "regular", now=T0 + 30) is Decision.SERVE_CACHE
    assert b.calls_used(T0) == 1, "a cache hit must not charge a call"


def test_request_after_ttl_fetches_again():
    b = _budget()
    b.record_fetch(_q(figi="X"), now=T0)
    assert b.decide("X", "regular", now=T0 + 61) is Decision.FETCH


def test_closed_market_ttl_is_long_because_nothing_moves():
    b = _budget()
    b.record_fetch(_q(figi="X", session="closed"), now=T0)
    assert b.decide("X", "closed", now=T0 + 1800) is Decision.SERVE_CACHE
    assert b.decide("X", "regular", now=T0 + 1800) is Decision.FETCH


def test_unknown_session_falls_back_to_the_shortest_ttl():
    b = _budget()
    assert b.ttl("nonsense") == min(b.ttl_by_session.values())


def test_exhausted_budget_never_serves_a_stale_quote_as_current():
    """The whole point. A stale quote relabeled as current is the failure mode
    this system exists to prevent, so exhaustion is an outcome, not a fallback."""
    b = _budget(monthly_limit=1)
    b.record_fetch(_q(figi="X"), now=T0)
    assert b.decide("X", "regular", now=T0 + 3600) is Decision.BUDGET_EXHAUSTED
    assert b.cached("X") is not None, "the cache still holds it; the agent just may not pass it off as current"


def test_budget_resets_on_month_rollover():
    b = _budget(monthly_limit=1)
    b.record_fetch(_q(figi="X"), now=T0)
    next_month = T0 + 40 * 86400
    assert b.remaining(next_month) == 1
    assert b.decide("X", "regular", now=next_month) is Decision.FETCH


def test_daily_pacing_stops_a_first_week_burn():
    """500 calls spent in three days is a cap that fails on the 4th."""
    b = QuoteBudget(monthly_limit=500, enforce_daily_pacing=True)
    allowance = int(b.daily_allowance(T0))
    assert allowance > 0
    for i in range(allowance):
        assert b.decide(f"S{i}", "regular", now=T0) is Decision.FETCH
        b.record_fetch(_q(figi=f"S{i}"), now=T0)
    assert b.decide("S999", "regular", now=T0) is Decision.BUDGET_EXHAUSTED
    assert b.decide("S999", "regular", now=T0 + 86400) is Decision.FETCH, "next day, new allowance"


def test_a_call_that_reached_the_source_counts_even_when_it_returned_nothing():
    b = _budget(monthly_limit=2)
    b.record_spent_call(now=T0)
    assert b.remaining(T0) == 1


def test_dedupe_across_callers_is_one_call():
    b = _budget()
    assert b.decide("AAPL", "regular", now=T0) is Decision.FETCH
    b.record_fetch(_q(figi="AAPL"), now=T0)
    for _ in range(20):
        assert b.decide("AAPL", "regular", now=T0 + 5) is Decision.SERVE_CACHE
    assert b.calls_used(T0) == 1


def test_zero_or_negative_limit_is_rejected():
    with pytest.raises(ValueError):
        QuoteBudget(monthly_limit=0)
